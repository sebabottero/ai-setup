#!/bin/sh
# Packs ai-setup (with its git history) into a zip to keep on Drive or a USB stick before wiping the machine.
# Usage: ./backup.sh [--without <layer>] [target-folder]
#   --without <layer>  leaves that layer folder out. The .git history too (it may hold the layer in its commits).
# Layers kept in another folder (--layers-dir) are not in this zip: back them up with their own repo. Verifies the zip at the end.
set -e
skip=""
while [ $# -gt 0 ]; do
  case "$1" in
    --without|--sin) skip="$2"; shift 2 ;;
    *) break ;;
  esac
done
here=$(cd "$(dirname "$0")" && pwd)
name=$(basename "$here")
out="${1:-$HOME/Downloads}/ai-setup-$(date +%Y%m%d)${skip:+-without-$skip}.zip"
cd "$(dirname "$here")"
rm -f "$out"
if [ -n "$skip" ]; then
  [ -d "$here/$skip" ] || { echo "There is no layer $skip"; exit 1; }
  zip -qr "$out" "$name" -x "*/build/*" "*/.DS_Store" "*/__pycache__/*" "$name/$skip/*" "$name/.git/*"
  echo "Without layer $skip and without .git (the history contains it). To restore with history, use a full zip."
else
  zip -qr "$out" "$name" -x "*/build/*" "*/.DS_Store" "*/__pycache__/*"
fi
unzip -tq "$out" >/dev/null || { echo "The zip is damaged: $out"; exit 1; }
count=$(unzip -Z1 "$out" | wc -l | tr -d ' ')
unzip -Z1 "$out" | grep -q "^$name/install.py$" || { echo "$name/install.py is missing from the zip"; exit 1; }
echo "Saved to $out ($count files, $(date '+%Y-%m-%d %H:%M')). Verified."
