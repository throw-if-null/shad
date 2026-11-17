"""
Test support that drives shad the way its users do.

`run` calls the entry point in this process and returns the exit code and
the two streams. `TmuxServer` starts a separate tmux server for one test,
on a private socket, and `Pane` runs a command in a window of it under a
real pseudo-terminal, for the commands that drive tmux or need a terminal.
`TmuxCase` wires both to a temporary home, config and data directory.

No command imports this module.
"""

from __future__ import annotations

import contextlib
import io
import itertools
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypeVar
from unittest.mock import patch

import shad
from shad.cli import main

# The directory `import shad` resolved to. A shad subprocess gets it as
# PYTHONPATH so it runs the code under test: an editable install of another
# checkout would win otherwise.
PACKAGE_PARENT = Path(shad.__file__).resolve().parent.parent

KEEPER = "shad-test-server"  # the session that keeps a test server alive

_counter = itertools.count(1)

T = TypeVar("T")


@dataclass(frozen=True)
class Result:
    code: int
    out: str
    err: str


def run(argv: Sequence[str], *, env: Mapping[str, str | None] | None = None) -> Result:
    """
    `shad <argv>` in this process, through `cli.main`: the exit code, stdout
    and stderr a caller observes.

    *env* is applied to the process environment for the call and undone
    afterwards; a None value removes the variable. The commands read the
    environment directly, so this is how a run is pointed at a temporary
    config (SHAD_CONFIG), data directory (XDG_DATA_HOME) or home.
    """
    out, err = io.StringIO(), io.StringIO()
    with (
        patch.dict(os.environ),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(err),
    ):
        for name, value in (env or {}).items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        code = main(list(argv))
    return Result(code, out.getvalue(), err.getvalue())


def shad_argv(*args: str) -> list[str]:
    """The command line that runs this shad as a separate process."""
    return [sys.executable, "-m", "shad", *args]


class TmuxServer:
    """
    A separate tmux server, started by one test for its use alone and
    killed by it. The user's server is never touched.

    tmux keeps its default socket under $TMUX_TMPDIR, and a client inside
    tmux follows $TMUX instead. The environment this server hands out sets
    the first to a private directory and removes the second, so every tmux
    call a shad process started by the test makes reaches this server and
    never the user's. The calls this class makes name the socket outright (-S):
    with TMUX_TMPDIR alone, tmux falls back to the user's server once the
    directory is gone. The user's tmux.conf is not read (-f /dev/null), so
    the tests see tmux's defaults.

    The socket directory is under /tmp whatever TMPDIR says: a Unix socket
    path is limited to about 100 bytes.
    """

    def __init__(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix="shad-tmux-", dir="/tmp"))
        # The path tmux derives from TMUX_TMPDIR, so -S and the environment agree.
        self.socket = self.directory / f"tmux-{os.getuid()}" / "default"
        self.socket.parent.mkdir(mode=0o700)  # tmux creates it for its default path only
        self.env: dict[str, str] = {**os.environ, "TMUX_TMPDIR": str(self.directory)}
        self.env.pop("TMUX", None)
        try:
            # A server exits with its last session, and a global option needs
            # a running server. The keeper outlives every session a test
            # creates.
            self.tmux("new-session", "-d", "-s", KEEPER, "sleep 100000")
            # A pane whose command has exited stays, with the exit status.
            self.tmux("set-option", "-g", "remain-on-exit", "on")
            self.tmux("set-option", "-g", "default-shell", "/bin/sh")
        except Exception:
            self.kill()
            raise

    def tmux(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["tmux", "-S", str(self.socket), "-f", "/dev/null", *args],
            env=self.env,
            capture_output=True,
            text=True,
            check=check,
            timeout=30,
        )

    @property
    def socket_path(self) -> str:
        """The socket as the running server reports it."""
        return self.tmux("display-message", "-p", "#{socket_path}").stdout.strip()

    def sessions(self) -> list[str]:
        """Every session on this server except the keeper."""
        result = self.tmux("list-sessions", "-F", "#S", check=False)
        return [name for name in result.stdout.split() if name != KEEPER]

    def new_session(
        self, name: str, *, cwd: Path | None = None, command: str | None = None
    ) -> None:
        args = ["new-session", "-d", "-s", name, "-x", "120", "-y", "40"]
        if cwd is not None:
            args += ["-c", str(cwd)]
        if command is not None:
            args.append(command)
        self.tmux(*args)

    def kill(self) -> None:
        self.tmux("kill-server", check=False)
        shutil.rmtree(self.directory, ignore_errors=True)


class Pane:
    """
    A window on *server* that runs one command under a real pseudo-terminal.

    Keys go in through `send` and `type`; the screen comes back through
    `screen`. The window stays after the command exits, so `wait_exit` can
    read its status. *env* is applied on top of the pane's environment,
    which is the server's, with TMUX set by tmux to this server.
    """

    def __init__(
        self,
        server: TmuxServer,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        cwd: Path,
        width: int = 100,
        height: int = 30,
    ) -> None:
        self.server = server
        self.name = f"shad-test-pane-{next(_counter)}"
        assignments = " ".join(f"{name}={shlex.quote(value)}" for name, value in env.items())
        command = f"exec env {assignments} {shlex.join(argv)}"
        server.tmux(
            "new-session", "-d", "-s", self.name,
            "-x", str(width), "-y", str(height), "-c", str(cwd), command,
        )

    def send(self, *keys: str) -> None:
        """Key names as tmux spells them: `q`, `Enter`, `Down`, `C-c`."""
        self.server.tmux("send-keys", "-t", self.name, *keys)

    def type(self, text: str) -> None:
        """*text* as typed, with no key name interpreted."""
        self.server.tmux("send-keys", "-t", self.name, "-l", text)

    def screen(self) -> str:
        """
        Everything the pane has shown, scrollback included: when the
        command exits, tmux scrolls a line into history to place its
        "Pane is dead" marker, so the visible rows alone lose output.
        """
        result = self.server.tmux("capture-pane", "-p", "-S", "-", "-t", self.name)
        return result.stdout.rstrip("\n")

    def current_command(self) -> str:
        """The foreground process, as shad's `pane_commands` reads it."""
        result = self.server.tmux(
            "display-message", "-p", "-t", self.name, "#{pane_current_command}"
        )
        return result.stdout.strip()

    def wait_for(self, text: str, *, timeout: float = 10.0) -> str:
        """The screen once *text* appears on it."""
        return self._wait(lambda: self.screen(), lambda screen: text in screen, timeout, text)

    def wait_for_command(self, name: str, *, timeout: float = 10.0) -> str:
        """The foreground command once it is *name*."""
        return self._wait(self.current_command, lambda found: found == name, timeout, name)

    def wait_exit(self, *, timeout: float = 10.0) -> int:
        """The command's exit status once it has ended."""

        def status() -> int | None:
            result = self.server.tmux(
                "display-message", "-p", "-t", self.name,
                "#{pane_dead}:#{pane_dead_status}:#{pane_pid}",
            )
            dead, code, pid = result.stdout.strip().split(":")
            if dead != "1":
                return None
            return int(code) if code else _unreaped_status(int(pid))

        code = self._wait(status, lambda found: found is not None, timeout, "exit")
        assert code is not None  # _wait returned because it is
        return code

    def _wait(
        self, read: Callable[[], T], done: Callable[[T], bool], timeout: float, what: str
    ) -> T:
        deadline = time.monotonic() + timeout
        while True:
            value = read()
            if done(value):
                return value
            if time.monotonic() > deadline:
                raise AssertionError(
                    f"{what!r} did not happen within {timeout}s; screen:\n{self.screen()}"
                )
            time.sleep(0.05)


def _unreaped_status(pid: int) -> int | None:
    """
    The exit status of *pid*, a process that has exited but that its parent
    has not reaped, read from /proc. tmux 3.4 (Ubuntu 24.04) sometimes never
    reaps a pane process that exits within its first moments: the pane is
    dead, the process stays a zombie, and pane_dead_status stays empty.
    None while the process has not exited.
    """
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    fields = stat.rpartition(")")[2].split()  # the state onward; the name may hold spaces
    if fields[0] != "Z" or len(fields) < 50:
        return None
    code = int(fields[49])  # exit_code, field 52 of /proc/[pid]/stat, in waitpid's form
    return code >> 8 if code & 0x7F == 0 else 128 + (code & 0x7F)


class TmuxCase(unittest.TestCase):
    """
    A test with a tmux server, a home, a config and a data directory of its
    own. `self.env` is the environment a shad run or pane gets: HOME and the
    XDG directories under the temporary root, SHAD_CONFIG at self.config,
    PATH with self.bin first, and the server's socket directory.
    """

    def setUp(self) -> None:
        tmp = TemporaryDirectory(prefix="shad-test-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        self.bin = self.root / "bin"
        self.data = self.root / "data"
        self.config = self.root / "shad.toml"
        for directory in (self.home, self.bin, self.data):
            directory.mkdir()
        self.server = TmuxServer()
        self.addCleanup(self.server.kill)
        self.env: dict[str, str] = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.data),
            "SHAD_CONFIG": str(self.config),
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "PYTHONPATH": str(PACKAGE_PARENT),
            "TMUX_TMPDIR": str(self.server.directory),
        }

    def write_config(self, text: str) -> None:
        self.config.write_text(text)

    def run_shad(self, *args: str) -> Result:
        """`shad <args>` in this process, outside any tmux client."""
        return run(args, env={**self.env, "TMUX": None})

    def pane(
        self, *args: str, cwd: Path | None = None, width: int = 100, height: int = 30
    ) -> Pane:
        """`shad <args>` as a process in a pane of this test's server."""
        return Pane(
            self.server, shad_argv(*args), env=self.env, cwd=cwd or self.root,
            width=width, height=height,
        )

    def fake_harness(self, name: str) -> Path:
        """
        A *name* command on self.bin that sleeps. A pane running it reports
        *name* as its foreground command, which is how shad tells that a
        harness is still running. bash's `exec -a` sets the process name; a
        script that merely ran sleep would report `sleep`.
        """
        script = self.bin / name
        script.write_text(f"#!/bin/bash\nexec -a {name} sleep 100000\n")
        script.chmod(0o755)
        return script
