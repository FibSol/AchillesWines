#!/bin/bash
# Generate PWA icons from the SVG source.
# Requires: imagemagick (apt install imagemagick) or inkscape.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ICONS_DIR="$SCRIPT_DIR/../public/icons"
SVG_SRC="$ICONS_DIR/icon.svg"

mkdir -p "$ICONS_DIR"

if command -v convert &>/dev/null; then
  echo "Using ImageMagick..."
  convert -background none -size 192x192 "$SVG_SRC" "$ICONS_DIR/icon-192x192.png"
  convert -background none -size 512x512 "$SVG_SRC" "$ICONS_DIR/icon-512x512.png"
elif command -v inkscape &>/dev/null; then
  echo "Using Inkscape..."
  inkscape --export-type=png --export-width=192 --export-height=192 \
    --export-filename="$ICONS_DIR/icon-192x192.png" "$SVG_SRC"
  inkscape --export-type=png --export-width=512 --export-height=512 \
    --export-filename="$ICONS_DIR/icon-512x512.png" "$SVG_SRC"
else
  echo "ERROR: Neither ImageMagick nor Inkscape found. Install one and retry." >&2
  exit 1
fi

echo "Icons generated:"
ls -lh "$ICONS_DIR"/*.png
