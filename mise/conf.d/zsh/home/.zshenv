{%- set envs = mise_env | default(value=[]) -%}
{%- set code = vars.homebrew_prefix ~ "/bin/code" -%}
# zsh reads this file in each shell: login, interactive, script, `ssh server command`. It holds
# the environment variables, without a command and without output. The setup of the session
# (Homebrew) is in .zprofile, and the interactive setup is in .zshrc.
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

# The editor. Most tools read VISUAL first, then EDITOR: VISUAL is the full-screen editor, and
# EDITOR the editor for a terminal without a full screen. Both get the same editor: VS Code if
# Homebrew installed it, else vim. If the parent process gives VISUAL or EDITOR, for example
# EDITOR=true from an agent, these values stay.
if [ -z "${VISUAL:-}${EDITOR:-}" ]; then
  export VISUAL='{% if code is file %}{{ code }} --wait{% else %}vim{% endif %}'
  export EDITOR="${VISUAL}"
fi
