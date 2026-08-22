"""
providers.py — Data source providers for QUAL Waveform Viewer
=============================================================
Three providers feed parsed frames into a queue.Queue:
    frame = {"t_s": float, "u": [u1, u2, u3]}  (all values in mV)
 
Binary current frames are accepted to keep sync with the live protocol, but the
viewer still forwards only voltage frames to the GUI/logger.
 
QualSerialProvider  — real UART (USART1/UART_SP for qual-mtr-test, baud selectable)
QualSimulationProvider — synthetic 3-phase sine generator
QualFileProvider    — replay a saved log file
list_serial_ports() — enumerate available COM ports
"""
from __future__ import annotations
 
import math
import queue
import re
import threading
import time
from pathlib import Path
from typing import Optional
 
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
 
def list_serial_ports() -> list[str]:
    """Return a list of available serial port names."""
    try:
        import serial.tools.list_ports
        return [p.device for p in serial.tools.list_ports.comports()]
    except Exception:
        return []
 
 
_LINE_RE = re.compile(
    r'^\$Q,(\d+),(\d+),([+-]?\d+(?:\.\d+)?),([+-]?\d+(?:\.\d+)?),([+-]?\d+(?:\.\d+)?)'
)
 
_BINARY_VOLTAGE_SYNC = 0xA5
_BINARY_CURRENT_SYNC = 0xA6
_BINARY_SYNC_VALUES = (_BINARY_VOLTAGE_SYNC, _BINARY_CURRENT_SYNC)
_BINARY_PACKET_SIZE = 13       # 1 sync + 3 timestamp + 8 data + 1 checksum
_BINARY_PAYLOAD_SIZE = 11      # bytes 1–11 (checksum covers these)
_BINARY_TS_SIZE = 3            # bytes 1–3: 24-bit timestamp
_BINARY_DATA_SIZE = 8          # bytes 4–11: sample_index + V1/V2/V3
_BINARY_VOLTAGE_SCALE_MV = 10.0
_BINARY_CURRENT_SCALE_MA = 1.0
_BINARY_SAMPLES_PER_CYCLE = 128
_BINARY_FS_HZ = _BINARY_SAMPLES_PER_CYCLE * 50
_BINARY_SAMPLE_MASK = (1 << 18) - 1
_BINARY_SIGN_BIT = 1 << 17
# Timestamp bit masks (24-bit little-endian)
_BINARY_TS_MS_MASK  = 0x3FF          # bits 9:0   → milliseconds 0–999
_BINARY_TS_SEC_SHIFT = 10            # bits 15:10 → seconds 0–59
_BINARY_TS_SEC_MASK  = 0x3F
_BINARY_TS_MIN_SHIFT = 16            # bits 21:16 → minutes 0–59
_BINARY_TS_MIN_MASK  = 0x3F
 
 
def _parse_line(line: str) -> Optional[dict]:
    """Parse a $Q CSV line.  Returns frame dict or None."""
    m = _LINE_RE.match(line.strip())
    if not m:
        return None
    sec  = int(m.group(1))
    ms   = int(m.group(2))
    u1   = float(m.group(3))
    u2   = float(m.group(4))
    u3   = float(m.group(5))
    t_s  = sec + ms / 1000.0
    return {"t_s": t_s, "u": [u1, u2, u3]}
 
 
def _parse_saved_csv_line(line: str) -> Optional[dict]:
    """Parse a saved waveform CSV row.
 
    Supports two formats:
      Legacy (4-col):  t_s, U1_mV, U2_mV, U3_mV
      Current (16-col): t_s, fw_min, fw_sec, fw_ms, U1_mV, U2_mV, U3_mV, ...
    """
    parts = [part.strip() for part in line.strip().split(",")]
    if not parts or parts[0] == "t_s" or parts[0] == "index":
        return None
    try:
        t_s = float(parts[0])
    except ValueError:
        return None
    if len(parts) >= 7:
        # Current format: fw_min at [1], fw_sec at [2], fw_ms at [3], U1-U3 at [4-6]
        try:
            fw_min = int(parts[1]) if parts[1] != "" else 0
            fw_sec = int(parts[2]) if parts[2] != "" else 0
            fw_ms  = int(parts[3]) if parts[3] != "" else 0
            u1 = float(parts[4])
            u2 = float(parts[5])
            u3 = float(parts[6])
        except ValueError:
            return None
        return {"t_s": t_s, "u": [u1, u2, u3],
                "fw_min": fw_min, "fw_sec": fw_sec, "fw_ms": fw_ms}
    if len(parts) >= 4:
        # Legacy format: U1-U3 at [1-3]
        try:
            u1 = float(parts[1])
            u2 = float(parts[2])
            u3 = float(parts[3])
        except ValueError:
            return None
        return {"t_s": t_s, "u": [u1, u2, u3]}
    return None
 
 
def _parse_playback_line(line: str) -> Optional[dict]:
    """Parse either legacy $Q lines or the app's saved CSV rows."""
    return _parse_line(line) or _parse_saved_csv_line(line)
 
 
def _binary_checksum(payload: bytes) -> int:
    checksum = 0
    for value in payload:
        checksum ^= value
    return checksum
 
 
def _decode_signed18(value: int) -> int:
    if value & _BINARY_SIGN_BIT:
        return value - (1 << 18)
    return value
 
 
def _find_binary_sync(buf: bytes) -> int:
    indices = []
    for sync_value in _BINARY_SYNC_VALUES:
        idx = buf.find(bytes([sync_value]))
        if idx != -1:
            indices.append(idx)
    return min(indices) if indices else -1
 
 
def _parse_binary_packet(packet: bytes, state: dict, counters: Optional[dict] = None) -> Optional[dict]:
    if len(packet) != _BINARY_PACKET_SIZE or packet[0] not in _BINARY_SYNC_VALUES:
        return None
    if _binary_checksum(packet[1:1 + _BINARY_PAYLOAD_SIZE]) != packet[-1]:
        if counters is not None:
            counters["checksum_errors"] = counters.get("checksum_errors", 0) + 1
        return None
 
    sync_value = packet[0]
 
    # --- Timestamp: bytes 1–3, 24-bit little-endian ---
    ts_raw = int.from_bytes(packet[1:4], byteorder="little", signed=False)
    ts_ms  = ts_raw & _BINARY_TS_MS_MASK
    ts_sec = (ts_raw >> _BINARY_TS_SEC_SHIFT) & _BINARY_TS_SEC_MASK
    ts_min = (ts_raw >> _BINARY_TS_MIN_SHIFT) & _BINARY_TS_MIN_MASK
 
    # --- ADC data: bytes 4–11, 64-bit little-endian ---
    payload = int.from_bytes(packet[4:4 + _BINARY_DATA_SIZE], byteorder="little", signed=False)
    sample_pos = payload & 0xFF
    if sample_pos >= _BINARY_SAMPLES_PER_CYCLE:
        return None
 
    raw_s1 = (payload >> 8) & _BINARY_SAMPLE_MASK
    raw_s2 = (payload >> 26) & _BINARY_SAMPLE_MASK
    raw_s3 = (payload >> 44) & _BINARY_SAMPLE_MASK
 
    if sync_value == _BINARY_VOLTAGE_SYNC:
        scale = _BINARY_VOLTAGE_SCALE_MV
        value_key = "u"
        last_sample_pos = state.get("last_voltage_sample_pos")
        if last_sample_pos is None:
            state["last_voltage_sample_pos"] = sample_pos
            state["total_voltage_samples"] = 0
        else:
            delta = (sample_pos - last_sample_pos) % _BINARY_SAMPLES_PER_CYCLE
            if delta == 0:
                return None
            state["total_voltage_samples"] += delta
            state["last_voltage_sample_pos"] = sample_pos
 
        t_s = float(state["total_voltage_samples"])
        state["last_voltage_t_s"] = t_s
    else:
        scale = _BINARY_CURRENT_SCALE_MA
        value_key = "i"
        t_s = float(state.get("last_voltage_t_s", 0.0))
 
    values = [
        _decode_signed18(raw_s1) * scale,
        _decode_signed18(raw_s2) * scale,
        _decode_signed18(raw_s3) * scale,
    ]
 
    frame: dict = {
        "t_s": t_s,
        value_key: values,
        "sample_index": sample_pos,
        "fw_min": ts_min,
        "fw_sec": ts_sec,
        "fw_ms":  ts_ms,
    }
 
    # --- Zero-crossing RMS (voltage path only) ---
    # Each of 6 signals has its own accumulator.
    # When sign changes (prev * curr < 0), the signal just crossed zero.
    # At that point compute RMS over samples accumulated since last crossing,
    # inject into frame, then reset the accumulator.
    if sync_value == _BINARY_VOLTAGE_SYNC:
        u1, u2, u3 = values
        u12 = u1 - u2
        u23 = u2 - u3
        u31 = u3 - u1
 
        # Instantaneous compound voltages always present in voltage frames
        frame["U12_mV"] = u12
        frame["U23_mV"] = u23
        frame["U31_mV"] = u31
 
        sigs = {
            "U1":  u1,  "U2":  u2,  "U3":  u3,
            "U12": u12, "U23": u23, "U31": u31,
        }
        zc: dict = state.setdefault("_zc", {})
        for name, val in sigs.items():
            acc  = zc.setdefault(name, {"prev": None, "sq_sum": 0.0, "n": 0})
            prev = acc["prev"]
            if prev is not None:
                crossing = (
                    (prev != 0 and val == 0) or   # entering zero
                    (prev == 0 and val != 0) or   # leaving zero
                    (prev > 0  and val <  0) or   # pos -> neg
                    (prev < 0  and val >  0)      # neg -> pos
                )
                if crossing:
                    if acc["n"] >= 4:
                        frame[f"rms_{name}_mV"] = math.sqrt(acc["sq_sum"] / acc["n"])
                    acc["sq_sum"] = 0.0
                    acc["n"]      = 0
            if val != 0:          # never accumulate zero samples
                acc["sq_sum"] += val * val
                acc["n"]      += 1
            acc["prev"] = val
 
    return frame
 
 
# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------
 
class _BaseProvider:
    def __init__(self, out_q: queue.Queue):
        self._q     = out_q
        self._mirror_q: Optional[queue.Queue] = None
        self._stop  = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.bytes_rx = 0
        self.lines_rx  = 0
        self.frames_rx = 0
        self.loaded_frames = 0
        self.frames_dropped = 0
        self.checksum_errors = 0
        self.raw_sniff: str = ""   # hex of first 8 bytes received
        self.error: Optional[str] = None
 
    def set_mirror_queue(self, mirror_q: Optional[queue.Queue]):
        self._mirror_q = mirror_q
 
    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
 
    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
 
    def _push(self, frame: dict):
        if self._mirror_q is not None:
            self._mirror_q.put_nowait(frame)
        try:
            self._q.put_nowait(frame)
        except queue.Full:
            try:
                self._q.get_nowait()
            except queue.Empty:
                self.frames_dropped += 1
                return
            try:
                self._q.put_nowait(frame)
                self.frames_dropped += 1
            except queue.Full:
                self.frames_dropped += 1
 
    def _run(self):
        raise NotImplementedError
 
 
# ---------------------------------------------------------------------------
# Serial provider
# ---------------------------------------------------------------------------
 
class QualSerialProvider(_BaseProvider):
    def __init__(self, port: str, baud: int, out_q: queue.Queue):
        super().__init__(out_q)
        self._port = port
        self._baud = baud
 
    def _run(self):
        try:
            import serial
        except ImportError:
            self.error = "pyserial not installed"
            return
        try:
            ser = serial.Serial(self._port, self._baud, timeout=0.1)
        except Exception as exc:
            self.error = str(exc)
            return
        buf = b""
        binary_state = {
            "last_voltage_sample_pos": None,
            "total_voltage_samples": 0,
            "last_voltage_t_s": 0.0,
        }
        parse_counters: dict = {}
        sniff_buf = bytearray()
        mode: Optional[str] = None
        try:
            while not self._stop.is_set():
                chunk = ser.read(ser.in_waiting or 1)
                if not chunk:
                    continue
                self.bytes_rx += len(chunk)
                if len(sniff_buf) < 8:
                    sniff_buf.extend(chunk)
                    self.raw_sniff = sniff_buf[:8].hex(" ")
                self.checksum_errors = parse_counters.get("checksum_errors", 0)
                buf += chunk
                while True:
                    if mode is None:
                        buf = buf.lstrip(b"\r\n\t ")
                        if not buf:
                            break
                        if buf.startswith(b"$Q,"):
                            mode = "ascii"
                            continue
                        if buf[0] in _BINARY_SYNC_VALUES:
                            mode = "binary"
                            continue
                        ascii_idx = buf.find(b"$Q,")
                        binary_idx = _find_binary_sync(buf)
                        candidates = [idx for idx in (ascii_idx, binary_idx) if idx != -1]
                        if not candidates:
                            buf = b""
                            break
                        buf = buf[min(candidates):]
                        continue
 
                    if mode == "ascii":
                        if b"\n" not in buf:
                            break
                        line, buf = buf.split(b"\n", 1)
                        try:
                            text = line.decode("ascii", errors="ignore")
                        except Exception:
                            continue
                        self.lines_rx += 1
                        frame = _parse_line(text)
                        if frame:
                            self.frames_rx += 1
                            self._push(frame)
                            continue
                        mode = None
                        continue
 
                    if len(buf) < _BINARY_PACKET_SIZE:
                        break
                    if buf[0] not in _BINARY_SYNC_VALUES:
                        sync_idx = _find_binary_sync(buf)
                        if sync_idx == -1:
                            buf = b""
                            mode = None
                            break
                        buf = buf[sync_idx:]
                        if len(buf) < _BINARY_PACKET_SIZE:
                            break
 
                    packet = buf[:_BINARY_PACKET_SIZE]
                    frame = _parse_binary_packet(packet, binary_state, parse_counters)
                    if frame is None:
                        buf = buf[1:]
                        continue
 
                    buf = buf[_BINARY_PACKET_SIZE:]
                    self.lines_rx += 1
                    if "u" in frame:
                        self.frames_rx += 1
                        self._push(frame)
        except Exception as exc:
            self.error = str(exc)
        finally:
            try:
                ser.close()
            except Exception:
                pass
 
 
# ---------------------------------------------------------------------------
# Simulation provider
# ---------------------------------------------------------------------------
 
class QualSimulationProvider(_BaseProvider):
    """Generates synthetic 3-phase sinusoidal data at QUAL protocol rate."""
 
    # QUAL sends 128 samples per power cycle (50 Hz -> 6400 samp/s)
    QUAL_FS = 128 * 50  # 6400 Hz
 
    def __init__(
        self,
        out_q: queue.Queue,
        freq_hz: float = 50.0,
        v_rms_mv: float = 230_000.0,
        i_rms_ma: float = 10_000.0,   # kept for API compat; not used
        phi_deg: float = 0.0,
    ):
        super().__init__(out_q)
        self._freq    = freq_hz
        self._v_rms   = v_rms_mv
        self._phi_rad = math.radians(phi_deg)
 
    def _run(self):
        vpeak  = self._v_rms * math.sqrt(2)
        fs     = self.QUAL_FS
        period = 1.0 / fs          # 156.25 us between samples
        t      = 0.0
        sample_idx = 0             # Thêm biến đếm index
        t0_wall = time.monotonic()
 
        while not self._stop.is_set():
            # Burst 128 samples (one power cycle) then sleep until real-time catches up
            for _ in range(128):
                u1 = vpeak * math.sin(2 * math.pi * self._freq * t)
                u2 = vpeak * math.sin(2 * math.pi * self._freq * t - 2 * math.pi / 3)
                u3 = vpeak * math.sin(2 * math.pi * self._freq * t + 2 * math.pi / 3)
                
                # Truyền sample_idx vào key "t_s" thay vì truyền t
                self._push({"t_s": float(sample_idx), "u": [u1, u2, u3]})
                
                self.frames_rx += 1
                t += period
                sample_idx += 1    # Tăng index sau mỗi mẫu được sinh ra
 
            # Pace to real-time: sleep until wall-clock matches simulated time
            elapsed_wall = time.monotonic() - t0_wall
            sleep_s = t - elapsed_wall
            if sleep_s > 0.0005:
                time.sleep(sleep_s - 0.0003)   # wake slightly early
 
 
# ---------------------------------------------------------------------------
# File / playback provider
# ---------------------------------------------------------------------------
 
class QualFileProvider(_BaseProvider):
    """Replays a saved QUAL log file, honouring the embedded timestamps."""
 
    def __init__(self, path: str, out_q: queue.Queue, speed: float = 1.0):
        super().__init__(out_q)
        self._path  = Path(path)
        self._speed = max(0.01, speed)
 
    def _run(self):
        try:
            lines = self._path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception as exc:
            self.error = str(exc)
            return
 
        # Pre-parse all valid frames
        frames: list[dict] = []
        for raw in lines:
            self.lines_rx += 1
            f = _parse_playback_line(raw)
            if f:
                frames.append(f)
 
        self.loaded_frames = len(frames)
 
        if not frames:
            self.error = "No valid playback frames found in file"
            return
 
        t_file_start = frames[0]["t_s"]
        t_wall_start = time.monotonic()
 
        for frame in frames:
            if self._stop.is_set():
                break
            # Compute how long to wait (scaled by speed)
            t_file_offset = (frame["t_s"] - t_file_start) / (128 * 50.0) # Convert index back to seconds
            t_wall_target = t_wall_start + t_file_offset / self._speed
            wait = t_wall_target - time.monotonic()
            if wait > 0.001:
                time.sleep(wait)
            self.frames_rx += 1
            self._push(frame)