"""Locate bundled assets both in a checkout and in a frozen build."""

from __future__ import annotations

import sys
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def asset(*parts: str) -> Path:
    return project_root().joinpath("assets", *parts)
