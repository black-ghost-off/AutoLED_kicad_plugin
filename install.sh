#!/bin/sh
# Install (symlink) the AutoLED plugin into KiCad's user scripting plugin folder.
# Usage: ./install.sh [kicad-version]   (default: newest version folder found)
set -e
SRC="$(cd "$(dirname "$0")" && pwd)/auto_led"
case "$(uname)" in
  Darwin) BASE="$HOME/Documents/KiCad" ;;
  *)      BASE="${XDG_DATA_HOME:-$HOME/.local/share}/kicad" ;;
esac
VER="${1:-$(ls "$BASE" 2>/dev/null | grep -E '^[0-9]+\.[0-9]+$' | sort -V | tail -1)}"
[ -n "$VER" ] || { echo "No KiCad version folder in $BASE; pass the version, e.g. ./install.sh 9.0"; exit 1; }
DEST="$BASE/$VER/scripting/plugins"
mkdir -p "$DEST"
ln -sfn "$SRC" "$DEST/auto_led"
echo "Linked $SRC -> $DEST/auto_led"
echo "In the PCB editor: Tools > External Plugins > Refresh Plugins"
