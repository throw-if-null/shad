"""
Shell completion script for shad.

Usage:
  shad completion bash   # print bash completion script

To install:
  echo 'source <(shad completion bash)' >> ~/.bashrc

Source the script rather than pasting its text into a startup file. A pasted
copy is a snapshot: it keeps offering the command surface that existed when it
was written, long after `shad` itself has moved on.

The enum values in `config/schema.py` are interpolated into the script when it
is generated, so `shad config set <key> <TAB>` can offer real values without a
second process launch.
"""

from __future__ import annotations

import argparse

from shad import parsers
from shad.config import HARNESSES, OC_POSITIONS
from shad.output import Output
from shad.todo import STATUSES

# Helper functions read `cur`, `args`, `flags`, `_shad_cmd` and the project
# arrays as locals of `_shad_complete`. Bash scopes locals dynamically, so a
# callee sees its caller's locals; nothing leaks into the user's shell.
_BASH_TEMPLATE = r"""
_shad_offer() {
    local current="$1"
    shift
    mapfile -t COMPREPLY < <(compgen -W "$*" -- "$current")
}

# Hand the word back to readline so its own filename rules apply: tilde
# expansion, trailing slashes, and quoting of names that contain spaces.
_shad_offer_paths() {
    COMPREPLY=()
    compopt -o default
}

_shad_offer_dirs() {
    COMPREPLY=()
    compopt -o dirnames
}

# Print the flags in $1 that are not already present in the remaining
# arguments, so a flag is never offered twice on one command line.
_shad_unused() {
    local -a candidates=()
    read -r -a candidates <<<"$1"
    shift

    local candidate used
    for candidate in "${candidates[@]}"; do
        for used in "$@"; do
            [[ "$candidate" == "$used" ]] && continue 2
        done
        printf '%s ' "$candidate"
    done
}

# Fill _shad_top, _shad_groups and _shad_group_pairs from `shad config keys`,
# which prints plain dotted paths. `shad projects` output is decorated with
# ●/◆ bullets for humans and is not safe to parse.
_shad_load_projects() {
    _shad_top=()
    _shad_groups=()
    _shad_group_pairs=()

    local raw line
    raw=$("${_shad_cmd[@]}" config keys 2>/dev/null) || return 0

    while IFS= read -r line; do
        if [[ "$line" =~ ^projects\.([^.]+)\.([^.]+)\.path$ ]]; then
            _shad_group_pairs+=("${BASH_REMATCH[1]} ${BASH_REMATCH[2]}")
            _shad_groups+=("${BASH_REMATCH[1]}")
        elif [[ "$line" =~ ^projects\.([^.]+)\.path$ ]]; then
            _shad_top+=("${BASH_REMATCH[1]}")
        fi
    done <<<"$raw"

    # One key line per field, so every group name repeats.
    if ((${#_shad_groups[@]} > 0)); then
        mapfile -t _shad_groups < <(printf '%s\n' "${_shad_groups[@]}" | sort -u)
    fi
}

# Print the sub-projects of the group that $1 names, applying the same
# exact-then-prefix rule as shared/config.py::resolve_prefix.
_shad_subprojects() {
    local token="$1" entry group exact=""

    for entry in "${_shad_group_pairs[@]}"; do
        group="${entry%% *}"
        [[ "$group" == "$token" ]] && exact="$token"
    done

    for entry in "${_shad_group_pairs[@]}"; do
        group="${entry%% *}"
        if [[ -n "$exact" ]]; then
            [[ "$group" == "$exact" ]] && printf '%s ' "${entry##* }"
        elif [[ "$group" == "$token"* ]]; then
            printf '%s ' "${entry##* }"
        fi
    done
}

_shad_is_top() {
    local key
    for key in "${_shad_top[@]}"; do
        [[ "$key" == "$1" ]] && return 0
    done
    return 1
}

# True when $1 resolves to a top-level project, so `status` is a valid next
# word. An exact match wins over a group that shares the prefix,
# which is why a token can be both a project and a group stem at once.
_shad_resolves_to_project() {
    local token="$1" key
    local -a matches=()

    for key in "${_shad_top[@]}" "${_shad_groups[@]}"; do
        if [[ "$key" == "$token" ]]; then
            _shad_is_top "$token"
            return
        fi
    done

    for key in "${_shad_top[@]}" "${_shad_groups[@]}"; do
        [[ "$key" == "$token"* ]] && matches+=("$key")
    done

    ((${#matches[@]} == 1)) && _shad_is_top "${matches[0]}"
}

_shad_complete_config() {
    if ((${#args[@]} == 0)); then
        _shad_offer "$cur" "show path keys get set unset edit validate"
        return
    fi

    case "${args[0]}" in
    show)
        _shad_offer "$cur" "$(_shad_unused "--json --raw" "${flags[@]}")"
        ;;
    get)
        if ((${#args[@]} == 1)); then
            _shad_offer "$cur" "$("${_shad_cmd[@]}" config keys 2>/dev/null)"
        else
            _shad_offer "$cur" "$(_shad_unused "--json" "${flags[@]}")"
        fi
        ;;
    validate)
        _shad_offer "$cur" "$(_shad_unused "--json" "${flags[@]}")"
        ;;
    unset)
        if ((${#args[@]} == 1)); then
            _shad_offer "$cur" "$("${_shad_cmd[@]}" config keys 2>/dev/null)"
        else
            _shad_offer "$cur" "$(_shad_unused "--force" "${flags[@]}")"
        fi
        ;;
    set)
        if ((${#args[@]} == 1)); then
            _shad_offer "$cur" "$("${_shad_cmd[@]}" config keys 2>/dev/null)"
        elif ((${#args[@]} == 2)); then
            # config/schema.py picks the field from the last key segment, so
            # the same suffix always carries the same value domain.
            case "${args[1]##*.}" in
            harness) _shad_offer "$cur" "__SHAD_HARNESSES__" ;;
            oc_position) _shad_offer "$cur" "__SHAD_OC_POSITIONS__" ;;
            git_panel | todo_panel) _shad_offer "$cur" "true false" ;;
            path) _shad_offer_dirs ;;
            esac
        else
            _shad_offer "$cur" "$(_shad_unused "--force" "${flags[@]}")"
        fi
        ;;
    esac
}

_shad_todo_keys() {
    "${_shad_cmd[@]}" todo list --keys 2>/dev/null
}

_shad_todo_labels() {
    "${_shad_cmd[@]}" todo label list 2>/dev/null
}

_shad_complete_todo() {
    if ((${#args[@]} == 0)); then
        _shad_offer "$cur" "panel add list status edit rm label"
        return
    fi

    local -a rest=("${args[@]:1}")

    case "${args[0]}" in
    add)
        # The title is the one positional; --label may repeat, so it is
        # always offered.
        _shad_offer "$cur" "--label"
        ;;
    list)
        _shad_offer "$cur" "$(_shad_unused "--json --keys" "${flags[@]}")"
        ;;
    status)
        if ((${#rest[@]} == 0)); then
            _shad_offer "$cur" "$(_shad_todo_keys)"
        elif ((${#rest[@]} == 1)); then
            _shad_offer "$cur" "__SHAD_TODO_STATUSES__"
        fi
        ;;
    edit | rm)
        if ((${#rest[@]} == 0)); then
            _shad_offer "$cur" "$(_shad_todo_keys)"
        fi
        ;;
    label)
        if ((${#rest[@]} == 0)); then
            _shad_offer "$cur" "add rm list"
        elif [[ "${rest[0]}" == "rm" ]]; then
            if ((${#rest[@]} == 1)); then
                _shad_offer "$cur" "$(_shad_todo_labels)"
            else
                _shad_offer "$cur" "$(_shad_unused "--force" "${flags[@]}")"
            fi
        fi
        ;;
    esac
}

_shad_complete() {
    local cur prev=""
    cur="${COMP_WORDS[COMP_CWORD]}"
    ((COMP_CWORD > 0)) && prev="${COMP_WORDS[COMP_CWORD - 1]}"

    # `--config PATH` is a global option that must precede the subcommand.
    # Bash breaks `--config=PATH` apart on the `=`, so accept both spellings.
    if [[ "$prev" == "--config" ]] ||
        { [[ "$prev" == "=" ]] && ((COMP_CWORD > 1)) && [[ "${COMP_WORDS[COMP_CWORD - 2]}" == "--config" ]]; }; then
        _shad_offer_paths
        return
    fi

    # `--harness NAME` takes one of a fixed set. These names mirror
    # shared/config.py::HARNESSES; the completion tests assert they match.
    if [[ "$prev" == "--harness" ]] ||
        { [[ "$prev" == "=" ]] && ((COMP_CWORD > 1)) && [[ "${COMP_WORDS[COMP_CWORD - 2]}" == "--harness" ]]; }; then
        _shad_offer "$cur" "opencode claude"
        return
    fi

    # Drop that option pair from the word list so it cannot shift any later
    # position, and replay it to the `shad config keys` call below; otherwise
    # the project names offered come from a different file than the one the
    # command will read.
    local -a words=() _shad_cmd=("${COMP_WORDS[0]}")
    local index=0
    while ((index < COMP_CWORD)); do
        if [[ "${COMP_WORDS[index]}" == "--config" ]]; then
            index=$((index + 1))
            [[ "${COMP_WORDS[index]}" == "=" ]] && index=$((index + 1))
            if ((index < COMP_CWORD)); then
                _shad_cmd+=(--config "${COMP_WORDS[index]}")
                index=$((index + 1))
            fi
            continue
        fi
        if [[ "${COMP_WORDS[index]}" == "--harness" || "${COMP_WORDS[index]}" == "--label" ]]; then
            # Keep the flag itself, so it is not offered a second time, but
            # drop its value: it is not a project name and must not shift
            # any later position.
            words+=("${COMP_WORDS[index]}")
            index=$((index + 1))
            [[ "${COMP_WORDS[index]}" == "=" ]] && index=$((index + 1))
            ((index < COMP_CWORD)) && index=$((index + 1))
            continue
        fi
        words+=("${COMP_WORDS[index]}")
        index=$((index + 1))
    done

    # Flags are accepted in any position, so positions are counted over the
    # non-flag words only.
    local -a positional=() flags=()
    local word
    for word in "${words[@]}"; do
        if [[ "$word" == -* ]]; then
            flags+=("$word")
        else
            positional+=("$word")
        fi
    done

    # positional[0] is the command name itself.
    if ((${#positional[@]} == 1)); then
        local top_flags="--debug --json --version --help"
        ((${#_shad_cmd[@]} == 1)) && top_flags="--config $top_flags"
        _shad_offer "$cur" \
            "projects git config completion init cheat todo sessions" \
            "$(_shad_unused "$top_flags" "${flags[@]}")"
        return
    fi

    local command="${positional[1]-}"
    local -a args=("${positional[@]:2}")

    case "$command" in
    completion)
        ((${#args[@]} == 0)) && _shad_offer "$cur" "bash"
        return
        ;;
    init)
        if [[ "$prev" == "--path" ]] ||
            { [[ "$prev" == "=" ]] && ((COMP_CWORD > 1)) && [[ "${COMP_WORDS[COMP_CWORD - 2]}" == "--path" ]]; }; then
            _shad_offer_dirs
            return
        fi
        _shad_offer "$cur" \
            "$(_shad_unused "--path --group --key --session --harness --wizard --install-deps" "${flags[@]}")"
        return
        ;;
    config)
        _shad_complete_config
        return
        ;;
    todo)
        if [[ "$prev" == "--label" ]] ||
            { [[ "$prev" == "=" ]] && ((COMP_CWORD > 1)) && [[ "${COMP_WORDS[COMP_CWORD - 2]}" == "--label" ]]; }; then
            _shad_offer "$cur" "$(_shad_todo_labels)"
            return
        fi
        _shad_complete_todo
        return
        ;;
    sessions)
        if ((${#args[@]} == 0)); then
            _shad_offer "$cur" "save restore stop show"
        elif [[ "${args[0]}" == "save" || "${args[0]}" == "stop" ]]; then
            _shad_offer "$cur" "$(_shad_unused "--all --pick" "${flags[@]}")"
        elif [[ "${args[0]}" == "restore" ]]; then
            _shad_offer "$cur" "$(_shad_unused "--no-attach" "${flags[@]}")"
        elif [[ "${args[0]}" == "show" ]]; then
            _shad_offer "$cur" "$(_shad_unused "--json" "${flags[@]}")"
        fi
        return
        ;;
    projects | git) ;;
    *)
        return
        ;;
    esac

    local -a _shad_top=() _shad_groups=() _shad_group_pairs=()
    _shad_load_projects

    local extra=""
    if [[ "$command" == "git" ]]; then
        if ((${#args[@]} == 0)); then
            _shad_offer "$cur" "sync panel"
            return
        fi
        case "${args[0]}" in
        sync) extra="--switch --yes --dry-run" ;;
        panel) extra="--no-fetch" ;;
        *) return ;;
        esac
        args=("${args[@]:1}")
    else
        # An action ends a `projects` line; only its --json may follow it.
        for word in "${args[@]}"; do
            case "$word" in
            status)
                _shad_offer "$cur" "$(_shad_unused "--json" "${flags[@]}")"
                return
                ;;
            esac
        done
        # Two names is the longest valid `projects` line; past that the
        # command itself errors, so offer nothing.
        ((${#args[@]} > 2)) && return
        # Opening a project takes --harness and the open options --resume
        # and --pick; with no name the line lists, which has --json instead.
        extra="--harness --resume --pick"
        ((${#args[@]} == 0)) && extra="--json --harness"
    fi

    local flag_words
    flag_words=$(_shad_unused "$extra" "${flags[@]}")

    case ${#args[@]} in
    0)
        _shad_offer "$cur" "${_shad_top[*]}" "${_shad_groups[*]}" "$flag_words"
        ;;
    1)
        local candidates
        candidates=$(_shad_subprojects "${args[0]}")
        if [[ "$command" == "projects" ]] && _shad_resolves_to_project "${args[0]}"; then
            candidates="$candidates status"
        fi
        _shad_offer "$cur" "$candidates" "$flag_words"
        ;;
    2)
        if [[ "$command" == "projects" ]]; then
            _shad_offer "$cur" "status" "$flag_words"
        else
            _shad_offer "$cur" "$flag_words"
        fi
        ;;
    *)
        _shad_offer "$cur" "$flag_words"
        ;;
    esac
}

complete -F _shad_complete shad
"""

BASH_COMPLETION = (
    _BASH_TEMPLATE.replace("__SHAD_HARNESSES__", " ".join(HARNESSES))
    .replace("__SHAD_OC_POSITIONS__", " ".join(OC_POSITIONS))
    .replace("__SHAD_TODO_STATUSES__", " ".join(STATUSES))
    .strip()
)


def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(
        sub,
        "completion",
        run=run,
        help="Print the bash completion script",
        description=(
            "Print the bash completion script to stdout. The script is the\n"
            "machine form as it is; there is no --json.\n\n"
            "To install:\n"
            "  echo 'source <(shad completion bash)' >> ~/.bashrc\n\n"
            "Source the script rather than pasting its text into a startup file.\n"
            "A pasted copy keeps completing the command surface that existed when\n"
            "it was written."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("shell", choices=["bash"], help="Shell to generate completions for")


def run(args: argparse.Namespace, *, out: Output) -> None:
    out.plain(BASH_COMPLETION)
