#!/bin/bash
# L2J Mobius C6 Interlude - Login Server Launcher
export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
export PATH="$JAVA_HOME/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGIN_DIR="$SCRIPT_DIR/dist/login"

echo "=== L2J Login Server ==="
echo "Java: $(java -version 2>&1 | head -1)"
echo "Working dir: $LOGIN_DIR"
echo ""

cd "$LOGIN_DIR"
mkdir -p log

java $(cat java.cfg) -jar ../libs/LoginServer.jar 2>&1 | tee log/stdout.log
