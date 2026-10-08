"""
Minimal, comment-preserving TOML value editor.

`tomllib` reads TOML but the stdlib has no writer, and shad has no external
dependencies beyond `rich`.  This module edits the config file as text so
comments, ordering, and alignment survive a `shad config set`.

Scope and limits
----------------
- Scalar values only.  Multi-line values (arrays spanning lines, triple-quoted
  strings) are detected and rejected instead of being rewritten.
- Inline tables are not edited in place.
- Callers MUST verify the result with `tomllib` before replacing the real file;
  see `shad.config.command._commit`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from shad.shared.errors import ShadError

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


# ── key / value formatting ────────────────────────────────────────────────


def split_dotted(key: str) -> list[str]:
    """Split a dotted key path into segments.  Quoted segments may contain dots."""
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None

    for ch in key:
        if quote is not None:
            if ch == quote:
                quote = None
            else:
                buf.append(ch)
        elif ch in "\"'":
            quote = ch
        elif ch == ".":
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)

    if quote is not None:
        raise ShadError(f"unterminated quote in key '{key}'")

    parts.append("".join(buf).strip())
    if any(not part for part in parts):
        raise ShadError(f"invalid key '{key}'")
    return parts


def format_key(parts: list[str]) -> str:
    """Render a key path as TOML, quoting segments that are not bare keys."""
    out: list[str] = []
    for part in parts:
        if _BARE_KEY.match(part):
            out.append(part)
        else:
            escaped = part.replace("\\", "\\\\").replace('"', '\\"')
            out.append(f'"{escaped}"')
    return ".".join(out)


def format_value(value: object) -> str:
    """
    Render a Python scalar, or a list of scalars, as a TOML value literal.

    A list renders on one line, which is what keeps it inside the scope of
    set_value(): a value that spans lines is rejected there, not rewritten.
    """
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(format_value(item) for item in value) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


# ── line scanning ─────────────────────────────────────────────────────────


@dataclass
class _Section:
    table: list[str]
    array: bool
    header: int | None  # None for the implicit root section
    start: int          # first body line index
    end: int            # exclusive


@dataclass
class _KeyLine:
    index: int
    path: list[str]
    eq: int
    comment: int
    complete: bool  # False when the value continues on following lines


def _consume(
    line: str, ml: str | None, depth: int
) -> tuple[str | None, int, int, int]:
    """
    Walk one line, tracking multi-line string and array state.

    Returns (multiline delimiter after the line, bracket depth after the line,
    index of the first top-level '=', index of the comment start).  The two
    indices are -1 when absent and only meaningful for a line that starts
    outside a continuation.
    """
    eq = -1
    comment = -1
    i = 0
    n = len(line)

    while i < n:
        if ml is not None:
            if line.startswith(ml, i):
                ml = None
                i += 3
            else:
                i += 1
            continue

        if line.startswith('"""', i) or line.startswith("'''", i):
            ml = line[i : i + 3]
            i += 3
            continue

        ch = line[i]
        if ch in "\"'":
            quote = ch
            i += 1
            while i < n:
                if quote == '"' and line[i] == "\\":
                    i += 2
                    continue
                if line[i] == quote:
                    i += 1
                    break
                i += 1
            continue

        if ch == "#":
            comment = i
            break
        if ch == "=" and eq < 0:
            eq = i
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        i += 1

    return ml, depth, eq, comment


def _header_path(line: str, comment: int) -> tuple[list[str], bool] | None:
    """Parse a table header line into (path, is_array_of_tables)."""
    body = (line if comment < 0 else line[:comment]).strip()
    if body.startswith("[[") and body.endswith("]]"):
        return split_dotted(body[2:-2]), True
    if body.startswith("[") and body.endswith("]"):
        return split_dotted(body[1:-1]), False
    return None


def _scan(lines: list[str]) -> tuple[list[_Section], list[_KeyLine]]:
    sections = [_Section(table=[], array=False, header=None, start=0, end=len(lines))]
    keys: list[_KeyLine] = []
    ml: str | None = None
    depth = 0

    for index, raw in enumerate(lines):
        logical_start = ml is None and depth == 0
        ml, depth, eq, comment = _consume(raw, ml, depth)
        if not logical_start:
            continue

        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("["):
            header = _header_path(raw, comment)
            if header is None:
                continue
            table, array = header
            sections[-1].end = index
            sections.append(
                _Section(
                    table=table,
                    array=array,
                    header=index,
                    start=index + 1,
                    end=len(lines),
                )
            )
            continue

        if eq < 0:
            continue

        keys.append(
            _KeyLine(
                index=index,
                path=sections[-1].table + split_dotted(raw[:eq]),
                eq=eq,
                comment=comment,
                complete=ml is None and depth == 0,
            )
        )

    return sections, keys


def _join(lines: list[str], original: str) -> str:
    if not lines:
        return ""
    trailing = "\n" if (original.endswith("\n") or not original) else ""
    return "\n".join(lines) + trailing


def _replace_value(line: str, key: _KeyLine, literal: str) -> str:
    head = line[: key.eq + 1]
    tail = "" if key.comment < 0 else line[key.comment :]
    middle = line[key.eq + 1 :] if key.comment < 0 else line[key.eq + 1 : key.comment]

    lead = middle[: len(middle) - len(middle.lstrip())] or " "
    trail = middle[len(middle.rstrip()) :]
    return head + lead + literal + trail + tail


# ── public edits ──────────────────────────────────────────────────────────


def set_value(text: str, parts: list[str], literal: str) -> str:
    """
    Return *text* with the key path *parts* set to the TOML *literal*.

    Updates the value in place when the key exists, appends it to the matching
    table when the table exists, and otherwise appends a new table at the end.
    """
    if len(parts) < 2:
        raise ShadError("key must contain at least one dot, e.g. defaults.harness")

    lines = text.splitlines()
    sections, keys = _scan(lines)

    for key in keys:
        if key.path != parts:
            continue
        if not key.complete:
            raise ShadError(
                f"'{format_key(parts)}' has a multi-line value; edit the file with "
                f"'shad config edit'"
            )
        lines[key.index] = _replace_value(lines[key.index], key, literal)
        return _join(lines, text)

    table = parts[:-1]
    entry = f"{format_key([parts[-1]])} = {literal}"

    for section in sections:
        if section.table != table or section.array:
            continue
        # Insert after the last key line, so trailing comments that introduce the
        # next table stay attached to it.
        insert_at = section.start
        for key in keys:
            if section.start <= key.index < section.end:
                insert_at = key.index + 1
        lines.insert(insert_at, entry)
        return _join(lines, text)

    while lines and not lines[-1].strip():
        lines.pop()
    if lines:
        lines.append("")
    lines.append(f"[{format_key(table)}]")
    lines.append(entry)
    return _join(lines, text)


def remove_path(text: str, parts: list[str]) -> str:
    """
    Return *text* with the key or table at *parts* removed.

    Removing a table also removes its sub-tables.  Raises ShadError when the
    path is not present in the file.
    """
    lines = text.splitlines()
    sections, keys = _scan(lines)

    def _under(path: list[str]) -> bool:
        return path[: len(parts)] == parts

    drop: set[int] = set()

    for key in keys:
        if _under(key.path):
            if not key.complete:
                raise ShadError(
                    f"'{format_key(key.path)}' has a multi-line value; edit the file "
                    f"with 'shad config edit'"
                )
            drop.add(key.index)

    for section in sections:
        if section.header is None or not _under(section.table):
            continue
        drop.update(range(section.header, min(section.end, len(lines))))

    if not drop:
        raise ShadError(f"key not found: {format_key(parts)}")

    kept = [line for index, line in enumerate(lines) if index not in drop]
    while kept and not kept[-1].strip():
        kept.pop()
    return _join(kept, text)
