# Claude Code

Research guide for Claude Code transcript evidence. Checked 2026-10-13.

Claim labels: **Upstream fact** (pinned link), **Live observation** (seen in
this lab), **Telltale implementation** (Telltale code/docs), **Open question**.

## 1. Upstream and docs

- Repository (changelog, issues, plugins; the CLI source is not published):
  <https://github.com/anthropics/claude-code>
- Docs index: <https://code.claude.com/docs/llms.txt>. The relevant pages are
  [sessions](https://code.claude.com/docs/en/sessions),
  [.claude directory](https://code.claude.com/docs/en/claude-directory),
  [env vars](https://code.claude.com/docs/en/env-vars),
  [settings](https://code.claude.com/docs/en/settings),
  [sandboxing](https://code.claude.com/docs/en/sandboxing), and
  [headless / Agent SDK](https://code.claude.com/docs/en/headless).
  These docs are not versioned. Quotes below were read on 2026-10-13.

## 2. Versions

| What | Version | Commit |
| --- | --- | --- |
| Researched upstream | `v2.1.296` (2026-10-09) | `2301018b1f61073c501a8e7a4813ef48c239163b` |
| Locally installed | `2.1.296 (Claude Code)` (**Live observation**, `--version`) | same tag |

## 3. Install and authentication

Operator-controlled: native installer or npm `@anthropic-ai/claude-code`.
Sign in with a Claude account, an API key, or a cloud provider configured by
the operator. Do not script around login or permission prompts.
Non-interactive runs use `claude -p`.

## 4. Storage and discovery

- **Upstream fact** (sessions doc): transcripts are written to
  `~/.claude/projects/<project>/<session-id>.jsonl`. `<project>` is the working
  directory with non-alphanumerics replaced by `-`. Names longer than 200
  characters are truncated and get a hash appended.
- **Upstream fact** (.claude directory doc): on Windows `~/.claude` is
  `%USERPROFILE%\.claude`. `CLAUDE_CONFIG_DIR` moves everything, including
  transcripts. `CLAUDE_CODE_PROJECT_DIR_NAME` (v2.1.234+, only with
  `CLAUDE_CONFIG_DIR`) pins the project directory name.
- **Upstream fact**: related paths are
  - `projects/<project>/<session>/subagents/` (subagent transcripts)
  - `projects/<project>/<session>/tool-results/` (large tool outputs spilled
    out of the transcript)
  - set-aside copies `<session>.orphaned-<ts>-<suffix>.jsonl` and
    `<session>.jsonl.superseded-<ts>`
  - `history.jsonl` (typed prompts)
- **Upstream fact**: retention deletes transcripts older than
  `cleanupPeriodDays` (default 30). `CLAUDE_CODE_SKIP_PROMPT_HISTORY=1`
  suppresses transcript writes. `CLAUDE_CODE_TRANSCRIPT_LOCAL_GC=1`
  (v2.1.287+) trims pre-compaction history in long `-p`/SDK sessions.

## 5. Record format

- **Upstream fact** (sessions doc): "Each line is a JSON object for a message,
  tool use, or metadata entry. The entry format is internal to Claude Code and
  changes between versions." No schema is published.
- **Upstream fact** (changelog at `2301018b`): transcripts contain
  `parentUuid` chains
  ([CHANGELOG.md#L6303](https://github.com/anthropics/claude-code/blob/2301018b1f61073c501a8e7a4813ef48c239163b/CHANGELOG.md#L6303),
  [#L7214](https://github.com/anthropics/claude-code/blob/2301018b1f61073c501a8e7a4813ef48c239163b/CHANGELOG.md#L7214)),
  "attachment entries"
  ([#L2588](https://github.com/anthropics/claude-code/blob/2301018b1f61073c501a8e7a4813ef48c239163b/CHANGELOG.md#L2588)),
  and "tool call, tool result or thinking blocks that a real session keeps"
  ([#L145](https://github.com/anthropics/claude-code/blob/2301018b1f61073c501a8e7a4813ef48c239163b/CHANGELOG.md#L145)).
- **Telltale implementation**: Telltale expects top-level `type`
  `user`/`assistant`, a `message` object with `role`/`model`/`content`, a
  `sessionId`, and content blocks `text`, `tool_use`, `tool_result`
  ([claude/native.rs#L198-L262](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/claude/native.rs#L198-L262)).
- **Open question**: the exact top-level `type` values for non-message entries
  (attachment, system, summary, snapshot, and so on) and their fields. They
  must be captured live from a sandboxed run before anyone names them in a
  fixture.

## 6. Tool calls and results

The working model is that content blocks follow the Anthropic Messages API
shape: an assistant `tool_use` block (`id`, `name`, `input`) is answered by a
user `tool_result` block (`tool_use_id`, `content`, optional `is_error`).
**Telltale implementation** correlates on `tool_use_id` → `id`. **Open
question**: we have not yet seen this in a live capture made by this lab.
Large outputs may sit in `tool-results/` instead of inline (**Upstream fact**,
.claude directory doc).

## 7. Timing, status, correlation

- Per-entry timestamps: **Telltale implementation** treats them as optional
  ([capability profile](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/docs/agent-capability-profiles.md)).
- There are no tool start/end times, exit codes, or PIDs in the documented
  surface. `is_error` is the only success/error signal Telltale reads.
- `uuid`/`parentUuid` form a tree. Forks and `/branch` copy transcripts, and
  two terminals resuming one session interleave into one file (sessions doc).

## 8. Missing or optional

- Workspace and cwd are not part of Telltale's contract. Provider is often
  absent.
- Thinking blocks may be present (see §5). Telltale does not accept them.

## 9. Controlled scenarios

- Run in a real sandbox (container/VM, or `bwrap` with a private home). Set
  `HOME=$LAB/h`, and also set `CLAUDE_CONFIG_DIR=$LAB/h/.claude` so nothing
  touches the operator's `~/.claude`. Claude Code's own sandboxing (see the
  sandboxing doc) is a second layer, not the isolation boundary.
- Use a fabricated repo, `.invalid` domains, and fake MCP servers you control.
- Run one scenario that forces a subagent and one that triggers a large tool
  output, so `subagents/` and `tool-results/` get exercised.

## 10. Evidence collection

Copy `projects/<project>/` recursively after the session ends, including
`subagents/` and `tool-results/`. For a session that is still writing, drop a
trailing partial line. Record `claude --version` and the env overrides you
used. The transcript is plaintext and records anything a tool read (.claude
directory doc), so treat a raw capture as sensitive even inside the lab.

## 11. Public-safe fixtures

Hand-build fixtures with synthetic `sessionId`/`uuid` values and synthetic
content. Only use entry types that appear in a live capture recorded in this
lab, and note the capture's version in the fixture.

## 12. Telltale identity and limits

- **Telltale implementation**: `claude.projects`, `Home/.claude/projects`,
  recursive `*.jsonl`
  ([claude/mod.rs](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/crates/telltale-sources/src/sources/claude/mod.rs)).
  `CLAUDE_CONFIG_DIR` is not consulted. Subagent transcripts under
  `<session>/subagents/` are reached by recursion. `tool-results/` spill files
  and `.jsonl.superseded-*` are not. See
  [session-sources.md](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/docs/session-sources.md)
  and the [Claude adapter spec](https://github.com/Dark-Roast-Cyber/telltale/blob/2e8c56aa45583525e4536640adb2c977ba45d46b/openspec/specs/claude-canonical-observation-v2-adapter/spec.md)
  (unknown discriminators and unknown content blocks fail closed).
- **Live observation** (Telltale `0.7.0-rc.2`/`07a380d`, synthetic files): a
  user → assistant `tool_use` → user `tool_result` transcript parses (1 tool
  call, 1 result). Replacing the assistant text block with a `thinking` block
  fails the whole source with `unknown_content_block`. Adding a top-level
  `system`, `attachment`, or `summary` line fails it with
  `unknown_discriminator`. The top-level shapes were guessed (see §5), so only
  the thinking-block result is a confirmed compatibility finding.

## 13. Validation status and maintenance

- Upstream facts come from the docs (unversioned, read 2026-10-13) and the
  changelog at `2301018b`.
- Live: `--version` only, plus Telltale scans of synthetic files. No
  transcript was captured. Telltale's own matrix records a bounded live
  validation (5 sources). **Open question**: whether those sources lacked
  thinking blocks and non-message entries, or Telltale handled them some way
  this lab did not reproduce.
- Next step: make one sandboxed capture per entry type, record their
  discriminators here, then rerun the Telltale variants.
