# Qwen Code

Research guide for Qwen Code chat-recording evidence. Checked 2026-10-13.

Claim labels: **Upstream fact** (pinned link), **Live observation** (seen in
this lab), **Telltale implementation** (Telltale code/docs), **Open question**.

## 1. Upstream and docs

- Repository: <https://github.com/QwenLM/qwen-code>
- Docs: <https://qwenlm.github.io/qwen-code-docs/en/users/overview>. The docs
  source is in the repo under `docs/users/`, for example
  [settings.md](https://github.com/QwenLM/qwen-code/blob/c1a8218f38203e272e6e965778ed6a2795cfeed7/docs/users/configuration/settings.md),
  [auth.md](https://github.com/QwenLM/qwen-code/blob/c1a8218f38203e272e6e965778ed6a2795cfeed7/docs/users/configuration/auth.md),
  and [sandbox.md](https://github.com/QwenLM/qwen-code/blob/c1a8218f38203e272e6e965778ed6a2795cfeed7/docs/users/features/sandbox.md).
- The record format is defined in
  [`chatRecordingService.ts`](https://github.com/QwenLM/qwen-code/blob/c1a8218f38203e272e6e965778ed6a2795cfeed7/packages/core/src/services/chatRecordingService.ts).

## 2. Versions

| What | Version | Commit |
| --- | --- | --- |
| Researched upstream | `v0.25.1` (stable, 2026-10-11) | `c1a8218f38203e272e6e965778ed6a2795cfeed7` |
| Locally installed | not installed (`qwen` not on PATH) | — |

## 3. Install and authentication

Operator-controlled: npm `@qwen-code/qwen-code`. Authentication is configured
by the operator (see auth.md). Do not automate around it.

## 4. Storage and discovery

**Upstream fact**
([storage.ts#L172-L203](https://github.com/QwenLM/qwen-code/blob/c1a8218f38203e272e6e965778ed6a2795cfeed7/packages/core/src/config/storage.ts#L172-L203),
[#L615-L623](https://github.com/QwenLM/qwen-code/blob/c1a8218f38203e272e6e965778ed6a2795cfeed7/packages/core/src/config/storage.ts#L615-L623),
[chatRecordingService.ts#L1354-L1370](https://github.com/QwenLM/qwen-code/blob/c1a8218f38203e272e6e965778ed6a2795cfeed7/packages/core/src/services/chatRecordingService.ts#L1354-L1370)):

- The global dir is `$QWEN_HOME`, or `~/.qwen`, or `<tmpdir>/.qwen` when there
  is no home directory.
- The runtime base dir is the global dir unless `QWEN_RUNTIME_DIR` (or a
  pinned runtime context) overrides it.
- Transcripts are written to
  `<runtime>/projects/<sanitized-cwd>/chats/<sessionId>.jsonl`.
  `<sessionId>.runtime.json` sits beside each one.
- Large tool outputs can go to `<runtime>/tmp/<project-hash>/tool-results/`.
- The class comment still says `~/.qwen/tmp/<project_id>/chats/`
  ([#L1133](https://github.com/QwenLM/qwen-code/blob/c1a8218f38203e272e6e965778ed6a2795cfeed7/packages/core/src/services/chatRecordingService.ts#L1133)).
  The code above is authoritative.

Windows: `os.homedir()` makes this `%USERPROFILE%\.qwen`. **Open question**:
not checked on a host.

## 5. Record format

**Upstream fact**: one `ChatRecord` per line
([#L355-L520](https://github.com/QwenLM/qwen-code/blob/c1a8218f38203e272e6e965778ed6a2795cfeed7/packages/core/src/services/chatRecordingService.ts#L355-L520)).
It carries:

- `uuid`, `parentUuid` (a tree), `sessionId`, `timestamp`, `cwd`, `version`,
  and optional `gitBranch`
- `type` of `user`, `assistant`, `tool_result`, or `system`, with an optional
  `subtype` from roughly 40 values (`chat_compression`, `slash_command`,
  `ui_telemetry`, `custom_title`, `session_model`, `file_history_snapshot`,
  `turn_result`, `managed_session_*`, `agent_message`, …)
- `message`, a Gemini `Content` object (`role` + `parts`) "stored in the exact
  format needed for API calls … text, functionCall, functionResponse, thought
  parts" ([#L458-L466](https://github.com/QwenLM/qwen-code/blob/c1a8218f38203e272e6e965778ed6a2795cfeed7/packages/core/src/services/chatRecordingService.ts#L458-L466))
- `model`, `usageMetadata`, `toolCallResult`, `systemPayload`, `provenance`,
  and subagent fields `agentId`, `isSidechain`, `agentRunId`

Records can also go to a "managed session" sink instead of the legacy file
([#L1635-L1690](https://github.com/QwenLM/qwen-code/blob/c1a8218f38203e272e6e965778ed6a2795cfeed7/packages/core/src/services/chatRecordingService.ts#L1635-L1690)).
**Open question**: where that sink writes, and in what shape.

## 6. Tool calls and results

**Upstream fact**:

- An `assistant` record's `message.parts[]` contains
  `{functionCall: {id, name, args}}`
  ([recordAssistantTurn #L2774](https://github.com/QwenLM/qwen-code/blob/c1a8218f38203e272e6e965778ed6a2795cfeed7/packages/core/src/services/chatRecordingService.ts#L2774)).
- A `tool_result` record's `message.parts[]` contains
  `{functionResponse: {id, name, response}}`, plus `toolCallResult`
  (`callId`, `status`, display data)
  ([recordToolResult #L2940](https://github.com/QwenLM/qwen-code/blob/c1a8218f38203e272e6e965778ed6a2795cfeed7/packages/core/src/services/chatRecordingService.ts#L2940)).
- Correlate on `functionResponse.id` = `functionCall.id`, or
  `toolCallResult.callId`. **Open question**: confirm in a live capture that
  the IDs are always present.

## 7. Timing, status, correlation

Each record has a `timestamp`. Tool status is `toolCallResult.status`. There
are no tool start/end times or OS PIDs in the documented interface.

## 8. Missing or optional

`message` is optional (for example on `system` records), and `toolCallResult`
fields are partial. Thought parts may appear in `parts`.

## 9. Controlled scenarios

Container/VM, with `HOME`, `QWEN_HOME`, and `QWEN_RUNTIME_DIR` all under
`$LAB/h`. Use a fabricated repo and `.invalid` domains. Qwen's own sandbox
(sandbox.md) is a second layer, not the isolation boundary.

## 10. Evidence collection

Copy `projects/<cwd>/chats/` after the run, plus the matching
`tmp/<hash>/tool-results/`. Drop trailing partial lines from live files.
Record `qwen --version` and the `version` field from the records.

## 11. Public-safe fixtures

Hand-build fixtures with Gemini `Content` parts, synthetic UUIDs, and
synthetic text. The lab generator wrote only to scratch.

## 12. Telltale identity and limits

- **Telltale implementation**: `qwen.projects`, `Home/.qwen/projects`,
  recursive `*.jsonl`
  ([qwen/mod.rs](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/qwen/mod.rs)).
  `QWEN_HOME`/`QWEN_RUNTIME_DIR` are not consulted. Known discriminators do not
  include `system`. Tool extraction reads `content[]` blocks
  (`text`/`tool_use`/`tool_result`) or `tool_calls`, not `message.parts`
  ([qwen/native.rs#L282-L440](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/qwen/native.rs#L282-L440)).
  See the [OpenClaw/Qwen spec](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/openspec/specs/openclaw-qwen-canonical-observation-v2-adapters/spec.md)
  and the matrix ("fixture-backed only").
- **Live observation** (Telltale `0.7.0-rc.2`/`07a380d`, synthetic files in
  the upstream shape):
  - A user-only file parses (1 user message).
  - user + assistant `functionCall` + `tool_result` `functionResponse` fails
    with `invalid_tool_result`.
  - Adding a `system`/`ui_telemetry` record fails with
    `unknown_discriminator`.

## 13. Validation status and maintenance

- Upstream facts are pinned at `c1a8218f`. Not installed, and no real store
  was read.
- **Open question**: how often `system` records occur in ordinary sessions.
  The code builds `system` anchor records for `custom_title` and
  `session_source`
  ([#L1992-L2020](https://github.com/QwenLM/qwen-code/blob/c1a8218f38203e272e6e965778ed6a2795cfeed7/packages/core/src/services/chatRecordingService.ts#L1992-L2020)).
  It is not yet confirmed when they are written. Check with a sandboxed
  capture.
- To update: re-read the `ChatRecord` interface and `Storage.getProjectDir` at
  each release.
