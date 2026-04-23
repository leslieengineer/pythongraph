"""
providers.py — Data source providers for QUAL Waveform Viewer
=============================================================
Three providers feed parsed frames into a queue.Queue:
  frame = {"t_s": float, "u": [u1, u2, u3]}  (all values in mV)

QualSerialProvider  — real UART (960000 baud, USART1/CLI)
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

_BINARY_SYNC = 0xA5
_BINARY_SYNC_BYTES = bytes([_BINARY_SYNC])
_BINARY_PACKET_SIZE = 10
_BINARY_PAYLOAD_SIZE = 8
_BINARY_SCALE_MV = 10.0
_BINARY_SAMPLES_PER_CYCLE = 156
_BINARY_FS_HZ = _BINARY_SAMPLES_PER_CYCLE * 50
_BINARY_SAMPLE_MASK = (1 << 18) - 1
_BINARY_SIGN_BIT = 1 << 17


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
    """Parse a saved waveform CSV row: t_s,U1_mV,U2_mV,U3_mV."""
    parts = [part.strip() for part in line.strip().split(",")]
    if len(parts) < 4:
        return None
    if parts[0] == "t_s":
        return None
    try:
        t_s = float(parts[0])
        u1 = float(parts[1])
        u2 = float(parts[2])
        u3 = float(parts[3])
    except ValueError:
        return None
    return {"t_s": t_s, "u": [u1, u2, u3]}


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


def _parse_binary_packet(packet: bytes, state: dict) -> Optional[dict]:
    if len(packet) != _BINARY_PACKET_SIZE or packet[0] != _BINARY_SYNC:
        return None
    if _binary_checksum(packet[1:1 + _BINARY_PAYLOAD_SIZE]) != packet[-1]:
        return None

    payload = int.from_bytes(packet[1:1 + _BINARY_PAYLOAD_SIZE], byteorder="little", signed=False)
    sample_pos = payload & 0xFF
    if sample_pos >= _BINARY_SAMPLES_PER_CYCLE:
        return None

    raw_u1 = (payload >> 8) & _BINARY_SAMPLE_MASK
    raw_u2 = (payload >> 26) & _BINARY_SAMPLE_MASK
    raw_u3 = (payload >> 44) & _BINARY_SAMPLE_MASK
    u1 = _decode_signed18(raw_u1) * _BINARY_SCALE_MV
    u2 = _decode_signed18(raw_u2) * _BINARY_SCALE_MV
    u3 = _decode_signed18(raw_u3) * _BINARY_SCALE_MV

    last_sample_pos = state.get("last_sample_pos")
    if last_sample_pos is None:
        state["last_sample_pos"] = sample_pos
        state["total_samples"] = 0
    else:
        delta = (sample_pos - last_sample_pos) % _BINARY_SAMPLES_PER_CYCLE
        if delta == 0:
            return None
        state["total_samples"] += delta
        state["last_sample_pos"] = sample_pos

    t_s = state["total_samples"] / _BINARY_FS_HZ
    return {"t_s": t_s, "u": [u1, u2, u3]}


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class _BaseProvider:
    def __init__(self, out_q: queue.Queue):
        self._q     = out_q
        self._mirror_q: Optional[queue.Queue] = None
        self._stop  = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.lines_rx  = 0
        self.frames_rx = 0
        self.loaded_frames = 0
        self.frames_dropped = 0
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
        binary_state = {"last_sample_pos": None, "total_samples": 0}
        mode: Optional[str] = None
        try:
            while not self._stop.is_set():
                chunk = ser.read(ser.in_waiting or 1)
                if not chunk:
                    continue
                buf += chunk
                while True:
                    if mode is None:
                        buf = buf.lstrip(b"\r\n\t ")
                        if not buf:
                            break
                        if buf.startswith(b"$Q,"):
                            mode = "ascii"
                            continue
                        if buf.startswith(_BINARY_SYNC_BYTES):
                            mode = "binary"
                            continue
                        ascii_idx = buf.find(b"$Q,")
                        binary_idx = buf.find(_BINARY_SYNC_BYTES)
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
                    if buf[0] != _BINARY_SYNC:
                        sync_idx = buf.find(_BINARY_SYNC_BYTES)
                        if sync_idx == -1:
                            buf = b""
                            mode = None
                            break
                        buf = buf[sync_idx:]
                        if len(buf) < _BINARY_PACKET_SIZE:
                            break

                    packet = buf[:_BINARY_PACKET_SIZE]
                    frame = _parse_binary_packet(packet, binary_state)
                    if frame is None:
                        buf = buf[1:]
                        continue

                    buf = buf[_BINARY_PACKET_SIZE:]
                    self.lines_rx += 1
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

    # QUAL sends 156 samples per power cycle (50 Hz → ~7800 samp/s)
    QUAL_FS = 156 * 50  # 7800 Hz

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
        period = 1.0 / fs          # ~128 µs between samples
        t      = 0.0
        t0_wall = time.monotonic()

        while not self._stop.is_set():
            # Burst 156 samples (one power cycle) then sleep until real-time catches up
            for _ in range(156):
                u1 = vpeak * math.sin(2 * math.pi * self._freq * t)
                u2 = vpeak * math.sin(2 * math.pi * self._freq * t - 2 * math.pi / 3)
                u3 = vpeak * math.sin(2 * math.pi * self._freq * t + 2 * math.pi / 3)
                self._push({"t_s": t, "u": [u1, u2, u3]})
                self.frames_rx += 1
                t += period

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
            t_file_offset = frame["t_s"] - t_file_start
            t_wall_target = t_wall_start + t_file_offset / self._speed
            wait = t_wall_target - time.monotonic()
            if wait > 0.001:
                time.sleep(wait)
            self.frames_rx += 1
            self._push(frame)
