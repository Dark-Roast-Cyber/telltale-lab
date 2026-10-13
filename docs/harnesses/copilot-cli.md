# GitHub Copilot CLI

Research guide for Copilot CLI session evidence. Checked 2026-10-13.

Claim labels: **Upstream fact** (pinned link), **Live observation** (seen in
this lab), **Telltale implementation** (Telltale code/docs), **Open question**.

## 1. Upstream and docs

- Repository (README, changelog, installer; the CLI source is not published):
  <https://github.com/github/copilot-cli>
- Docs:
  [CLI configuration directory reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference),
  [CLI best practices](https://docs.github.com/en/copilot/how-tos/copilot-cli/cli-best-practices),
  and [session data](https://docs.github.com/en/copilot/concepts/security-governance-and-network-settings/session-data).
  These docs are not versioned. Quotes below were read on 2026-10-13.

## 2. Versions

| What | Version | Commit |
| --- | --- | --- |
| Researched upstream | `v1.0.96` (stable, 2026-10-12) | `dcdc0273c0250d8b32677ca99bc0e1f5006daa89` |
| Locally installed | `GitHub Copilot CLI 1.0.78` (**Live observation**, `--version`) | `v1.0.78` = `2392889bf7d2d3f3f9a7ad354c6017a21e4f9928` |

The changelog at `v1.0.96` ends at the 1.0.95 entry.

## 3. Install and authentication

Operator-controlled: `install.sh`, npm, or a package manager. Sign in with a
GitHub account that has Copilot access. Non-interactive runs use `-p`. Avoid
`--allow-all*` outside a disposable VM.

## 4. Storage and discovery

- **Upstream fact** (config dir reference): config, session history, and logs
  live in `~/.copilot`. `COPILOT_HOME` relocates it; `--config-dir` is a
  legacy equivalent. On Windows this is `C:\Users\<user>\.copilot`. Older XDG
  locations are migrated to `~/.copilot` when `COPILOT_HOME` is unset.
- **Upstream fact**: relevant contents are
  - `logs/process-{timestamp}-{pid}.log` (one per session), plus
    `logs/extensions/`
  - `session-state/<session-id>/` with `events.jsonl` and workspace artifacts
    (`workspace.yaml`, `plan.md`, `checkpoints/`, `files/` per the
    best-practices page)
  - `session-store.db`, a SQLite store for cross-session indexing and search
- **Live observation** (1.0.78 `--help`): `--log-dir` defaults to
  `~/.copilot/logs/`. Even `--help` extracted the package into
  `$HOME/.cache/copilot/pkg/linux-x64/1.0.78/` with `COPILOT_HOME` set.
- **Upstream fact** (changelog at `dcdc0273`):
  - 0.0.342: new sessions are stored in `~/.copilot/session-state`
    ([changelog.md#L3252-L3257](https://github.com/github/copilot-cli/blob/dcdc0273c0250d8b32677ca99bc0e1f5006daa89/changelog.md#L3252-L3257))
  - 0.0.422: usage metrics are persisted to `events.jsonl`
    ([#L2393](https://github.com/github/copilot-cli/blob/dcdc0273c0250d8b32677ca99bc0e1f5006daa89/changelog.md#L2393))
  - 1.0.40: `--config-dir` is deprecated for `COPILOT_HOME`
    ([#L1694](https://github.com/github/copilot-cli/blob/dcdc0273c0250d8b32677ca99bc0e1f5006daa89/changelog.md#L1694))
  - 1.0.52: old process logs in `~/.copilot/logs/` are pruned at startup
    ([#L1484](https://github.com/github/copilot-cli/blob/dcdc0273c0250d8b32677ca99bc0e1f5006daa89/changelog.md#L1484))

## 5. Native format

- **Upstream fact**: there is no published schema for `events.jsonl` or for
  process log lines.
- **Telltale implementation**: the process-log adapter reads leading RFC 3339
  timestamps, `Workspace initialized: <id>`, `Accumulated output items (N):
  [JSON array]` with Responses-style items (`function_call`, `reasoning`, …),
  and `Session completed.`
  ([fixture](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/tests/fixtures/session_stores/copilot/process-fixture.log),
  [spec](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/openspec/specs/copilot-process-log-canonical-observation-v2-adapter/spec.md)).
  **Open question**: whether 1.0.96 still writes these lines at the default
  log level.
- **Open question**: `events.jsonl` record types and tool fields. Capture them
  live before writing fixtures.

## 6. Tool calls and results

Process logs, per Telltale's model: `function_call` items with `name`,
`arguments` (a JSON string), and `call_id`. Results appear only on some
records. `events.jsonl` presumably has richer tool lifecycle data, but this is
an **Open question**.

## 7. Timing, status, correlation

Process logs give per-line timestamps. The PID is in the filename (Telltale
does not extract it). The workspace ID is used as the session ID. There are no
exit codes.

## 8. Missing or optional

Per Telltale's capability profile: no user context, no content parts, and
partial tool results.

## 9. Controlled scenarios

Container/VM, with `HOME`, `COPILOT_HOME`, and `XDG_CACHE_HOME` under
`$LAB/h`. Use `--log-dir $LAB/h/logs-copilot` if you also want a Telltale
project-local copy. Use a fabricated repo and `.invalid` URLs with
`--allow-url`/`--deny-url` set explicitly.

## 10. Evidence collection

After the session exits, copy `logs/`, `session-state/<id>/`, and (if needed)
`sqlite3 session-store.db ".backup snap.db"`. Record `copilot --version`. Note
that startup pruning can delete old process logs.

## 11. Public-safe fixtures

Hand-build process-log lines and JSON items with synthetic IDs. Do not build
`events.jsonl` fixtures until a live capture defines the shape.

## 12. Telltale identity and limits

- **Telltale implementation**: `copilot.process_log`, **project-local only**,
  `<project>/logs/copilot/*.log`, non-recursive, with no home-relative root
  ([copilot/mod.rs](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/copilot/mod.rs),
  [session-sources.md](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/docs/session-sources.md)).
  The default `~/.copilot/logs`, `session-state/*/events.jsonl`, and
  `session-store.db` are not acquired.
- **Telltale implementation**: install inventory for `copilot` checks only the
  VS Code extensions `github.copilot`/`github.copilot-chat`. It does not check
  a `copilot` executable or npm package
  ([copilot/install.rs](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/copilot/install.rs)).
- **Live observation** (Telltale `0.7.0-rc.2`/`07a380d`):
  - With the Telltale fixture log copied to
    `$HOME/.copilot/logs/process-*.log`, `scan --client copilot` found 0
    sources.
  - The same file under `<project>/logs/copilot/` with an explicit
    `--project-config` was found and parsed (3 records).
  - Without `--project-config`, a copy under `$HOME/github/proj/logs/copilot`
    was not found. **Open question**: whether the default project roots apply
    when `--root` is explicit.

## 13. Validation status and maintenance

- Upstream facts come from docs.github.com (read 2026-10-13) and the changelog
  at `dcdc0273`.
- Live: `--version`/`--help`, plus Telltale scans of synthetic trees. No
  session was run.
- Next step: run one sandboxed session, record the `events.jsonl` types and
  current process-log lines, and decide whether `~/.copilot` sources need
  their own Telltale identity. That is a Telltale scope decision, not lab work.
