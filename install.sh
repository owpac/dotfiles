#!/bin/sh

# Installs mise, clones this repository into ~/.dotfiles, selects the mode of this machine, then
# runs mise bootstrap. mise links the files of mise/ into ~/.config/mise.

# -e: exit on error
# -u: exit on unset variables
set -eu

log_color() {
  color_code="$1"
  shift

  printf "\033[${color_code}m%s\033[0m\n" "$*" >&2
}

log_red() {
  log_color "0;31" "$@"
}

log_green() {
  log_color "0;32" "$@"
}

log_blue() {
  log_color "0;34" "$@"
}

log_task() {
  log_blue "👉" "$@"
}

log_done() {
  log_green "✅" "$@"
}

log_error() {
  log_red "❌" "$@"
}

error() {
  log_error "$@"
  exit 1
}

# set default values
DOTFILES_USER=${DOTFILES_USER:-"owpac"}
DOTFILES_HTTPS_URL=${DOTFILES_HTTPS_URL:-"https://github.com/${DOTFILES_USER}/dotfiles.git"}
DOTFILES_SSH_URL=${DOTFILES_SSH_URL:-"git@github.com:${DOTFILES_USER}/dotfiles.git"}
# mise/config.toml expects these paths (dotfiles.root and the entry "~/.config/mise").
DOTFILES_DIR="${HOME}/.dotfiles"
MISE_DIR="${HOME}/.config/mise"

# --- mise and git -----------------------------------------------------------------------
# On macOS, Homebrew installs mise and git. Homebrew stays on the machine, and mise sees the
# packages that Homebrew installed. On Linux, the script of mise installs mise in ~/.local/bin.
if [ "$(uname)" = "Darwin" ]; then
  if [ ! -x /opt/homebrew/bin/brew ]; then
    log_task "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  fi
  eval "$(/opt/homebrew/bin/brew shellenv)"
  for package in git mise; do
    command -v "$package" >/dev/null 2>&1 || brew install "$package"
  done
elif [ "$(uname)" = "Linux" ]; then
  command -v git >/dev/null 2>&1 || error "Install git first."
  if ! command -v mise >/dev/null 2>&1; then
    log_task "Installing mise in ~/.local/bin..."
    curl -fsSL https://mise.run | sh
    export PATH="${HOME}/.local/bin:${PATH}"
  fi
else
  error "Unsupported operating system."
fi
log_done "mise $(mise --version) ready"

# --- Repository -------------------------------------------------------------------------
# Use the HTTPS URL for the clone: the SSH key comes from 1Password, which is not set up yet.
if [ -d "${DOTFILES_DIR}/.git" ]; then
  log_task "'${DOTFILES_DIR}' already exists. Pulling latest changes..."
  git -C "${DOTFILES_DIR}" pull --ff-only
else
  if [ -e "${DOTFILES_DIR}" ]; then
    backup="${DOTFILES_DIR}.$(date +%Y%m%d%H%M%S)"
    log_task "Moving the current '${DOTFILES_DIR}' to '${backup}'..."
    mv "${DOTFILES_DIR}" "${backup}"
  fi
  git clone "${DOTFILES_HTTPS_URL}" "${DOTFILES_DIR}"
fi

# --- Config directory of mise -----------------------------------------------------------
# mise links each file of mise/ into ~/.config/mise. A config that mise did not link goes to a
# backup.
if [ -e "${MISE_DIR}/config.toml" ] && [ ! -L "${MISE_DIR}/config.toml" ]; then
  backup="${MISE_DIR}.$(date +%Y%m%d%H%M%S)"
  log_task "Moving the current mise config to '${backup}'..."
  mv "${MISE_DIR}" "${backup}"
fi
mkdir -p "${MISE_DIR}"

# --- Roles of this machine --------------------------------------------------------------
# The roles select the setup of this machine (see mise/config.toml): minimal, server,
# workstation and work. mise saves the roles in its state directory (vars.roles). The
# task modules writes the roles and their modules into ~/.config/mise/miserc.local.toml. Both
# stay on this machine, outside this repository.
miserc="${MISE_DIR}/miserc.local.toml"
if [ ! -f "${miserc}" ]; then
  if [ -n "${REMOTE_CONTAINERS:-}${CODESPACES:-}${VSCODE_REMOTE_CONTAINERS_SESSION:-}${GITPOD_HOST:-}" ]; then
    roles="minimal"
  elif [ -n "${SSH_CLIENT:-}" ]; then
    roles="server"
  elif [ -t 0 ]; then
    printf "🙋 Should install in minimal mode? [y/N] "
    read -r answer
    case "${answer}" in
      [yY]*) roles="minimal" ;;
      *)
        printf "🙋 What profile do you want? [personal/work] "
        read -r profile
        case "${profile}" in
          work) roles="workstation work" ;;
          *) roles="workstation" ;;
        esac
        ;;
    esac
  else
    roles="workstation"
  fi
  MISE_CONFIG_DIR="${DOTFILES_DIR}/mise" mise vars roles="${roles}"
  MISE_CONFIG_DIR="${DOTFILES_DIR}/mise" mise run --skip-tools modules
  log_done "Roles of this machine: ${roles}"
fi

# --- Links of the config of mise --------------------------------------------------------
# mise reads the modules through their links in ~/.config/mise/conf.d, and these links do not
# exist yet. Create the links of ~/.config/mise and ~/.config/mise/conf.d first, from the config
# in this repository. mise bootstrap then reads the whole config: the roles and their modules.
log_task "Linking the config of mise..."
MISE_CONFIG_DIR="${DOTFILES_DIR}/mise" mise dot apply --yes "${MISE_DIR}" "${MISE_DIR}/conf.d"

# --- Bootstrap --------------------------------------------------------------------------
# The first run installs the packages, 1Password among them. The keys from 1Password and the
# files encrypted with age need a second run, after the sign-in to 1Password. On a workstation,
# the templates that read 1Password stop the dotfiles of the first run: mise then writes no
# dotfile. The second run writes them.
log_task "Running 'mise bootstrap'..."
if ! mise bootstrap --prompt-vars --yes; then
  grep -q workstation "${miserc}" || error "mise bootstrap failed."
  log_task "The first run stopped before the keys from 1Password. The second run writes them."
fi

if grep -q workstation "${miserc}"; then
  log_task "Open 1Password, sign in, and turn on 'Integrate with 1Password CLI' (Settings > Developer)."
  printf "🙋 Press Enter when 1Password is ready. "
  read -r _
  log_task "Running 'mise bootstrap' again for the keys and the secrets..."
  mise bootstrap --yes
  # mise renders the templates of a run before it writes the files of this run. The templates that
  # read fnox (~/.workrc, ~/.npmrc) need the age key and age.toml, which the run above wrote.
  log_task "Writing the files that read fnox..."
  mise dot apply --yes
fi

# update the remote URL to SSH
git -C "${DOTFILES_DIR}" remote set-url origin "${DOTFILES_SSH_URL}"

log_done "Configuration successfully applied! 🎉"
