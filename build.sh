#!/usr/bin/env bash
# Build radio_browser with Nuitka on macOS or Linux.
# Usage:
#   ./build.sh              # onefile binary (default)
#   ./build.sh --standalone # folder output (faster cold start)
#   ./build.sh --debug      # keep terminal window for debugging

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

STANDALONE=0
DEBUG=0

for arg in "$@"; do
    case $arg in
        --standalone) STANDALONE=1 ;;
        --debug)      DEBUG=1 ;;
    esac
done

# Ensure Nuitka is present
if ! python -c "import nuitka" 2>/dev/null; then
    echo "Installing Nuitka and required build helpers..."
    pip install nuitka zstandard ordered-set
fi

OUT_DIR="$SCRIPT_DIR/build"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

BINARY_NAME="radio_browser"

NUITKA_ARGS=(
    -m nuitka
    --enable-plugin=wx
    --include-package=accessible_output2
    --include-package=sound_lib
    --include-package=libloader
    --include-package=platform_utils
    --include-package=platformdirs
    "--output-filename=$BINARY_NAME"
    "--output-dir=$OUT_DIR"
)

if [[ "$STANDALONE" -eq 1 ]]; then
    NUITKA_ARGS+=(--standalone)
    echo "Mode: standalone (folder)"
else
    NUITKA_ARGS+=(--onefile --remove-output)
    echo "Mode: onefile (single binary)"
fi

# macOS: suppress the console by creating an app bundle in standalone mode
if [[ "$(uname -s)" == "Darwin" ]]; then
    if [[ "$STANDALONE" -eq 1 ]]; then
        NUITKA_ARGS+=(--macos-create-app-bundle)
    fi
fi

NUITKA_ARGS+=("$SCRIPT_DIR/src/radio_browser.py")

echo "Running: python ${NUITKA_ARGS[*]}"
python "${NUITKA_ARGS[@]}"

if [[ -f "$OUT_DIR/$BINARY_NAME" ]]; then
    chmod +x "$OUT_DIR/$BINARY_NAME"
    SIZE=$(du -sh "$OUT_DIR/$BINARY_NAME" | cut -f1)
    HASH=$(shasum -a 256 "$OUT_DIR/$BINARY_NAME" | awk '{print $1}')
    echo ""
    echo "Build successful!"
    echo "  Output : $OUT_DIR/$BINARY_NAME"
    echo "  Size   : $SIZE"
    echo "  SHA256 : $HASH"
elif [[ -d "$OUT_DIR/${BINARY_NAME}.app" ]]; then
    echo ""
    echo "Build successful! App bundle: $OUT_DIR/${BINARY_NAME}.app"
else
    echo "Build output not found — Nuitka may have reported an error above."
    exit 1
fi
