#!/bin/bash
# L2J Mobius C6 Interlude - Game Server Launcher
export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
export PATH="$JAVA_HOME/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GAME_DIR="$SCRIPT_DIR/dist/game"

echo "=== L2J Game Server ==="
echo "Java: $(java -version 2>&1 | head -1)"
echo "Working dir: $GAME_DIR"
echo ""

cd "$GAME_DIR"
mkdir -p log

java $(cat java.cfg) -jar ../libs/GameServer.jar 2>&1 | tee log/stdout.log
