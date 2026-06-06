"""CLI wiring for `kompose run` — actions runner.

This module owns:
- the argparse subparser registration (`register_top_level`)
- the `--` separator interception (`split_forwarded_args`)
- the zsh completion preamble (`ZSH_PREAMBLE`) with helpers that scan
  `<host>/.kompose/commands.yaml` and commands/*.yaml.

The execution logic lives in `kompose.commands`.
"""

from __future__ import annotations

import argparse

from kompose.commands import cmd_run

from . import _shared


# Completion hints referenced by `arg.complete`. The string values point at
# zsh functions defined in ZSH_PREAMBLE below — shtab inlines that preamble
# into the generated script.
_COMPLETE_RUN_FIRST = {"zsh": "_kompose_run_first"}
_COMPLETE_RUN_SECOND = {"zsh": "_kompose_run_second"}


def _add_run_args(parser: argparse.ArgumentParser) -> None:
    """Args for `kompose run`. The `--` arg-forwarding is intercepted by
    `split_forwarded_args` before argparse runs, so we don't declare a
    positional for forwarded args here.
    """
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Echo the docker exec command before running",
    )
    first = parser.add_argument(
        "first", nargs="?", metavar="<service|action>",
        help="Action name (auto-resolved), or service name when followed by an action",
    )
    first.complete = _COMPLETE_RUN_FIRST
    second = parser.add_argument(
        "second", nargs="?", metavar="<action>",
        help="Action name when the first arg is a service",
    )
    second.complete = _COMPLETE_RUN_SECOND


def register_top_level(subparsers) -> None:
    p = _shared.add_subparser(
        subparsers, "run",
        "Run a per-service action declared in .kompose/commands.yaml",
    )
    _add_run_args(p)
    p.set_defaults(func=cmd_run)


def split_forwarded_args(argv: list[str]) -> tuple[list[str], list[str]]:
    """Split argv on `--` when the `run` subcommand is being invoked.

    Everything after the first `--` (post-`run`) is `forwarded`; what remains
    is the normal argparse input. Outside of `run`, argv is returned untouched
    so other subcommands keep argparse's default `--` semantics.
    """
    if "run" not in argv or "--" not in argv:
        return argv, []
    run_idx = argv.index("run")
    try:
        sep_idx = argv.index("--", run_idx)
    except ValueError:
        return argv, []
    return argv[:sep_idx], argv[sep_idx + 1:]


# Walks <host>/.kompose/commands.yaml and commands/*.yaml with awk to feed
# zsh completion. Trade-off: no Python startup on Tab (snappy), but relies on
# the schema's standard 2-space indentation (services > <svc> > actions >
# <name>). Other indentations still execute fine (Python uses a real YAML
# parser), only completion misses.
ZSH_PREAMBLE = r"""
# --- kompose run helpers ---

_kompose_run_pairs() {
  local ws="$(_kompose_workspace)"
  local host="$(_kompose_host_dir)"
  local -a files
  [[ -f $ws/$host/.kompose/commands.yaml ]] && files+=($ws/$host/.kompose/commands.yaml)
  files+=($ws/$host/.kompose/commands/*.yaml(N))
  [[ ${#files[@]} -eq 0 ]] && return
  awk '
    FNR==1 { svc=""; in_svc=0; in_actions=0; per_file_svc=FILENAME; sub(/.*\//, "", per_file_svc); sub(/\.yaml$/, "", per_file_svc) }
    /^services:[[:space:]]*$/ { in_services=1; next }
    in_services && /^[^[:space:]]/ { in_services=0 }
    in_services && /^  [a-zA-Z0-9_-]+:[[:space:]]*$/ {
      svc=$0; sub(/^  /, "", svc); sub(/:.*/, "", svc); in_actions=0; next
    }
    in_services && svc != "" && /^    actions:[[:space:]]*$/ { in_actions=1; next }
    in_services && /^  [a-zA-Z0-9_-]+:/ && !/^    / { in_actions=0 }
    in_actions && /^      [a-zA-Z0-9_-]+/ {
      a=$0; sub(/^      /, "", a); sub(/:.*/, "", a)
      print svc "\t" a
    }
    /^actions:[[:space:]]*$/ { in_actions_top=1; next }
    in_actions_top && /^[^[:space:]]/ { in_actions_top=0 }
    in_actions_top && /^  [a-zA-Z0-9_-]+/ {
      a=$0; sub(/^  /, "", a); sub(/:.*/, "", a)
      print per_file_svc "\t" a
    }
  ' "${files[@]}"
}

# First positional of `kompose run`: a service OR a unique action.
_kompose_run_first() {
  local -a pairs services actions
  pairs=("${(@f)$(_kompose_run_pairs)}")
  for p in $pairs; do
    services+=("${p%%	*}")
    actions+=("${p##*	}")
  done
  typeset -aU services
  _describe 'action' actions
  _describe 'service' services
}

# Second positional of `kompose run <svc>`: actions of that service.
_kompose_run_second() {
  local svc="${words[CURRENT-1]}"
  local -a pairs filtered
  pairs=("${(@f)$(_kompose_run_pairs)}")
  for p in $pairs; do
    [[ "${p%%	*}" == "$svc" ]] && filtered+=("${p##*	}")
  done
  _describe 'action' filtered
}
"""
