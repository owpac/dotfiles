#!/bin/sh

# -e: exit on error
# -u: exit on unset variables
set -eu

source lib/logs.sh

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

# POSIX way to get script's dir: https://stackoverflow.com/a/29834779/12156188
script_dir="$(cd -P -- "$(dirname -- "$(command -v -- "$0")")" && pwd -P)"

log_task "Running 'chezmoi init --source=$script_dir'"
chezmoi init --source=$script_dir

log_task "Running 'chezmoi apply --force'"
chezmoi apply --force

log_done "Configuration successfully applied! 🎉"
