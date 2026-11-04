{% if "/opt/homebrew/bin/brew" is file -%}
fpath+=("{{ exec(command="/opt/homebrew/bin/brew --prefix") }}/share/zsh/site-functions")

eval "$(/opt/homebrew/bin/brew shellenv)"
{% elif "/opt/homebrew/bin" is dir -%}
# mise installs the Homebrew packages in /opt/homebrew, also without Homebrew.
fpath+=("/opt/homebrew/share/zsh/site-functions")

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"
{% endif -%}

fpath=("${HOME}/.local/bin/completions" $fpath)

