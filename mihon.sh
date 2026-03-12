#!/usr/bin/env bash
# Mihon Linux launcher
# Run from anywhere: ~/mihon-linux/mihon.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Use Wayland if available, fallback to X11
if [ -n "$WAYLAND_DISPLAY" ]; then
    exec python3 run.py "$@"
else
    exec GDK_BACKEND=x11 python3 run.py "$@"
fi
