"""
logger.py — Asynchronous CSV logger for QUAL Waveform Viewer
============================================================
QualDataLogger consumes frames from a queue.Queue and writes them
to a CSV file on a dedicated background thread so the GUI is never
blocked by disk I/O.
 
Frame format expected:
    {"t_s": float, "u": [p1, p2, p3]}
"""
from __future__ import annotations
 
import csv
import math
import queue
import threading
from pathlib import Path
from typing import Optional
 
_SENTINEL = object()
_CSV_HEADER = [
    "index", "fw_min", "fw_sec", "fw_ms",
    "P1_val", "P2_val", "P3_val",
    "rms_P1_val", "rms_P2_val", "rms_P3_val",
    "P12_val", "P23_val", "P31_val",
    "rms_P12_val", "rms_P23_val", "rms_P31_val",
]
 
 
def export_csv_snapshot(path: str, t_values, u_values,
                        fw_min_values=None, fw_sec_values=None, fw_ms_values=None):
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _fw_min = fw_min_values if fw_min_values is not None else []
    _fw_sec = fw_sec_values if fw_sec_values is not None else []
    _fw_ms  = fw_ms_values  if fw_ms_values  is not None else []
 
    p1v = [float(v) for v in u_values[0]]
    p2v = [float(v) for v in u_values[1]]
    p3v = [float(v) for v in u_values[2]]
    p12v = [a - b for a, b in zip(p1v, p2v)]
    p23v = [a - b for a, b in zip(p2v, p3v)]
    p31v = [a - b for a, b in zip(p3v, p1v)]
    n_rows = len(p1v)
 
    def _zc_rms_array(sig):
        out = [None] * len(sig)
        prev, sq_sum, n = None, 0.0, 0
        for i, val in enumerate(sig):
            if prev is not None:
                crossing = (
                    (prev != 0 and val == 0) or
                    (prev == 0 and val != 0) or
                    (prev > 0  and val <  0) or
                    (prev < 0  and val >  0)
                )
                if crossing:
                    if n >= 4:
                        out[i] = math.sqrt(sq_sum / n)
                    sq_sum, n = 0.0, 0
            if val != 0:
                sq_sum += val * val
                n      += 1
            prev = val
        return out
 
    rms_p1  = _zc_rms_array(p1v)
    rms_p2  = _zc_rms_array(p2v)
    rms_p3  = _zc_rms_array(p3v)
    rms_p12 = _zc_rms_array(p12v)
    rms_p23 = _zc_rms_array(p23v)
    rms_p31 = _zc_rms_array(p31v)
 
    def _f(v): return f"{v:.3f}" if v is not None else ""
 
    row_count = 0
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(_CSV_HEADER)
        for i in range(n_rows):
            t_s  = float(t_values[i])
            p1f, p2f, p3f = p1v[i], p2v[i], p3v[i]
            fw_min = int(_fw_min[i]) if i < len(_fw_min) else ""
            fw_sec = int(_fw_sec[i]) if i < len(_fw_sec) else ""
            fw_ms  = int(_fw_ms[i])  if i < len(_fw_ms)  else ""
            writer.writerow([
                f"{t_s:.0f}", fw_min, fw_sec, fw_ms,
                _f(p1f), _f(p2f), _f(p3f),
                _f(rms_p1[i]),  _f(rms_p2[i]),  _f(rms_p3[i]),
                _f(p12v[i]),    _f(p23v[i]),    _f(p31v[i]),
                _f(rms_p12[i]), _f(rms_p23[i]), _f(rms_p31[i]),
            ])
            row_count += 1
        fh.flush()
    return row_count
 
 
def prepare_csv_log(path: str, overwrite: bool = False):
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and csv_path.exists() and csv_path.stat().st_size > 0:
        return
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(_CSV_HEADER)
        fh.flush()
 
 
class QualDataLogger:
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
                            _rms("rms_P1_val"),  _rms("rms_P2_val"),  _rms("rms_P3_val"),
                            _f(item.get("P12_val")), _f(item.get("P23_val")), _f(item.get("P31_val")),
                            _rms("rms_P12_val"), _rms("rms_P23_val"), _rms("rms_P31_val"),
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