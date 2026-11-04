"""`python -m shad`: the entry point the `shad` console script runs."""

from __future__ import annotations

import sys

from shad.cli import main

if __name__ == "__main__":
    sys.exit(main())
