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


BASH_COMPLETION = r"""
_shad_complete() {
    local cur prev words
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    words=("${COMP_WORDS[@]}")

    # shad <TAB>  →  top-level subcommands
    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=($(compgen -W "projects completion init" -- "$cur"))
        return
    fi

    if [[ "${words[1]}" == "completion" && ${COMP_CWORD} -eq 2 ]]; then
        COMPREPLY=($(compgen -W "bash zsh" -- "$cur"))
        return
    fi

    if [[ "${words[1]}" != "projects" ]]; then
        return
    fi

    # Collect project tokens from `shad projects` (each line is either a bare
    # project key or "  <group> <key>").  We parse them into two lists:
    #   _shad_top   – top-level keys and group names
    #   _shad_subs  – "group key" pairs (as single entries)
    local raw
    raw=$(shad projects 2>/dev/null)

    local top_keys=()
    local group_keys=()
    while IFS= read -r line; do
        # lines starting with two spaces are "  group key"
        if [[ "$line" =~ ^"  "([^ ]+)" "([^ ]+)$ ]]; then
            group_keys+=("${BASH_REMATCH[1]} ${BASH_REMATCH[2]}")
        elif [[ -n "$line" ]]; then
            top_keys+=("$line")
        fi
    done <<< "$raw"

    # shad projects <TAB>  →  top-level keys + group names
    if [[ ${COMP_CWORD} -eq 2 ]]; then
        COMPREPLY=($(compgen -W "${top_keys[*]}" -- "$cur"))
        return
    fi

    # shad projects <group> <TAB>  →  sub-keys for that group
    if [[ ${COMP_CWORD} -eq 3 ]]; then
        local group_tok="${words[2]}"
        local sub_candidates=()
        for entry in "${group_keys[@]}"; do
            local g="${entry%% *}"
            local k="${entry##* }"
            if [[ "$g" == "$group_tok"* ]]; then
                sub_candidates+=("$k")
            fi
        done
        COMPREPLY=($(compgen -W "${sub_candidates[*]}" -- "$cur"))
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
            _values 'command' projects completion init
            ;;
        args)
            case $words[2] in
                completion)
                    _values 'shell' bash zsh
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

                    if [[ ${#words} -eq 3 ]]; then
                        _values 'project' "${top_keys[@]}"
                    elif [[ ${#words} -eq 4 ]]; then
                        local grp="${words[3]}"
                        local subs=(${=group_map[$grp]})
                        _values 'project' "${subs[@]}"
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
        raise ValueError(f"unsupported shell: {shell!r}")
