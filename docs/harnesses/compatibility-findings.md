# Compatibility findings: upstream storage vs Telltale acquisition

This file lists only confirmed or strongly evidenced differences. Anything
weaker is marked **OPEN**. Checked 2026-10-13.

## How the findings were produced

- **Upstream side**: source or docs read at pinned commits (linked per
  finding). No harness was run beyond `--version`/`--help`, and no real
  session store was read.
- **Telltale side**: Telltale `0.7.0-rc.2`, build `07a380d`. Its
  `crates/telltale-sources` and `crates/telltale-schema` are identical to
  `2e8c56a` (checked with `git diff --stat 07a380d 2e8c56a`). Each run used a
  synthetic tree in a scratch directory:

  ```sh
  env -i PATH=/usr/bin:/bin HOME=$FX telltale scan --once --root $FX --dry-run \
    --client <id> --no-local-config --install-inventory-disabled \
    --state-path $TMP/s.json --log-path $TMP/l.jsonl
  ```

  Results were read from `source_processing` in the health event.
- **Status values**: **Confirmed** means the Telltale behavior was observed on
  a synthetic file whose shape comes from pinned upstream code or tests.
  **Strong** means the difference is visible in both code bases but was not
  executed. Neither status means a real harness-generated store was tested.

Links: `TT` = `https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b`.

## Codex (upstream `rust-v0.160.0` `a956835d` through `rust-v0.162.1` `092d3acd`)

**F1. `token_usage_record` lines reject the whole rollout. Confirmed.**

- Upstream:
  - `token_usage_record` is a top-level rollout item
    ([rollout_payload.rs#L54-L56](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/history/src/rollout_payload.rs#L54-L56)).
  - It is always persisted
    ([policy.rs#L42-L48](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/rollout/src/policy.rs#L42-L48)).
  - It is written after each model response that reports usage
    ([session/mod.rs#L4736-L4751](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/session/mod.rs#L4736-L4751)).
  - The payload has no `type` field
    ([protocol.rs#L2293-L2302](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/protocol/src/protocol.rs#L2293-L2302)).
  - The same holds at Telltale's own evidence commit `47379efd`.
- Telltale: the discriminator falls through to `token_usage_record`, which is
  not in `is_known_codex_discriminator`
  ([TT/…/codex/native.rs#L767-L785](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/codex/native.rs#L767-L785)).
  The result is `unknown_discriminator`
  ([canonical.rs#L103-L109](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/codex/canonical.rs#L103-L109)).
- Repro: take a baseline rollout (`session_meta`, `task_started`, user
  `message`, `function_call` `exec_command`, `function_call_output`,
  assistant `message`, `task_complete`), which parses with 7 records. Insert
  one `{"type":"token_usage_record","payload":{"thread_id":…,"turn_id":…,"session_id":…,"root_turn_id":…,"response_id":…,"usage":{…},"turn_token_usage":{…},"thread_token_usage":{…}}}`
  line. The result is `parse_err 1`, `unknown_discriminator`, 0 records.
- Impact: if real rollouts contain this line (the code says every turn with
  usage writes one), Codex acquisition would fail for every current session.
  **OPEN**: confirm with one sandboxed real rollout. Telltale reports bounded
  live validation, which this finding does not explain.

**F2. Legacy-mode `event_msg` `agent_message` rejects the rollout. Confirmed.**

- Upstream: `UserMessage`, `AgentMessage`, `PatchApplyEnd`, `McpToolCallEnd`,
  `WebSearchEnd`, `ContextCompacted`, and others are persisted only in legacy
  history mode
  ([policy.rs#L141-L158](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/rollout/src/policy.rs#L141-L158)).
  Legacy is the `ThreadHistoryMode` default
  ([protocol.rs#L791-L798](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/protocol/src/protocol.rs#L791-L798)),
  but the TUI and `exec` request `paginated` for new threads
  ([exec/src/lib.rs#L1461](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/exec/src/lib.rs#L1461)).
- Telltale: `user_message` is accepted, but `agent_message`,
  `patch_apply_end`, `mcp_tool_call_end`, `web_search_end`, and
  `context_compacted` are not known.
- Repro: add `{"type":"event_msg","payload":{"type":"agent_message","message":"…"}}`
  to the baseline. Result: `unknown_discriminator`. (A `user_message` event
  alone parses: 8 records.)
- Affects older rollouts and any client that does not request pagination.

**F3. Other persisted `event_msg` and `response_item` types reject the rollout. Confirmed for `turn_aborted` and `web_search_call`; Strong for the rest.**

- Upstream, persisted in both modes: `turn_aborted`, `thread_rolled_back`,
  `thread_goal_updated`, `thread_settings_applied`
  ([policy.rs#L127-L140](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/rollout/src/policy.rs#L127-L140)).
- Upstream, persisted `response_item` types: `local_shell_call`,
  `web_search_call`, `tool_search_call`, `tool_search_output`,
  `additional_tools`, `agent_message`, `compaction`, `context_compaction`,
  `configuration_update`, `image_generation_call`
  ([policy.rs#L80-L101](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/rollout/src/policy.rs#L80-L101)).
- Upstream, top-level item types: `compacted`, `retained_context`,
  `security_risk_score`, `inter_agent_communication*`, `realtime_item`.
- Telltale: none of these are in the auxiliary list
  ([native.rs#L825-L868](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/codex/native.rs#L825-L868))
  or in the known discriminators.
- Repro: add `{"type":"event_msg","payload":{"type":"turn_aborted","turn_id":"t","reason":"interrupted"}}`
  or `{"type":"response_item","payload":{"type":"web_search_call","status":"completed","action":{"type":"search","query":"x.invalid"}}}`.
  Both give `unknown_discriminator`.

**F4. Paginated `item_completed` accepts only 4 of 20 `TurnItem` variants. Strong.**

- Upstream: paginated mode persists every `ItemCompleted`
  ([policy.rs#L249-L281](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/rollout/src/policy.rs#L249-L281)).
  The variants include `FileChange`, `McpToolCall`, `WebSearch`, `Plan`, and
  `ContextCompaction`
  ([items.rs#L42-L78](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/protocol/src/items.rs#L42-L78)).
- Telltale: anything other than `AgentMessage|UserMessage|Reasoning|CommandExecution`
  returns "completed item variant is unsupported"
  ([native.rs#L522](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/codex/native.rs#L522)).
  Telltale's test rejects `Plan` on purpose.
- Repro idea: a valid paginated rollout plus one `item_completed` with
  `item.type: "FileChange"`.

**F5. Rejection of `exec_command_begin`/`exec_command_end` is harmless. Confirmed (clarification).**
Upstream lists both as transient and never persisted
([policy.rs#L160-L224](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/rollout/src/policy.rs#L160-L224)).
Telltale rejecting them (observed: `unknown_discriminator`) only matters for
hand-made fixtures.

**F6. Opt-in `.jsonl.zst` rollouts are not discovered. Strong.**
Feature `local_thread_store_compression` is default off
([features/src/lib.rs#L1243-L1247](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/features/src/lib.rs#L1243-L1247)).
When enabled, it compresses rollouts older than 7 days in `sessions/` and
`archived_sessions/`. Telltale's pattern is `Extension("jsonl")`.
Repro idea: `zstd` a baseline rollout to `*.jsonl.zst` and scan; expect 0
sources.

- **OPEN**: `codex.headless_sessions` (`$CODEX_HOME/headless`). No upstream
  writer was found. Upstream defines only `sessions` and `archived_sessions`
  ([rollout/src/lib.rs#L86-L87](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/rollout/src/lib.rs#L86-L87)),
  and exec sessions are marked by `source: "exec"`.
- **Not a difference**: the current shell tool is `function_call`
  `exec_command` with a JSON-string `arguments` and a `cmd` string. Telltale
  keeps `arguments` as-is.

## Claude Code (upstream `v2.1.296` `2301018b`)

**F7. `thinking` content blocks reject the whole transcript. Confirmed (Telltale); Strong (upstream).**

- Upstream: the changelog refers to "tool call, tool result or thinking blocks
  that a real session keeps"
  ([CHANGELOG.md#L145](https://github.com/anthropics/claude-code/blob/2301018b1f61073c501a8e7a4813ef48c239163b/CHANGELOG.md#L145)).
  The transcript format is officially internal
  ([sessions doc](https://code.claude.com/docs/en/sessions)).
- Telltale: content blocks other than `text`/`tool_use`/`tool_result` return
  `unknown_content_block`
  ([TT/…/claude/canonical.rs#L125-L135](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/claude/canonical.rs#L125-L135)).
- Repro: in a parsing 3-line transcript, change the assistant content to
  `[{"type":"thinking","thinking":"…","signature":"x"},{"type":"tool_use",…}]`.
  Result: `unknown_content_block`.
- **OPEN**: whether real transcripts persist thinking blocks with this exact
  tag. Telltale reports bounded live validation, which suggests either they
  don't or the sampled sessions had none.

**F8. `CLAUDE_CONFIG_DIR` relocations are not discovered. Strong.**
Upstream: `CLAUDE_CONFIG_DIR` moves session history
([env-vars doc](https://code.claude.com/docs/en/env-vars),
[sessions doc](https://code.claude.com/docs/en/sessions)). Telltale resolves
only `Home/.claude/projects`
([claude/mod.rs](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/claude/mod.rs)).
Repro idea: start a sandboxed session with `CLAUDE_CONFIG_DIR=$LAB/alt` and
scan `--root $HOME`.

- **OPEN**: top-level non-message entries (attachment, system, summary, and so
  on). Telltale rejects unknown `type` values (observed for guessed
  `system`/`attachment`/`summary` lines), but the real tags are unverified.

## OpenCode (upstream v2 `v2.0.0` `63f7ceec` through `v2.0.27` `1f4d07a4`)

**F9. Fresh v2 databases produce no records; only a diagnostic warning signals it. Confirmed.**

- Upstream: the v2 bootstrap schema has `session_v2`, `session_message`,
  `session_pending`, `session_inbox`, and `event`, and no `message`/`part`
  ([schema.gen.ts#L148-L224](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/packages/core/src/database/schema.gen.ts#L148-L224)).
  The same holds at v2.0.0, v2.0.13, v2.0.20, and v2.0.24. v1.19.0 still has
  `message`/`part`
  ([v1.19.0 session/sql.ts#L68-L92](https://github.com/anomalyco/opencode/blob/733b2c627e5aec39cb33cc22373bdce33053ef2c/packages/core/src/session/sql.ts#L68-L92)).
- Telltale: reads only `message` and `part` if present
  ([TT/…/opencode/native.rs#L248-L276](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/opencode/native.rs#L248-L276)).
- Repro: create `opencode/opencode.db` with `project`, `session_v2`, and
  `session_message` holding a user row and an assistant row whose `data`
  contains `content:[{type:"tool",state:{status:"completed",…}}]`. Result:
  `parse_ok 1, records 0, failures []`. The scan summary does carry the
  diagnostic warnings `selected_sources_produced_no_records`
  (`suspicious_zero`) and `source_coverage_partial`, so the loss is visible to
  an operator who reads diagnostics, but no scanner error is raised.
  Reconfirmed against HEAD `2e8c56a` with `tlab analyze`, which now reports
  this case as `not_evaluable` (`no_records_acquired`).
- **OPEN**: whether upgraded databases keep stale v1 tables. Telltale's
  Desktop v2.0.24 validation read `part` rows.

**F10. `OPENCODE_DB` and channel database names are not discovered. Strong.**
Upstream: the filename is `opencode-<channel>.db` outside
`latest|dev|beta|next|prod`, or `$OPENCODE_DB`
([database-path.ts](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/packages/cli/src/database-path.ts)).
Telltale uses `ExactFile("opencode.db")`.

**F11. The macOS CLI path differs. Strong.**
Upstream v2.0.27 CLI uses `$XDG_DATA_HOME` or `~/.local/share` on all
platforms
([global-roots.ts](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/packages/util/src/global-roots.ts)).
Telltale's macOS `DataHome` is `~/Library/Application Support`
([session-sources.md](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/docs/session-sources.md)).
**OPEN**: the Desktop app's macOS path.

## OpenClaw (boundary `v2026.7.1` `2d2ddc43` → `v2026.7.2-beta.1` / `v2026.8.1` `ea806575`; current `v2026.10.2` `b8952d47`)

**F12. The default SQLite session store is not reached. Strong.**
Upstream: sessions and transcripts are in
`agents/<id>/agent/openclaw-agent.sqlite` (agent schema 8, first shipped in
`v2026.7.2-beta.1`; documented default from `v2026.8.1`)
([agent-schema-history.md#L11-L20](https://github.com/openclaw/openclaw/blob/b8952d477f0c932d8ddc6da5c89cab5a169b6ff1/docs/reference/database-schemas/agent-schema-history.md#L11-L20),
[session.md#L232-L261](https://github.com/openclaw/openclaw/blob/b8952d477f0c932d8ddc6da5c89cab5a169b6ff1/docs/concepts/session.md#L232-L261)).
Telltale reads only `*.jsonl*` files under `~/.openclaw/agents`.
Repro idea: on a sandboxed ≥ v2026.8.1 install, scan; expect at most leftover
legacy files.

**F13. The documented legacy JSONL shape is rejected. Confirmed.**
Upstream: a header `type:"session"`, then `type:"message"` entries with
`toolCall` blocks and `role:"toolResult"`
([session-management-compaction.md@v2026.7.1#L132-L145](https://github.com/openclaw/openclaw/blob/2d2ddc43d0dcf71f31283d780f9fe9ff4cc04fe4/docs/reference/session-management-compaction.md#L132-L145),
[transcript-payload.test.ts#L404-L429](https://github.com/openclaw/openclaw/blob/b8952d477f0c932d8ddc6da5c89cab5a169b6ff1/src/config/sessions/transcript-payload.test.ts#L404-L429)).
Telltale accepts `user`/`assistant`/`tool_call`/`tool_result`/`session_meta`
and similar, and its fixtures use that shape. Repro: a file containing only
`{"type":"message","id":"e1","parentId":null,"message":{"role":"user","content":[{"type":"text","text":"x"}]}}`
gives `unknown_discriminator`.

**F14. zstd reset/delete archives are discovered and fail. Confirmed.**
Upstream: `*.jsonl.deleted.<timestamp>.zst` in the sessions directory
([maintenance.md#L26](https://github.com/openclaw/openclaw/blob/b8952d477f0c932d8ddc6da5c89cab5a169b6ff1/docs/reference/session-management-compaction/maintenance.md#L26)).
Telltale's pattern is `FileNameContains(".jsonl")`. Repro: zstd any parsing
OpenClaw fixture to `sess.jsonl.deleted.2026-10-13T00-00-00.000Z.zst`.
Result: `source_read`.

**F15. `OPENCLAW_STATE_DIR` is not honored. Strong**
([cli/transcripts.md#L33-L34](https://github.com/openclaw/openclaw/blob/b8952d477f0c932d8ddc6da5c89cab5a169b6ff1/docs/cli/transcripts.md#L33-L34)).

## Qwen Code (upstream `v0.25.1` `c1a8218f`)

**F16. Gemini `functionCall`/`functionResponse` parts fail acquisition. Confirmed.**
Upstream: `message` is a Gemini `Content` with `parts` holding
`functionCall`/`functionResponse`
([chatRecordingService.ts#L458-L466](https://github.com/QwenLM/qwen-code/blob/c1a8218f38203e272e6e965778ed6a2795cfeed7/packages/core/src/services/chatRecordingService.ts#L458-L466),
[#L2774](https://github.com/QwenLM/qwen-code/blob/c1a8218f38203e272e6e965778ed6a2795cfeed7/packages/core/src/services/chatRecordingService.ts#L2774),
[#L2940](https://github.com/QwenLM/qwen-code/blob/c1a8218f38203e272e6e965778ed6a2795cfeed7/packages/core/src/services/chatRecordingService.ts#L2940)).
Telltale reads `content[]`/`tool_calls`. Repro: a user record, an `assistant`
record with `message.parts:[{functionCall:{id,name,args}}]`, and a
`tool_result` record with `functionResponse`. Result: `invalid_tool_result`.

**F17. `type: "system"` records reject the file. Confirmed.**
Upstream: `type` includes `system` with many subtypes
([#L355-L413](https://github.com/QwenLM/qwen-code/blob/c1a8218f38203e272e6e965778ed6a2795cfeed7/packages/core/src/services/chatRecordingService.ts#L355-L413)).
Repro: add `{"type":"system","subtype":"ui_telemetry",…}`. Result:
`unknown_discriminator`.

**F18. `QWEN_HOME`/`QWEN_RUNTIME_DIR` are not honored. Strong**
([storage.ts#L172-L203](https://github.com/QwenLM/qwen-code/blob/c1a8218f38203e272e6e965778ed6a2795cfeed7/packages/core/src/config/storage.ts#L172-L203)).

## GitHub Copilot CLI (upstream `v1.0.96` `dcdc0273`; local 1.0.78)

**F19. Default `~/.copilot` evidence is not acquired. Confirmed for logs.**
Upstream: process logs go to `~/.copilot/logs/process-{timestamp}-{pid}.log`
and session history to `~/.copilot/session-state/<id>/events.jsonl`
([config dir reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference)).
The 1.0.78 `--help` shows the `--log-dir` default `~/.copilot/logs/`.
Telltale registers only project-local `logs/copilot`. Repro: copy Telltale's
own `process-fixture.log` to `$HOME/.copilot/logs/` and scan; 0 sources. The
same file under `<project>/logs/copilot` with `--project-config` parses (3
records).

**F20. Install inventory misses the CLI. Strong.**
Telltale's `copilot` install definition checks only VS Code extension IDs
([copilot/install.rs](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/copilot/install.rs)).
A `copilot` executable on PATH is not reported.

- **OPEN**: whether 1.0.96 still emits the `Accumulated output items` lines
  Telltale parses.
- **OPEN**: the `events.jsonl` schema.
- **OPEN**: default project roots not applied in an isolated run with explicit
  `--root`.

## Maintenance

Rerun each repro after any Telltale source change or harness release. Move a
finding to a resolved section, with the fixing commit, only after the same
synthetic repro passes. Strong findings need a sandboxed real capture to
become Confirmed against upstream output.
