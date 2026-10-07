#!/bin/sh
# Launcher installed as /app/bin/mihon-linux inside the Flatpak sandbox.
# The development launcher (mihon.sh) is not used here: it cd's next to itself
# and hunts for a host JDK, neither of which applies inside /app.
exec python3 /app/share/mihon-linux-app/run.py "$@"
