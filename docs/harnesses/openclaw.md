# OpenClaw

Research guide for OpenClaw session evidence. Checked 2026-10-13.

Claim labels: **Upstream fact** (pinned link), **Live observation** (seen in
this lab), **Telltale implementation** (Telltale code/docs), **Open question**.

## 1. Upstream and docs

- Repository: <https://github.com/openclaw/openclaw>
- Docs: <https://docs.openclaw.ai>. The docs source is in the repo under `docs/`.
  The relevant pages are
  [concepts/session.md](https://github.com/openclaw/openclaw/blob/b8952d477f0c932d8ddc6da5c89cab5a169b6ff1/docs/concepts/session.md),
  [database-schemas/layout.md](https://github.com/openclaw/openclaw/blob/b8952d477f0c932d8ddc6da5c89cab5a169b6ff1/docs/reference/database-schemas/layout.md),
  [agent-schema-history.md](https://github.com/openclaw/openclaw/blob/b8952d477f0c932d8ddc6da5c89cab5a169b6ff1/docs/reference/database-schemas/agent-schema-history.md),
  [session-management-compaction/maintenance.md](https://github.com/openclaw/openclaw/blob/b8952d477f0c932d8ddc6da5c89cab5a169b6ff1/docs/reference/session-management-compaction/maintenance.md),
  and [platforms/windows.md](https://github.com/openclaw/openclaw/blob/b8952d477f0c932d8ddc6da5c89cab5a169b6ff1/docs/platforms/windows.md).

## 2. Versions

| What | Version | Commit |
| --- | --- | --- |
| Researched upstream | `v2026.10.2` (stable, 2026-10-12) | `b8952d477f0c932d8ddc6da5c89cab5a169b6ff1` |
| Last stable documenting JSONL as the store | `v2026.7.1` (2026-07-13) | `2d2ddc43d0dcf71f31283d780f9fe9ff4cc04fe4` |
| First release with SQLite sessions (agent schema 8) | `v2026.7.2-beta.1` (pre-release, 2026-07-15) | `3337cd3c525ba85eba171913eb35b49afe0b0b4b` (tag object) |
| First stable documenting SQLite as default | `v2026.8.1` (2026-08-30) | `ea806575e6450e4d1efdfc72c19f04be982a1b9b` |
| Locally installed | not installed | — |

**Version boundary.** Releases up to `v2026.7.1` used JSONL (**Upstream
fact**,
[session.md@v2026.7.1#L114-L117](https://github.com/openclaw/openclaw/blob/2d2ddc43d0dcf71f31283d780f9fe9ff4cc04fe4/docs/concepts/session.md#L114-L117)).
Agent schema 8, "sessions and transcripts moved into SQLite", first shipped in
`v2026.7.2-beta.1`
([agent-schema-history.md#L11-L20](https://github.com/openclaw/openclaw/blob/b8952d477f0c932d8ddc6da5c89cab5a169b6ff1/docs/reference/database-schemas/agent-schema-history.md#L11-L20)).
`v2026.8.1` is the first stable release whose docs name SQLite as the default
([session.md@v2026.8.1#L199-L203](https://github.com/openclaw/openclaw/blob/ea806575e6450e4d1efdfc72c19f04be982a1b9b/docs/concepts/session.md#L199-L203)).

## 3. Install and authentication

Operator-controlled: npm `openclaw` or the installer. The Gateway and model
providers are configured by the operator. On Windows there is a native CLI and
Gateway, a Windows Hub app, or a WSL2 Gateway (platforms/windows.md).

## 4. Storage and discovery

- **Upstream fact**: the state root is `~/.openclaw`, overridden by
  `OPENCLAW_STATE_DIR`
  ([cli/transcripts.md#L20-L34](https://github.com/openclaw/openclaw/blob/b8952d477f0c932d8ddc6da5c89cab5a169b6ff1/docs/cli/transcripts.md#L20-L34)).
- **Upstream fact** (v2026.10.2,
  [session.md#L232-L261](https://github.com/openclaw/openclaw/blob/b8952d477f0c932d8ddc6da5c89cab5a169b6ff1/docs/concepts/session.md#L232-L261)):
  - Runtime session rows and transcripts live in
    `~/.openclaw/agents/<agentId>/agent/openclaw-agent.sqlite`.
  - Archived transcript files live in `~/.openclaw/agents/<agentId>/sessions/`.
  - `sessions.json` plus hot JSONL are only the legacy migration source.
    `openclaw doctor --fix` imports them. Startup never falls back to them.
- **Upstream fact**: reset/delete archives are written to the sessions
  directory as `*.jsonl.deleted.<timestamp>.zst` (plain JSONL when zstd is
  unavailable). Opt-in cold storage writes `.jsonl.zst`
  ([maintenance.md#L20-L40, #L95-L129](https://github.com/openclaw/openclaw/blob/b8952d477f0c932d8ddc6da5c89cab5a169b6ff1/docs/reference/session-management-compaction/maintenance.md#L20-L40)).
- **Open question**: the native Windows state root (presumably
  `%USERPROFILE%\.openclaw`). The docs did not state it in the pages read.

## 5. Native format and relationships

### Legacy JSONL (≤ v2026.7.1, and files left behind after import)

**Upstream fact**
([session-management-compaction.md@v2026.7.1#L132-L145](https://github.com/openclaw/openclaw/blob/2d2ddc43d0dcf71f31283d780f9fe9ff4cc04fe4/docs/reference/session-management-compaction.md#L132-L145)):

- The first line is a header: `type: "session"`, `id`, `cwd`, `timestamp`,
  optional `parentSession`.
- Every later entry has `id` and `parentId` (a tree), plus a `type` of
  `message` (roles `user`/`assistant`/`toolResult`), `custom_message`,
  `custom`, `compaction`, or `branch_summary`.

### SQLite (agent schema 8+, default from v2026.8.1)

**Upstream fact**
([openclaw-agent-schema.sql](https://github.com/openclaw/openclaw/blob/b8952d477f0c932d8ddc6da5c89cab5a169b6ff1/src/state/openclaw-agent-schema.sql)):

```sql
session_nodes(session_key PK, current_session_id, entry_json, status, created_at, ...,
  last_activity_at) STRICT                                            -- L16-L49
session_windows(session_id PK, session_key -> session_nodes, previous_session_id,
  reason, created_at, updated_at, started_at, ended_at, status, model_provider,
  model, agent_harness_id, parent_session_key, ...) STRICT            -- L159-L183
transcript_events(session_id -> session_windows, seq, event_json TEXT,
  created_at, event_zstd BLOB, event_utf8_bytes, navigation_json,
  PRIMARY KEY(session_id, seq)) STRICT                                -- L566-L606
session_transcript_archives(session_id, generation, reason, encoding, archive_blob, ...)
session_transcript_cold_archives(session_id PK, archive_name, storage 'file'|'sqlite', ...)
```

`session_key` → `session_windows.session_id` (one window per reset, rollover,
or fork) → ordered `transcript_events.seq`. From schema 23, an event body is
either `event_json` or a zstd `event_zstd` BLOB. Readers must handle both.

## 6. Tool calls and results

**Upstream fact** (upstream test shapes,
[transcript-payload.test.ts#L336, #L404-L429](https://github.com/openclaw/openclaw/blob/b8952d477f0c932d8ddc6da5c89cab5a169b6ff1/src/config/sessions/transcript-payload.test.ts#L336)):
an assistant `message.content[]` block
`{type: "toolCall", id, name, arguments}` is answered by a `message` with
`role: "toolResult"` and `toolCallId`. Correlate on `toolCallId` = `id`. Tool
calls and their results are kept paired across compaction chunks
(compaction doc).

## 7. Timing, status, correlation

Entries carry `timestamp`. SQLite rows add `created_at`, and window/node
lifecycle times and `status`. **Open question**: tool execution timing and
exit status inside `event_json`.

## 8. Missing or optional

Process ID and exit code are not documented. Telltale's capability profile
lists ToolExecution as Unknown.

## 9. Controlled scenarios

Install inside a container/VM. Set `HOME` and `OPENCLAW_STATE_DIR` under
`$LAB/h`, and use a fake provider endpoint on `.invalid` or a local stub. Run a
pre-boundary release (`v2026.7.1`) and a current one to produce both stores.
Then run `doctor --fix` on a copy to observe the import and which files remain.

## 10. Evidence collection

Stop the Gateway first. Run `sqlite3 openclaw-agent.sqlite ".backup snap.db"`
(the WAL is folded in), and copy `agents/<id>/sessions/` as-is. Record the
`schema_meta` contents and `openclaw --version`.

## 11. Public-safe fixtures

JSONL fixtures should follow the documented header + `message` tree shape with
synthetic IDs. SQLite fixtures should be created from the pinned DDL with
synthetic `event_json`.

## 12. Telltale identity and limits

- **Telltale implementation**: `openclaw.agents`, `Home/.openclaw/agents`,
  recursive, file name contains `.jsonl`
  ([openclaw/mod.rs](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/openclaw/mod.rs)).
  `OPENCLAW_STATE_DIR` is not consulted. The SQLite store is not read. Known
  discriminators are `user`/`assistant`/`tool_call`/`tool_result`/
  `session_meta` and similar, with blocks `text`/`tool_use`/`tool_result`
  ([openclaw/native.rs#L270-L380](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/openclaw/native.rs#L270-L380)).
  Its fixtures use that shape. See the
  [OpenClaw/Qwen spec](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/openspec/specs/openclaw-qwen-canonical-observation-v2-adapters/spec.md)
  and [validation matrix](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/docs/source-validation-matrix.md)
  ("fixture-backed only").
- **Live observation** (Telltale `0.7.0-rc.2`/`07a380d`, synthetic files):
  - A JSONL file in the documented upstream shape (header + `message` entries
    with `toolCall`/`toolResult`) fails with `unknown_discriminator`. So does a
    single `type: "message"` user entry.
  - A zstd-compressed `sess-1.jsonl.deleted.<ts>.zst` is discovered and fails
    with `source_read`.
  - A Telltale-shape fixture parses.
- So on ≥ v2026.8.1 Telltale reaches only leftover legacy files and archives,
  and it rejects the documented legacy shape anyway.

## 13. Validation status and maintenance

- Upstream facts are pinned at `b8952d47` and `2d2ddc43`, and the boundary
  docs at `ea806575`. Not installed locally, and no real store was read.
- **Open question**: whether `event_json` in SQLite has the same shape as the
  legacy JSONL entries.
- To update: watch `agent-schema-history.md` and `openclaw-agent-schema.sql`
  for new schema versions.
