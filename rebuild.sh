#!/bin/bash
# L2J Mobius C6 Interlude - Rebuild Server
export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
export PATH="$JAVA_HOME/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Rebuilding L2J Server ==="
cd "$SCRIPT_DIR"
ant jar 2>&1

if [ $? -eq 0 ]; then
    echo ""
    echo "Copying JARs to dist..."
    cp ~/build/dist/libs/*.jar "$SCRIPT_DIR/dist/libs/"
    cp ~/build/dist/db_installer/*.jar "$SCRIPT_DIR/dist/db_installer/"
    echo "Build complete!"
else
    echo "Build FAILED!"
    exit 1
fi
