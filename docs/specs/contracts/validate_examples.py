#!/usr/bin/env python3
"""Validate contract examples against the JSON Schemas (jsonschema) and the
pydantic models. The two validators are independent cross-checks.

* every valid example must pass both
* every invalid example must fail; when the expected keyword is a JSON-Schema
  keyword, jsonschema must report exactly that keyword at that path.
  "semantic" examples must pass JSON Schema but fail pydantic (cross-field
  rules that JSON Schema cannot express)

Usage: python docs/specs/contracts/validate_examples.py   (exit 0 = all as declared)
"""

import json
import sys
from pathlib import Path

import jsonschema

HERE = Path(__file__).resolve().parent
SPECS = HERE.parent
sys.path.insert(0, str(SPECS.parent.parent / "src"))

from sonicclue.domain.model import CONTRACT_TYPES  # noqa: E402


def pointer(err) -> str:
    return "".join(f"/{p}" for p in err.absolute_path)


def main() -> int:
    failures = []
    count = 0
    schemas = {p.name.split(".")[0]: json.loads(p.read_text()) for p in (SPECS / "schemas").glob("*.schema.json")}
    for p in sorted((HERE / "examples/valid").glob("*.json")):
        name = p.stem
        doc = json.loads(p.read_text())
        count += 1
        errs = list(jsonschema.Draft202012Validator(schemas[name]).iter_errors(doc))
        if errs:
            failures.append(f"{p.name}: schema rejects valid example: {errs[0].message}")
        try:
            CONTRACT_TYPES[name].model_validate(doc)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{p.name}: pydantic rejects valid example: {str(exc).splitlines()[0]}")
    for p in sorted((HERE / "examples/invalid").glob("*.json")):
        if p.name.endswith(".expected-error.json"):
            continue
        exp = json.loads(p.with_name(p.stem + ".expected-error.json").read_text())
        name = exp["contract"]
        doc = json.loads(p.read_text())
        count += 1
        errs = list(jsonschema.Draft202012Validator(schemas[name]).iter_errors(doc))
        try:
            CONTRACT_TYPES[name].model_validate(doc)
            py_ok = True
        except Exception:  # noqa: BLE001
            py_ok = False
        if py_ok:
            failures.append(f"{p.name}: pydantic accepted an invalid example")
        if exp["keyword"] == "semantic":
            if errs and exp["path"] != "/schema_version":
                failures.append(f"{p.name}: expected schema to accept (semantic rule) but got {errs[0].validator}")
        else:
            hits = [e for e in errs if e.validator == exp["keyword"] and pointer(e) == exp["path"]]
            if not hits:
                got = ", ".join(f"{e.validator}@{pointer(e)}" for e in errs) or "no error"
                failures.append(f"{p.name}: expected {exp['keyword']}@{exp['path']}, got {got}")
    for f in failures:
        print("FAIL", f)
    print(f"{count - len(failures)}/{count} examples behave as declared")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
