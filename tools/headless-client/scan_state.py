"""
Thread-safe scan progress tracking with SQLite persistence and SSE events.

Central state store for the multi-agent terrain scanner. Protected by
threading.Lock() for safe access from N worker threads + dashboard.
"""
from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional


class RegionStatus(str, Enum):
    PENDING = "pending"
    SCANNING = "scanning"
    COMPLETE = "complete"
    ERROR = "error"


class WorkerStatus(str, Enum):
    IDLE = "idle"
    CONNECTING = "connecting"
    SCANNING = "scanning"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class RegionState:
    region_x: int
    region_y: int
    status: RegionStatus = RegionStatus.PENDING
    total_cells: int = 0
    scanned_cells: int = 0
    assigned_worker: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    error: str = ""

    @property
    def key(self) -> str:
        return f"{self.region_x}_{self.region_y}"

    @property
    def progress(self) -> float:
        if self.total_cells == 0:
            return 0.0
        return self.scanned_cells / self.total_cells


@dataclass
class WorkerState:
    name: str
    status: WorkerStatus = WorkerStatus.IDLE
    current_region: str = ""
    x: int = 0
    y: int = 0
    z: int = 0
    cells_scanned: int = 0
    cells_per_sec: float = 0.0
    errors: int = 0
    started_at: float = 0.0
    last_update: float = 0.0


class ScanProgress:
    """Central thread-safe state store with SQLite persistence and SSE events."""

    def __init__(self, db_path: str = "scan_progress.db"):
        self._lock = threading.Lock()
        self._regions: dict[str, RegionState] = {}
        self._workers: dict[str, WorkerState] = {}
        self._sse_subscribers: list[queue.Queue] = []
        self._event_log: list[dict] = []
        self._db_path = db_path
        self._started_at = 0.0
        self._scan_mode = "block"  # "block" or "cell"
        self._step = 8

        # Initialize SQLite
        self._init_db()
        self._load_from_db()

    def _init_db(self):
        """Create SQLite tables if they don't exist."""
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS regions (
                key TEXT PRIMARY KEY,
                region_x INTEGER,
                region_y INTEGER,
                status TEXT,
                total_cells INTEGER,
                scanned_cells INTEGER,
                assigned_worker TEXT,
                started_at REAL,
                completed_at REAL,
                error TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scan_cells (
                region_key TEXT,
                cell_x INTEGER,
                cell_y INTEGER,
                height INTEGER,
                nswe INTEGER,
                PRIMARY KEY (region_key, cell_x, cell_y)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scan_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.commit()
        conn.close()

    def _load_from_db(self):
        """Load previous progress from SQLite."""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.execute("SELECT * FROM regions")
        for row in cursor:
            key, rx, ry, status, total, scanned, worker, started, completed, error = row
            self._regions[key] = RegionState(
                region_x=rx, region_y=ry,
                status=RegionStatus(status),
                total_cells=total,
                scanned_cells=scanned,
                assigned_worker=worker,
                started_at=started,
                completed_at=completed,
                error=error or "",
            )

        # Load scan mode
        cursor = conn.execute("SELECT value FROM scan_meta WHERE key='scan_mode'")
        row = cursor.fetchone()
        if row:
            self._scan_mode = row[0]

        cursor = conn.execute("SELECT value FROM scan_meta WHERE key='step'")
        row = cursor.fetchone()
        if row:
            self._step = int(row[0])

        conn.close()

        loaded = len(self._regions)
        complete = sum(1 for r in self._regions.values() if r.status == RegionStatus.COMPLETE)
        if loaded:
            print(f"[STATE] Loaded {loaded} regions from DB ({complete} complete)")

    def set_scan_config(self, scan_mode: str, step: int):
        """Set scan mode and persist."""
        with self._lock:
            self._scan_mode = scan_mode
            self._step = step
            conn = sqlite3.connect(self._db_path)
            conn.execute("INSERT OR REPLACE INTO scan_meta (key, value) VALUES ('scan_mode', ?)", (scan_mode,))
            conn.execute("INSERT OR REPLACE INTO scan_meta (key, value) VALUES ('step', ?)", (str(step),))
            conn.commit()
            conn.close()

    @property
    def scan_mode(self) -> str:
        return self._scan_mode

    @property
    def step(self) -> int:
        return self._step

    # ========================================================================
    # REGION MANAGEMENT
    # ========================================================================

    def add_region(self, region_x: int, region_y: int, total_cells: int):
        """Register a region for scanning (if not already tracked)."""
        key = f"{region_x}_{region_y}"
        with self._lock:
            if key in self._regions:
                return  # Already tracked
            state = RegionState(
                region_x=region_x,
                region_y=region_y,
                total_cells=total_cells,
            )
            self._regions[key] = state
            self._persist_region(state)

    def get_next_region(self, worker_name: str) -> Optional[RegionState]:
        """Atomically claim the next PENDING region for a worker."""
        with self._lock:
            for key in sorted(self._regions.keys()):
                region = self._regions[key]
                if region.status == RegionStatus.PENDING:
                    region.status = RegionStatus.SCANNING
                    region.assigned_worker = worker_name
                    region.started_at = time.time()
                    self._persist_region(region)
                    self._push_event("region_update", {
                        "region": key,
                        "status": region.status.value,
                        "worker": worker_name,
                    })
                    return region
            return None

    def release_region(self, region_key: str, status: RegionStatus = RegionStatus.PENDING,
                       error: str = ""):
        """Release a region (back to pending on error, or mark complete)."""
        with self._lock:
            region = self._regions.get(region_key)
            if not region:
                return
            region.status = status
            region.error = error
            if status == RegionStatus.COMPLETE:
                region.completed_at = time.time()
            elif status == RegionStatus.PENDING:
                region.assigned_worker = ""
                region.started_at = 0.0
            self._persist_region(region)
            self._push_event("region_update", {
                "region": region_key,
                "status": status.value,
                "error": error,
            })

    def record_cell(self, region_key: str, cell_x: int, cell_y: int,
                    height: int, nswe: int):
        """Record a scanned cell and update progress."""
        with self._lock:
            region = self._regions.get(region_key)
            if region:
                region.scanned_cells += 1

            # Batch persist cells (write every time for correctness)
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "INSERT OR REPLACE INTO scan_cells (region_key, cell_x, cell_y, height, nswe) "
                "VALUES (?, ?, ?, ?, ?)",
                (region_key, cell_x, cell_y, height, nswe)
            )
            if region:
                conn.execute(
                    "UPDATE regions SET scanned_cells = ? WHERE key = ?",
                    (region.scanned_cells, region_key)
                )
            conn.commit()
            conn.close()

    def record_cells_batch(self, region_key: str,
                           cells: list[tuple[int, int, int, int]]):
        """Record multiple cells at once. Each tuple: (cell_x, cell_y, height, nswe)."""
        with self._lock:
            region = self._regions.get(region_key)
            if region:
                region.scanned_cells += len(cells)

            conn = sqlite3.connect(self._db_path)
            conn.executemany(
                "INSERT OR REPLACE INTO scan_cells (region_key, cell_x, cell_y, height, nswe) "
                "VALUES (?, ?, ?, ?, ?)",
                [(region_key, cx, cy, h, n) for cx, cy, h, n in cells]
            )
            if region:
                conn.execute(
                    "UPDATE regions SET scanned_cells = ? WHERE key = ?",
                    (region.scanned_cells, region_key)
                )
            conn.commit()
            conn.close()

    def get_scanned_cells(self, region_key: str) -> dict[tuple[int, int], tuple[int, int]]:
        """Load previously scanned cells for a region. Returns {(cx,cy): (height, nswe)}."""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.execute(
            "SELECT cell_x, cell_y, height, nswe FROM scan_cells WHERE region_key = ?",
            (region_key,)
        )
        result = {}
        for cx, cy, h, n in cursor:
            result[(cx, cy)] = (h, n)
        conn.close()
        return result

    # ========================================================================
    # WORKER MANAGEMENT
    # ========================================================================

    def register_worker(self, name: str):
        """Register a new worker."""
        with self._lock:
            self._workers[name] = WorkerState(name=name, started_at=time.time())
            self._push_event("worker_update", {
                "worker": name, "status": "idle",
            })

    def update_worker(self, name: str, **kwargs):
        """Update worker state fields."""
        with self._lock:
            worker = self._workers.get(name)
            if not worker:
                return
            for k, v in kwargs.items():
                if hasattr(worker, k):
                    setattr(worker, k, v)
            worker.last_update = time.time()
            self._push_event("worker_update", {
                "worker": name,
                **{k: v.value if isinstance(v, Enum) else v for k, v in kwargs.items()},
            })

    def remove_worker(self, name: str):
        """Remove a worker from tracking."""
        with self._lock:
            self._workers.pop(name, None)
            self._push_event("worker_update", {
                "worker": name, "status": "removed",
            })

    # ========================================================================
    # STATUS / SNAPSHOT
    # ========================================================================

    def get_status(self) -> dict:
        """Get full status snapshot for the dashboard."""
        with self._lock:
            total_cells = sum(r.total_cells for r in self._regions.values())
            scanned_cells = sum(r.scanned_cells for r in self._regions.values())
            total_regions = len(self._regions)
            complete_regions = sum(1 for r in self._regions.values()
                                  if r.status == RegionStatus.COMPLETE)
            scanning_regions = sum(1 for r in self._regions.values()
                                   if r.status == RegionStatus.SCANNING)
            error_regions = sum(1 for r in self._regions.values()
                                if r.status == RegionStatus.ERROR)

            # Speed calculation
            total_speed = sum(w.cells_per_sec for w in self._workers.values()
                              if w.status == WorkerStatus.SCANNING)
            eta_seconds = 0
            if total_speed > 0 and scanned_cells < total_cells:
                eta_seconds = (total_cells - scanned_cells) / total_speed

            return {
                "total_cells": total_cells,
                "scanned_cells": scanned_cells,
                "progress": scanned_cells / total_cells if total_cells else 0,
                "total_regions": total_regions,
                "complete_regions": complete_regions,
                "scanning_regions": scanning_regions,
                "error_regions": error_regions,
                "pending_regions": total_regions - complete_regions - scanning_regions - error_regions,
                "total_speed": round(total_speed, 1),
                "eta_seconds": round(eta_seconds),
                "scan_mode": self._scan_mode,
                "step": self._step,
                "regions": {
                    k: {
                        "region_x": r.region_x,
                        "region_y": r.region_y,
                        "status": r.status.value,
                        "total_cells": r.total_cells,
                        "scanned_cells": r.scanned_cells,
                        "progress": round(r.progress, 4),
                        "worker": r.assigned_worker,
                    }
                    for k, r in self._regions.items()
                },
                "workers": {
                    k: {
                        "name": w.name,
                        "status": w.status.value,
                        "current_region": w.current_region,
                        "x": w.x, "y": w.y, "z": w.z,
                        "cells_scanned": w.cells_scanned,
                        "cells_per_sec": round(w.cells_per_sec, 1),
                        "errors": w.errors,
                    }
                    for k, w in self._workers.items()
                },
            }

    # ========================================================================
    # SSE EVENTS
    # ========================================================================

    def subscribe_sse(self) -> queue.Queue:
        """Subscribe to SSE events. Returns a queue that receives event dicts."""
        q: queue.Queue = queue.Queue(maxsize=256)
        with self._lock:
            self._sse_subscribers.append(q)
        return q

    def unsubscribe_sse(self, q: queue.Queue):
        """Remove an SSE subscriber."""
        with self._lock:
            try:
                self._sse_subscribers.remove(q)
            except ValueError:
                pass

    def _push_event(self, event_type: str, data: dict):
        """Push an event to all SSE subscribers. Must be called under lock."""
        event = {
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
        }
        self._event_log.append(event)
        # Keep last 500 events
        if len(self._event_log) > 500:
            self._event_log = self._event_log[-500:]

        dead = []
        for q in self._sse_subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                dead.append(q)
        for q in dead:
            try:
                self._sse_subscribers.remove(q)
            except ValueError:
                pass

    def push_log(self, message: str, level: str = "info"):
        """Push a log event to SSE subscribers."""
        with self._lock:
            self._push_event("log", {"message": message, "level": level})

    # ========================================================================
    # PERSISTENCE
    # ========================================================================

    def _persist_region(self, region: RegionState):
        """Write region state to SQLite. Must be called under lock."""
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            INSERT OR REPLACE INTO regions
            (key, region_x, region_y, status, total_cells, scanned_cells,
             assigned_worker, started_at, completed_at, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            region.key, region.region_x, region.region_y,
            region.status.value, region.total_cells, region.scanned_cells,
            region.assigned_worker, region.started_at, region.completed_at,
            region.error,
        ))
        conn.commit()
        conn.close()

    def reset(self):
        """Reset all progress (for fresh start)."""
        with self._lock:
            self._regions.clear()
            self._workers.clear()
            conn = sqlite3.connect(self._db_path)
            conn.execute("DELETE FROM regions")
            conn.execute("DELETE FROM scan_cells")
            conn.execute("DELETE FROM scan_meta")
            conn.commit()
            conn.close()
            self._push_event("log", {"message": "Progress reset", "level": "warn"})
