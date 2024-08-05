# Thomas' dotfiles

Bootstrap your local env in a single command!

This dotfiles repository is currently aimed for MacOS.

It's also suitable for use in [**GitHub Codespaces**](https://docs.github.com/codespaces/customizing-your-codespace/personalizing-codespaces-for-your-account#dotfiles), [**Gitpod**](https://www.gitpod.io/docs/config-dotfiles), [**VS Code Remote - Containers**](https://code.visualstudio.com/docs/remote/containers#_personalizing-with-dotfile-repositories), or even Linux distributions, through the [**minimum mode**](#minimum-mode).

Managed with [`chezmoi`](https://chezmoi.io), a dotfiles manager.

## Getting started

You can use the [install script](./install.sh) to install the dotfiles on any machine with a single command. Simply run the following command in your terminal:

```bash
sh -c "$(curl -fsSL https://get.owpac.com/dotfiles)"
```

<details><summary> Using the full URL</summary>

```bash
sh -c "$(curl -fsSL https://raw.githubusercontent.com/owpac/dotfiles/main/install.sh)"
```

</details>

<details><summary> Using wget</summary>

```bash
sh -c "$(wget -qO- https://raw.githubusercontent.com/owpac/dotfiles/main/install.sh)"
```

</details>

---

## Documentation

**If you followed the steps above so far, you already finished installing the dotfiles. Have fun!**

The below information is more for reference purposes.

_**TL;DR**:_

There are 3 possible modes, listed be order of priority:

1.  [**Minimum mode**](#minimum-mode): it contains command prompt configuration.
2.  [**Personal mode**](#personal-mode): it is the base configuration for any other Profiles.
3.  [**Work mode**](#work-mode): it is a derived Profile from the base, adding work email & other work related configurations.

> [!TIP]
> There is an automatic **Headless mode**: if `SSH_CLIENT` env var is detected during init, the headless mode installs .ssh/authorized_keys files.

### Minimum mode

The first step of installation will ask if you want a **Minimum** mode installation. The minimum mode only installs the needed dotfiles for the command prompt and is compatible with more distributions. It's also suit for ephemeral environment.

It will be enabled by default when running in a Dev Container.

### Personal mode

The installation will ask if the machine is a **Personal** profile type. The personal profile is the base of every dotfiles configuration. All other profiles inherits from it.

### Work mode

The installation will ask if the machine is a **Work** profile type. The work profile is derived from the base and add some work related configurations.

### Convenience script

The [getting started](#getting-started) step used the [convenience script](./install.sh) to install this dotfiles. There are some extra options that you can use to tweak the installation if you need.

It supports some environment variables:

- `DOTFILES_USER`: Defaults to `owpac`.
- `DOTFILES_HTTPS_URL`: Defaults to `https://github.com/${DOTFILES_USER}/dotfiles.git`.
- `DOTFILES_SSH_URL`: Defaults to `"git@github.com:${DOTFILES_USER}/dotfiles.git`.
- `DOTFILES_DIR`: Defaults to `${HOME}/.dotfiles`.

For example, you can use it to clone and install the dotfiles repository in an other directory:

```console
DOTFILES_DIR=.chezmoi sh -c "$(curl -fsSL https://get.owpac.com/dotfiles)"
```

### Installing without the convenience script

If you prefer not to use the convenience script to install the dotfiles, you can also do it manually:

```bash
git clone https://github.com/owpac/dotfiles "$HOME/.dotfiles"

"$HOME/.dotfiles/install.sh"
```

---

### TODO

- add script to init & install packages for raspberry pi
