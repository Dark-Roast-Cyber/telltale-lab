"""Source-native synthetic evidence generators, keyed by Telltale source identity."""

from __future__ import annotations

from pathlib import Path

from ..scenario import Scenario
from ..util import LabError
from . import codex, opencode

GENERATORS = {codex.SOURCE_ID: codex, opencode.SOURCE_ID: opencode}
# `compatible`: record shapes Telltale is known to acquire (the default).
# `upstream`: shapes current harness releases persist, per docs/harnesses/;
# use it to check whether Telltale can read what harnesses write today.
PROFILES = ("compatible", "upstream")


def generate(scenario: Scenario, source_id: str, root: Path, profile: str = "compatible") -> list[Path]:
    """Write a Telltale fixture-layout root containing one synthetic source."""
    if source_id not in scenario.formats:
        raise LabError(f"scenario {scenario.id!r} does not declare format {source_id!r}")
    module = GENERATORS.get(source_id)
    if module is None:
        raise LabError(f"no generator for {source_id!r}")
    if profile not in PROFILES:
        raise LabError(f"unknown profile {profile!r}; expected one of {', '.join(PROFILES)}")
    root.mkdir(parents=True, exist_ok=True)
    # The marker makes Telltale use fixture layout and keeps emitting scans behind --allow-fixtures.
    (root / ".telltale-fixtures").write_bytes(b"")
    return module.write(scenario, root, profile)


def generator_version(source_id: str, profile: str = "compatible") -> str:
    return GENERATORS[source_id].GENERATOR_VERSIONS[profile]
