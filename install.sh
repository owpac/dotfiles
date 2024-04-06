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

install_hombrew() {
  if [ ! "$(command -v brew)" ]; then
    log_task "Installing 'brew'..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  else
    log_done "Homebrew already installed! 🍺"
  fi
}

install_chezmoi() {
  if [ ! "$(command -v chezmoi)" ]; then
    log_task "Installing 'chezmoi'..."

    bin_dir="${HOME}/.local/bin"
    chezmoi_dir="${bin_dir}/chezmoi"
    log_task "Installing chezmoi to '${chezmoi_dir}'"
    if [ "$(command -v curl)" ]; then
      chezmoi_install_script="$(curl -fsSL https://get.chezmoi.io)"
    elif [ "$(command -v wget)" ]; then
      chezmoi_install_script="$(wget -qO- https://get.chezmoi.io)"
    else
      error "To install chezmoi, you must have curl or wget."
    fi
    sh -c "${chezmoi_install_script}" -- -b "${bin_dir}"
  else
    log_done "Chezmoi already installed! 🏠"
  fi
}

install_based_on_os() {
  package_name="$1"

  if [ "$(uname)" = "Darwin" ]; then
    log_task "Using brew."

    if [ ! "$(command -v brew)" ]; then
      log_error "Homebrew is not installed."
      install_hombrew
    fi

    log_task "Installing '$package_name'..."
    brew install "$package_name"

  elif [ "$(uname)" = "Linux" ]; then
    log_task "Using apt."

    if [ ! "$(command -v apt)" ]; then
      error "Apt is not available."
    fi

    if [ ! "$(command -v chezmoi)" ]; then
      log_error "'chezmoi' is not installed."
      install_chezmoi

      if [ "$package_name" == "chezmoi" ]; then
        return # exit from the function because we just installed chezmoi
      fi
    fi

    log_task "Installing '$package_name'..."
    sudo apt update
    sudo apt install -y "$package_name"

  else
    error "Unsupported operating system."
  fi
}

install() {
  package_name="$1"

  if [ ! "$(command -v $package_name)" ]; then
    log_error "'$package_name' not installed."
    install_based_on_os "$package_name"
  else
    log_done "'$package_name' already installed! 📦"
  fi
}

# install dependencies
install "chezmoi"
install "git"

# set default values
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
