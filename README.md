# Telltale evidence lab

The lab validates human-authored scenario v1 JSON, generates synthetic Codex and
OpenCode session stores, and compares [Telltale](https://github.com/Dark-Roast-Cyber/telltale)'s observed findings with labels
written before analysis. Start with Telltale's [documentation map](https://github.com/Dark-Roast-Cyber/telltale/blob/main/docs/README.md) and [source validation matrix](https://github.com/Dark-Roast-Cyber/telltale/blob/main/docs/source-validation-matrix.md). Scenario tool commands are data. `generate` and
`analyze` never execute them.

[Agent Archaeology](https://agentarchaeology.ai/) explains the evidence model.
[Candidate detections](https://github.com/Dark-Roast-Cyber/telltale-detections)
use this lab; successful execution is not proof of detection quality.

For the scoped Daybreak work, read `docs/daybreak-adversarial-scope.md` and use
only `scenarios`, `generate`, and `analyze`. Do not use the separate `capture`
command for these scenarios. The scenario validator requires fabricated secret
markers and reserved URL hosts.

On Linux, with Python 3 and a Telltale binary from revision `2e8c56a`:

```sh
PYTHONPATH=src python3 -m evidence_lab scenarios
PYTHONDONTWRITEBYTECODE=1 TELLTALE_BIN=/tmp/telltale-daybreak-target/release/telltale \
  python3 -m unittest discover -s tests -v
```

The tests cover validator failures, both source-native generators, and analysis
of the baseline scenario through both source adapters. Put output and the Cargo
target directory under `/tmp`, outside either repository. The companion
`telltale-detections/scripts/linux-check.sh` runs the full local Linux gate.

`generate` and `analyze` take `--profile`. The default, `compatible`, writes
record shapes Telltale is known to acquire, so detections can be tested.
`upstream` writes pinned harness tags (Codex rust-v0.162.1,
OpenCode v2.0.27; see `docs/harnesses/`), not "current releases." Against Telltale `2e8c56a` it gives
`not_evaluable`: Codex rollouts fail on `token_usage_record` (finding F1) and
OpenCode v2 databases yield zero records (F9). Use it to check whether a
Telltale build can read what harnesses write today.

Scenario labels are independent evidence. A `missed`, `false_positive`, or
`not_evaluable` result is retained for review; changing a label to make a test
green would erase the finding.
