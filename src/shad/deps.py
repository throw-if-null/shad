"""
What the root injects into a slice's `run`: the output streams, the trace,
the tmux, the editor and the harnesses this run drives, the config file and the data
directory this run resolved, and the configuration loaded from them. One
Deps per run.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from shad.config import Config, load
from shad.editor import Editor
from shad.harness import Harnesses
from shad.output import Output
from shad.tmux import Tmux
from shad.trace import Trace


@dataclass(frozen=True)
class Deps:
    out: Output
    trace: Trace
    tmux: Tmux
    editor: Editor
    harnesses: Harnesses
    # --config, else $SHAD_CONFIG, else the per-OS default. The config
    # actions and `init` edit this file; every other command reads it
    # through `config`.
    config_file: Path
    # The per-OS data directory: the snapshot, and the todo files by default.
    data_dir: Path

    @cached_property
    def config(self) -> Config:
        """
        The file loaded and validated, once per run, on the first command
        that needs it: `shad config validate` and `shad init` must run when
        it does not load. Raises as `load` does.
        """
        return load(self.config_file, data_dir=self.data_dir)
