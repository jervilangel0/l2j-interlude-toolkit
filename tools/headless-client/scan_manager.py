"""
Scan Manager — Orchestrates N scan workers for parallel terrain scanning.

Discovers regions, manages worker lifecycle, exposes control API
for the dashboard.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import threading
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
from scan_state import ScanProgress, RegionStatus
from scan_worker import ScanWorker
from l2_client import full_connect_or_create

# Import geodata constants
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'geodata'))
from l2d_parser import REGION_CELLS_X, REGION_CELLS_Y

# All 139 known L2 Interlude geodata regions (region_x, region_y)
KNOWN_REGIONS = [
    (11, 10), (11, 11), (11, 12), (11, 13),
    (12, 10), (12, 11), (12, 12), (12, 13), (12, 14), (12, 15),
    (13, 10), (13, 11), (13, 12), (13, 13), (13, 14), (13, 15),
    (14, 10), (14, 11), (14, 12), (14, 13), (14, 14), (14, 15),
    (15, 10), (15, 11), (15, 12), (15, 13), (15, 14), (15, 15), (15, 16), (15, 17),
    (16, 10), (16, 11), (16, 12), (16, 13), (16, 14), (16, 15), (16, 16), (16, 17),
    (17, 10), (17, 11), (17, 12), (17, 13), (17, 14), (17, 15), (17, 16), (17, 17), (17, 18),
    (18, 10), (18, 11), (18, 12), (18, 13), (18, 14), (18, 15), (18, 16), (18, 17), (18, 18), (18, 19),
    (19, 10), (19, 11), (19, 12), (19, 13), (19, 14), (19, 15), (19, 16), (19, 17), (19, 18), (19, 19),
    (20, 10), (20, 11), (20, 12), (20, 13), (20, 14), (20, 15), (20, 16), (20, 17), (20, 18), (20, 19),
    (21, 10), (21, 11), (21, 12), (21, 13), (21, 14), (21, 15), (21, 16), (21, 17), (21, 18), (21, 19),
    (22, 10), (22, 11), (22, 12), (22, 13), (22, 14), (22, 15), (22, 16), (22, 17), (22, 18), (22, 19), (22, 20),
    (23, 10), (23, 11), (23, 12), (23, 13), (23, 14), (23, 15), (23, 16), (23, 17), (23, 18), (23, 19), (23, 20),
    (24, 10), (24, 11), (24, 12), (24, 13), (24, 14), (24, 15), (24, 16), (24, 17), (24, 18), (24, 19), (24, 20),
    (25, 10), (25, 11), (25, 12), (25, 13), (25, 14), (25, 15), (25, 16), (25, 17), (25, 18), (25, 19),
    (26, 10), (26, 11), (26, 12), (26, 13), (26, 14), (26, 15), (26, 16),
]


def _worker_name(prefix: str, index: int, total: int) -> str:
    """Generate worker name with appropriate digit padding."""
    width = 3 if total >= 100 else 2
    return f"{prefix}{index:0{width}d}"


class ScanManager:
    """Orchestrator that spawns and manages N scan workers."""

    def __init__(self, progress: ScanProgress,
                 login_host: str = "127.0.0.1", login_port: int = 2106,
                 output_dir: str = "",
                 account_prefix: str = "scanner",
                 password: str = "scanner",
                 db_name: str = "l2jmobiusc6",
                 db_user: str = "root"):
        self.progress = progress
        self.login_host = login_host
        self.login_port = login_port
        self.output_dir = output_dir
        self.account_prefix = account_prefix
        self.password = password
        self.db_name = db_name
        self.db_user = db_user

        self._workers: dict[str, ScanWorker] = {}
        self._running = False
        self._target_count = 0  # how many workers were requested

        # Bootstrap state
        self._bootstrap_running = False
        self._bootstrap_lock = threading.Lock()

    # ========================================================================
    # BOOTSTRAP — account creation + GM promotion from dashboard
    # ========================================================================

    def bootstrap(self, num: int, promote: bool = True) -> dict:
        """Create N accounts + characters and optionally promote to GM.
        Runs synchronously — call from a background thread.
        Returns {created, failed, promoted}.
        """
        with self._bootstrap_lock:
            if self._bootstrap_running:
                self.progress.push_log("Bootstrap already running", "warn")
                return {"created": 0, "failed": 0, "promoted": 0}
            self._bootstrap_running = True

        try:
            return self._do_bootstrap(num, promote)
        finally:
            with self._bootstrap_lock:
                self._bootstrap_running = False

    def _do_bootstrap(self, num: int, promote: bool) -> dict:
        names = [_worker_name(self.account_prefix, i + 1, num) for i in range(num)]
        created = 0
        failed = 0

        self.progress.push_log(
            f"Creating {num} accounts ({names[0]}..{names[-1]})", "info")

        for i, name in enumerate(names):
            try:
                self.progress.push_log(
                    f"Creating account {i+1}/{num}: {name}", "info")

                game = full_connect_or_create(
                    username=name,
                    password=self.password,
                    char_name=name,
                    class_id=0x00,
                    login_host=self.login_host,
                    login_port=self.login_port,
                )
                if game:
                    game.close()
                    created += 1
                else:
                    failed += 1
                    self.progress.push_log(f"Failed to create {name}", "error")
            except Exception as e:
                failed += 1
                import traceback
                tb = traceback.format_exc()
                self.progress.push_log(f"Error creating {name}: {e}", "error")
                print(f"[BOOTSTRAP] {name} failed:\n{tb}")

            # Delay between creations to avoid login server rate limits
            if i < num - 1:
                time.sleep(2.0)

            # Push progress
            self.progress._lock.acquire()
            try:
                self.progress._push_event("bootstrap_progress", {
                    "current": i + 1,
                    "total": num,
                    "created": created,
                    "failed": failed,
                    "phase": "creating",
                })
            finally:
                self.progress._lock.release()

        self.progress.push_log(
            f"Account creation done: {created} OK, {failed} failed", "info")

        promoted = 0
        if promote and created > 0:
            self.progress.push_log(f"Promoting {len(names)} characters to GM...", "info")
            promoted = self._promote_to_gm(names)
            self.progress.push_log(
                f"GM promotion: {promoted}/{len(names)} promoted", "info")

        self.progress._lock.acquire()
        try:
            self.progress._push_event("bootstrap_progress", {
                "current": num,
                "total": num,
                "created": created,
                "failed": failed,
                "promoted": promoted,
                "phase": "done",
            })
        finally:
            self.progress._lock.release()

        return {"created": created, "failed": failed, "promoted": promoted}

    def _promote_to_gm(self, names: list[str]) -> int:
        """Promote characters to GM via MariaDB CLI."""
        promoted = 0
        # Batch all names into one SQL for speed
        placeholders = ", ".join(f"'{n}'" for n in names)
        sql = f"UPDATE characters SET accesslevel = 1 WHERE char_name IN ({placeholders});"

        for cmd in ["mariadb", "mysql"]:
            try:
                result = subprocess.run(
                    [cmd, "-u", self.db_user, "-h", "127.0.0.1",
                     self.db_name, "-e", sql],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0:
                    promoted = len(names)
                    self.progress.push_log(
                        f"All {promoted} characters promoted to GM", "info")
                else:
                    self.progress.push_log(
                        f"GM promotion error: {result.stderr.strip()}", "error")
                return promoted
            except FileNotFoundError:
                continue
            except Exception as e:
                self.progress.push_log(f"GM promotion error: {e}", "error")
                return 0

        self.progress.push_log(
            "Neither 'mariadb' nor 'mysql' CLI found!", "error")
        return 0

    @property
    def bootstrap_running(self) -> bool:
        return self._bootstrap_running

    # ========================================================================
    # REGION DISCOVERY
    # ========================================================================

    def discover_regions(self, from_files: bool = True):
        """Register regions to scan."""
        if from_files:
            geodata_dir = Path(self.output_dir) if self.output_dir else (
                Path(__file__).resolve().parent.parent.parent
                / "dist" / "game" / "data" / "geodata"
            )
            regions = set()
            for f in geodata_dir.glob("*.l2d"):
                parts = f.stem.split("_")
                if len(parts) == 2:
                    try:
                        regions.add((int(parts[0]), int(parts[1])))
                    except ValueError:
                        pass

            if not regions:
                regions = set(KNOWN_REGIONS)

            for rx, ry in sorted(regions):
                step = self.progress.step
                total_cells = (REGION_CELLS_X // step) * (REGION_CELLS_Y // step)
                self.progress.add_region(rx, ry, total_cells)
        else:
            for rx, ry in KNOWN_REGIONS:
                step = self.progress.step
                total_cells = (REGION_CELLS_X // step) * (REGION_CELLS_Y // step)
                self.progress.add_region(rx, ry, total_cells)

        status = self.progress.get_status()
        self.progress.push_log(
            f"Discovered {status['total_regions']} regions "
            f"({status['complete_regions']} already complete)", "info")

    # ========================================================================
    # SCAN LIFECYCLE
    # ========================================================================

    def start(self, num_workers: int = 1, scan_mode: str = "block"):
        """Start scanning with N workers."""
        step = 8 if scan_mode == "block" else 1
        self.progress.set_scan_config(scan_mode, step)

        self.discover_regions()

        self._running = True
        self._target_count = num_workers
        self.progress.push_log(
            f"Starting {num_workers} workers (mode={scan_mode})", "info")

        # Stagger delay between worker startups to avoid overwhelming login server
        stagger = 2.0

        for i in range(num_workers):
            name = _worker_name(self.account_prefix, i + 1, num_workers)
            self.add_worker(name, stagger_delay=i * stagger)

    def stop(self):
        """Stop all workers gracefully."""
        self._running = False
        self.progress.push_log("Stopping all workers...", "warn")

        for worker in list(self._workers.values()):
            worker.stop()

        for worker in list(self._workers.values()):
            worker.join(timeout=10.0)

        self._workers.clear()
        self.progress.push_log("All workers stopped", "info")

    def add_worker(self, name: str = "", stagger_delay: float = 0.0):
        """Add and start a new worker."""
        if not name:
            idx = len(self._workers) + 1
            total = max(self._target_count, idx)
            name = _worker_name(self.account_prefix, idx, total)

        if name in self._workers:
            self.progress.push_log(f"Worker {name} already exists", "warn")
            return

        worker = ScanWorker(
            name=name,
            progress=self.progress,
            username=name,
            password=self.password,
            login_host=self.login_host,
            login_port=self.login_port,
            output_dir=self.output_dir,
        )
        self._workers[name] = worker
        self._target_count = max(self._target_count, len(self._workers))

        if stagger_delay > 0:
            def delayed_start():
                time.sleep(stagger_delay)
                if self._running:
                    worker.start()
            t = threading.Thread(target=delayed_start, daemon=True)
            t.start()
        else:
            worker.start()

    def remove_worker(self, name: str = ""):
        """Stop and remove a worker."""
        if not name:
            if self._workers:
                name = sorted(self._workers.keys())[-1]
            else:
                return

        worker = self._workers.pop(name, None)
        if worker:
            worker.stop()
            worker.join(timeout=5.0)
            self.progress.remove_worker(name)
            self.progress.push_log(f"Removed worker {name}", "info")

    def get_status(self) -> dict:
        """Get current scan status."""
        status = self.progress.get_status()
        status["running"] = self._running
        status["num_workers"] = len(self._workers)
        status["bootstrap_running"] = self._bootstrap_running
        return status
