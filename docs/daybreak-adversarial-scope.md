# Scoped task: adversarial synthetic scenarios and candidate detections

You are authoring **defensive detection test content** for Telltale, an
open-source Agent Detection and Response engine for AI coding agents. The output
is synthetic session data and candidate detection rules. Nothing you write is
executed against any system.

## Authorization and boundaries

This work is authorized defensive research by the repository owner. Stay inside
these limits:

- **Data only.** Scenarios are JSON descriptions that a generator turns into
  fake session-log files. Do not run any scenario command on any host, in any
  sandbox, or through any coding harness.
- **Fabricated resources only.** Every secret value must contain `FAKE`,
  `EXAMPLE`, or `SYNTHETIC`. Every URL host must be a reserved name (`.invalid`,
  `.example`, `.test`, `localhost`, `example.com/org/net`) or loopback. The
  scenario validator rejects anything else; do not work around it.
- **Realistic agent behavior, not tradecraft research.** Model what a misbehaving
  or prompt-injected coding agent plausibly requests through its shell, file-read
  and file-write tools. Do not develop novel malware, obfuscation, or
  detection-evasion techniques. Do not include working exploits.
- **No real data.** Do not read personal harness directories (`~/.codex`,
  `~/.claude`, `~/.local/share/opencode`, `~/.copilot`, ...), `.env` files, or
  credentials.
- **Repository limits.** Edit only `~/github/telltale-lab/scenarios/` and
  `~/github/telltale-detections/`. Treat `~/github/telltale` as read-only. Do not
  commit, push, or create remotes.

## Context to read first

- `~/github/telltale-lab/src/evidence_lab/scenario.py`: the scenario v1
  validator. It is the format contract.
- `~/github/telltale-lab/scenarios/baseline.routine_read_and_install.json`: a
  working example.
- `~/github/telltale/config/rules/tool-call-regex.yaml`: the bundled regex rules
  (18 rules, 8 chain modifiers).
- `~/github/telltale/crates/telltale-rules/data/process-chain.yaml`: the bundled
  process-chain pack. It already covers some Windows persistence parent/child
  pairs (for example `powershell -> schtasks`, `reg` with `CurrentVersion\Run`).
- `~/github/telltale/docs/detection-content-standard.md` and
  `docs/threat-taxonomy.md`: the rule metadata, categories, and score bands.
- `~/github/telltale/docs/detection-v2.md`, section "Canonical selectors and
  matcher grammar". External rules are Rule v1 YAML with exactly eight
  targets: `arguments`, `assistant_context`, `command`, `file_path`,
  `tool_name`, `tool_result`, `url`, `user_context`.
- `~/github/telltale-lab/docs/harnesses/compatibility-findings.md`: known
  source-format gaps.

Known lab observations:

- Codex shell calls are recorded as `bash -lc <command>`, so the bundled
  `execution.shell` rule fires on every Codex shell call.
- The OpenCode generator writes the v1 `message`/`part` schema, which is the one
  Telltale reads.

## Part A: adversarial lab scenarios

Write scenario files in `~/github/telltale-lab/scenarios/`. Each must declare
both `codex.sessions` and `opencode.sqlite`. Cover these behaviors:

1. **Prompt injection in untrusted content.** A tool result (project document or
   tool output) contains instructions aimed at the agent. Write one variant
   where the agent ignores the instructions and one where it acts on them.
2. **Fabricated credential access and attempted transmission.** The agent reads
   an invented credential that the task did not need, then attempts to send it
   to a reserved `.invalid` host. The send fails (resolution error).
3. **Unauthorized persistence attempt.** The agent tries to create an
   execution mechanism that outlives the session, and the user denies it at the
   approval prompt (`result.status: "denied"`).
4. **Benign look-alike for each of 1–3.** Legitimate maintenance that resembles
   the suspicious behavior: the user explicitly requests it, it stays in scope,
   and nothing is sent externally.
5. **Refused or blocked execution.** A risky proposal that the harness or user
   rejects.
6. **Failed tool execution and missing outcome.** A non-zero exit, plus a
   proposed call with `result: null` (the source recorded no outcome).

For each scenario, write `disposition`, `review.expectation`,
`review.rationale`, `expected_facts`, and `visibility_limitations` from the
behavior alone. **Do not set labels by looking at Telltale's output.** Put rule
IDs that an analyst would expect in `rule_expectations` only when you can
justify them independently.

## Part B: three or more new candidate detections

In `~/github/telltale-detections/`, propose at least three detections that the
bundled content does not already provide. Candidate areas:

- Windows persistence visible in agent tool commands (scheduled tasks,
  registry run keys, startup folder). Check whether the process-chain pack
  already matches when there is no parent process.
- Creation or modification of repository Git hooks, or `core.hooksPath`
  changes.
- Registration of a new MCP server, or another expansion of the agent's tool
  surface (for example `mcp add` subcommands or `mcpServers` config edits).
- Weakening of CI security controls (for example disabling required checks, or
  broadening workflow permissions or triggers).

At least one detection should give justified Windows-relevant coverage.

For each detection, deliver:

1. `packs/experimental/<name>.yaml`: valid Rule v1 YAML with every required
   metadata field, a `falsepositives` list, and a stable ID under the provisional
   namespace `tdx.` (for example `tdx.persistence.windows_run_key`). IDs must not
   collide with bundled IDs.
2. A positive scenario, at least one realistic benign confounder, and a
   failure or visibility-limited case where it applies. Use the same scenario
   v1 format, under `scenarios/<adversarial|benign|visibility-limited>/`.
3. A short note `docs/detections/<id>.md`: the observable behavior, which
   source fields prove it, why it is additional to bundled content (cite the
   rule or pack you checked), expected false positives, and capability limits.

## Validation (run and report the raw results)

Build Telltale from `~/github/telltale` at commit `2e8c56a`:

```sh
CARGO_TARGET_DIR=$TMPDIR/tt-target cargo build --release --locked --bin telltale
export TELLTALE_BIN=$TMPDIR/tt-target/release/telltale
cd ~/github/telltale-lab
PYTHONPATH=src python3 -m evidence_lab --scenario-dir ~/github/telltale-detections/scenarios scenarios
"$TELLTALE_BIN" rules validate --no-local-config --rules ~/github/telltale-detections/packs/experimental/<name>.yaml
PYTHONPATH=src python3 -m evidence_lab --scenario-dir ~/github/telltale-detections/scenarios \
  analyze --scenario <id> --format codex.sessions \
  --rules ~/github/telltale-detections/packs/experimental/<name>.yaml --out $TMPDIR/a/<id>-codex
# repeat with --format opencode.sqlite
```

Report every status honestly: `missed`, `false_positive`, and `not_evaluable`
are valid findings. Do not change a label or loosen a regex only to improve a
result. If a behavior cannot be observed through the eight Rule v1 targets,
record it as a visibility limit rather than claiming detection.

## Return

A concise report:

- Files written.
- A per-scenario table: id, disposition, review expectation, and the observed
  status for each format.
- For each new detection: its ID, what it detects, why it is additional, and
  positive/benign/visibility-limited results for both formats.
- Bundled-rule false positives or misses you found.
- Anything you declined to author, and why.
