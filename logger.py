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
import math
import queue
import threading
from pathlib import Path
from typing import Optional
 
_SENTINEL = object()   # poison pill to stop the writer thread
_CSV_HEADER = [
    "index", "fw_min", "fw_sec", "fw_ms",
    "U1_mV", "U2_mV", "U3_mV",
    "rms_U1_mV", "rms_U2_mV", "rms_U3_mV",
    "U12_mV", "U23_mV", "U31_mV",
    "rms_U12_mV", "rms_U23_mV", "rms_U31_mV",
]
 
 
def export_csv_snapshot(path: str, t_values, u_values,
                        fw_min_values=None, fw_sec_values=None, fw_ms_values=None):
    """Write a complete CSV snapshot immediately and return the row count."""
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _fw_min = fw_min_values if fw_min_values is not None else []
    _fw_sec = fw_sec_values if fw_sec_values is not None else []
    _fw_ms  = fw_ms_values  if fw_ms_values  is not None else []
 
    # Pre-compute per-row zero-crossing RMS for all 6 signals.
    # Each accumulator tracks (prev, sq_sum, n); RMS is emitted on sign change.
    u1v = [float(v) for v in u_values[0]]
    u2v = [float(v) for v in u_values[1]]
    u3v = [float(v) for v in u_values[2]]
    u12v = [a - b for a, b in zip(u1v, u2v)]
    u23v = [a - b for a, b in zip(u2v, u3v)]
    u31v = [a - b for a, b in zip(u3v, u1v)]
    n_rows = len(u1v)
 
    def _zc_rms_array(sig):
        """Return array of RMS values aligned to zero-crossing rows.
        Zeros are never accumulated. Any sign transition triggers emit+reset.
        """
        out = [None] * len(sig)
        prev, sq_sum, n = None, 0.0, 0
        for i, val in enumerate(sig):
            if prev is not None:
                crossing = (
                    (prev != 0 and val == 0) or   # entering zero
                    (prev == 0 and val != 0) or   # leaving zero
                    (prev > 0  and val <  0) or   # pos -> neg
                    (prev < 0  and val >  0)      # neg -> pos
                )
                if crossing:
                    if n >= 4:
                        out[i] = math.sqrt(sq_sum / n)
                    sq_sum, n = 0.0, 0
            if val != 0:          # never accumulate zero samples
                sq_sum += val * val
                n      += 1
            prev = val
        return out
 
    rms_u1  = _zc_rms_array(u1v)
    rms_u2  = _zc_rms_array(u2v)
    rms_u3  = _zc_rms_array(u3v)
    rms_u12 = _zc_rms_array(u12v)
    rms_u23 = _zc_rms_array(u23v)
    rms_u31 = _zc_rms_array(u31v)
 
    def _f(v): return f"{v:.3f}" if v is not None else ""
 
    row_count = 0
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(_CSV_HEADER)
        for i in range(n_rows):
            t_s  = float(t_values[i])
            u1f, u2f, u3f = u1v[i], u2v[i], u3v[i]
            fw_min = int(_fw_min[i]) if i < len(_fw_min) else ""
            fw_sec = int(_fw_sec[i]) if i < len(_fw_sec) else ""
            fw_ms  = int(_fw_ms[i])  if i < len(_fw_ms)  else ""
            writer.writerow([
                f"{t_s:.0f}", fw_min, fw_sec, fw_ms,
                _f(u1f), _f(u2f), _f(u3f),
                _f(rms_u1[i]),  _f(rms_u2[i]),  _f(rms_u3[i]),
                _f(u12v[i]),    _f(u23v[i]),    _f(u31v[i]),
                _f(rms_u12[i]), _f(rms_u23[i]), _f(rms_u31[i]),
            ])
            row_count += 1
        fh.flush()
    return row_count
 
 
def prepare_csv_log(path: str, overwrite: bool = False):
    """Ensure the CSV path exists and contains the header row."""
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and csv_path.exists() and csv_path.stat().st_size > 0:
        return
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(_CSV_HEADER)
        fh.flush()
 
 
class QualDataLogger:
    """Thread-safe CSV logger."""
 
    def __init__(self, path: str, in_q: queue.Queue, truncate: bool = False):
        self._path  = Path(path)
        self._q     = in_q
        self._thread: Optional[threading.Thread] = None
        self.rows_written = 0
        self.error: Optional[str] = None
        self._flush_every = 256
        self._truncate = truncate
 
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
            file_has_rows = self._path.exists() and self._path.stat().st_size > 0
            file_mode = "w" if self._truncate else "a"
            with self._path.open(file_mode, newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                if self._truncate or not file_has_rows:
                    writer.writerow(_CSV_HEADER)
                    fh.flush()
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
                        t  = item["t_s"]
                        u  = item["u"]
                        fw_min = item.get("fw_min", "")
                        fw_sec = item.get("fw_sec", "")
                        fw_ms  = item.get("fw_ms",  "")
                        def _f(v):   return f"{v:.3f}" if v is not None else ""
                        def _rms(k): return _f(item.get(k))
                        writer.writerow([
                            f"{t:.0f}", fw_min, fw_sec, fw_ms,
                            _f(u[0]),   _f(u[1]),   _f(u[2]),
                            _rms("rms_U1_mV"),  _rms("rms_U2_mV"),  _rms("rms_U3_mV"),
                            _f(item.get("U12_mV")), _f(item.get("U23_mV")), _f(item.get("U31_mV")),
                            _rms("rms_U12_mV"), _rms("rms_U23_mV"), _rms("rms_U31_mV"),
                        ])
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