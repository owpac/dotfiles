# Brew distribution (planned)

This directory contains a draft Homebrew formula for `kompose`. It is not yet
published — the file is here as a starting point for when distribution via
`brew install` is wanted.

## Steps to publish

1. **Tag a release** of the dotfiles repo (e.g. `kompose-v1.1.0`) — or move the
   `packages/kompose/` subtree to its own repo if a clean release surface is
   preferred.

2. **Create the tap repo**: `owpac/homebrew-kompose` on GitHub (the
   `homebrew-` prefix is required by `brew tap`).

3. **Fill in the formula** (`kompose.rb`):
   - `url`: the GitHub-generated tarball URL for the tag (`https://github.com/owpac/dotfiles/archive/refs/tags/kompose-v1.1.0.tar.gz`) or the PyPI sdist URL if published.
   - `sha256`: `shasum -a 256 <downloaded tarball>`.
   - Resource block(s) for each runtime dep — regenerate with:
     ```
     brew update-python-resources kompose
     ```
     (Run from inside a tap checkout where the formula lives.)

4. **Place the formula** in the tap repo at `Formula/kompose.rb` and push.

5. **Install**:
   ```
   brew tap owpac/kompose
   brew install kompose
   ```

## Why a virtualenv install?

The formula uses `Language::Python::Virtualenv`, which is the standard pattern
for Python CLIs distributed via Homebrew (httpie, awscli, mitmproxy, ansible,
glances all follow it). It creates an isolated venv in
`/opt/homebrew/Cellar/kompose/...` with pinned versions of every Python
dependency. No interference with the user's global Python environment.

## Relationship with the current pipx-based install

Today the dotfiles repo installs kompose via `pipx install --editable` from a
local checkout (see `home/.chezmoiscripts/run_onchange_after_install-kompose.sh.tmpl`).
That keeps code changes live during development.

When brew distribution is in place, the pipx install can stay for development
work on the dotfiles host(s), while other machines (or new users) can simply
`brew install kompose`. The two installation paths produce the same `kompose`
binary on `$PATH`.
