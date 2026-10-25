# Thomas' dotfiles

Bootstrap your local env in a single command!

This dotfiles repository is currently aimed for MacOS.

It's also suitable for use in [**GitHub Codespaces**](https://docs.github.com/codespaces/customizing-your-codespace/personalizing-codespaces-for-your-account#dotfiles), [**Gitpod**](https://www.gitpod.io/docs/config-dotfiles), [**VS Code Remote - Containers**](https://code.visualstudio.com/docs/remote/containers#_personalizing-with-dotfile-repositories), or even Linux distributions, through the [**role `minimal`**](#roles-and-modules).

Managed with [`mise`](https://mise.jdx.dev): this repository lives in `~/.dotfiles`. mise links each file of `mise/` into `~/.config/mise`, so every mise command reads this config. `mise bootstrap` applies it.

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

### Roles and modules

Each machine selects its setup on 3 axes:

- **Roles**: the type of machine. A role is a config environment of mise: `mise/config.<role>.toml` holds its setup, and lists its modules (`vars.modules_<role>`).
- **Modules**: the blocks of setup that a machine turns on as a whole, for example `herdr` or `agents`. A module is a config environment too: `modules/<module>/mise.<module>.toml` holds all its setup, and mise reads it only when the machine selects the module.
- **Systems**: `macos` or `linux`. A module keeps its system variants: `os` on an entry, `os()` in a template.

| Role (`vars.roles`) | Modules | Content |
| ------------------- | ------- | ------- |
| `minimal` | `zsh`, `git` | The shell and git. For containers, Codespaces and other ephemeral environments. |
| `server` | `zsh`, `git`, `ssh`, `nas`, `pac`, `kompose` | The NAS: the shell, SSH and the CLI tools of owpac. |
| `workstation` | `zsh`, `git`, `macos`, `ssh`, `secrets`, `pac`, `aerospace`, `agents`, `herdr`, `raycast`, `iterm2` | A Mac: packages, macOS preferences, coding agents and the full shell. |
| `workstation work` | the modules of `workstation`, and `doctolib` | A Mac for work: the role `workstation`, plus the work tools and secrets. |

`vars.modules_base` in `mise/config.toml` lists the modules of each machine. mise saves the roles of the machine (`vars.roles`) in its state directory. The task `modules` writes the roles and their modules into `~/.config/mise/miserc.local.toml`. The roles and this file stay on the machine, outside this repository.

> [!NOTE]
> The install script selects the role `minimal` in a Dev Container or a Codespace, and the role `server` when `SSH_CLIENT` is set. Otherwise, it asks for the mode. Then it saves the roles, and runs the task `modules`.

### Layout

- `mise/`: the global config of mise. mise links each file of this folder into `~/.config/mise`.
  - `config.toml`: the setup of each machine.
  - `config.<role>.toml`: the setup of a role, and the list of its modules.
  - `miserc.toml`: the settings that mise reads before the config files. `auto_env = false` keeps the platform environments of mise off, so a module can have the name `macos`.
  - `tasks/`: the task `modules`, which writes the roles and the modules of this machine. `mise bootstrap` runs the setup scripts of the modules (`modules/<module>/tasks/`) at the end (task `bootstrap`).
- `modules/<module>/`: one folder for each module. mise links each file of a module into `~/.config/mise/conf.d/<module>/`, except `home/` and `data/`. `mise.<module>.toml` declares the dotfile group of the module, its templates, its packages and its tasks. `home/` holds the files of the group, at their path in the home directory: `modules/herdr/home/.config/herdr/config.toml` goes to `~/.config/herdr/config.toml`. mise links a plain file, and renders a template ([Tera](https://mise.jdx.dev/templates.html)). `tasks/` holds the setup scripts of the module, and `data/` the files that they read, such as the snapshots of the macOS preferences and the backups of the module `macos`, encrypted with age.
- `lib/`: the shell functions of the tasks. A task follows its link to find this folder.

### Daily use

- `mise bootstrap`: apply the setup. Add `--dry-run` to see the changes first.
- `mise run --skip-tools update`: pull this repository, write the roles and the modules of this machine (task `modules`), then run `mise bootstrap --update --prune-dotfiles`. `--prune-dotfiles` removes the files that a group does not deploy any more, after the dotfiles and before the tools. This task replaces `chezmoi update`. Before a task, mise installs all the tools of the config. If one install fails, the task stops before its first step, for example for a private tool without SSH agent. The task needs no tool, so `--skip-tools` removes this risk.
- Change the roles of this machine: `mise vars roles="workstation work"`, then run `mise run --skip-tools update`.
- `mise bootstrap status` and `mise dot status`: see what differs from the config.
- `mise dot diff`: see the content changes of the dotfiles.
- Edit a linked dotfile in place: the change goes into this repository. Edit a template in `modules/<module>/home/`, then run `mise dot apply`.
- `mise dot add --group <group> <file>`: move a file into `modules/<group>/home/`, and link it. A group needs no entry for a plain file. Do not use `mise dot add` for a secret: mise copies the content in clear text.
- A template needs an entry in its group, for example `"~/.zshrc" = { mode = "template" }` under `[dotfile_groups.zsh.entries]` in `modules/zsh/mise.zsh.toml`. `mise dot add` ignores `--mode template` in a group.
- A new module: create `modules/<module>/mise.<module>.toml` with its group: `[dotfile_groups.<module>]` and `root = "<module>/home"`. Move its files into `modules/<module>/home/`. Add the module to the list of a role (`vars.modules_<role>` in `mise/config.<role>.toml`), then run `mise run --skip-tools update`. The other machines get the module at their next `mise run --skip-tools update`.
- A package of a module: add it to the file of the module. Add `os = "macos"` or `os = "linux"` if the package exists on one system only. `mise bootstrap packages use --global` writes into `mise/config.toml`. For a cask (`brew-cask:`), add the entry by hand, then run `mise bootstrap`: a hook installs the cask with Homebrew, so `brew upgrade` sees it. `mise bootstrap packages use` installs the cask with mise, without the metadata of Homebrew.
- Turn off a module on one machine: `mise vars modules_off="<module> <module>"`, then run `mise run --skip-tools update`. mise does not read the file of the module any more, so its packages and its tasks also go away from the setup. For example, a machine without access to the private repositories of owpac turns off `pac` and `kompose`. Do not edit `miserc.local.toml`: the task `modules` writes it again.
- Remove a dotfile: remove its source, then run `mise dot apply --prune`. Remove a whole group from this machine: `mise dot unapply --group <group>`. To remove a module, also remove its folder and its name in the lists of the roles. If the module has a task, also remove this task from the task `bootstrap` (`mise/config.workstation.toml`).
- Add a file to `mise/` or to a module, for example `modules/<module>/mise.<module>.toml`: run `mise dot apply` to create its link. mise reads the file after this command.
- `mise use --global <tool>` and `mise bootstrap packages use --global <package>` write into this repository, through the link. Then commit the change.
- A secret: `fnox set <NAME> --global --provider age`. fnox asks for the value, encrypts it with age, and writes it into `modules/secrets/home/.config/fnox/config.toml`, through the link. The provider comes from the template `age.toml`: mise reads its public key in 1Password, so this repository does not hold it. For a secret of Doctolib, add `--profile doctolib`: the module `doctolib` activates this profile (`FNOX_PROFILE`).
- A command with the secrets: `fnox exec -- <command>`. No secret enters the interactive shell (`env = "exec"`).
- Role `work`: `mise run generate-hosts` writes the local domains of Doctolib into `/etc/hosts`. The private parts of the setup of Doctolib are secrets of fnox, in the profile `doctolib`: `~/.workrc`, `~/.npmrc` and the list of the domains. Edit them with `mise run edit-secret --profile doctolib <NAME>` (`WORKRC`, `NPMRC` or `DOCTOLIB_HOSTS`). Do not use `fnox edit`: with the provider in the imported file `age.toml`, fnox 1.42.1 writes the new value in clear into `config.toml`. The shell function `artifacts-login` (in `~/.workrc`) gets a new CodeArtifact token. `ES_API_KEY` is a secret of fnox (profile `doctolib`): run a command that needs it with `fnox exec`.

### Convenience script

The [getting started](#getting-started) step used the [convenience script](./install.sh) to install this dotfiles. There are some extra options that you can use to tweak the installation if you need.

It supports some environment variables:

- `DOTFILES_USER`: Defaults to `owpac`.
- `DOTFILES_HTTPS_URL`: Defaults to `https://github.com/${DOTFILES_USER}/dotfiles.git`.
- `DOTFILES_SSH_URL`: Defaults to `"git@github.com:${DOTFILES_USER}/dotfiles.git`.

The script always clones into `~/.dotfiles`: `mise/config.toml` expects this path. Before the first `mise bootstrap`, the links of `~/.config/mise` do not exist, and mise cannot read the modules. So the script first creates the links of `~/.config/mise` and `~/.config/mise/conf.d` from the config in `~/.dotfiles/mise` (`MISE_CONFIG_DIR`). Then `mise bootstrap` reads the whole config.

On a Mac, the first `mise bootstrap` installs 1Password. Then the script asks you to sign in to 1Password, and runs `mise bootstrap` again for the SSH keys and the encrypted files.

---

### Guides

- [Tracking macOS app preferences](./docs/macos-preferences.md) — snapshot & re-import app settings via `pac preferences`, without the noise of a tracked live plist.

---

### TODO

- add script to init & install packages for raspberry pi
