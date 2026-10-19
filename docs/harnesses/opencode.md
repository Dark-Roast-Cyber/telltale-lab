# OpenCode

Research guide for OpenCode SQLite session evidence. Checked 2026-10-13.

Claim labels: **Upstream fact** (pinned link), **Live observation** (seen in
this lab), **Telltale implementation** (Telltale code/docs), **Open question**.

## 1. Upstream and docs

- Canonical repository: <https://github.com/anomalyco/opencode>. `sst/opencode`
  resolves to the same repository via the GitHub API. The default branch is
  `dev`.
- Docs: <https://opencode.ai/docs>. The docs source is in the repo under
  `services/www/src/docs/content/`, for example
  [troubleshooting.mdx](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/services/www/src/docs/content/troubleshooting.mdx).

## 2. Versions

| What | Version | Commit |
| --- | --- | --- |
| Researched upstream (v2 line) | tag `v2.0.27` (2026-10-12) | `1f4d07a4a519185955ae8ab2ea3607805509e386` |
| Newest v2 tag seen | `v2.0.28` (2026-10-13) | `026b106bc5d41b679ffc413264229c340871e4d3` |
| Newest GitHub Release (v1 line) | `v1.19.0` (2026-10-11) | `733b2c627e5aec39cb33cc22373bdce33053ef2c` |
| First v2 tag | `v2.0.0` (2026-09-11) | `63f7ceecbed2d7d9a627518d935dd963b9d4ac9f` |
| Locally installed | `opencode v2.0.27` (**Live observation**, `--version`) | — |

The v2 tags have no GitHub Release objects. The two lines store sessions
differently (§5).

## 3. Install and authentication

Operator-controlled: install script, npm `opencode-ai`, or Desktop builds.
Providers are configured with `opencode auth`. In v2 a background service owns
the database by default; `--standalone` runs a private server instead
(**Live observation**, `opencode --help`).

## 4. Storage and discovery

- **Upstream fact** (v2.0.27): data root is `$XDG_DATA_HOME/opencode`, falling
  back to `~/.local/share/opencode`, on every platform with a home directory
  ([global-roots.ts](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/packages/util/src/global-roots.ts)).
  The CLI code does not use a macOS `Library` or Windows `AppData` branch.
- **Upstream fact**: the DB filename is `opencode.db` for channels
  `latest|dev|beta|next|prod` and `opencode-<channel>.db` for other channels.
  `OPENCODE_DB` overrides it (absolute, or relative to the data root)
  ([database-path.ts](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/packages/cli/src/database-path.ts)).
- **Upstream fact**: WAL mode, `busy_timeout=5000`, and file modes 0600 on
  `db`, `-wal`, `-shm`
  ([database.ts](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/packages/core/src/database/database.ts)).
- **Open question**: the Desktop app's data root on Windows and macOS.
  Telltale's Windows notes cite `AppData` locations for Desktop v2.0.24.

## 5. Native format and relationships

### v1 line (through v1.19.0)

- **Upstream fact**: tables `session`, `message(id, session_id, data JSON)`,
  `part(id, message_id, session_id, data JSON)`
  ([v1.19.0 session/sql.ts#L22-L92](https://github.com/anomalyco/opencode/blob/733b2c627e5aec39cb33cc22373bdce33053ef2c/packages/core/src/session/sql.ts#L22-L92)).
  Tool parts carry `callID` and `state.status` of
  `pending|running|completed|error`
  ([message-v2.ts#L300-L370](https://github.com/anomalyco/opencode/blob/733b2c627e5aec39cb33cc22373bdce33053ef2c/packages/opencode/src/session/message-v2.ts#L300-L370)).
  This is the shape Telltale's adapter targets.

### v2 line (v2.0.0+)

- **Upstream fact**: a fresh database is bootstrapped from `schema.gen.ts`
  ([migration.ts](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/packages/core/src/database/migration.ts)).
  It has **no `message` or `part` tables**. Session history lives in
  ([schema.gen.ts#L148-L224](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/packages/core/src/database/schema.gen.ts#L148-L224)):

```sql
CREATE TABLE session_v2 (id text PRIMARY KEY, project_id text NOT NULL,
  workspace_id text, parent_id text, fork_session_id text, fork_boundary text,
  slug text NOT NULL, directory text NOT NULL, path text, title text,
  version text NOT NULL, ..., agent text, model text,
  time_created integer NOT NULL, time_updated integer NOT NULL, time_idle integer, ...);
CREATE TABLE session_message (id text PRIMARY KEY,
  session_id text NOT NULL REFERENCES session_v2(id) ON DELETE CASCADE,
  type text NOT NULL, seq integer NOT NULL,
  time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL);
CREATE UNIQUE INDEX session_message_session_seq_idx ON session_message(session_id, seq);
CREATE TABLE event (id text PRIMARY KEY, aggregate_id text NOT NULL, seq integer NOT NULL,
  created integer DEFAULT 0 NOT NULL, type text NOT NULL, data text NOT NULL);
```

  `session_pending`, `session_inbox`, and `event`/`event_sequence` hold queued
  input and the event-sourced log.
- **Upstream fact**: a `session_message` row is the encoded message with `id`
  and `type` moved into columns and the rest stored as JSON in `data`
  ([projector.ts#L395-L400](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/packages/core/src/session/projector.ts#L395-L400)).
  Message `type` is one of `user`, `synthetic`, `system`, `skill`, `shell`,
  `assistant`, `compaction`, `idle`, `agent-switched`, `model-switched`,
  `location-switched`
  ([session-message.ts#L45-L322](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/packages/schema/src/session-message.ts#L45-L322)).
  Ordering within a session is `seq`.
- **Upstream fact**: upgraded v1 databases are migrated into the v2 tables
  ([v1-migration.bun.ts](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/packages/core/src/database/v1-migration.bun.ts)).
  v2 core defines no `message`/`part` table writers
  ([session/sql.ts](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/packages/core/src/session/sql.ts)).
  **Open question**: whether migrated databases keep the old v1 tables, and
  for how long.

## 6. Tool calls and results (v2)

**Upstream fact**
([session-message.ts#L112-L246](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/packages/schema/src/session-message.ts#L112-L246)):

- Tools are entries in an `assistant` message's `content[]` with
  `type: "tool"`, `id` (the call ID), `name`, optional `executed`, `state`,
  and `time {created, ran?, completed?}`.
- `state.status` is `streaming` (`input` is a string), `running` (`input`,
  `metadata`), `completed` (`input`, non-empty `content[]`, `metadata?`), or
  `error` (`input`, `error`, `content?`). There is no `pending` state in v2.
- The call and its result live in the same content entry, so there is no
  cross-row correlation. User `!` shell commands are separate `shell` messages
  with `command`, `status`, `exit?`, `output?`, and
  `time {created, completed?}`.

## 7. Timing, status, correlation

Times are epoch milliseconds. `assistant.time` has `created`, `streamed?`, and
`completed?`. Tool `time.ran`/`completed` and the `shell` `exit` are
source-reported. `idle` messages mark turn boundaries with
`outcome: succeeded|failed|interrupted`. There is no OS PID.

## 8. Missing or optional

Tool `time.ran`/`completed`, `assistant.tokens`, `cost`, and `error` are
optional. Reasoning text is stored as `reasoning` content entries.

## 9. Controlled scenarios

Use a real sandbox with `HOME`, `XDG_DATA_HOME`, `XDG_CONFIG_HOME`,
`XDG_STATE_HOME`, and `XDG_CACHE_HOME` all under `$LAB/h`. Prefer
`--standalone`, so no shared background service writes into an operator store.
Even `--help` created `~/.config/opencode`, `~/.cache/opencode/bin`, and
`~/.local/state/opencode` under the override (**Live observation**). Use
fabricated repos and `.invalid` domains. Exercise one completed tool, one
error tool, one user shell command, and one interrupted turn.

## 10. Evidence collection

Stop OpenCode, or at least the service, first. Then
`sqlite3 opencode.db ".backup snapshot.db"`. The backup API includes committed
WAL content. Never copy `opencode.db` alone while `-wal` is live. Record
`PRAGMA user_version`, the `migration` table rows, and the list from
`sqlite_master`.

## 11. Public-safe fixtures

Create the schema from the DDL above with synthetic rows (`ses_…`, `msg_…`,
`/synthetic/work`). The lab generator wrote a minimal
`session_v2`/`session_message` DB to a scratch directory only.

## 12. Telltale identity and limits

- **Telltale implementation**: `opencode.sqlite`, `DataHome/opencode/opencode.db`
  as an exact filename
  ([opencode/mod.rs](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/opencode/mod.rs)).
  macOS `DataHome` is `~/Library/Application Support`. Extraction reads only
  the `message` and `part` tables if they exist
  ([native.rs#L248-L276](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/opencode/native.rs#L248-L276)).
  See [opencode-live-ingestion.md](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/docs/opencode-live-ingestion.md),
  [session-sources.md](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/docs/session-sources.md),
  and the [OpenCode adapter spec](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/openspec/specs/opencode-sqlite-canonical-observation-v2-adapter/spec.md).
- **Live observation** (Telltale `0.7.0-rc.2`/`07a380d`): a synthetic v2-shape
  DB with one user message and one assistant message with a completed tool was
  discovered and reported `source_processing.parse_success_source_count` 1, records 0, failures [], with the
  `selected_sources_produced_no_records` and `source_coverage_partial` diagnostic warnings (no scanner error).
- Not reached: `OPENCODE_DB` overrides, `opencode-<channel>.db`, and on macOS
  the CLI's XDG path.

## 13. Validation status and maintenance

- Upstream facts are pinned at `1f4d07a4` (v2) and `733b2c62` (v1). The v2
  schema was also confirmed at v2.0.0, v2.0.13, v2.0.20, and v2.0.24.
- Live: `--version`/`--help`, plus a Telltale scan of a synthetic DB. No real
  store was opened.
- **Open question**: Telltale's Desktop v2.0.24 validation read `part` rows,
  which suggests that store was upgraded from v1 and kept its v1 tables.
  Confirm with a fresh sandboxed v2 store.
- To update: diff `packages/core/src/database/schema.gen.ts`,
  `packages/schema/src/session-message.ts`, and `packages/cli/src/database-path.ts`
  at the new tag.
