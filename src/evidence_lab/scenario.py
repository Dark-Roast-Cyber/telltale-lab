"""Scenario format v1: a human-authored behavior description, its independent
labels, and the deterministic inputs used to generate source-native evidence.

Labels (`disposition`, `review`, `rule_expectations`) are written by people.
Nothing in this module reads detector output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .util import LabError, parse_utc, read_json, sha256_file

FORMAT = "telltale-lab/scenario/v1"
DISPOSITIONS = {"benign", "malicious", "unknown", "not_applicable"}
REVIEW_EXPECTATIONS = {"alert", "hunt", "no_alert", "not_evaluable"}
SUPPORTED_FORMATS = {"codex.sessions", "opencode.sqlite"}
TOOLS = {"shell", "read_file", "write_file"}
RESULT_STATUSES = {"ok", "error", "denied"}
FAKE_MARKER = re.compile(r"FAKE|EXAMPLE|SYNTHETIC")
RESERVED_HOST = re.compile(
    r"(^|\.)(invalid|example|test|localhost)$|^(example\.(com|org|net))$|^127\.\d+\.\d+\.\d+$"
)
URL_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s'\"`)]+")
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,80}$")

TOP_LEVEL_KEYS = {
    "format", "id", "title", "description", "disposition", "review", "expected_facts",
    "visibility_limitations", "synthetic_resources", "permitted_operations", "formats",
    "session", "steps", "rule_expectations", "notes", "live",
}
REQUIRED_KEYS = {
    "format", "id", "title", "description", "disposition", "review", "expected_facts",
    "visibility_limitations", "synthetic_resources", "permitted_operations", "formats",
    "session", "steps",
}


@dataclass(frozen=True)
class Scenario:
    data: dict[str, Any]
    path: Path | None
    sha256: str | None

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def formats(self) -> list[str]:
        return list(self.data["formats"])

    @property
    def steps(self) -> list[dict[str, Any]]:
        return self.data["steps"]

    @property
    def session(self) -> dict[str, Any]:
        return self.data["session"]

    def secrets(self) -> list[dict[str, str]]:
        return list(self.data["synthetic_resources"].get("secrets", []))

    def rule_expectations(self) -> dict[str, list[str]]:
        exp = self.data.get("rule_expectations") or {}
        return {
            "must_match": list(exp.get("must_match", [])),
            "must_not_match": list(exp.get("must_not_match", [])),
        }


def _fail(source: str, message: str) -> LabError:
    return LabError(f"invalid scenario {source}: {message}")


def _require_str(obj: dict, key: str, source: str, allow_empty: bool = False) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise _fail(source, f"`{key}` must be a non-empty string")
    return value


def _require_str_list(obj: dict, key: str, source: str, allow_empty: bool = True) -> list[str]:
    value = obj.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise _fail(source, f"`{key}` must be a list of non-empty strings")
    if not allow_empty and not value:
        raise _fail(source, f"`{key}` must not be empty")
    return value


def _check_urls(text: str, source: str, where: str) -> None:
    for url in URL_PATTERN.findall(text):
        host = (urlsplit(url).hostname or "").lower()
        if not host or not RESERVED_HOST.search(host):
            raise _fail(
                source,
                f"{where} references non-reserved host {host!r}; use .invalid/.example/.test or loopback",
            )


def validate(data: Any, source: str = "<memory>") -> dict[str, Any]:
    if not isinstance(data, dict):
        raise _fail(source, "top level must be an object")
    unknown = set(data) - TOP_LEVEL_KEYS
    if unknown:
        raise _fail(source, f"unknown keys {sorted(unknown)}")
    missing = REQUIRED_KEYS - set(data)
    if missing:
        raise _fail(source, f"missing keys {sorted(missing)}")
    if data["format"] != FORMAT:
        raise _fail(source, f"`format` must be {FORMAT!r}")
    if not isinstance(data["id"], str) or not ID_PATTERN.match(data["id"]):
        raise _fail(source, "`id` must match [a-z0-9][a-z0-9_.-]{2,80}")
    _require_str(data, "title", source)
    _require_str(data, "description", source)
    if data["disposition"] not in DISPOSITIONS:
        raise _fail(source, f"`disposition` must be one of {sorted(DISPOSITIONS)}")

    review = data["review"]
    if not isinstance(review, dict) or set(review) != {"expectation", "rationale"}:
        raise _fail(source, "`review` must have exactly `expectation` and `rationale`")
    if review["expectation"] not in REVIEW_EXPECTATIONS:
        raise _fail(source, f"`review.expectation` must be one of {sorted(REVIEW_EXPECTATIONS)}")
    _require_str(review, "rationale", source)

    _require_str_list(data, "expected_facts", source, allow_empty=False)
    _require_str_list(data, "visibility_limitations", source)
    _require_str_list(data, "permitted_operations", source)

    resources = data["synthetic_resources"]
    if not isinstance(resources, dict) or set(resources) - {"secrets", "paths", "domains"}:
        raise _fail(source, "`synthetic_resources` may contain only secrets, paths, domains")
    for secret in resources.get("secrets", []):
        if not isinstance(secret, dict) or set(secret) != {"id", "value"}:
            raise _fail(source, "each secret must have exactly `id` and `value`")
        if not FAKE_MARKER.search(secret["value"]):
            raise _fail(source, f"secret {secret['id']!r} must contain FAKE, EXAMPLE, or SYNTHETIC")
    _require_str_list(resources, "paths", source)
    for domain in _require_str_list(resources, "domains", source):
        if not RESERVED_HOST.search(domain.lower()):
            raise _fail(source, f"domain {domain!r} is not a reserved test domain")

    formats = _require_str_list(data, "formats", source, allow_empty=False)
    if set(formats) - SUPPORTED_FORMATS:
        raise _fail(source, f"unsupported formats {sorted(set(formats) - SUPPORTED_FORMATS)}")

    session = data["session"]
    if not isinstance(session, dict):
        raise _fail(source, "`session` must be an object")
    if set(session) - {"start", "cwd", "model", "provider", "step_seconds"}:
        raise _fail(source, "`session` has unknown keys")
    parse_utc(_require_str(session, "start", source))
    _require_str(session, "cwd", source)
    step_seconds = session.get("step_seconds", 2)
    if not isinstance(step_seconds, (int, float)) or step_seconds <= 0:
        raise _fail(source, "`session.step_seconds` must be positive")

    steps = data["steps"]
    if not isinstance(steps, list) or not steps:
        raise _fail(source, "`steps` must be a non-empty list")
    if steps[0].get("type") != "user":
        raise _fail(source, "the first step must be a user message")
    for index, step in enumerate(steps):
        where = f"steps[{index}]"
        if not isinstance(step, dict):
            raise _fail(source, f"{where} must be an object")
        kind = step.get("type")
        if kind in ("user", "assistant"):
            if set(step) != {"type", "text"}:
                raise _fail(source, f"{where} message steps take exactly `type` and `text`")
            _require_str(step, "text", source)
            _check_urls(step["text"], source, where)
        elif kind == "tool":
            allowed = {"type", "tool", "command", "path", "content", "result"}
            if set(step) - allowed:
                raise _fail(source, f"{where} has unknown keys {sorted(set(step) - allowed)}")
            tool = step.get("tool")
            if tool not in TOOLS:
                raise _fail(source, f"{where}.tool must be one of {sorted(TOOLS)}")
            if tool == "shell":
                _check_urls(_require_str(step, "command", source), source, where)
            else:
                _require_str(step, "path", source)
            if tool == "write_file":
                _check_urls(_require_str(step, "content", source, allow_empty=True), source, where)
            if "result" not in step:
                raise _fail(source, f"{where} must state `result` (null = no result was recorded)")
            result = step["result"]
            if result is not None:
                if not isinstance(result, dict) or set(result) - {"status", "output", "exit_code"}:
                    raise _fail(source, f"{where}.result has unknown keys")
                if result.get("status") not in RESULT_STATUSES:
                    raise _fail(source, f"{where}.result.status must be one of {sorted(RESULT_STATUSES)}")
                _check_urls(_require_str(result, "output", source, allow_empty=True), source, where)
                if "exit_code" in result and not isinstance(result["exit_code"], int):
                    raise _fail(source, f"{where}.result.exit_code must be an integer")
        else:
            raise _fail(source, f"{where}.type must be user, assistant, or tool")

    expectations = data.get("rule_expectations")
    if expectations is not None:
        if not isinstance(expectations, dict) or set(expectations) - {"must_match", "must_not_match"}:
            raise _fail(source, "`rule_expectations` takes must_match and must_not_match")
        must = set(_require_str_list(expectations, "must_match", source))
        must_not = set(_require_str_list(expectations, "must_not_match", source))
        if must & must_not:
            raise _fail(source, f"rule ids both required and forbidden: {sorted(must & must_not)}")
    if "notes" in data:
        _require_str_list(data, "notes", source)
    live = data.get("live")
    if live is not None:
        if not isinstance(live, dict) or set(live) - {"prompt", "files"}:
            raise _fail(source, "`live` takes `prompt` and optional `files`")
        _check_urls(_require_str(live, "prompt", source), source, "live.prompt")
        files = live.get("files", {})
        if not isinstance(files, dict):
            raise _fail(source, "`live.files` must map relative paths to text")
        for rel, content in files.items():
            parts = Path(rel).parts
            if Path(rel).is_absolute() or not parts or ".." in parts or "\\" in rel or ":" in rel:
                raise _fail(source, f"`live.files` path {rel!r} must be a plain relative path")
            if not isinstance(content, str):
                raise _fail(source, f"`live.files[{rel!r}]` must be text")
            _check_urls(content, source, f"live.files[{rel!r}]")
    return data


def load(path: Path) -> Scenario:
    data = read_json(path)
    validate(data, str(path))
    return Scenario(data=data, path=path, sha256=sha256_file(path))


def discover(directories: list[Path]) -> dict[str, Scenario]:
    """Load every `*.json` scenario under the given directories, keyed by id."""
    found: dict[str, Scenario] = {}
    for directory in directories:
        if not directory.is_dir():
            raise LabError(f"scenario directory does not exist: {directory}")
        for path in sorted(directory.rglob("*.json")):
            if any(part.startswith(".") for part in path.relative_to(directory).parts):
                continue  # hidden tool/editor directories are never scenarios
            scenario = load(path)
            if scenario.id in found:
                raise LabError(f"duplicate scenario id {scenario.id!r} in {path} and {found[scenario.id].path}")
            found[scenario.id] = scenario
    return found


def builtin_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "scenarios"


def resolve(ref: str, extra_dirs: list[Path]) -> Scenario:
    """Resolve a scenario by file path or id (built-ins plus extra directories)."""
    candidate = Path(ref)
    if candidate.suffix == ".json" and candidate.is_file():
        return load(candidate)
    directories = [builtin_dir(), *extra_dirs]
    found = discover([d for d in directories if d.is_dir()])
    if ref not in found:
        raise LabError(f"unknown scenario {ref!r}; run `tlab scenarios list`")
    return found[ref]
