# Codex CLI

Research guide for generating and analyzing Codex rollout evidence. Checked
2026-10-13.

Claim labels: **Upstream fact** (pinned link), **Live observation** (seen in
this lab), **Telltale implementation** (Telltale code/docs), **Open question**.

## 1. Upstream and docs

- Repository: <https://github.com/openai/codex>
- Docs: <https://developers.openai.com/codex> (config reference linked from
  [`docs/config.md`](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/docs/config.md)),
  [`docs/exec.md`](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/docs/exec.md),
  [`docs/sandbox.md`](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/docs/sandbox.md).
- The rollout format is defined in code, not in a user doc. Read the files
  linked below rather than relying on prose.

## 2. Versions

| What | Version | Commit |
| --- | --- | --- |
| Researched upstream | `rust-v0.162.1` (2026-10-09) | `092d3acd6bec3e3a14bdc7e7a2810ab628ab759d` |
| Locally installed | `codex-cli 0.160.0` (**Live observation**, `--version`) | `rust-v0.160.0` = `a956835d020762cb2b570053af06f643a11c0ecc` |
| Telltale's own pinned evidence | — | `47379efd5289cba801c5a66273064fbe3bf92f60` (cited in the Telltale Codex spec) |

The persistence policy and record envelope below are the same at all three
commits for the items that matter here (`token_usage_record`, legacy
`agent_message`, paginated `item_completed`).

## 3. Install and authentication

Operator-controlled: npm `@openai/codex`, release binaries, or a package
manager; sign in with `codex login` (ChatGPT account or API key). Do not script
around login or approvals. `codex exec` is the non-interactive entry point;
`--ephemeral` disables persistence (**Live observation**, `codex exec --help`
on 0.160.0).

## 4. Storage and discovery

- **Upstream fact**: root is `$CODEX_HOME`, default `~/.codex`; a set
  `CODEX_HOME` must already exist
  ([home-dir/src/lib.rs#L6-L30](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/utils/home-dir/src/lib.rs#L6-L30)).
- **Upstream fact**: rollouts live in `sessions/` and `archived_sessions/`
  ([rollout/src/lib.rs#L86-L87](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/rollout/src/lib.rs#L86-L87)),
  under `YYYY/MM/DD/`
  ([recorder.rs#L1750-L1752](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/rollout/src/recorder.rs#L1750-L1752)),
  named `rollout-<YYYY-MM-DDTHH-MM-SS>-<thread>[_<rollout>].jsonl`
  ([rollout_file_name.rs](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/rollout/src/rollout_file_name.rs)).
- **Upstream fact**: an opt-in feature `local_thread_store_compression`
  (stage UnderDevelopment, default off) compresses rollouts older than 7 days
  to `.jsonl.zst`
  ([features/src/lib.rs#L1243-L1247](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/features/src/lib.rs#L1243-L1247),
  [compression.rs#L333-L370](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/rollout/src/compression.rs#L333-L370)).
- **Upstream fact**: `CODEX_HOME` also holds SQLite stores (`state_5.sqlite`,
  `thread_history_1.sqlite`, `logs_2.sqlite`, and others)
  ([state/src/sqlite.rs#L34-L39](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/state/src/sqlite.rs#L34-L39)).
  `thread_history_1.sqlite` is a projection materialized from rollout files
  ([thread_history_materialization.rs](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/thread-store/src/local/thread_history_materialization.rs)).
  The rollout JSONL stays the primary evidence.
- Windows: same layout under `%CODEX_HOME%` or `%USERPROFILE%\.codex`.
  **Open question**: not checked on a native Windows install.
- **Open question**: no upstream `headless/` directory was found. Exec sessions
  are written to `sessions/` with `session_meta.payload.source = "exec"`.

## 5. Record format

Each line is a `RolloutLine`: `timestamp`, optional `ordinal`, and a flattened
`{type, payload}` item
([history/src/lib.rs#L357-L368](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/history/src/lib.rs#L357-L368)).
Top-level `type` values (**Upstream fact**,
[rollout_payload.rs#L31-L72](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/history/src/rollout_payload.rs#L31-L72)):
`session_meta`, `response_item`, `inter_agent_communication`,
`inter_agent_communication_metadata`, `compacted`, `turn_context`,
`token_usage_record`, `world_state`, `retained_context`,
`security_risk_score`, `event_msg`, `realtime_item`.

There are two history modes
([protocol.rs#L791-L798](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/protocol/src/protocol.rs#L791-L798)).
The TUI and `codex exec` request `paginated` for every non-ephemeral new
thread. They fall back to `legacy` only when the server rejects pagination
([exec/src/lib.rs#L1461](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/exec/src/lib.rs#L1461),
[tui app_server_session.rs#L2170](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/tui/src/app_server_session.rs#L2170)).
The same is true at 0.160.0. Older rollouts, and clients that do not request
pagination, use `legacy`. `codex migrate-rollouts` converts legacy sessions
(**Live observation**, `codex --help`).

What is persisted
([policy.rs#L22-L283](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/rollout/src/policy.rs#L22-L283)):

- `response_item` always, for: `additional_tools`, `message`, `agent_message`,
  `reasoning`, `local_shell_call`, `function_call`, `tool_search_call`,
  `function_call_output`, `tool_search_output`, `custom_tool_call`,
  `custom_tool_call_output`, `web_search_call`, `image_generation_call`,
  `configuration_update`, `compaction`, `context_compaction`.
- `event_msg` in both modes: `token_count`, `thread_goal_updated`,
  `thread_rolled_back`, `turn_aborted`, `task_started`, `task_complete`,
  `thread_settings_applied`, `item_completed`. `TurnStarted`/`TurnComplete`
  serialize as `task_started`/`task_complete`
  ([protocol.rs#L1424-L1434](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/protocol/src/protocol.rs#L1424-L1434)).
- `event_msg` in **legacy only**: `user_message`, `agent_message`,
  `agent_reasoning`, `agent_reasoning_raw_content`, `entered_review_mode`,
  `exited_review_mode`, `patch_apply_end`, `context_compacted`,
  `mcp_tool_call_end`, `web_search_end`, `image_generation_end`, and
  non-completed `sub_agent_activity`.
- **Never persisted** (transient): `exec_command_begin`, `exec_command_end`,
  `exec_command_output_delta`, `mcp_tool_call_begin`, `error`, `warning`,
  and others.
- Paginated `item_completed` events carry a typed `TurnItem` (`UserMessage`,
  `AgentMessage`, `Reasoning`, `CommandExecution`, `FileChange`,
  `McpToolCall`, `WebSearch`, `Plan`, `ContextCompaction`, …;
  [items.rs#L42-L78](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/protocol/src/items.rs#L42-L78)).
  Command output above 64 KiB is middle-truncated with a marker before it is
  persisted.

Session/thread relationships: `session_meta.payload.id` is the thread,
`session_id` is the root thread, and `parent_thread_id`/`forked_from_id` link
subagents and forks
([SessionMeta](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/protocol/src/protocol.rs)).

## 6. Tool calls and results

- **Upstream fact**: the default shell tool is `exec_command`. It is a
  `function_call` whose `arguments` is a JSON **string** with a required `cmd`
  string plus optional `workdir`, `tty`, `yield_time_ms`, `max_output_tokens`,
  `shell`, `login`
  ([shell_spec.rs#L24-L116](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/tools/handlers/shell_spec.rs#L24-L116)).
  `write_stdin` continues a running process. `unified_exec` is Stable and
  enabled by default.
- **Upstream fact**: `function_call_output.output` is a string or an array of
  content items
  ([models.rs ResponseItem](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/protocol/src/models.rs#L1012-L1268)).
  For `exec_command` the text starts with a header: `Chunk ID:`,
  `Wall time: N seconds`, `Process exited with code N` or
  `Process running with session ID N`, then `Output:`
  ([tools/context.rs#L524-L546](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/tools/context.rs#L524-L546)).
- Correlation: `function_call.call_id` matches `function_call_output.call_id`.
  `custom_tool_call` (for example `apply_patch`) carries a raw string `input`.
- Paginated `CommandExecution` items carry structured `command` (argv),
  `cwd`, `status` (`in_progress|completed|failed|declined`),
  `aggregated_output`, `exit_code`, `duration`, `process_id`
  ([items.rs#L244](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/protocol/src/items.rs#L244)).

## 7. Timing, status, correlation

- Every line has a writer `timestamp`. `item_completed` adds
  `started_at_ms`/`completed_at_ms`
  ([protocol.rs#L1964-L1976](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/protocol/src/protocol.rs#L1964-L1976)).
- Exit status of `exec_command` appears only in output text for raw
  `function_call_output`. It is structured only in paginated
  `CommandExecution`.
- `token_usage_record` lines carry `thread_id`, `turn_id`, `response_id`, and
  usage. They are written after each model response that reports usage
  ([session/mod.rs#L4736-L4751](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/session/mod.rs#L4736-L4751)).

## 8. Missing or optional

- No OS process ID in raw tool records (unified exec `session_id` is not a PID).
- `exec_command_end` is never persisted, so do not design evidence around it.
- `reasoning` may be encrypted (`encrypted_content`). Do not try to decode it.

## 9. Controlled scenarios

- Run Codex inside a real sandbox: a disposable container or VM, or
  `bwrap`/`firejail` with a private `$HOME`. Inside it, set
  `HOME=$LAB/h CODEX_HOME=$LAB/h/.codex` (create the dir first). A HOME
  override alone is not isolation, because Codex can read and write anything
  the user can.
- Keep Codex's own sandbox on (`-s workspace-write` or `read-only`). Never use
  `--dangerously-bypass-approvals-and-sandbox` outside a disposable VM.
- Use a fabricated workspace (synthetic repo, fake `.env.example`-style
  values that are obviously fake, `*.invalid` hostnames).
- Cover both modes: a normal `codex exec` (paginated) and a resumed or
  migrated legacy rollout if one is available.

## 10. Evidence collection

Rollouts are append-only JSONL. Copy the file after the run ends. For a live
session, copy and drop a trailing partial line. Record `codex --version`,
`session_meta.payload.cli_version`, and `history_mode`. Ignore the SQLite
projections unless a scenario specifically targets them. If you do need them,
use `sqlite3 src.db ".backup dst.db"` while Codex is stopped.

## 11. Public-safe fixtures

Build fixtures by hand from the record shapes above, using synthetic IDs
(`00000000-0000-4000-8000-…`), `/synthetic/work` paths, and `.invalid`
domains. Never commit a real rollout, even a redacted one. The generator used
for the findings in this lab wrote only to a scratch directory.

## 12. Telltale identity and limits

- **Telltale implementation**: `codex.sessions`, `codex.archived_sessions`,
  `codex.headless_sessions` under `CodexHome`, recursive `*.jsonl`
  ([codex/mod.rs](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/codex/mod.rs)).
  See [session-sources.md](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/docs/session-sources.md),
  [source-validation-matrix.md](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/docs/source-validation-matrix.md),
  [agent-capability-profiles.md](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/docs/agent-capability-profiles.md),
  and the [Codex adapter spec](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/openspec/specs/codex-canonical-observation-v2-adapter/spec.md).
- Accepted auxiliaries are a closed list
  ([native.rs#L825-L868](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/codex/native.rs#L825-L868)).
  Any other discriminator rejects the whole source with
  `unknown_discriminator`
  ([canonical.rs#L103-L109](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/codex/canonical.rs#L103-L109)).
  Only four completed-item variants are accepted
  ([native.rs#L522](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/codex/native.rs#L522)).
- **Live observation** (Telltale `0.7.0-rc.2`, build `07a380d`, whose
  `telltale-sources` is identical to `2e8c56a`; synthetic rollouts; `scan
  --once --dry-run --client codex`): a baseline rollout parses. Adding a single
  `token_usage_record`, legacy `agent_message`, `turn_aborted`,
  `web_search_call`, or `exec_command_end` line makes the source fail with
  `unknown_discriminator` and zero records. See
  [compatibility-findings.md](compatibility-findings.md).
- `.jsonl.zst` files do not match the `jsonl` extension pattern.

## 13. Validation status and maintenance

- Upstream facts: pinned at `092d3acd` (and cross-checked at `a956835d` and
  `47379efd`).
- Live: only `--version`/`--help`, plus Telltale scans of synthetic files. No
  model run and no real rollout was read.
- Not validated: real rollout line frequencies, the Windows layout, and
  `thread_settings_applied` emission conditions.
- To update this guide: re-read `rollout/src/policy.rs`,
  `history/src/rollout_payload.rs`, `protocol/src/items.rs`, and
  `core/src/tools/handlers/shell_spec.rs` at the new tag. Then rerun the
  synthetic variants against the current Telltale build.
