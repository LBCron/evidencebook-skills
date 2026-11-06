#!/usr/bin/env python3
"""The pack JSON Schema (schemas/pack-source.schema.json) and the lint that
checks a pack-source.yaml against it (Terms Pack Studio PRD v5 section 15 item 1).

Every Terms Pack is one `pack-source.yaml`, told apart by `scope.kind`:
admission, deal, conduct, live, and the report kind (`after_the_fact`, which is
also what an absent scope means). The schema owns a source's structure: its
members, their types and closed sets. The validators the kinds already have
(pack_compile.validate_source) own the rules that read across members, and run
only on a source the schema accepts.

A conduct pack is private to its owner: it is judged only for them and nobody
else ever receives or adjudicates it (PRD v5 section 5). It has the judgment
form of a report pack, under its own `scope.kind` so one is never shipped to a
counterparty by accident.
"""
import json
import pathlib

import jsonschema

SCHEMA_PATH = pathlib.Path(__file__).resolve().parents[1] / "schemas" / "pack-source.schema.json"
KINDS = ("admission", "deal", "conduct", "live", "after_the_fact")


def schema():
    return json.loads(SCHEMA_PATH.read_text())


def kind_of(source):
    scope = source.get("scope") if isinstance(source, dict) else None
    return scope.get("kind", "after_the_fact") if isinstance(scope, dict) else "after_the_fact"


def _path(error):
    return ".".join(f"[{p}]" if isinstance(p, int) else str(p) for p in error.absolute_path).replace(".[", "[")


def _leaves(error):
    """The innermost errors: the reason for a failed oneOf/anyOf, not the branch count."""
    if not error.context:
        return [error]
    best = jsonschema.exceptions.best_match(error.context)
    return _leaves(best) if best is not None else [error]


def _message(error):
    at = _path(error)
    if error.validator == "required":
        missing = error.message.split("'")[1]
        return f"{at + '.' if at else ''}{missing} is required"
    if error.validator == "additionalProperties":
        extra = sorted(set(error.instance) - set(error.schema.get("properties", {})), key=str)
        return "; ".join(f"{at + '.' if at else ''}{k} is not a field of this kind of pack" for k in extra)
    if error.validator == "enum":
        return f"{at} {error.instance!r} must be one of {error.validator_value}"
    return f"{at}: {error.message}" if at else error.message


def schema_issues(source):
    """Every way `source` breaks the schema, each naming its field."""
    if not isinstance(source, dict):
        return ["pack source must be a mapping"]
    if kind_of(source) not in KINDS:
        return [f"scope.kind {kind_of(source)!r} must be one of {list(KINDS)}"]
    validator = jsonschema.Draft202012Validator(schema())
    issues = []
    for error in sorted(validator.iter_errors(source), key=lambda e: [str(p) for p in e.absolute_path]):
        for leaf in _leaves(error):
            msg = _message(leaf)
            if msg not in issues:
                issues.append(msg)
    return issues
