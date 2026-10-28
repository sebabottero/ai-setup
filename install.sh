#!/bin/sh
# Installs ai-setup into the AI tools on this machine. Options: ./install.sh --help
# It runs the tests first (guard, receipts, install into a temporary home): if they fail, nothing is installed.
set -e
here=$(dirname "$0")
command -v python3 >/dev/null || { echo "python3 is missing: install the Command Line Tools (xcode-select --install)"; exit 1; }
python3 -I -m unittest discover -s "$here/tests" -q 2>/dev/null || {
  echo "The tests fail: not installing. Details: python3 -m unittest discover -s tests"; exit 1; }
exec python3 -I "$here/install.py" "$@"
