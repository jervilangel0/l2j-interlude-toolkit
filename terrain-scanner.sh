#!/bin/bash
# L2 Terrain Scanner - Headless client geodata probing
# Connects to your L2J server and scans terrain without a game client
#
# Usage:
#   ./terrain-scanner.sh --test                     # Quick connection test
#   ./terrain-scanner.sh --scan --region 20 18      # Single agent scan
#   ./terrain-scanner.sh --dashboard                # Web dashboard (multi-agent)
#   ./terrain-scanner.sh --bootstrap --num 20       # Create scanner accounts

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== L2 Terrain Scanner ==="
echo ""
echo "Make sure your L2J server is running first:"
echo "  brew services start mariadb"
echo "  l2j start"
echo ""

cd "$SCRIPT_DIR/tools/headless-client"

case "$1" in
  --dashboard)
    shift
    echo "Starting web dashboard on http://localhost:5556"
    echo ""
    python3 dashboard.py "$@"
    ;;
  --bootstrap)
    shift
    echo "Bootstrapping scanner accounts..."
    echo ""
    python3 bootstrap.py "$@"
    ;;
  *)
    python3 terrain_scanner.py "$@"
    ;;
esac
