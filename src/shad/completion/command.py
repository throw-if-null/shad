"""
Shell completion scripts for shad.

Usage:
  shad completion bash   # print bash completion script
  shad completion zsh    # print zsh completion script

To install:
  # bash
  shad completion bash >> ~/.bashrc

  # zsh
  shad completion zsh >> ~/.zshrc
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
        COMPREPLY=($(compgen -W "bash zsh" -- "$cur"))
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


ZSH_COMPLETION = r"""
_shad() {
    local state

    _arguments \
        '1: :->cmd' \
        '*: :->args'

    case $state in
        cmd)
            _values 'command' projects config completion init cheat
            ;;
        args)
            case $words[2] in
                completion)
                    _values 'shell' bash zsh
                    ;;
                config)
                    local config_actions=(show path keys get set unset edit validate)
                    if [[ ${#words} -eq 3 ]]; then
                        _values 'action' "${config_actions[@]}"
                    elif [[ ${#words} -eq 4 ]]; then
                        case $words[3] in
                            get|set|unset)
                                local cfg_keys=(${(f)"$(shad config keys 2>/dev/null)"})
                                _values 'key' "${cfg_keys[@]}"
                                ;;
                            show)
                                _values 'flag' --raw
                                ;;
                        esac
                    fi
                    ;;
                projects)
                    local raw
                    raw=$(shad projects 2>/dev/null)

                    local top_keys=()
                    local -A group_map

                    while IFS= read -r line; do
                        if [[ "$line" =~ ^"  "([^ ]+)" "([^ ]+)$ ]]; then
                            local g="${match[1]}" k="${match[2]}"
                            group_map[$g]+=" $k"
                        elif [[ -n "$line" ]]; then
                            top_keys+=("$line")
                        fi
                    done <<< "$raw"

                    local actions=(status stop)

                    if [[ ${#words} -eq 3 ]]; then
                        _values 'project' "${top_keys[@]}"
                    elif [[ ${#words} -eq 4 ]]; then
                        local tok="${words[3]}"
                        local subs=(${=group_map[$tok]})
                        if [[ ${#subs} -gt 0 ]]; then
                            _values 'project' "${subs[@]}"
                        else
                            _values 'action' "${actions[@]}"
                        fi
                    elif [[ ${#words} -eq 5 ]]; then
                        _values 'action' "${actions[@]}"
                    fi
                    ;;
            esac
            ;;
    esac
}

compdef _shad shad
""".strip()


def print_completion(shell: str) -> None:
    if shell == "bash":
        print(BASH_COMPLETION)
    elif shell == "zsh":
        print(ZSH_COMPLETION)
    else:
        raise ShadError(f"unsupported shell: {shell!r}")
