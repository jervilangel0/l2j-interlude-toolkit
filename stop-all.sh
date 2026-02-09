#!/bin/bash
# L2J Mobius C6 Interlude - Stop All Servers
echo "=== Stopping L2J Servers ==="

# Find and kill GameServer
GAME_PIDS=$(pgrep -f "GameServer.jar" 2>/dev/null)
if [ -n "$GAME_PIDS" ]; then
    echo "Stopping Game Server (PID: $GAME_PIDS)..."
    kill $GAME_PIDS
else
    echo "Game Server not running."
fi

# Find and kill LoginServer
LOGIN_PIDS=$(pgrep -f "LoginServer.jar" 2>/dev/null)
if [ -n "$LOGIN_PIDS" ]; then
    echo "Stopping Login Server (PID: $LOGIN_PIDS)..."
    kill $LOGIN_PIDS
else
    echo "Login Server not running."
fi

echo "Done."
