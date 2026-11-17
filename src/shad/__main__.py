"""`python -m shad`: exits with what `cli.main` returns, as the `shad` console script does."""

from __future__ import annotations

import sys

from shad.cli import main

if __name__ == "__main__":
    sys.exit(main())
