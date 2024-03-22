#!/bin/sh

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

# install Homebrew
if [ ! "$(command -v brew)" ]; then
  log_task "Installing 'brew'..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
else
  log_done "Homebrew already installed! 🍺"
fi

# install git
if [ ! "$(command -v git)" ]; then
  log_task "Installing 'git'..."
  brew install git
else
  log_done "Git already installed! 🐙"
fi

# install 1password
if [ ! "$(command -v op)" ]; then
  log_task "Installing '1password'..."
  brew install 1password 1password-cli
else
  log_done "1password already installed! 🔐"
fi

# install chezmoi
if [ ! "$(command -v chezmoi)" ]; then
  log_task "Installing 'chezmoi'..."
  brew install chezmoi
else
  log_done "Chezmoi already installed! 🏠"
fi

DOTFILES_USER=${DOTFILES_USER:-"owpac"}
DOTFILES_HTTPS_URL=${DOTFILES_HTTPS_URL:-"https://github.com/${DOTFILES_USER}/dotfiles.git"}
DOTFILES_SSH_URL=${DOTFILES_SSH_URL:-"git@github.com:${DOTFILES_USER}/dotfiles.git"}
DOTFILES_DIR=${DOTFILES_DIR:-"${HOME}/.dotfiles"}

# use HTTPS clone URL to avoid SSH key setup without 1Password
git clone $DOTFILES_HTTPS_URL $DOTFILES_DIR
cd $DOTFILES_DIR
# update the remote URL to SSH
git remote set-url origin $DOTFILES_SSH_URL

log_task "Running 'chezmoi init --source $DOTFILES_DIR'"
chezmoi init --source $DOTFILES_DIR

log_task "Running 'chezmoi apply --force'"
chezmoi apply --force

log_done "Configuration successfully applied! 🎉"
