"""Configuration loader (spec §4, §7.6).

Thresholds live in ``config/thresholds.yaml``, never hardcoded — they drift and
get re-anchored each quarter. A tiny hand-rolled YAML reader is included so the
tool runs with zero third-party deps if PyYAML is not installed.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any

_REL = os.path.join("config", "thresholds.yaml")
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))


def _default_config_path() -> str:
    """Locate thresholds.yaml whether running from the repo checkout (`python -m`)
    or as an installed console script (search the current working directory)."""
    candidates = [
        os.path.join(os.path.dirname(_PKG_DIR), _REL),  # repo layout
        os.path.join(os.getcwd(), _REL),                # cwd is the checkout
        os.path.join(_PKG_DIR, _REL),                   # packaged copy, if bundled
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]


DEFAULT_CONFIG_PATH = _default_config_path()


def _load_yaml(path: str) -> dict:
    try:
        import yaml  # type: ignore

        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except ImportError:
        with open(path, "r", encoding="utf-8") as fh:
            return _mini_yaml(fh.read())


def _coerce(value: str) -> Any:
    v = value.strip()
    if v == "":
        return None
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_coerce(x.strip().strip('"').strip("'")) for x in inner.split(",")]
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    for caster in (int, float):
        try:
            return caster(v)
        except ValueError:
            pass
    return v.strip('"').strip("'")


def _mini_yaml(text: str) -> dict:
    """Minimal YAML subset parser: nested maps by 2-space indent, scalars and
    inline ``[a, b]`` lists. Sufficient for thresholds.yaml; not general."""
    root: dict = {}
    stack = [(-1, root)]
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip() if not _in_quotes_hash(raw) else raw.rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, _, val = line.strip().partition(":")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if val.strip() == "":
            new: dict = {}
            parent[key.strip()] = new
            stack.append((indent, new))
        else:
            parent[key.strip()] = _coerce(val)
    return root


def _in_quotes_hash(line: str) -> bool:
    # We never put '#' inside quoted values in thresholds.yaml; keep simple.
    return False


class Config:
    def __init__(self, data: dict):
        self._d = data

    def __getitem__(self, key: str) -> Any:
        return self._d[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._d.get(key, default)

    @property
    def last_reanchored(self) -> date:
        raw = self._d.get("last_reanchored")
        if isinstance(raw, date):
            return raw
        return datetime.strptime(str(raw), "%Y-%m-%d").date()

    def cadence_days(self, indicator_id: str) -> int:
        return int(self._d["cadence_days"][indicator_id])

    @property
    def staleness_multiplier(self) -> float:
        return float(self._d.get("staleness_multiplier", 1.5))

    def reanchor_overdue(self, today: date) -> bool:
        nag = int(self._d["guardrails"]["reanchor_nag_days"])
        return (today - self.last_reanchored).days > nag


def load_config(path: str | None = None) -> Config:
    return Config(_load_yaml(path or _default_config_path()))
