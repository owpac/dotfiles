{%- set envs = mise_env | default(value=[]) -%}
# Enable Powerlevel10k instant prompt. Should stay close to the top of ~/.zshrc.
# Initialization code that may require console input (password prompts, [y/n]
# confirmations, etc.) must go above this block; everything else may go below.
if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi

### OMZ

export ZSH=$HOME/.oh-my-zsh
export HOMEBREW_NO_ANALYTICS=1

ZSH_THEME="powerlevel10k/powerlevel10k"
DISABLE_MAGIC_FUNCTIONS=true      # Disable slow URL paste escaping (bracketed-paste issues)
ZSH_AUTOSUGGEST_BUFFER_MAX_SIZE=20 # Skip autosuggestion lookup for long buffers (perf)

plugins=(
  mise
  git
  {%- if os() == "macos" %}
  zoxide
  {%- endif %}
  autoupdate
  colored-man-pages
  zsh-syntax-highlighting
  zsh-autosuggestions
)

source $ZSH/oh-my-zsh.sh

{%- if os() == "macos" and "workstation" in envs %}

### Claude

# Subscription token of the VS Code Agents window (native mode, no Copilot). VS Code sets
# VSCODE_RESOLVING_ENVIRONMENT while it reads the shell environment at launch from the Dock:
# the token stays out of the other shells, so the claude CLI keeps its Keychain login.
# The token comes from the task claude-token (mise run claude-token).
if [[ -n "$VSCODE_RESOLVING_ENVIRONMENT" ]]; then
  CLAUDE_CODE_OAUTH_TOKEN=$(security find-generic-password -a "$USER" -s claude-code-oauth-token -w 2>/dev/null) \
    && export CLAUDE_CODE_OAUTH_TOKEN
fi

### herdr

# In iTerm2, use the "herdr" profile while the herdr client runs. In this profile, cmd + key
# sends the herdr prefix + the same key (see ~/.config/herdr/scripts/make-iterm-profile).
# The CLI commands (herdr tab list, herdr pane split...) keep the current profile.
if [[ "$TERM_PROGRAM" == iTerm.app ]] && (( $+commands[herdr] )); then
  herdr() {
    if [[ $# -eq 0 || "$1" == --session || "$1" == --remote || "$1 $2" == "session attach" ]]; then
      printf '\e]1337;SetProfile=herdr\a'
      command herdr "$@"
      local ret=$?
      printf '\e]1337;SetProfile=%s\a' "${ITERM_PROFILE:-Default}"
      return $ret
    fi
    command herdr "$@"
  }
fi

### worktrunk

# The function wt replaces the command wt: `wt switch` can then change the directory of this
# shell. It also loads the completions, so it comes after Oh My Zsh (compinit).
if (( $+commands[wt] )); then
  eval "$(command wt config shell init zsh)"
fi
{%- endif %}

### Aliases

alias terractx='terraform workspace select $1'
alias ghpr='gh pr create -df -t $(git_current_branch) && gh pr view -w && bin/dev ci:build'
alias gbrm="git for-each-ref --format='%(refname:short)' refs/heads | grep -v \"master\|main\" | xargs git branch -D"
# Claude Code: start each session with Opus 1M, in auto mode. The managed settings of the work Mac
# block the "model" and "permissions.defaultMode" settings, so the options are added here.
# Claude Code 2.1.316 accepts these options before a subcommand (agents, stop, mcp...).
alias claude='claude --model "opus[1m]" --permission-mode auto'

{% if "work" in envs -%}
### Work

[[ ! -f ~/.workrc ]] || source ~/.workrc
{%- endif %}

# To customize prompt, run `p10k configure` or edit ~/.p10k.zsh.
[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh
