#!/bin/sh

# Installs mise, clones this repository into ~/.dotfiles, links ~/.config/mise to mise/ of this
# repository, selects the roles of this machine, then runs mise bootstrap.

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
# mise/config.toml expects DOTFILES_DIR (dotfiles.root). mise reads its config in MISE_DIR.
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
# ~/.config/mise is one link to mise/ of this repository, as `mise bootstrap --config-dir mise`
# makes it. mise then reads the whole config from this repository, and `mise bootstrap --update`
# pulls this repository. Another config directory goes to a backup.
if [ "$(readlink "${MISE_DIR}" 2>/dev/null || true)" != "${DOTFILES_DIR}/mise" ]; then
  if [ -e "${MISE_DIR}" ] || [ -L "${MISE_DIR}" ]; then
    backup="${MISE_DIR}.$(date +%Y%m%d%H%M%S)"
    log_task "Moving the current mise config to '${backup}'..."
    mv "${MISE_DIR}" "${backup}"
  fi
  mkdir -p "$(dirname "${MISE_DIR}")"
  ln -s "${DOTFILES_DIR}/mise" "${MISE_DIR}"
  log_done "Linked ${MISE_DIR} to ${DOTFILES_DIR}/mise"
fi

# --- Roles of this machine --------------------------------------------------------------
# The roles select the setup of this machine: minimal, server, workstation and work. Each role is
# a set of environments in mise/miserc.toml (env_sets). DOTFILES_ROLES gives them without a
# question, for example DOTFILES_ROLES="workstation work". The first mise bootstrap saves them
# into ~/.config/mise/miserc.local.toml (--save-env), in mise/ of this repository: git ignores
# this file. A machine with saved roles gets no question.
miserc="${MISE_DIR}/miserc.local.toml"
roles=""
if ! grep -q '^env' "${miserc}" 2>/dev/null; then
  if [ -n "${DOTFILES_ROLES:-}" ]; then
    roles=$(printf '%s' "${DOTFILES_ROLES}" | tr ' ' ',')
  elif [ -n "${REMOTE_CONTAINERS:-}${CODESPACES:-}${VSCODE_REMOTE_CONTAINERS_SESSION:-}${GITPOD_HOST:-}" ]; then
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
          work) roles="workstation,work" ;;
          *) roles="workstation" ;;
        esac
        ;;
    esac
  else
    roles="workstation"
  fi
  log_done "Roles of this machine: ${roles}"
fi

# --- Bootstrap --------------------------------------------------------------------------
# The first run installs the packages, 1Password among them. The keys from 1Password and the
# files encrypted with age need a second run, after the sign-in to 1Password. On a workstation,
# the templates that read 1Password stop the first run before its dotfiles. The second run writes
# them.
# -E selects the roles of a new machine, and --save-env saves them, also when the run fails. The
# next runs read them in miserc.local.toml.
set --
if [ -n "${roles}" ]; then
  set -- -E "${roles}" --save-env
fi
log_task "Running 'mise bootstrap'..."
if ! mise bootstrap --prompt-vars --yes "$@"; then
  grep -q workstation "${miserc}" || error "mise bootstrap failed."
  log_task "The first run stopped before the keys from 1Password. The second run writes them."
fi

if grep -q workstation "${miserc}"; then
  log_task "Open 1Password, sign in, and turn on 'Integrate with 1Password CLI' (Settings > Developer)."
  printf "🙋 Press Enter when 1Password is ready. "
  read -r _
  # The files of fnox need no step here: their group waits for the age key and the config of fnox
  # (depends in the module doctolib).
  log_task "Running 'mise bootstrap' again for the keys and the secrets..."
  mise bootstrap --yes
fi

# update the remote URL to SSH
git -C "${DOTFILES_DIR}" remote set-url origin "${DOTFILES_SSH_URL}"

log_done "Configuration successfully applied! 🎉"
