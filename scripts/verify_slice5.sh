#!/usr/bin/env bash
# Build and test the bridge after Slice 5 (Cloudflare interceptor).
# Requires JDK 21. Run from anywhere.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Detect a JDK if JAVA_HOME is unset: derive it from javac on PATH.
if [ -z "${JAVA_HOME:-}" ] && command -v javac >/dev/null 2>&1; then
    JAVA_HOME="$(dirname "$(dirname "$(readlink -f "$(command -v javac)")")")"
fi
JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-21-openjdk}"

if [ ! -x "$JAVA_HOME/bin/javac" ]; then
    echo "[verify_slice5] JDK not found at $JAVA_HOME. Set JAVA_HOME to a JDK 21 install." >&2
    exit 1
fi

cd "$REPO_ROOT/bridge"

echo "[verify_slice5] Compiling Kotlin sources..."
JAVA_HOME="$JAVA_HOME" ./gradlew compileKotlin compileTestKotlin --rerun-tasks

echo "[verify_slice5] Running JVM tests..."
JAVA_HOME="$JAVA_HOME" ./gradlew test --tests 'eu.kanade.tachiyomi.network.interceptor.CloudflareInterceptorTest'

echo "[verify_slice5] Building fat jar..."
JAVA_HOME="$JAVA_HOME" ./gradlew jar

cd "$REPO_ROOT"

echo "[verify_slice5] Running Python tests..."
PYTHONPATH=. python -m unittest tests.test_http_client tests.test_challenge_bridge -v

echo "[verify_slice5] All checks passed."
