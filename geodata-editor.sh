#!/bin/bash
# L2J Geodata Editor - Web UI
# Opens a visual map editor in your browser

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export GEODATA_DIR="$SCRIPT_DIR/dist/game/data/geodata"

echo "=== L2J Geodata Editor ==="
echo "Geodata: $GEODATA_DIR"
echo ""
echo "Opening http://localhost:5555 ..."
echo "Press Ctrl+C to stop"
echo ""

# Open browser after a short delay
(sleep 2 && open http://localhost:5555) &

cd "$SCRIPT_DIR/tools/geodata"
python3 app.py
