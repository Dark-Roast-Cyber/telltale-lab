# Telltale evidence lab

The lab validates human-authored scenario v1 JSON, generates synthetic Codex and
OpenCode session stores, and compares findings from
[Telltale](https://github.com/Dark-Roast-Cyber/telltale) with labels written before
analysis. Scenario tool commands are data. `generate` and `analyze` never execute them.

## Browse

- [CLI](src/evidence_lab/cli.py), [generators](src/evidence_lab/native/), and [assessment](src/evidence_lab/analysis.py)
- [Synthetic scenarios](scenarios/) and [tests](tests/)

## Run

Use Python 3 and a Telltale binary matching the tested baseline in
[the CLI adapter](src/evidence_lab/telltale.py):

```sh
PYTHONPATH=src python3 -m evidence_lab scenarios
PYTHONDONTWRITEBYTECODE=1 TELLTALE_BIN=/path/to/telltale \
  python3 -m unittest discover -s tests -v
```

Put generated stores, reports, and build output outside the repositories. The
companion [detections gate](https://github.com/Dark-Roast-Cyber/telltale-detections/blob/main/scripts/linux-check.sh)
owns its revision requirements and runs the combined local Linux assessment.

`generate` and `analyze` take `--profile`. The default, `compatible`, writes
record shapes Telltale is known to acquire, so detections can be tested.
`upstream` writes pinned harness shapes, not an assertion of current-release
support. See the [generators](src/evidence_lab/native/) for versions and the
[compatibility findings](docs/harnesses/compatibility-findings.md) for historical
acquisition gaps at their recorded revisions.

Scenario labels are independent evidence. A `missed`, `false_positive`, or
`not_evaluable` result is retained for review; changing a label to make a test
green would erase the finding. A successful run is not proof of detection quality.

For [Daybreak](docs/daybreak-adversarial-scope.md), use only `scenarios`, `generate`,
and `analyze`, not `capture`. The validator requires fabricated secret markers
and reserved URL hosts.

## Related

- [Candidate detections](https://github.com/Dark-Roast-Cyber/telltale-detections): provisional rule packs assessed with this lab
- [Agent Archaeology](https://agentarchaeology.ai/): evidence and investigation context
