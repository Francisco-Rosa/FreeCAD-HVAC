#!/bin/sh
# Run Ruff on the given files with the project's settings (see AGENTS.md section 5):
# apply the selected lint fixes, then the formatter.
#   tools/ruff.sh path/to/file.py [more paths...]
set -e
uvx ruff check --preview --line-length 120 --select E302,E303,I \
    --config 'lint.isort.split-on-trailing-comma=false' --fix -q "$@"
uvx ruff format --line-length 120 --config 'format.skip-magic-trailing-comma=true' -q "$@"
