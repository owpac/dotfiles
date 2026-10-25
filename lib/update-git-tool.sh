#!/usr/bin/env bash
# Usage: update-git-tool.sh <tool> <command>
# Example: update-git-tool.sh "pypi:git+ssh://git@github.com/owpac/pac.git" pac
#
# Reinstall a Python tool that mise installs from a git repository on github.com, when:
#   - its command does not start: a new minor version of Python breaks its venv, and mise does
#     not reinstall the tool;
#   - the default branch has a new commit. On github.com, `latest` is the last tag. Without a tag,
#     mise installs the default branch once, and `mise upgrade` does not follow the new commits.
#     uv keeps the installed commit in the direct_url.json file of the package.
# The hooks post-tools of the modules pac and kompose run this script.

set -u

# lib/ is at the root of this repository: find it from the path of this script.
source "$(dirname "$(readlink -f "$0")")/logs.sh"

tool="$1"
command="$2"
remote="${tool#pypi:git+}"

head=$(git ls-remote "$remote" HEAD 2>/dev/null | cut -f1)
installed=""
if dir=$(mise where "$tool" 2>/dev/null); then
  file=$(grep -l "$remote" "$dir"/*/lib/python*/site-packages/*.dist-info/direct_url.json 2>/dev/null | head -1)
  [ -n "$file" ] && installed=$(grep -o '[0-9a-f]\{40\}' "$file" | head -1)
fi

if ! mise exec -- "$command" --version >/dev/null 2>&1; then
  log_task "Reinstalling $command: it does not start"
elif [ -n "$head" ] && [ "$installed" != "$head" ]; then
  log_task "Reinstalling $command: new commit ${head:0:7} on the default branch"
else
  exit 0
fi
mise install --force "$tool"
