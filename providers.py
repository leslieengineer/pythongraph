"""
providers.py — Data source providers for QUAL Waveform Viewer
=============================================================
"""
from __future__ import annotations
 
import math
import queue
import re
import threading
import time
from pathlib import Path
from typing import Optional
 
def list_serial_ports() -> list[str]:
    try:
        import serial.tools.list_ports
        return [p.device for p in serial.tools.list_ports.comports()]
    except Exception:
        return []
 
_LINE_RE = re.compile(
    r'^\$Q,(\d+),(\d+),([+-]?\d+(?:\.\d+)?),([+-]?\d+(?:\.\d+)?),([+-]?\d+(?:\.\d+)?)'
)
 
_BINARY_SYNC         = 0xA5
_BINARY_PACKET_SIZE  = 13
_BINARY_SAMPLE_MASK  = (1 << 18) - 1
_BINARY_SIGN_BIT     = 1 << 17
 
_BINARY_TS_MS_MASK   = 0x3FF
_BINARY_TS_SEC_SHIFT = 10
_BINARY_TS_SEC_MASK  = 0x3F
_BINARY_TS_MIN_SHIFT = 16
_BINARY_TS_MIN_MASK  = 0x3F
 
 
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
    return buf.find(bytes([_BINARY_SYNC]))
 
 
def _enrich_frame(frame: dict, state: dict) -> dict:
    u1, u2, u3 = frame["u"]
    frame["P12_val"] = u1 - u2
    frame["P23_val"] = u2 - u3
    frame["P31_val"] = u3 - u1
 
    sigs = {
        "P1": u1, "P2": u2, "P3": u3,
        "P12": frame["P12_val"], "P23": frame["P23_val"], "P31": frame["P31_val"],
    }
    zc: dict = state.setdefault("_zc", {})
    for name, val in sigs.items():
        acc = zc.setdefault(name, {"prev": None, "sq_sum": 0.0, "n": 0})
        prev = acc["prev"]
        if prev is not None:
            crossing = (
                (prev != 0 and val == 0) or
                (prev == 0 and val != 0) or
                (prev > 0  and val <  0) or
                (prev < 0  and val >  0)
            )
            if crossing:
                if acc["n"] >= 4:
                    frame[f"rms_{name}_val"] = math.sqrt(acc["sq_sum"] / acc["n"])
                acc["sq_sum"] = 0.0
                acc["n"]      = 0
        if val != 0:
            acc["sq_sum"] += val * val
            acc["n"]      += 1
        acc["prev"] = val
    return frame
 
 
def _parse_line(line: str) -> Optional[dict]:
    m = _LINE_RE.match(line.strip())
    if not m:
        return None
    sec = int(m.group(1))
    ms  = int(m.group(2))
    u1  = float(m.group(3))
    u2  = float(m.group(4))
    u3  = float(m.group(5))
    return {"t_s": sec + ms / 1000.0, "u": [u1, u2, u3]}
 
 
def _parse_saved_csv_line(line: str) -> Optional[dict]:
    parts = [part.strip() for part in line.strip().split(",")]
    if not parts or parts[0] == "t_s" or parts[0] == "index":
        return None
    try:
        t_s = float(parts[0])
    except ValueError:
        return None
    if len(parts) >= 7:
        try:
            fw_min = int(parts[1]) if parts[1] != "" else 0
            fw_sec = int(parts[2]) if parts[2] != "" else 0
            fw_ms  = int(parts[3]) if parts[3] != "" else 0
            u1 = float(parts[4])
            u2 = float(parts[5])
            u3 = float(parts[6])
            return {"t_s": t_s, "u": [u1, u2, u3], "fw_min": fw_min, "fw_sec": fw_sec, "fw_ms": fw_ms}
        except ValueError:
            pass
    if len(parts) >= 4:
        try:
            return {"t_s": t_s, "u": [float(parts[1]), float(parts[2]), float(parts[3])]}
        except ValueError:
            pass
    return None
 
 
def _parse_binary_packet(packet: bytes, state: dict, config: dict, counters: Optional[dict] = None) -> Optional[dict]:
    if len(packet) != _BINARY_PACKET_SIZE or packet[0] != _BINARY_SYNC:
        return None
        
    if _binary_checksum(packet[1:12]) != packet[-1]:
        if counters is not None:
            counters["checksum_errors"] = counters.get("checksum_errors", 0) + 1
        return None
 
    adc_scale = config.get("adc_scale", 1.0)
 
    ts_raw = int.from_bytes(packet[1:4], byteorder="little", signed=False)
    ts_ms  = ts_raw & _BINARY_TS_MS_MASK
    ts_sec = (ts_raw >> _BINARY_TS_SEC_SHIFT) & _BINARY_TS_SEC_MASK
    ts_min = (ts_raw >> _BINARY_TS_MIN_SHIFT) & _BINARY_TS_MIN_MASK
 
    payload = int.from_bytes(packet[4:12], byteorder="little", signed=False)
    
    sample_pos = payload & 0xFF                     
    raw_s1 = (payload >> 8)  & _BINARY_SAMPLE_MASK  
    raw_s2 = (payload >> 26) & _BINARY_SAMPLE_MASK  
    raw_s3 = (payload >> 44) & _BINARY_SAMPLE_MASK  
 
    last_sample_pos = state.get("last_sample_pos")
    if last_sample_pos is None:
        state["last_sample_pos"] = sample_pos
        state["total_samples"] = 0
    else:
        if sample_pos == last_sample_pos:
            return None  
        elif sample_pos > last_sample_pos:
            delta = sample_pos - last_sample_pos
        else:
            delta = 1  
            
        if delta > 10:
            delta = 1
            
        state["total_samples"] += delta
        state["last_sample_pos"] = sample_pos
 
    def apply_adc_scale(raw_val):
        return (_decode_signed18(raw_val) * 64) / adc_scale
 
    frame = {
        "t_s": float(state["total_samples"]),
        "u": [apply_adc_scale(raw_s1), apply_adc_scale(raw_s2), apply_adc_scale(raw_s3)],
        "sample_index": sample_pos,
        "fw_min": ts_min, "fw_sec": ts_sec, "fw_ms": ts_ms
    }
    return frame
 
 
class _BaseProvider:
    def __init__(self, out_q: queue.Queue, config: dict = None):
        self._q = out_q
        self._config = config or {}
        self._mirror_q: Optional[queue.Queue] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state = {}
        
        self.bytes_rx = 0
        self.lines_rx = 0
        self.frames_rx = 0
        self.loaded_frames = 0
        self.frames_dropped = 0
        self.checksum_errors = 0
        self.raw_sniff: str = ""
        self.error: Optional[str] = None
        self.is_finished = False   # Cờ báo hiệu đã load hoàn tất luồng dữ liệu
 
    def set_mirror_queue(self, mirror_q: Optional[queue.Queue]):
        self._mirror_q = mirror_q
 
    def _run_wrapper(self):
        try:
            self._run()
        finally:
            self.is_finished = True  # Luôn bật cờ khi thread kết thúc an toàn
            
    def start(self):
        self._stop.clear()
        self.is_finished = False
        self._thread = threading.Thread(target=self._run_wrapper, daemon=True)
        self._thread.start()
 
    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
 
    def _push(self, frame: dict):
        frame = _enrich_frame(frame, self._state)
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
 
 
class QualSerialProvider(_BaseProvider):
    def __init__(self, port: str, baud: int, out_q: queue.Queue, config: dict = None):
        super().__init__(out_q, config)
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
                        if buf[0] == _BINARY_SYNC:
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
                    if buf[0] != _BINARY_SYNC:
                        sync_idx = _find_binary_sync(buf)
                        if sync_idx == -1:
                            buf = b""
                            mode = None
                            break
                        buf = buf[sync_idx:]
                        if len(buf) < _BINARY_PACKET_SIZE:
                            break
 
                    packet = buf[:_BINARY_PACKET_SIZE]
                    frame = _parse_binary_packet(packet, self._state, self._config, parse_counters)
                    
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
 
 
class QualSimulationProvider(_BaseProvider):
    def __init__(self, out_q: queue.Queue, v_rms_mv: float = 230_000.0, phi_deg: float = 0.0, config: dict = None):
        super().__init__(out_q, config)
        self._v_rms   = v_rms_mv
        self._phi_rad = math.radians(phi_deg)
 
    def _run(self):
        vpeak = self._v_rms * math.sqrt(2)
        spc = self._config.get("samples_per_cycle", 312)
        eff_spc = max(1, int(spc // 2))
        sample_idx = 0
        while not self._stop.is_set():
            for _ in range(eff_spc):
                angle = (2 * math.pi * sample_idx) / eff_spc + self._phi_rad
                u1 = vpeak * math.sin(angle)
                u2 = vpeak * math.sin(angle - 2 * math.pi / 3)
                u3 = vpeak * math.sin(angle + 2 * math.pi / 3)
                
                self._push({"t_s": float(sample_idx), "u": [u1, u2, u3]})
                self.frames_rx += 1
                sample_idx += 1
            time.sleep(0.02)
 
 
class QualFileProvider(_BaseProvider):
    def __init__(self, path: str, out_q: queue.Queue, speed: float = 1.0, config: dict = None):
        super().__init__(out_q, config)
        self._path  = Path(path)
        self._speed = max(0.0, speed)
 
    def _run(self):
        try:
            file_obj = self._path.open("r", encoding="utf-8", errors="ignore")
        except Exception as exc:
            self.error = str(exc)
            return
            
        spc = self._config.get("samples_per_cycle", 312)
        eff_spc = spc / 2.0  
        freq = self._config.get("grid_freq", 50.0)
        
        t_file_start = None
        t_wall_start = time.monotonic()
 
        try:
            with file_obj:
                for raw in file_obj:
                    if self._stop.is_set():
                        break
                        
                    self.lines_rx += 1
                    
                    if not raw.strip() or raw.startswith("index") or raw.startswith("t_s"):
                        continue
                        
                    f = _parse_saved_csv_line(raw) or _parse_line(raw)
                    if not f:
                        continue
                        
                    self.loaded_frames += 1
                    
                    if t_file_start is None:
                        t_file_start = f["t_s"]
                        t_wall_start = time.monotonic()
                    
                    if self._speed > 0.0:
                        t_file_offset = (f["t_s"] - t_file_start) / (eff_spc * freq)
                        t_wall_target = t_wall_start + t_file_offset / self._speed
                        wait = t_wall_target - time.monotonic()
                        if wait > 0.001:
                            time.sleep(wait)
                            
                    self.frames_rx += 1
                    self._push(f)
        except Exception as exc:
            self.error = str(exc)