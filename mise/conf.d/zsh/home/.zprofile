{%- set prefix = vars.homebrew_prefix -%}
{%- set brew = prefix ~ "/bin/brew" -%}
{%- set bin = prefix ~ "/bin" -%}
# zsh reads this file in a login shell, after /etc/zprofile (path_helper of macOS). It sets up
# the session: Homebrew, and the folders of the completions. The environment variables are in
# .zshenv. Homebrew asks for `brew shellenv` here: path_helper changes the order of PATH before
# this file.
{% if brew is file -%}
fpath+=("{{ prefix }}/share/zsh/site-functions")

eval "$({{ brew }} shellenv)"
{% elif bin is dir -%}
# mise installs the Homebrew packages in {{ prefix }}, also without Homebrew.
fpath+=("{{ prefix }}/share/zsh/site-functions")

export PATH="{{ prefix }}/bin:{{ prefix }}/sbin:${PATH}"
{% endif -%}

fpath=("${HOME}/.local/bin/completions" $fpath)
