"""
L2 Terrain Scanner — Automated geodata extraction via headless client.

Connects to the L2J server as a GM character, systematically teleports
across the world grid, and probes terrain height + walkability to
generate L2D geodata files.

Approach:
  1. Teleport to (x, y, high_z) — server doesn't snap Z on teleport
  2. Send ValidatePosition — server corrects Z to ground level
  3. Attempt movement in 4 cardinal directions
  4. If server allows/blocks, record NSWE flags
  5. Compile into L2D geodata format

Usage:
  python3 terrain_scanner.py --test                          # Quick connection test
  python3 terrain_scanner.py --scan --region 20 18           # Scan a full region
  python3 terrain_scanner.py --scan --area 83000 148000 84000 149000  # Scan area by world coords
  python3 terrain_scanner.py --probe 83000 148000 -3400      # Probe a single point
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Add parent path for imports
sys.path.insert(0, os.path.dirname(__file__))
from l2_client import L2GameClient, full_connect

# Also need the geodata tools
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'geodata'))
from l2d_parser import (
    REGION_CELLS_X, REGION_CELLS_Y, BLOCK_CELLS_X, BLOCK_CELLS_Y,
    REGION_BLOCKS_X, REGION_BLOCKS_Y, BLOCK_CELLS,
    TYPE_FLAT, TYPE_COMPLEX, TYPE_MULTILAYER,
    NSWE_ALL_L2D, Cell, BlockFlat, BlockComplex, BlockMultilayer,
    GeoRegion, write_l2d, region_to_world_coords, world_to_region_coords,
)


# ============================================================================
# SCANNER CONFIGURATION
# ============================================================================

@dataclass
class ScanConfig:
    """Configuration for terrain scanning."""
    username: str = "admin"
    password: str = "admin"
    login_host: str = "127.0.0.1"
    login_port: int = 2106
    char_slot: int = 0

    # Scanning parameters
    cell_size: int = 16             # World units per geodata cell
    probe_z: int = 10000            # Z height for initial teleport (very high)
    settle_time: float = 0.3        # Seconds to wait after teleport for Z correction
    move_settle_time: float = 0.2   # Seconds to wait after movement attempt
    validate_interval: float = 0.1  # Seconds between ValidatePosition sends

    # Output
    output_dir: str = ""            # Where to save generated L2D files


# ============================================================================
# POSITION TRACKER (enhanced packet handling)
# ============================================================================

class PositionTracker:
    """Enhanced position tracking with Z-correction detection."""

    def __init__(self, game: L2GameClient):
        self.game = game
        self._last_z_update = 0.0
        self._z_corrected = False
        self._move_result = None  # None=pending, True=allowed, False=blocked

        # Override handlers for tracking
        game._handlers[0x04] = self._on_user_info
        game._handlers[0x28] = self._on_teleport
        game._handlers[0x47] = self._on_stop_move
        game._handlers[0x61] = self._on_validate_location
        game._handlers[0x76] = self._on_set_to_location
        game._handlers[0x01] = self._on_move_to_location

    def _on_user_info(self, data: bytearray):
        """UserInfo (0x04) — full character state."""
        self.game.x = struct.unpack_from("<i", data, 1)[0]
        self.game.y = struct.unpack_from("<i", data, 5)[0]
        self.game.z = struct.unpack_from("<i", data, 9)[0]
        self._z_corrected = True
        self._last_z_update = time.time()

    def _on_teleport(self, data: bytearray):
        """TeleportToLocation (0x28)."""
        obj_id = struct.unpack_from("<I", data, 1)[0]
        if obj_id == self.game.object_id:
            self.game.x = struct.unpack_from("<i", data, 5)[0]
            self.game.y = struct.unpack_from("<i", data, 9)[0]
            self.game.z = struct.unpack_from("<i", data, 13)[0]
            self._last_z_update = time.time()

    def _on_stop_move(self, data: bytearray):
        """StopMove (0x47) — server stopped our movement (blocked or landed)."""
        obj_id = struct.unpack_from("<I", data, 1)[0]
        if obj_id == self.game.object_id:
            self.game.x = struct.unpack_from("<i", data, 5)[0]
            self.game.y = struct.unpack_from("<i", data, 9)[0]
            self.game.z = struct.unpack_from("<i", data, 13)[0]
            self._z_corrected = True
            self._last_z_update = time.time()
            self._move_result = False  # Movement was stopped

    def _on_validate_location(self, data: bytearray):
        """ValidateLocation (0x61) — server corrects our position."""
        obj_id = struct.unpack_from("<I", data, 1)[0]
        if obj_id == self.game.object_id:
            self.game.x = struct.unpack_from("<i", data, 5)[0]
            self.game.y = struct.unpack_from("<i", data, 9)[0]
            self.game.z = struct.unpack_from("<i", data, 13)[0]
            self._z_corrected = True
            self._last_z_update = time.time()

    def _on_set_to_location(self, data: bytearray):
        """SetToLocation (0x76)."""
        obj_id = struct.unpack_from("<I", data, 1)[0]
        if obj_id == self.game.object_id:
            self.game.x = struct.unpack_from("<i", data, 5)[0]
            self.game.y = struct.unpack_from("<i", data, 9)[0]
            self.game.z = struct.unpack_from("<i", data, 13)[0]
            self._z_corrected = True
            self._last_z_update = time.time()

    def _on_move_to_location(self, data: bytearray):
        """CharMoveToLocation (0x01) — movement was allowed."""
        obj_id = struct.unpack_from("<I", data, 1)[0]
        if obj_id == self.game.object_id:
            self._move_result = True

    def wait_for_z(self, timeout: float = 2.0) -> bool:
        """Wait until server corrects our Z position."""
        self._z_corrected = False
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._z_corrected:
                return True
            time.sleep(0.05)
        return False

    def probe_z(self, x: int, y: int, probe_z: int = 10000) -> int:
        """Teleport to position and get corrected Z height.

        Strategy: teleport high, send ValidatePosition with wrong Z,
        server corrects us to ground level.
        """
        # Teleport via GM command
        self.game.teleport_to(x, y, probe_z)
        time.sleep(0.15)

        # Force server to validate our position
        self.game.send_validate_position()
        time.sleep(0.1)

        # Wait for correction
        if self.wait_for_z(timeout=1.5):
            return self.game.z

        # If no correction, try sending validate again with a very wrong position
        old_z = self.game.z
        self.game.z = -30000  # Force mismatch
        self.game.send_validate_position()
        self.game.z = old_z
        time.sleep(0.1)

        if self.wait_for_z(timeout=1.0):
            return self.game.z

        # Fallback: use whatever Z we have
        return self.game.z

    def probe_movement(self, direction: str) -> bool:
        """Try to move in a direction and check if server allows it.

        direction: 'N', 'S', 'E', 'W'
        Returns True if movement was allowed.
        """
        dx, dy = 0, 0
        step = 16  # One geodata cell

        if direction == 'N':
            dy = -step
        elif direction == 'S':
            dy = step
        elif direction == 'E':
            dx = step
        elif direction == 'W':
            dx = -step

        target_x = self.game.x + dx
        target_y = self.game.y + dy
        target_z = self.game.z

        # Record starting position
        start_x, start_y = self.game.x, self.game.y

        # Reset movement result
        self._move_result = None

        # Send movement request
        self.game.send_move(target_x, target_y, target_z)
        time.sleep(0.15)

        # Check if movement was allowed or blocked
        if self._move_result is True:
            # Movement was allowed, teleport back to original position
            self.game.teleport_to(start_x, start_y, self.game.z)
            time.sleep(0.1)
            return True
        elif self._move_result is False:
            # Movement was explicitly blocked (StopMove)
            return False

        # Ambiguous: check if we actually moved
        dist_sq = (self.game.x - start_x) ** 2 + (self.game.y - start_y) ** 2
        if dist_sq > 4:  # Moved at least a couple units
            # We moved, teleport back
            self.game.teleport_to(start_x, start_y, self.game.z)
            time.sleep(0.1)
            return True

        return False


# ============================================================================
# TERRAIN SCANNER
# ============================================================================

class TerrainScanner:
    """Systematic terrain scanner that generates geodata."""

    def __init__(self, config: ScanConfig):
        self.config = config
        self.game: Optional[L2GameClient] = None
        self.tracker: Optional[PositionTracker] = None

    def connect(self) -> bool:
        """Connect to the server."""
        print("=" * 60)
        print("L2 TERRAIN SCANNER")
        print("=" * 60)
        print(f"Server: {self.config.login_host}:{self.config.login_port}")
        print(f"Account: {self.config.username}")
        print()

        self.game = full_connect(
            self.config.username,
            self.config.password,
            self.config.login_host,
            self.config.login_port,
            self.config.char_slot,
        )

        if not self.game:
            print("[SCANNER] Failed to connect!")
            return False

        # Start background packet processing
        self.game.start_packet_loop()
        time.sleep(0.5)

        # Set up position tracker
        self.tracker = PositionTracker(self.game)

        print(f"[SCANNER] Connected! Position: ({self.game.x}, {self.game.y}, {self.game.z})")
        return True

    def disconnect(self):
        """Disconnect from the server."""
        if self.game:
            self.game.close()
            self.game = None
            self.tracker = None
        print("[SCANNER] Disconnected.")

    def test_connection(self):
        """Quick test: connect, report position, try a teleport."""
        if not self.connect():
            return

        print()
        print("--- Connection Test ---")
        print(f"Character: {self.game.name}")
        print(f"Position: ({self.game.x}, {self.game.y}, {self.game.z})")
        print()

        # Test teleport to Giran
        print("Testing teleport to Giran Castle Town...")
        z = self.tracker.probe_z(83000, 148000, self.config.probe_z)
        print(f"Landed at: ({self.game.x}, {self.game.y}, {z})")
        print()

        # Test movement probing
        print("Testing movement probes...")
        for direction in ['N', 'S', 'E', 'W']:
            can_move = self.tracker.probe_movement(direction)
            status = "OK" if can_move else "BLOCKED"
            print(f"  {direction}: {status}")

        print()
        print("Connection test complete!")
        self.disconnect()

    def probe_point(self, world_x: int, world_y: int, world_z: int):
        """Probe a single world position."""
        if not self.connect():
            return

        print(f"\n--- Probing ({world_x}, {world_y}, {world_z}) ---")

        # Teleport and get corrected Z
        z = self.tracker.probe_z(world_x, world_y, world_z)
        print(f"Ground Z: {z}")

        # Probe all directions
        print("Movement check:")
        nswe = 0
        for direction, flag_bit in [('N', 0x08), ('S', 0x04), ('E', 0x01), ('W', 0x02)]:
            can_move = self.tracker.probe_movement(direction)
            if can_move:
                nswe |= flag_bit
            status = "OK" if can_move else "BLOCKED"
            print(f"  {direction}: {status}")

        # Convert to region coords
        rx, ry, cx, cy = world_to_region_coords(world_x, world_y)
        print(f"\nRegion: {rx}_{ry}, Cell: ({cx}, {cy})")
        print(f"NSWE: 0x{nswe:02X}")
        print(f"Height: {z}")

        self.disconnect()

    def scan_region(self, region_x: int, region_y: int, step: int = 8):
        """Scan an entire geodata region.

        step: cells to skip between probes (1=every cell, 8=one per block).
              Use step=8 for fast block-level scanning,
              step=1 for full cell-level scanning (VERY slow: 2048x2048 = 4M cells).
        """
        if not self.connect():
            return

        total_cells = (REGION_CELLS_X // step) * (REGION_CELLS_Y // step)
        print(f"\n--- Scanning Region {region_x}_{region_y} ---")
        print(f"Step: {step} (probing every {step} cells)")
        print(f"Total probes: {total_cells}")
        print(f"Estimated time: ~{total_cells * 0.5 / 60:.0f} minutes")
        print()

        # Initialize storage: height grid and NSWE grid
        heights = {}
        nswe_data = {}
        scanned = 0
        start_time = time.time()

        try:
            for cx in range(0, REGION_CELLS_X, step):
                for cy in range(0, REGION_CELLS_Y, step):
                    wx, wy = region_to_world_coords(region_x, region_y, cx, cy)

                    # Probe Z height
                    z = self.tracker.probe_z(wx, wy, self.config.probe_z)
                    heights[(cx, cy)] = z

                    # Probe NSWE
                    nswe = 0
                    for direction, flag_bit in [('N', 0x08), ('S', 0x04), ('E', 0x01), ('W', 0x02)]:
                        if self.tracker.probe_movement(direction):
                            nswe |= flag_bit
                    nswe_data[(cx, cy)] = nswe

                    scanned += 1
                    if scanned % 10 == 0:
                        elapsed = time.time() - start_time
                        rate = scanned / elapsed if elapsed > 0 else 0
                        eta = (total_cells - scanned) / rate if rate > 0 else 0
                        pct = 100 * scanned / total_cells
                        print(f"\r  [{pct:5.1f}%] {scanned}/{total_cells} "
                              f"({rate:.1f}/s, ETA {eta/60:.0f}m) "
                              f"pos=({wx},{wy},{z})", end="", flush=True)

        except KeyboardInterrupt:
            print(f"\n\n[SCANNER] Interrupted after {scanned} probes.")

        print(f"\n\nScanning complete: {scanned} cells probed.")
        elapsed = time.time() - start_time
        print(f"Time: {elapsed/60:.1f} minutes")

        # Build geodata region
        if scanned > 0:
            region = self._build_region(region_x, region_y, heights, nswe_data, step)
            output_path = self._get_output_path(region_x, region_y)
            write_l2d(region, output_path)
            print(f"Saved: {output_path}")

            # Also save raw scan data as JSON
            json_path = output_path.with_suffix('.scan.json')
            scan_data = {
                "region": f"{region_x}_{region_y}",
                "step": step,
                "scanned_cells": scanned,
                "time_seconds": elapsed,
                "heights": {f"{k[0]},{k[1]}": v for k, v in heights.items()},
                "nswe": {f"{k[0]},{k[1]}": v for k, v in nswe_data.items()},
            }
            json_path.write_text(json.dumps(scan_data, indent=2))
            print(f"Raw data: {json_path}")

        self.disconnect()

    def scan_area(self, x1: int, y1: int, x2: int, y2: int, step: int = 1):
        """Scan a rectangular area by world coordinates.

        Each cell is 16 world units, so step=1 probes every 16 units.
        """
        if not self.connect():
            return

        # Ensure x1 < x2 and y1 < y2
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)

        cell_step = step * 16  # Convert cell steps to world units
        total_x = (x2 - x1) // cell_step + 1
        total_y = (y2 - y1) // cell_step + 1
        total = total_x * total_y

        print(f"\n--- Scanning Area ---")
        print(f"World: ({x1},{y1}) to ({x2},{y2})")
        print(f"Grid: {total_x} x {total_y} = {total} probes")
        print(f"Estimated time: ~{total * 0.5 / 60:.0f} minutes")
        print()

        results = []
        scanned = 0
        start_time = time.time()

        try:
            wx = x1
            while wx <= x2:
                wy = y1
                while wy <= y2:
                    # Probe Z
                    z = self.tracker.probe_z(wx, wy, self.config.probe_z)

                    # Probe NSWE
                    nswe = 0
                    for direction, flag_bit in [('N', 0x08), ('S', 0x04), ('E', 0x01), ('W', 0x02)]:
                        if self.tracker.probe_movement(direction):
                            nswe |= flag_bit

                    rx, ry, cx, cy = world_to_region_coords(wx, wy)
                    results.append({
                        "world_x": wx, "world_y": wy, "world_z": z,
                        "region_x": rx, "region_y": ry,
                        "cell_x": cx, "cell_y": cy,
                        "nswe": nswe,
                    })

                    scanned += 1
                    if scanned % 5 == 0:
                        elapsed = time.time() - start_time
                        rate = scanned / elapsed if elapsed > 0 else 0
                        eta = (total - scanned) / rate if rate > 0 else 0
                        pct = 100 * scanned / total
                        print(f"\r  [{pct:5.1f}%] {scanned}/{total} "
                              f"({rate:.1f}/s, ETA {eta/60:.0f}m) "
                              f"({wx},{wy},{z}) NSWE=0x{nswe:02X}", end="", flush=True)

                    wy += cell_step
                wx += cell_step

        except KeyboardInterrupt:
            print(f"\n\n[SCANNER] Interrupted after {scanned} probes.")

        print(f"\n\nArea scan complete: {scanned} cells probed.")
        elapsed = time.time() - start_time
        print(f"Time: {elapsed:.1f} seconds")

        # Save results
        if results:
            output_dir = Path(self.config.output_dir or ".")
            output_dir.mkdir(parents=True, exist_ok=True)
            json_path = output_dir / f"area_scan_{x1}_{y1}_{x2}_{y2}.json"
            json_path.write_text(json.dumps(results, indent=2))
            print(f"Results: {json_path}")

            # Print summary
            print("\nResults:")
            print(f"{'World X':>10} {'World Y':>10} {'Z':>8} {'NSWE':>6} {'Directions':>15}")
            print("-" * 55)
            for r in results[:50]:  # Show first 50
                dirs = []
                if r["nswe"] & 0x08: dirs.append("N")
                if r["nswe"] & 0x04: dirs.append("S")
                if r["nswe"] & 0x01: dirs.append("E")
                if r["nswe"] & 0x02: dirs.append("W")
                dir_str = ",".join(dirs) if dirs else "BLOCKED"
                print(f"{r['world_x']:>10} {r['world_y']:>10} {r['world_z']:>8} "
                      f"0x{r['nswe']:02X}   {dir_str:>15}")
            if len(results) > 50:
                print(f"  ... and {len(results) - 50} more")

        self.disconnect()

    def _build_region(self, region_x: int, region_y: int,
                      heights: dict, nswe_data: dict, step: int) -> GeoRegion:
        """Build a GeoRegion from scanned data."""
        blocks = []

        for bx in range(REGION_BLOCKS_X):
            for by in range(REGION_BLOCKS_Y):
                # Check if we have data for this block
                base_cx = bx * BLOCK_CELLS_X
                base_cy = by * BLOCK_CELLS_Y

                # Find nearest scanned cell for this block
                nearest_cx = (base_cx // step) * step
                nearest_cy = (base_cy // step) * step

                if (nearest_cx, nearest_cy) in heights:
                    block_height = heights[(nearest_cx, nearest_cy)]
                    block_nswe = nswe_data.get((nearest_cx, nearest_cy), NSWE_ALL_L2D)

                    if step >= BLOCK_CELLS_X:
                        # Block-level scan: create flat blocks
                        blocks.append(BlockFlat(height=block_height))
                    else:
                        # Cell-level scan: create complex blocks
                        cells = []
                        for lx in range(BLOCK_CELLS_X):
                            for ly in range(BLOCK_CELLS_Y):
                                cx = base_cx + lx
                                cy = base_cy + ly
                                h = heights.get((cx, cy), block_height)
                                n = nswe_data.get((cx, cy), block_nswe)
                                cells.append(Cell(height=h, nswe=n))
                        blocks.append(BlockComplex(cells=cells))
                else:
                    # No data: flat walkable block at z=0
                    blocks.append(BlockFlat(height=0))

        return GeoRegion(region_x=region_x, region_y=region_y, blocks=blocks)

    def _get_output_path(self, region_x: int, region_y: int) -> Path:
        """Get output file path for a scanned region."""
        if self.config.output_dir:
            output_dir = Path(self.config.output_dir)
        else:
            # Default: same as server geodata
            output_dir = Path(__file__).resolve().parent.parent.parent / "dist" / "game" / "data" / "geodata"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / f"{region_x}_{region_y}.l2d"


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="L2 Terrain Scanner — Generate geodata via headless client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --test                              Quick connection test
  %(prog)s --probe 83000 148000 -3400          Probe single point
  %(prog)s --scan --region 20 18               Scan region (block-level)
  %(prog)s --scan --region 20 18 --step 1      Scan region (cell-level, slow!)
  %(prog)s --scan --area 83000 148000 84000 149000   Scan area
        """,
    )

    # Mode
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--test", action="store_true", help="Quick connection test")
    mode.add_argument("--probe", nargs=3, type=int, metavar=("X", "Y", "Z"),
                      help="Probe a single world position")
    mode.add_argument("--scan", action="store_true", help="Scan terrain")

    # Scan target
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--region", nargs=2, type=int, metavar=("RX", "RY"),
                        help="Scan a full geodata region")
    target.add_argument("--area", nargs=4, type=int, metavar=("X1", "Y1", "X2", "Y2"),
                        help="Scan rectangular area (world coords)")

    # Options
    parser.add_argument("--step", type=int, default=8,
                        help="Cell step size for scanning (default: 8 = one probe per block)")
    parser.add_argument("--user", default="admin", help="Login username")
    parser.add_argument("--pass", dest="password", default="admin", help="Login password")
    parser.add_argument("--host", default="127.0.0.1", help="Login server host")
    parser.add_argument("--port", type=int, default=2106, help="Login server port")
    parser.add_argument("--slot", type=int, default=0, help="Character slot")
    parser.add_argument("--output", default="", help="Output directory for geodata files")

    args = parser.parse_args()

    config = ScanConfig(
        username=args.user,
        password=args.password,
        login_host=args.host,
        login_port=args.port,
        char_slot=args.slot,
        output_dir=args.output,
    )

    scanner = TerrainScanner(config)

    if args.test:
        scanner.test_connection()
    elif args.probe:
        scanner.probe_point(*args.probe)
    elif args.scan:
        if args.region:
            scanner.scan_region(*args.region, step=args.step)
        elif args.area:
            scanner.scan_area(*args.area, step=args.step)
        else:
            print("Error: --scan requires --region or --area")
            sys.exit(1)


if __name__ == "__main__":
    main()
