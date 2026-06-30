"""engine/loader.py — load YAML test cases into TestCase objects."""

from __future__ import annotations

from pathlib import Path
from typing import List

import yaml

from .schema import Step, TestCase


def load_test(path: str | Path) -> TestCase:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    steps = [Step(action=s.get("action", ""), target=str(s.get("target", "")),
                  value=str(s.get("value", "")), note=s.get("note", ""))
             for s in (data.get("steps") or [])]
    for s in steps:
        s.validate()
    return TestCase(
        name=data.get("name", Path(path).stem),
        intent=data.get("intent", ""),
        transaction=data.get("transaction", ""),
        expect=data.get("expect", ""),
        steps=steps,
    )


def load_dir(folder: str | Path) -> List[TestCase]:
    folder = Path(folder)
    return [load_test(p) for p in sorted(folder.glob("*.y*ml"))]
