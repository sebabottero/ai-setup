#!/bin/sh
# Adds or updates a skill from GitHub (or any git repo) in core/skills. Help: ./add-skill.sh --help
set -e
command -v git >/dev/null || { echo "git is missing: xcode-select --install"; exit 1; }
exec python3 -I "$(dirname "$0")/add_skill.py" "$@"
