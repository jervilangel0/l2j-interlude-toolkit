"""
Single agent worker thread for the multi-agent terrain scanner.

Each worker has its own L2GameClient connection and scans regions
by sending admin_scan_geo commands that query GeoEngine directly.
This is orders of magnitude faster than teleport-based probing.
"""
from __future__ import annotations

import base64
import os
import queue
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
from l2_client import L2GameClient, full_connect_or_create
from scan_state import ScanProgress, RegionState, RegionStatus, WorkerStatus

# Import geodata tools
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'geodata'))
from l2d_parser import (
    REGION_CELLS_X, REGION_CELLS_Y, BLOCK_CELLS_X, BLOCK_CELLS_Y,
    REGION_BLOCKS_X, REGION_BLOCKS_Y, BLOCK_CELLS,
    NSWE_ALL_L2D, Cell, BlockFlat, BlockComplex,
    GeoRegion, write_l2d,
)


class ScanWorker:
    """Single agent worker that scans regions in its own thread."""

    def __init__(self, name: str, progress: ScanProgress,
                 username: str, password: str,
                 login_host: str = "127.0.0.1", login_port: int = 2106,
                 output_dir: str = ""):
        self.name = name
        self.progress = progress
        self.username = username
        self.password = password
        self.login_host = login_host
        self.login_port = login_port
        self.output_dir = output_dir

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.game: Optional[L2GameClient] = None

    def start(self):
        """Start the worker thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name=f"worker-{self.name}", daemon=True)
        self._thread.start()

    def stop(self):
        """Signal the worker to stop gracefully."""
        self._stop_event.set()

    def join(self, timeout: float = 10.0):
        """Wait for the worker thread to finish."""
        if self._thread:
            self._thread.join(timeout=timeout)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        """Main worker loop: connect -> scan regions -> repeat."""
        self.progress.register_worker(self.name)
        self.progress.push_log(f"Worker {self.name} started", "info")

        while not self._stop_event.is_set():
            try:
                # Connect
                self.progress.update_worker(self.name, status=WorkerStatus.CONNECTING)
                if not self._connect():
                    self.progress.update_worker(self.name, status=WorkerStatus.ERROR)
                    self.progress.push_log(f"Worker {self.name} connection failed, retrying in 5s", "error")
                    self._stop_event.wait(5.0)
                    continue

                self.progress.update_worker(self.name, status=WorkerStatus.SCANNING)

                # Scan regions until none left or stopped
                while not self._stop_event.is_set():
                    region = self.progress.get_next_region(self.name)
                    if not region:
                        self.progress.push_log(f"Worker {self.name}: no more regions to scan", "info")
                        break

                    self.progress.update_worker(self.name,
                                                current_region=region.key,
                                                status=WorkerStatus.SCANNING)
                    self.progress.push_log(
                        f"Worker {self.name} scanning region {region.key}", "info")

                    try:
                        self._scan_region(region)
                    except Exception as e:
                        self.progress.push_log(
                            f"Worker {self.name} error scanning {region.key}: {e}", "error")
                        self.progress.release_region(region.key, RegionStatus.PENDING, str(e))
                        self.progress.update_worker(self.name, errors=
                            self.progress._workers.get(self.name, None) and
                            self.progress._workers[self.name].errors + 1 or 1)
                        break  # Reconnect on error

                self._disconnect()

            except Exception as e:
                self.progress.push_log(f"Worker {self.name} fatal error: {e}", "error")
                self._disconnect()
                self._stop_event.wait(5.0)

        self.progress.update_worker(self.name, status=WorkerStatus.STOPPED)
        self.progress.push_log(f"Worker {self.name} stopped", "info")
        self._disconnect()

    def _connect(self) -> bool:
        """Connect to the L2 server."""
        try:
            self.game = full_connect_or_create(
                self.username, self.password,
                char_name=self.name,
                login_host=self.login_host,
                login_port=self.login_port,
            )
            if not self.game:
                return False

            self.game.start_packet_loop()
            time.sleep(0.5)
            self.progress.push_log(
                f"Worker {self.name} connected as {self.game.name} at "
                f"({self.game.x}, {self.game.y}, {self.game.z})", "info")
            return True
        except Exception as e:
            self.progress.push_log(f"Worker {self.name} connect error: {e}", "error")
            return False

    def _disconnect(self):
        """Disconnect from the server."""
        if self.game:
            try:
                self.game.close()
            except Exception:
                pass
            self.game = None

    def _drain_geodata_queue(self):
        """Drain any leftover messages from the geodata queue."""
        while True:
            try:
                self.game.geodata_queue.get_nowait()
            except queue.Empty:
                break

    def _scan_region(self, region: RegionState):
        """Scan all blocks in a region using admin_scan_geo commands.

        Sends one command per block-row (256 blocks), receives base64-encoded
        height+NSWE data. 256 commands per region = ~13s per region.
        """
        rx = region.region_x
        ry = region.region_y
        total_blocks = REGION_BLOCKS_X * REGION_BLOCKS_Y  # 65536

        # Clear any stale responses
        self._drain_geodata_queue()

        # Storage: indexed by (blockX, blockY)
        heights: dict[tuple[int, int], int] = {}
        nswe_data: dict[tuple[int, int], int] = {}

        start_time = time.time()

        for block_y in range(REGION_BLOCKS_Y):
            if self._stop_event.is_set():
                self.progress.release_region(region.key, RegionStatus.PENDING)
                return

            # Send scan command for this block row
            self.game.send_admin_command(f"scan_geo {rx} {ry} {block_y}")

            # Wait for response
            try:
                response = self.game.geodata_queue.get(timeout=10.0)
            except queue.Empty:
                raise RuntimeError(f"Timeout waiting for scan_geo response (blockY={block_y})")

            # Parse: GEODATA|regionX|regionY|blockY|<base64>
            parts = response.split("|")
            if len(parts) != 5 or parts[0] != "GEODATA":
                raise RuntimeError(f"Invalid scan response: {response[:100]}")

            resp_ry = int(parts[2])
            resp_by = int(parts[3])

            raw = base64.b64decode(parts[4])
            if len(raw) != 256 * 3:
                raise RuntimeError(f"Invalid data size: {len(raw)} (expected {256 * 3})")

            for bx in range(REGION_BLOCKS_X):
                offset = bx * 3
                height = struct.unpack_from("<h", raw, offset)[0]
                nswe = raw[offset + 2]
                heights[(bx, block_y)] = height
                nswe_data[(bx, block_y)] = nswe

            # Update progress
            scanned = (block_y + 1) * REGION_BLOCKS_X
            elapsed = time.time() - start_time
            rate = scanned / elapsed if elapsed > 0 else 0

            self.progress.update_worker(self.name,
                cells_scanned=scanned,
                cells_per_sec=rate,
                current_region=region.key,
            )

            # Push progress update every 16 rows
            if block_y % 16 == 0:
                self.progress._lock.acquire()
                try:
                    self.progress._push_event("progress_update", {
                        "region": region.key,
                        "scanned": scanned,
                        "total": total_blocks,
                        "rate": round(rate, 1),
                    })
                finally:
                    self.progress._lock.release()

        # Build GeoRegion from scanned block data
        geo_region = self._build_region(rx, ry, heights, nswe_data)
        output_path = self._get_output_path(rx, ry)
        write_l2d(geo_region, output_path)

        # Record block data to SQLite for persistence
        batch = []
        for (bx, by), h in heights.items():
            n = nswe_data.get((bx, by), 0xFF)
            batch.append((bx, by, h, n))
        self.progress.record_cells_batch(region.key, batch)

        # Mark complete
        self.progress.release_region(region.key, RegionStatus.COMPLETE)
        elapsed = time.time() - start_time
        self.progress.push_log(
            f"Region {region.key} complete ({elapsed:.1f}s) -> {output_path.name}", "info")

    def _build_region(self, region_x: int, region_y: int,
                      heights: dict, nswe_data: dict) -> GeoRegion:
        """Build a GeoRegion from scanned block data (height + NSWE per block)."""
        blocks = []

        for bx in range(REGION_BLOCKS_X):
            for by in range(REGION_BLOCKS_Y):
                h = heights.get((bx, by), 0)
                n = nswe_data.get((bx, by), 0xFF)
                # Block-level scan: create flat blocks with the scanned height
                blocks.append(BlockFlat(height=h))

        return GeoRegion(region_x=region_x, region_y=region_y, blocks=blocks)

    def _get_output_path(self, region_x: int, region_y: int) -> Path:
        """Get output file path for a scanned region."""
        if self.output_dir:
            output_dir = Path(self.output_dir)
        else:
            output_dir = (Path(__file__).resolve().parent.parent.parent
                          / "dist" / "game" / "data" / "geodata")
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / f"{region_x}_{region_y}.l2d"
