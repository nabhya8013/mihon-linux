#!/usr/bin/env bash
# Mihon Linux launcher
# Run from anywhere: ~/mihon-linux/mihon.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Point at a JDK so the JVM extension bridge can start. Override with
# MIHON_JAVA_HOME or your own JAVA_HOME if you have a system install.
if [ -z "$JAVA_HOME" ] && [ -z "$MIHON_JAVA_HOME" ]; then
    for candidate in \
        "$HOME/sdk/jdk-21.0.2" \
        /usr/lib/jvm/java-21-openjdk \
        /usr/lib/jvm/java-17-openjdk; do
        if [ -x "$candidate/bin/javac" ]; then
            export JAVA_HOME="$candidate"
            break
        fi
    done
else
    export JAVA_HOME="${MIHON_JAVA_HOME:-$JAVA_HOME}"
fi

# Use Wayland if available, fallback to X11
if [ -n "$WAYLAND_DISPLAY" ]; then
    exec python3 run.py "$@"
else
    exec GDK_BACKEND=x11 python3 run.py "$@"
fi
