#!/usr/bin/env bash
#
# Install the desktop entry, icons and AppStream metadata so Mihon for Linux
# shows up in the application launcher and in software centres.
#
# Installs per-user by default (~/.local/share). Pass a prefix to install
# system-wide, e.g. for packaging:
#
#     scripts/install-desktop-files.sh /usr
#
# Uninstall with:
#
#     scripts/install-desktop-files.sh --uninstall
#
set -euo pipefail

APP_ID="io.github.nabhya8013.MihonLinux"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_SRC="$REPO_DIR/data"

UNINSTALL=0
if [ "${1:-}" = "--uninstall" ]; then
    UNINSTALL=1
    shift
fi

PREFIX="${1:-$HOME/.local}"
DATADIR="$PREFIX/share"
BINDIR="$PREFIX/bin"

DESKTOP_FILE="$DATADIR/applications/$APP_ID.desktop"
METAINFO_FILE="$DATADIR/metainfo/$APP_ID.metainfo.xml"
ICON_FILE="$DATADIR/icons/hicolor/scalable/apps/$APP_ID.svg"
SYMBOLIC_FILE="$DATADIR/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg"
RASTER_ICON_SIZES="48 64 128 256"
LAUNCHER="$BINDIR/mihon-linux"

refresh_caches() {
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$DATADIR/applications" || true
    fi
    if command -v gtk4-update-icon-cache >/dev/null 2>&1; then
        gtk4-update-icon-cache -q -t -f "$DATADIR/icons/hicolor" || true
    elif command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t -f "$DATADIR/icons/hicolor" || true
    fi
}

if [ "$UNINSTALL" -eq 1 ]; then
    rm -f "$DESKTOP_FILE" "$METAINFO_FILE" "$ICON_FILE" "$SYMBOLIC_FILE" "$LAUNCHER"
    for size in $RASTER_ICON_SIZES; do
        rm -f "$DATADIR/icons/hicolor/${size}x${size}/apps/$APP_ID.png"
    done
    refresh_caches
    echo "Removed Mihon for Linux desktop integration from $PREFIX"
    exit 0
fi

install -Dm644 "$DATA_SRC/$APP_ID.desktop" "$DESKTOP_FILE"
install -Dm644 "$DATA_SRC/$APP_ID.metainfo.xml" "$METAINFO_FILE"
install -Dm644 "$DATA_SRC/icons/hicolor/scalable/apps/$APP_ID.svg" "$ICON_FILE"
install -Dm644 "$DATA_SRC/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg" "$SYMBOLIC_FILE"
for size in $RASTER_ICON_SIZES; do
    install -Dm644 \
        "$DATA_SRC/icons/hicolor/${size}x${size}/apps/$APP_ID.png" \
        "$DATADIR/icons/hicolor/${size}x${size}/apps/$APP_ID.png"
done

# The desktop entry runs `mihon-linux`, so drop a launcher on PATH that points
# back at this checkout. A distro package would ship a real entry point here
# instead.
install -d "$BINDIR"
cat > "$LAUNCHER" <<LAUNCHER_EOF
#!/usr/bin/env bash
exec "$REPO_DIR/mihon.sh" "\$@"
LAUNCHER_EOF
chmod +x "$LAUNCHER"

refresh_caches

echo "Installed Mihon for Linux desktop integration to $PREFIX"
echo
if ! printf '%s' ":$PATH:" | grep -q ":$BINDIR:"; then
    echo "Note: $BINDIR is not on your PATH, so the launcher will not resolve."
    echo "      Add it with:  export PATH=\"$BINDIR:\$PATH\""
fi
