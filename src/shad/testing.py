"""
Test support that drives shad the way its users do.

`run` calls the entry point in this process and returns the exit code and
the two streams. `TmuxServer` starts a separate tmux server for one test,
on a private socket, and `Pane` runs a command in a window of it under a
real pseudo-terminal, for the commands that drive tmux or need a terminal.
`TmuxCase` wires both to a temporary home, config and data directory.
`FakeEditor` is an $EDITOR that is a real program.

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
from shad.deps import Deps
from shad.output import Output
from shad.shared.config import Config
from shad.trace import Trace

# The directory `import shad` resolved to. A shad subprocess gets it as
# PYTHONPATH so it runs the code under test: an editable install of another
# checkout would win otherwise.
PACKAGE_PARENT = Path(shad.__file__).resolve().parent.parent

KEEPER = "shad-test-server"  # the session that keeps a test server alive

# What a test process must not inherit: the user's tmux, the user's kitty
# (restore would open real tabs), and the user's editor.
UNSET = ("TMUX", "KITTY_WINDOW_ID", "KITTY_LISTEN_ON", "VISUAL", "EDITOR")

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


def deps(
    cfg: Config, *, out: Output | None = None, config_file: Path | None = None
) -> Deps:
    """
    The Deps a unit test hands a slice's `run` directly: *cfg* stands in for
    the file, and *out* captures nothing unless given. `[TEST-3]`.
    """
    result = Deps(
        out=out or Output(stdout=io.StringIO(), stderr=io.StringIO()),
        trace=Trace(),
        config_file=config_file or Path(os.devnull),
    )
    result.__dict__["config"] = cfg  # seeds the cached_property, so no file is read
    return result


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

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        """
        *env* is added to this process's environment to form the server's.
        Every pane the server opens, including the panes a shad layout
        creates, inherits it.
        """
        self.directory = Path(tempfile.mkdtemp(prefix="shad-tmux-", dir="/tmp"))
        # The path tmux derives from TMUX_TMPDIR, so -S and the environment agree.
        self.socket = self.directory / f"tmux-{os.getuid()}" / "default"
        self.socket.parent.mkdir(mode=0o700)  # tmux creates it for its default path only
        self.env: dict[str, str] = {
            **os.environ, **(env or {}), "TMUX_TMPDIR": str(self.directory)
        }
        for name in UNSET:
            self.env.pop(name, None)
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
        """
        A detached session. *command* runs under `/bin/sh -c`; start it with
        `exec` when the pane's command must read as the program, because
        dash keeps `sh -c` alive around it.
        """
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
        env: Mapping[str, str | None],
        cwd: Path,
        width: int = 100,
        height: int = 30,
        session: str | None = None,
    ) -> None:
        """A None in *env* removes the variable. *session* names the tmux session."""
        self.server = server
        self.name = session or f"shad-test-pane-{next(_counter)}"
        # env takes its options before the assignments.
        removals = " ".join(f"-u {name}" for name, value in env.items() if value is None)
        assignments = " ".join(
            f"{name}={shlex.quote(value)}" for name, value in env.items() if value is not None
        )
        command = f"exec env {removals} {assignments} {shlex.join(argv)}"
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
    A test with a separate tmux server, home, config and data directory.
    `self.env` is the environment that every shad run, every pane and the
    server itself get: HOME and the XDG directories under the temporary
    root, SHAD_CONFIG at self.config, PATH with self.bin first, where a
    `shad` runs this checkout, PYTHONPATH for the same, the server's socket
    directory, and none of UNSET.
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
        shim = self.bin / "shad"
        shim.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -m shad "$@"\n')
        shim.chmod(0o755)
        self.env: dict[str, str | None] = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.data),
            "SHAD_CONFIG": str(self.config),
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "PYTHONPATH": str(PACKAGE_PARENT),
            **dict.fromkeys(UNSET),
        }
        self.server = TmuxServer(env={k: v for k, v in self.env.items() if v is not None})
        self.addCleanup(self.server.kill)
        self.env["TMUX_TMPDIR"] = str(self.server.directory)

    def write_config(self, text: str) -> None:
        self.config.write_text(text)

    def run_shad(self, *args: str) -> Result:
        """`shad <args>` in this process, outside any tmux client."""
        return run(args, env=self.env)

    def run_detached(self, *args: str) -> Result:
        """
        `shad <args>` as a process with no controlling terminal: what a
        script or a cron job sees. Its tmux calls reach this test's server.
        """
        env = {**os.environ, **{k: v for k, v in self.env.items() if v is not None}}
        for name in UNSET:
            env.pop(name, None)
        result = subprocess.run(
            shad_argv(*args), env=env, cwd=self.root, start_new_session=True,
            capture_output=True, text=True, timeout=60, check=False,
        )
        return Result(result.returncode, result.stdout, result.stderr)

    def pane(
        self,
        *args: str,
        env: Mapping[str, str | None] | None = None,
        cwd: Path | None = None,
        width: int = 100,
        height: int = 30,
        session: str | None = None,
    ) -> Pane:
        """
        `shad <args>` as a process in a pane of this test's server. The pane
        keeps the TMUX that tmux sets for it: that is how the process knows
        it runs inside tmux, and it names this server.
        """
        pane_env = {name: value for name, value in self.env.items() if name != "TMUX"}
        return Pane(
            self.server, shad_argv(*args), env={**pane_env, **(env or {})},
            cwd=cwd or self.root, width=width, height=height, session=session,
        )

    def attach_client(self, session: str, *, width: int = 100, height: int = 30) -> Pane:
        """
        A tmux client attached to *session*, running in a separate pane:
        what a user's terminal of *width* by *height* is to a session.
        Returns once it is attached.
        """
        pane = Pane(
            self.server,
            ["tmux", "-S", str(self.server.socket), "-f", "/dev/null",
             "attach-session", "-t", f"={session}"],
            env=self.env,
            cwd=self.root,
            width=width,
            height=height,
        )
        deadline = time.monotonic() + 10
        while session not in self.clients():
            if time.monotonic() > deadline:
                raise AssertionError(f"no client attached to {session}; screen:\n{pane.screen()}")
            time.sleep(0.05)
        return pane

    def clients(self) -> dict[str, str]:
        """The clients on the server, as {session: client tty}."""
        result = self.server.tmux(
            "list-clients", "-F", "#{client_session} #{client_tty}", check=False
        )
        pairs = (line.split(" ", 1) for line in result.stdout.splitlines() if " " in line)
        return {session: tty for session, tty in pairs}

    def wait_for_client_on(self, predicate: Callable[[str], bool], *, timeout: float = 10.0) -> str:
        """The first client session that *predicate* accepts, once there is one."""
        deadline = time.monotonic() + timeout
        while True:
            for session in self.clients():
                if predicate(session):
                    return session
            if time.monotonic() > deadline:
                raise AssertionError(f"clients: {self.clients()}; screen:\n{self.shell_screen()}")
            time.sleep(0.05)

    def shell_with_client(self, *, width: int = 100, height: int = 30) -> None:
        """A `shell` session running sh, with a client attached: a user at a prompt."""
        self.server.new_session("shell", cwd=self.root, command="sh")
        self.attach_client("shell", width=width, height=height)

    def type_into_shell(self, command: str) -> None:
        self.server.tmux("send-keys", "-t", "shell", command, "Enter")

    def shell_screen(self) -> str:
        result = self.server.tmux("capture-pane", "-p", "-S", "-", "-t", "shell", check=False)
        return result.stdout

    def wait_for_shell(self, text: str, *, timeout: float = 10.0) -> str:
        """The shell's screen once *text* appears on it."""
        deadline = time.monotonic() + timeout
        while True:
            screen = self.shell_screen()
            if text in screen:
                return screen
            if time.monotonic() > deadline:
                raise AssertionError(f"{text!r} did not appear; screen:\n{screen}")
            time.sleep(0.05)

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


class FakeEditor:
    """
    An $EDITOR for tests, as a real program. Each time it runs it records
    the file it was given and the text it found there, saves the next of
    *drafts* over the file (None leaves the file as it was), and exits with
    *status*. `command` is the value to put in EDITOR.
    """

    def __init__(
        self, directory: Path, drafts: Sequence[str | None] = (), *, status: int = 0
    ) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        for index, draft in enumerate(drafts):
            if draft is not None:
                (directory / f"draft-{index}.md").write_text(draft)
        (directory / "status").write_text(str(status))
        self.script = directory / "editor"
        self.script.write_text(
            f"#!{sys.executable}\n"
            "import pathlib, shutil, sys\n"
            f"state = pathlib.Path({str(directory)!r})\n"
            "path = pathlib.Path(sys.argv[-1])\n"
            "index = sum(1 for _ in state.glob('shown-*.path'))\n"
            "(state / f'shown-{index}.path').write_text(str(path))\n"
            "(state / f'shown-{index}.md').write_text(path.read_text())\n"
            "draft = state / f'draft-{index}.md'\n"
            "if draft.exists():\n"
            "    shutil.copyfile(draft, path)\n"
            "sys.exit(int((state / 'status').read_text()))\n"
        )
        self.script.chmod(0o755)

    @property
    def command(self) -> str:
        return str(self.script)

    def shown(self) -> list[tuple[Path, str]]:
        """Each file the editor was given, with the text it found, in order."""
        found: list[tuple[Path, str]] = []
        for index in itertools.count():
            record = self.directory / f"shown-{index}.path"
            if not record.exists():
                return found
            text = (self.directory / f"shown-{index}.md").read_text()
            found.append((Path(record.read_text()), text))
        raise AssertionError("unreachable")
