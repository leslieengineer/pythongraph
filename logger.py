"""
logger.py — Asynchronous CSV logger for QUAL Waveform Viewer
============================================================
QualDataLogger consumes frames from a queue.Queue and writes them
to a CSV file on a dedicated background thread so the GUI is never
blocked by disk I/O.

Frame format expected:
    {"t_s": float, "u": [u1, u2, u3]}
"""
from __future__ import annotations

import csv
import queue
import threading
from pathlib import Path
from typing import Optional

_SENTINEL = object()   # poison pill to stop the writer thread


class QualDataLogger:
    """Thread-safe CSV logger.

    Usage::

        log_q = queue.Queue(maxsize=...)
        logger = QualDataLogger("output.csv", log_q)
        logger.start()
        # ... push frames into log_q ...
        logger.stop()   # flushes remaining frames and closes file
    """

    def __init__(self, path: str, in_q: queue.Queue):
        self._path  = Path(path)
        self._q     = in_q
        self._thread: Optional[threading.Thread] = None
        self.rows_written = 0
        self.error: Optional[str] = None
        self._flush_every = 256

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="QualLogger")
        self._thread.start()

    def stop(self):
        """Signal the writer to flush and exit, then wait for it."""
        while True:
            try:
                self._q.put(_SENTINEL, timeout=0.5)
                break
            except queue.Full:
                continue
        if self._thread:
            self._thread.join(timeout=10.0)
            self._thread = None

    def _run(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["t_s", "U1_mV", "U2_mV", "U3_mV"])
                pending_since_flush = 0
                while True:
                    try:
                        item = self._q.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    if item is _SENTINEL:
                        fh.flush()
                        break
                    try:
                        t = item["t_s"]
                        u = item["u"]
                        writer.writerow([f"{t:.6f}", f"{u[0]:.3f}", f"{u[1]:.3f}", f"{u[2]:.3f}"])
                        self.rows_written += 1
                        pending_since_flush += 1
                        if pending_since_flush >= self._flush_every:
                            fh.flush()
                            pending_since_flush = 0
                    except Exception as exc:
                        self.error = str(exc)
                        fh.flush()
                        break
        except Exception as exc:
            self.error = str(exc)
