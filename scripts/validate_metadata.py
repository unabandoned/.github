#!/usr/bin/env python3
"""Validate an `.unabandoned.yml` fork-metadata file against the schema.

This is the single definition of what a valid `.unabandoned.yml` looks like.
It is imported by the dashboard builder (`build_dashboard.py`) so the two can
never disagree on the shape, and it runs as a CLI in `reusable-ci` so every
fork's metadata is checked on every pull request.

Usage:
    python3 validate_metadata.py [PATH ...]

With no PATH it defaults to `.unabandoned.yml` in the current directory. It
exits 0 when every file is valid, 1 when any file has errors, and 0 (with a
note) when a defaulted file is simply absent — infra repos legitimately have no
metadata, so "no file" is not a failure unless a path was named explicitly.
"""
from __future__ import annotations

import sys
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - surfaced as a clear CI message
    sys.stderr.write(
        "error: PyYAML is required (pip install pyyaml). "
        "On GitHub-hosted runners it is preinstalled.\n"
    )
    raise

SCHEMA_VERSION = 1
SCOPE_PREFIX = "@unabandoned/"
VALID_STATUSES = ("active", "seeking-replacement", "deprecated")


def _is_owner_repo(value: Any) -> bool:
    """True for a plausible "owner/name" GitHub slug."""
    if not isinstance(value, str):
        return False
    parts = value.split("/")
    return len(parts) == 2 and all(parts) and " " not in value


def validate(data: Any) -> list[str]:
    """Return a list of human-readable error strings (empty means valid)."""
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["top-level document must be a mapping/object"]

    # schema — optional but, if present, must be the version we understand.
    schema = data.get("schema", SCHEMA_VERSION)
    if not isinstance(schema, int) or schema != SCHEMA_VERSION:
        errors.append(
            f"`schema` must be the integer {SCHEMA_VERSION} "
            f"(got {schema!r})"
        )

    # package — required, scoped npm name.
    package = data.get("package")
    if not isinstance(package, str) or not package.strip():
        errors.append("`package` is required and must be a non-empty string")
    elif not package.startswith(SCOPE_PREFIX):
        errors.append(f"`package` must start with '{SCOPE_PREFIX}' (got {package!r})")

    # upstream — required mapping with repo + reason.
    upstream = data.get("upstream")
    if not isinstance(upstream, dict):
        errors.append("`upstream` is required and must be a mapping")
    else:
        if not _is_owner_repo(upstream.get("repo")):
            errors.append("`upstream.repo` is required and must be 'owner/name'")
        reason = upstream.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append("`upstream.reason` is required and must be a non-empty string")

    # summary / why-forked — required prose.
    for field in ("summary", "why-forked"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"`{field}` is required and must be a non-empty string")

    # status — optional, constrained.
    status = data.get("status", "active")
    if status not in VALID_STATUSES:
        errors.append(
            f"`status` must be one of {', '.join(VALID_STATUSES)} (got {status!r})"
        )

    # used-by — optional list of {consumer, purpose}.
    used_by = data.get("used-by")
    if used_by is not None:
        if not isinstance(used_by, list):
            errors.append("`used-by` must be a list when present")
        else:
            for i, entry in enumerate(used_by):
                if not isinstance(entry, dict):
                    errors.append(f"`used-by[{i}]` must be a mapping")
                    continue
                for key in ("consumer", "purpose"):
                    value = entry.get(key)
                    if not isinstance(value, str) or not value.strip():
                        errors.append(
                            f"`used-by[{i}].{key}` is required and must be a "
                            "non-empty string"
                        )

    # tags — optional list of strings.
    tags = data.get("tags")
    if tags is not None:
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            errors.append("`tags` must be a list of strings when present")

    return errors


def load(text: str) -> Any:
    """Parse YAML text into a Python object, raising on malformed YAML."""
    return yaml.safe_load(text)


def _validate_file(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as fh:
        try:
            data = load(fh.read())
        except yaml.YAMLError as exc:  # malformed YAML is a schema failure
            return [f"could not parse YAML: {exc}"]
    return validate(data)


def main(argv: list[str]) -> int:
    paths = argv[1:] or [".unabandoned.yml"]
    defaulted = not argv[1:]
    had_error = False

    for path in paths:
        try:
            errors = _validate_file(path)
        except FileNotFoundError:
            if defaulted:
                print(f"note: no {path} present — nothing to validate.")
                continue
            print(f"{path}: error — file not found")
            had_error = True
            continue

        if errors:
            had_error = True
            print(f"{path}: INVALID")
            for err in errors:
                print(f"  - {err}")
        else:
            print(f"{path}: ok")

    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
