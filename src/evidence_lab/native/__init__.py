"""Source-native synthetic evidence generators, keyed by Telltale source identity."""

from __future__ import annotations

from pathlib import Path

from ..scenario import Scenario
from ..util import LabError
from . import codex, opencode

GENERATORS = {codex.SOURCE_ID: codex, opencode.SOURCE_ID: opencode}


def generate(scenario: Scenario, source_id: str, root: Path) -> list[Path]:
    """Write a Telltale fixture-layout root containing one synthetic source."""
    if source_id not in scenario.formats:
        raise LabError(f"scenario {scenario.id!r} does not declare format {source_id!r}")
    module = GENERATORS.get(source_id)
    if module is None:
        raise LabError(f"no generator for {source_id!r}")
    root.mkdir(parents=True, exist_ok=True)
    # The marker makes Telltale use fixture layout and keeps emitting scans behind --allow-fixtures.
    (root / ".telltale-fixtures").write_bytes(b"")
    return module.write(scenario, root)


def generator_version(source_id: str) -> str:
    return GENERATORS[source_id].GENERATOR_VERSION
