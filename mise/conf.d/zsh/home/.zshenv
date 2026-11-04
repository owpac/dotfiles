{%- set envs = mise_env | default(value=[]) -%}
export PATH="${HOME}/.local/bin:${PATH}"
{% if "server" in envs or "workstation" in envs -%}
# uv uses the Python of mise, and never downloads its own Python.
export UV_PYTHON_PREFERENCE=only-system
{% endif -%}
{#- Work mode, with gh: export HOMEBREW_GITHUB_API_TOKEN="$(/opt/homebrew/bin/gh auth token 2>/dev/null)" (disabled) -#}
{% if "agents" in envs -%}
# Beads: every task lives in the home workspace (see ~/.config/ia/AGENTS.md).
# bd uses BEADS_DIR before any workspace of the current repository.
export BEADS_DIR="${HOME}/{{ vars.beads_dir }}"
{% endif -%}
