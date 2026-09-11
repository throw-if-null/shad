"""
Shell completion script for shad.

Usage:
  shad completion bash   # print bash completion script

To install:
  shad completion bash >> ~/.bashrc
"""

from __future__ import annotations

from shad.shared.errors import ShadError

BASH_COMPLETION = r"""
_shad_complete() {
    local cur prev words
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    words=("${COMP_WORDS[@]}")

    # shad <TAB>  →  top-level subcommands
    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=($(compgen -W "projects git config completion init cheat" -- "$cur"))
        return
    fi

    if [[ "${words[1]}" == "completion" && ${COMP_CWORD} -eq 2 ]]; then
        COMPREPLY=($(compgen -W "bash" -- "$cur"))
        return
    fi

    if [[ "${words[1]}" == "config" ]]; then
        local config_actions="show path keys get set unset edit validate"
        if [[ ${COMP_CWORD} -eq 2 ]]; then
            COMPREPLY=($(compgen -W "$config_actions" -- "$cur"))
            return
        fi
        case "${words[2]}" in
            get|set|unset)
                if [[ ${COMP_CWORD} -eq 3 ]]; then
                    COMPREPLY=($(compgen -W "$(shad config keys 2>/dev/null)" -- "$cur"))
                fi
                ;;
            show)
                COMPREPLY=($(compgen -W "--raw" -- "$cur"))
                ;;
        esac
        return
    fi

    if [[ "${words[1]}" == "git" && ${COMP_CWORD} -eq 2 ]]; then
        COMPREPLY=($(compgen -W "sync" -- "$cur"))
        return
    fi

    if [[ "${words[1]}" != "projects" && "${words[1]}" != "git" ]]; then
        return
    fi

    # Collect project tokens from `shad config keys`, which prints plain dotted
    # paths. `shad projects` output is decorated with ●/◆ bullets for humans and
    # is not safe to parse.
    local raw
    raw=$(shad config keys 2>/dev/null)

    local top_keys=()
    local group_keys=()
    while IFS= read -r line; do
        if [[ "$line" =~ ^projects\.([^.]+)\.([^.]+)\.path$ ]]; then
            group_keys+=("${BASH_REMATCH[1]} ${BASH_REMATCH[2]}")
        elif [[ "$line" =~ ^projects\.([^.]+)\.path$ ]]; then
            top_keys+=("${BASH_REMATCH[1]}")
        fi
    done <<< "$raw"

    # Group names are completable in their own right.
    local group_names=()
    local entry
    for entry in "${group_keys[@]}"; do
        group_names+=("${entry%% *}")
    done
    if [[ ${#group_names[@]} -gt 0 ]]; then
        local unique
        unique=$(printf '%s\n' "${group_names[@]}" | sort -u)
        group_names=()
        while IFS= read -r entry; do
            [[ -n "$entry" ]] && group_names+=("$entry")
        done <<< "$unique"
    fi

    local actions="status stop"

    # `shad git sync` carries one extra token before the project names, so
    # every position below is shifted by `base` rather than duplicated.
    local base=1
    local extra=""
    if [[ "${words[1]}" == "git" ]]; then
        base=2
        extra="--yes --dry-run"
        actions=""
    fi

    # shad projects <TAB>  →  top-level keys + group names
    if [[ ${COMP_CWORD} -eq $((base + 1)) ]]; then
        COMPREPLY=($(compgen -W "${top_keys[*]} ${group_names[*]} $extra" -- "$cur"))
        return
    fi

    # shad projects <token> <TAB>
    # Could be: sub-key of a group, OR action on a top-level project
    if [[ ${COMP_CWORD} -eq $((base + 2)) ]]; then
        local tok="${words[base + 1]}"
        # Check if tok matches a group
        local sub_candidates=()
        for entry in "${group_keys[@]}"; do
            local g="${entry%% *}"
            local k="${entry##* }"
            if [[ "$g" == "$tok"* ]]; then
                sub_candidates+=("$k")
            fi
        done
        if [[ ${#sub_candidates[@]} -gt 0 ]]; then
            COMPREPLY=($(compgen -W "${sub_candidates[*]} $extra" -- "$cur"))
        else
            # tok is a top-level project — offer actions
            COMPREPLY=($(compgen -W "$actions $extra" -- "$cur"))
        fi
        return
    fi

    # shad projects <group> <project> <TAB>  →  actions
    if [[ ${COMP_CWORD} -eq $((base + 3)) ]]; then
        COMPREPLY=($(compgen -W "$actions $extra" -- "$cur"))
        return
    fi
}

complete -F _shad_complete shad
""".strip()


def print_completion(shell: str) -> None:
    if shell != "bash":
        raise ShadError(f"unsupported shell: {shell!r}")
    print(BASH_COMPLETION)
