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
        COMPREPLY=($(compgen -W "projects config completion init cheat" -- "$cur"))
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

    if [[ "${words[1]}" != "projects" ]]; then
        return
    fi

    # Collect project tokens from `shad projects`.
    local raw
    raw=$(shad projects 2>/dev/null)

    local top_keys=()
    local group_keys=()
    while IFS= read -r line; do
        if [[ "$line" =~ ^"  "([^ ]+)" "([^ ]+)$ ]]; then
            group_keys+=("${BASH_REMATCH[1]} ${BASH_REMATCH[2]}")
        elif [[ -n "$line" ]]; then
            top_keys+=("$line")
        fi
    done <<< "$raw"

    local actions="status stop"

    # shad projects <TAB>  →  top-level keys + group names
    if [[ ${COMP_CWORD} -eq 2 ]]; then
        COMPREPLY=($(compgen -W "${top_keys[*]}" -- "$cur"))
        return
    fi

    # shad projects <token> <TAB>
    # Could be: sub-key of a group, OR action on a top-level project
    if [[ ${COMP_CWORD} -eq 3 ]]; then
        local tok="${words[2]}"
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
            COMPREPLY=($(compgen -W "${sub_candidates[*]}" -- "$cur"))
        else
            # tok is a top-level project — offer actions
            COMPREPLY=($(compgen -W "$actions" -- "$cur"))
        fi
        return
    fi

    # shad projects <group> <project> <TAB>  →  actions
    if [[ ${COMP_CWORD} -eq 4 ]]; then
        COMPREPLY=($(compgen -W "$actions" -- "$cur"))
        return
    fi
}

complete -F _shad_complete shad
""".strip()


def print_completion(shell: str) -> None:
    if shell != "bash":
        raise ShadError(f"unsupported shell: {shell!r}")
    print(BASH_COMPLETION)
