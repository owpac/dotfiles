# Homebrew formula for kompose.
#
# Placeholder — not yet published. To publish:
#   1. Push a tagged release of this repo (or publish kompose to PyPI).
#   2. Fill in `url` and `sha256` below.
#   3. Regenerate the `resource "pyyaml"` block via `brew update-python-resources kompose`.
#   4. Place this file in a tap repo (e.g. github.com/owpac/homebrew-kompose/Formula/kompose.rb).
#   5. Users can then run: `brew tap owpac/kompose && brew install kompose`.

class Kompose < Formula
  include Language::Python::Virtualenv

  desc "CLI for managing Docker Compose services on the homelab"
  homepage "https://github.com/owpac/dotfiles"
  url "PLACEHOLDER_TARBALL_URL"
  sha256 "PLACEHOLDER_SHA256"
  license "MIT"

  depends_on "python@3.12"

  # Regenerate this block with: brew update-python-resources kompose
  resource "pyyaml" do
    url "https://files.pythonhosted.org/packages/source/p/pyyaml/PyYAML-6.0.1.tar.gz"
    sha256 "PLACEHOLDER_PYYAML_SHA256"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "kompose", shell_output("#{bin}/kompose --version")
  end
end
