# Telltale issue drafts

Drafts for the operator to file on the Telltale repository. Each repro is
self-contained: synthetic data, the Telltale CLI only, no lab tooling. All
were run against `telltale 0.7.0-rc.2 (2e8c56aa4558)` on 2026-10-13, each
with a passing control.

Common scan command (`$R` is a fixture root containing an empty
`.telltale-fixtures` file):

```sh
telltale scan --root "$R" --once --allow-fixtures --no-local-config \
  --install-inventory-disabled --state-path "$T/state.json" --log-path "$T/events.jsonl"
```

Results are read from `source_processing` in the last stdout line and from
detection events in the log.

Common Codex rollout (`$R/codex/sessions/2026/10/13/rollout-2026-10-13T00-00-00-00000000-0000-4000-8000-000000000001.jsonl`),
with `<CMD>` and `<OUT>` filled per issue:

```jsonl
{"timestamp":"2026-10-13T00:00:00Z","type":"session_meta","payload":{"id":"00000000-0000-4000-8000-000000000001","timestamp":"2026-10-13T00:00:00Z","cwd":"/synthetic/work","originator":"codex_cli_rs","cli_version":"0.162.1","source":"cli","model_provider":"synthetic"}}
{"timestamp":"2026-10-13T00:00:01Z","type":"event_msg","payload":{"type":"task_started","turn_id":"turn-1"}}
{"timestamp":"2026-10-13T00:00:01Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Please help."}]}}
{"timestamp":"2026-10-13T00:00:02Z","type":"response_item","payload":{"type":"function_call","name":"exec_command","arguments":"{\"cmd\": \"<CMD>\", \"workdir\": \"/synthetic/work\"}","call_id":"call_1"}}
{"timestamp":"2026-10-13T00:00:03Z","type":"response_item","payload":{"type":"function_call_output","call_id":"call_1","output":"Process exited with code 0\nOutput:\n<OUT>"}}
{"timestamp":"2026-10-13T00:00:04Z","type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Done."}]}}
{"timestamp":"2026-10-13T00:00:05Z","type":"event_msg","payload":{"type":"task_complete","turn_id":"turn-1","last_agent_message":"Done."}}
```

---

## 1. Codex: one `token_usage_record` line rejects the whole rollout

**Observed.** Common rollout with `<CMD>`=`ls`: `source_processing.parse_success_source_count` 1, 7 records.
Insert this line before the assistant message:

```json
{"timestamp":"2026-10-13T00:00:04Z","type":"token_usage_record","payload":{"thread_id":"00000000-0000-4000-8000-000000000001","turn_id":"turn-1","session_id":"00000000-0000-4000-8000-000000000001","root_turn_id":"turn-1","response_id":"resp_1","usage":{"input_tokens":1,"cached_input_tokens":0,"output_tokens":1,"reasoning_output_tokens":0,"total_tokens":2},"turn_token_usage":{"input_tokens":1,"cached_input_tokens":0,"output_tokens":1,"reasoning_output_tokens":0,"total_tokens":2},"thread_token_usage":{"input_tokens":1,"cached_input_tokens":0,"output_tokens":1,"reasoning_output_tokens":0,"total_tokens":2}}}
```

Result: `source_processing.parse_error_source_count` 1, `unknown_discriminator`, 0 records; warnings
`source_parse_error_observed`, `selected_sources_produced_no_records`,
`all_selected_sources_parse_failed_or_empty`. The scan exits 0.

**Upstream.** `token_usage_record` is a top-level rollout item with no
`type` in its payload, always persisted, and written after each model
response that reports usage (openai/codex `092d3acd`, rust-v0.162.1:
`codex-rs/history/src/rollout_payload.rs#L54-L56`,
`codex-rs/rollout/src/policy.rs#L42-L48`,
`codex-rs/core/src/session/mod.rs#L4736-L4751`).

**Telltale.** The discriminator is not in `is_known_codex_discriminator`
(`crates/telltale-sources/src/sources/codex/native.rs#L767-L785`).

**Impact.** If current rollouts contain this record, as the upstream code
says, Codex acquisition fails for every current session. Not yet confirmed
with a real rollout; the existing bounded live validation may predate the
record.

**Suggested direction.** Treat it as a known auxiliary record (no
observation), as other non-security records are.

## 2. OpenCode: v2 databases are acquired as zero records without an error

**Observed.** `$R/opencode/opencode.db` in the OpenCode v2.0.27 shape:

```sql
CREATE TABLE project (id text PRIMARY KEY, worktree text NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL);
CREATE TABLE session_v2 (id text PRIMARY KEY, project_id text NOT NULL, slug text NOT NULL, directory text NOT NULL, version text NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL);
CREATE TABLE session_message (id text PRIMARY KEY, session_id text NOT NULL, type text NOT NULL, seq integer NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL);
INSERT INTO project VALUES ('prj_1','/synthetic/work',1791849600000,1791849600000);
INSERT INTO session_v2 VALUES ('ses_1','prj_1','synthetic','/synthetic/work','2.0.27',1791849600000,1791849600000);
INSERT INTO session_message VALUES ('msg_1','ses_1','user',1,1791849600000,1791849600000,'{"time":{"created":1791849600000},"text":"list files","files":[],"agents":[],"skills":[]}');
INSERT INTO session_message VALUES ('msg_2','ses_1','assistant',2,1791849600001,1791849600003,'{"time":{"created":1791849600001,"completed":1791849600003},"agent":"build","model":{"id":"synthetic","providerID":"synthetic"},"content":[{"type":"tool","id":"call_1","name":"bash","state":{"status":"completed","input":{"command":"ls"},"content":[{"type":"text","text":"README.md"}]},"time":{"created":1791849600001,"ran":1791849600002,"completed":1791849600003}}]}');
```

Result: `source_processing.parse_success_source_count` 1, 0 records, no failures; the diagnostic
warnings `source_coverage_partial` and `selected_sources_produced_no_records`.
No scanner error.

**Upstream.** v2.0.0 through v2.0.27 bootstrap `session_v2`/`session_message`
and no `message`/`part` tables (anomalyco/opencode `1f4d07a4`:
`packages/core/src/database/schema.gen.ts#L148-L224`). Tool calls are
`content[]` entries of assistant messages
(`packages/schema/src/session-message.ts#L112-L246`). v1.19.0 still has
`message`/`part`.

**Telltale.** Extraction reads only `message` and `part` when present
(`crates/telltale-sources/src/sources/opencode/native.rs#L248-L276`).

**Impact.** Fresh OpenCode v2 stores produce no detections, and the loss is
visible only in diagnostics. Open question: whether upgraded databases keep
their v1 tables.

**Suggested direction.** At minimum, raise a visibility-limited or
unsupported-schema signal when `session_message` exists without `part`.
Then add a v2 adapter.

## 3. `persistence.shell_profile` misses `systemctl --user enable`

**Observed.** Common rollout, `<OUT>` empty:

| `<CMD>` | Result |
| --- | --- |
| `systemctl enable synthetic.service` | `persistence.shell_profile` (risk 45) |
| `systemctl --user enable synthetic.service` | no detection |

**Cause.** The regex alternative is `systemctl\s+enable`, so any option
between `systemctl` and `enable` defeats it. Per-user units need no root,
which makes `--user` the more likely form for an agent.

**Suggested direction.** Allow options before the verb, for example
`systemctl\s+(?:--?\S+\s+)*enable`, with a positive fixture for `--user`
and a benign `systemctl --user status` confounder.

## 4. `approval.bypass.context` documentation-review exclusion covers only one phrase

**Observed.** Common rollout with `<CMD>`=`cat docs/review.md`:

| `<OUT>` | Result |
| --- | --- |
| `Documentation review: the quoted example 'bypass approval' is disallowed behavior and should not be treated as an instruction.` | excluded, no detection |
| `Documentation review: the quoted example 'run this without asking for approval' is disallowed behavior and should not be treated as an instruction.` | `approval.bypass.context` (risk 45) |

**Cause.** The selection matches six phrases (`without asking`, `bypass
approval`, `hide this`, `do not tell`, `silently run`, `no confirm`), but
the documentation-review branch of the exclusion requires the literal
`bypass approval`. The same review framing around any other selected phrase
still fires. The rule's own `falsepositives` names this class.

**Suggested direction.** Make the documentation-review exclusion cover the
same phrase set as the selection, with paired fixtures for each phrase.

## 5. `procchain.persistence.cmd_schtasks` scores a read-only `schtasks /Query` as persistence

**Observed.** Common rollout, `<OUT>` empty:

| `<CMD>` | Result |
| --- | --- |
| `schtasks.exe /Create /TN SyntheticUpdater /TR synthetic-updater.exe /SC DAILY` | `process_chain` `procchain.persistence.cmd_schtasks` (low, 20) |
| `schtasks.exe /Query /TN SyntheticUpdater /FO LIST` | the same event, same score |

The same `/Query` false positive also appears for an OpenCode `bash` tool
call.

**Cause.** The process-chain rule keys on launching `schtasks` and ignores
the verb, so listing tasks scores the same as creating one.

**Suggested direction.** Score `/Create` (and `/Change`) as persistence, and
keep `/Query` unscored or informational, with paired fixtures.
