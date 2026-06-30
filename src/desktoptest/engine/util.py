"""engine/util.py — tiny helpers shared across the engine."""

from __future__ import annotations

import json
import re
from typing import Any


def parse_json(text: str) -> Any:
    """
    Robustly extract a JSON object from a model response. Models occasionally
    wrap JSON in ```json fences or add a stray sentence; this strips that.
    """
    if not text:
        raise ValueError("empty model response")
    t = text.strip()
    # strip markdown fences if present
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
    if fence:
        t = fence.group(1).strip()
    # otherwise grab the outermost {...}
    if not t.startswith("{"):
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end != -1:
            t = t[start:end + 1]
    return json.loads(t)
