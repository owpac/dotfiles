{%- set prefix = vars.homebrew_prefix -%}
{%- set brew = prefix ~ "/bin/brew" -%}
{%- set bin = prefix ~ "/bin" -%}
{% if brew is file -%}
fpath+=("{{ prefix }}/share/zsh/site-functions")

eval "$({{ brew }} shellenv)"
{% elif bin is dir -%}
# mise installs the Homebrew packages in {{ prefix }}, also without Homebrew.
fpath+=("{{ prefix }}/share/zsh/site-functions")

export PATH="{{ prefix }}/bin:{{ prefix }}/sbin:${PATH}"
{% endif -%}

fpath=("${HOME}/.local/bin/completions" $fpath)
