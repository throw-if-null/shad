"""Validate a label name for `shad todo label add` and `shad todo label rm`."""

from __future__ import annotations

import argparse

from shad.config import LABEL_RE
from shad.errors import ShadError


def label_name(args: argparse.Namespace) -> str:
    name: str = args.name.strip()
    if not LABEL_RE.match(name):
        raise ShadError.validation(
            "invalid_label", f"invalid label {name!r}; use lowercase letters, digits and hyphens"
        )
    return name
