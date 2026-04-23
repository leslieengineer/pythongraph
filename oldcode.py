"""
QUAL Waveform Viewer
====================
Real-time oscilloscope for Sagemcom AMR QUAL samples via CLI UART
(firmware: CONFIG_METROLOGY_QUALIMETRY_TEST + CLI_TEST_FW_TRANSFER).
 
Modes:  Online (COM) | Simulation | Playback (log)
UART:   USART1 (CLI) at 960000 baud -- NOT USART2 (S1)
Format: $Q,<u32_sec>,<u16_ms>,<U1>,<U2>,<U3>,<I1>,<I2>,<I3>
"""
from __future__ import annotations
import queue, sys, time
from pathlib import Path
from typing import Optional
import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QStatusBar, QVBoxLayout, QWidget,
)
from logger import QualDataLogger
from providers import QualFileProvider, QualSerialProvider, QualSimulationProvider, list_serial_ports
 
BUFFER_SECS  = 120.0
QUAL_FS_HZ   = 156
MAX_SAMPLES  = int(BUFFER_SECS * QUAL_FS_HZ * 1.5)   # 120 s rolling
REFRESH_MS   = 33
SCATTER_MAX  = 2000   # show individual sample dots when point count is below this
WINDOW_OPTS  = ("1", "3", "5", "10", "30", "60", "120")  # seconds
DEFAULT_WIN  = "10"
COLORS_V = ("#FF4040", "#40FF40", "#4080FF")
COLORS_I = ("#FF8040", "#40FFC0", "#8080FF")
PHASE_LABELS_V = ("U1 (L1)", "U2 (L2)", "U3 (L3)")
PHASE_LABELS_I = ("I1 (L1)", "I2 (L2)", "I3 (L3)")
pg.setConfigOptions(antialias=True, background="#1A1A2E", foreground="#E0E0E0")
 
 
class _RollingBuffer:
    def __init__(self, capacity):
        self._cap  = capacity
        self._t    = np.empty(capacity, dtype=np.float64)
        self._u    = np.empty((3, capacity), dtype=np.float32)
        self._i    = np.empty((3, capacity), dtype=np.float32)
        self._head = 0
        self._size = 0
 
    def push(self, t_s, u, i):
        idx = self._head % self._cap
        self._t[idx]    = t_s
        self._u[:, idx] = u
        self._i[:, idx] = i
        self._head = (self._head + 1) % self._cap
        if self._size < self._cap:
            self._size += 1
 
    def view(self, window_s):
        if self._size == 0:
            empty = np.empty(0, dtype=np.float64)
            return empty, [empty]*3, [empty]*3
        cap = self._cap
        # Scan only enough samples to cover the window — no full-buffer traversal.
        n_scan = min(self._size, max(64, int(window_s * QUAL_FS_HZ * 2)))
        if self._size < self._cap:
            base = self._size - n_scan          # oldest index within [0..size-1]
            idx  = np.arange(base, self._size)
        else:
            idx = np.arange(self._head - n_scan, self._head) % cap
        t_all = self._t[idx]; t_max = t_all[-1]
        mask  = t_all >= (t_max - window_s)
        t_rel = t_all[mask] - t_max + window_s
        u_v   = [self._u[ph, idx[mask]] for ph in range(3)]
        i_v   = [self._i[ph, idx[mask]] for ph in range(3)]
        return t_rel, u_v, i_v
 
    @staticmethod
    def _rms_from_view(u_v, i_v):
        r_u = [float(np.sqrt(np.mean(d**2))) if len(d) else 0.0 for d in u_v]
        r_i = [float(np.sqrt(np.mean(d**2))) if len(d) else 0.0 for d in i_v]
        return r_u, r_i
 
    def reset(self):
        self._head = 0; self._size = 0
 
    @property
    def sample_count(self): return self._size
 
 
class QualMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QUAL Waveform Viewer  —  Sagemcom AMR QUAL stream")
        self.resize(1280, 780)
        self._gui_q = queue.Queue(maxsize=MAX_SAMPLES * 2)
        self._log_q = queue.Queue(maxsize=MAX_SAMPLES * 4)
        self._provider = None; self._logger = None
        self._buf = _RollingBuffer(MAX_SAMPLES)
        self._frames_total = 0; self._frames_since = 0
        self._tick_ts = time.monotonic(); self._frozen = False; self._i_gain = 1.0; self._u_gain = 1.0
        self._fs_samples_last = 0; self._fs_ts_last = time.monotonic(); self._fs_hz = 0.0
        self._play_path = ""; self._log_path = str(Path.home() / "qual_log.csv")
        self._build_ui(); self._build_plots()
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._on_tick)
 
    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central); root.setSpacing(4); root.setContentsMargins(6,6,6,4)
        conn_grp = QGroupBox("Connection"); conn_row = QHBoxLayout(conn_grp)
        conn_row.addWidget(QLabel("Mode:"))
        self._cb_mode = QComboBox()
        self._cb_mode.addItems(["Online (COM)", "Simulation", "Playback (log)"])
        self._cb_mode.currentIndexChanged.connect(self._on_mode_changed)
        conn_row.addWidget(self._cb_mode)
        self._lbl_port = QLabel("Port:"); conn_row.addWidget(self._lbl_port)
        self._cb_port = QComboBox(); self._cb_port.setMinimumWidth(90); conn_row.addWidget(self._cb_port)
        self._btn_refresh_ports = QPushButton("⟳")
        self._btn_refresh_ports.setFixedWidth(28)
        self._btn_refresh_ports.clicked.connect(self._refresh_ports)
        conn_row.addWidget(self._btn_refresh_ports)
        self._lbl_baud = QLabel("Baud:"); conn_row.addWidget(self._lbl_baud)
        self._cb_baud = QComboBox()
        for b in ("9600","19200","38400","57600","96000","115200","230400","460800","921600","960000","2000000"):
            self._cb_baud.addItem(b)
        self._cb_baud.setCurrentText("960000"); conn_row.addWidget(self._cb_baud)
        self._lbl_sim_freq = QLabel("Freq (Hz):"); conn_row.addWidget(self._lbl_sim_freq)
        self._spin_freq = QDoubleSpinBox()
        self._spin_freq.setRange(40.0,70.0); self._spin_freq.setValue(50.0); self._spin_freq.setSingleStep(0.1); self._spin_freq.setDecimals(1)
        conn_row.addWidget(self._spin_freq)
        self._lbl_sim_vrms = QLabel("V_rms (mV):"); conn_row.addWidget(self._lbl_sim_vrms)
        self._spin_vrms = QDoubleSpinBox()
        self._spin_vrms.setRange(0.0,1e8); self._spin_vrms.setValue(230000.0); self._spin_vrms.setDecimals(0); self._spin_vrms.setSingleStep(10000.0)
        conn_row.addWidget(self._spin_vrms)
        self._lbl_sim_irms = QLabel("I_rms (mA):"); conn_row.addWidget(self._lbl_sim_irms)
        self._spin_irms = QDoubleSpinBox()
        self._spin_irms.setRange(0.0,1e8); self._spin_irms.setValue(10000.0); self._spin_irms.setDecimals(0); self._spin_irms.setSingleStep(1000.0)
        conn_row.addWidget(self._spin_irms)
        self._lbl_sim_phi = QLabel("φ (°):"); conn_row.addWidget(self._lbl_sim_phi)
        self._spin_phi = QDoubleSpinBox()
        self._spin_phi.setRange(-180.0,180.0); self._spin_phi.setValue(0.0); self._spin_phi.setDecimals(1)
        conn_row.addWidget(self._spin_phi)
        self._btn_pick_file = QPushButton("Log…")
        self._btn_pick_file.clicked.connect(self._pick_log); conn_row.addWidget(self._btn_pick_file)
        self._lbl_speed = QLabel("Speed:"); conn_row.addWidget(self._lbl_speed)
        self._spin_speed = QDoubleSpinBox()
        self._spin_speed.setRange(0.1,100.0); self._spin_speed.setValue(1.0); self._spin_speed.setDecimals(1)
        conn_row.addWidget(self._spin_speed)
        conn_row.addStretch(1)
        self._btn_start = QPushButton("▶  Start")
        self._btn_start.setStyleSheet("background:#1A6E2E; color:white; font-weight:bold")
        self._btn_start.clicked.connect(self._on_start); conn_row.addWidget(self._btn_start)
        self._btn_stop = QPushButton("■  Stop")
        self._btn_stop.setStyleSheet("background:#6E1A1A; color:white; font-weight:bold")
        self._btn_stop.setEnabled(False); self._btn_stop.clicked.connect(self._on_stop); conn_row.addWidget(self._btn_stop)
        self._btn_freeze = QPushButton("❚❚ Freeze")
        self._btn_freeze.setCheckable(True); self._btn_freeze.clicked.connect(self._on_freeze); conn_row.addWidget(self._btn_freeze)
        root.addWidget(conn_grp)
        opt_row = QHBoxLayout()
        opt_row.addWidget(QLabel("Window (s):"))
        self._cb_window = QComboBox()
        for _wv in WINDOW_OPTS:
            self._cb_window.addItem(_wv)
        self._cb_window.setCurrentText(DEFAULT_WIN)
        self._cb_window.currentTextChanged.connect(self._on_window_changed)
        self._cb_window.setFixedWidth(60)
        opt_row.addWidget(self._cb_window)
        opt_row.addWidget(QLabel("U gain (mV→mV):"))
        self._spin_ugain = QDoubleSpinBox()
        self._spin_ugain.setRange(1e-9,1e6); self._spin_ugain.setValue(1.0); self._spin_ugain.setDecimals(6)
        self._spin_ugain.valueChanged.connect(self._on_ugain_changed); opt_row.addWidget(self._spin_ugain)
        opt_row.addWidget(QLabel("I gain (mA→mA):"))
        self._spin_igain = QDoubleSpinBox()
        self._spin_igain.setRange(1e-9,1e6); self._spin_igain.setValue(1.0); self._spin_igain.setDecimals(6)
        self._spin_igain.valueChanged.connect(self._on_igain_changed); opt_row.addWidget(self._spin_igain)
        self._chk_log = QCheckBox("Log to CSV"); opt_row.addWidget(self._chk_log)
        self._btn_log_file = QPushButton("Log file…")
        self._btn_log_file.setToolTip("Chon duong dan file CSV de ghi du lieu")
        self._btn_log_file.clicked.connect(self._pick_log_file); opt_row.addWidget(self._btn_log_file)
        self._chk_u1 = QCheckBox("U1"); self._chk_u1.setChecked(True)
        self._chk_u2 = QCheckBox("U2"); self._chk_u2.setChecked(True)
        self._chk_u3 = QCheckBox("U3"); self._chk_u3.setChecked(True)
        self._chk_i1 = QCheckBox("I1"); self._chk_i1.setChecked(True)
        self._chk_i2 = QCheckBox("I2"); self._chk_i2.setChecked(True)
        self._chk_i3 = QCheckBox("I3"); self._chk_i3.setChecked(True)
        for w in (self._chk_u1,self._chk_u2,self._chk_u3,self._chk_i1,self._chk_i2,self._chk_i3):
            w.stateChanged.connect(self._on_channel_toggle); opt_row.addWidget(w)
        opt_row.addStretch(1); root.addLayout(opt_row)
        self._plot_area = QVBoxLayout(); root.addLayout(self._plot_area, stretch=1)
        self._sb = QStatusBar(); self.setStatusBar(self._sb)
        self._lbl_status = QLabel("Stopped")
        self._lbl_diag   = QLabel("lines: 0 | frames: 0")
        self._lbl_rms_v  = QLabel("V_rms: —")
        self._lbl_rms_i  = QLabel("I_rms: —")
        self._lbl_fs     = QLabel("fs: —")
        self._lbl_fps    = QLabel("fps: —")
        for w in (self._lbl_status,self._lbl_diag,self._lbl_rms_v,self._lbl_rms_i,self._lbl_fs,self._lbl_fps):
            self._sb.addWidget(w); self._sb.addWidget(_separator())
        self._lbl_cursor = QLabel("Cursor: —")
        self._lbl_cursor.setStyleSheet("color:#FFD700; padding:0 8px; font-family:monospace;")
        self._sb.addPermanentWidget(self._lbl_cursor)
        self._refresh_ports(); self._on_mode_changed(0)
 
    def _build_plots(self):
        self._pw_v = pg.PlotWidget(title="Voltage  [mV]");
        self._pw_v.showGrid(x=True,y=True,alpha=0.25)
        self._pw_v.setLabel("left","U",units="mV"); self._pw_v.setLabel("bottom","Time (s)")
        self._pw_v.addLegend(offset=(10,10))
        self._curves_v = [self._pw_v.plot([],[],name=l,pen=pg.mkPen(c,width=1.5)) for l,c in zip(PHASE_LABELS_V,COLORS_V)]
        self._pw_i = pg.PlotWidget(title="Current  [mA or A]")
        self._pw_i.showGrid(x=True,y=True,alpha=0.25)
        self._pw_i.setLabel("left","I",units="mA"); self._pw_i.setLabel("bottom","Time (s)")
        self._pw_i.addLegend(offset=(10,10))
        self._curves_i = [self._pw_i.plot([],[],name=l,pen=pg.mkPen(c,width=1.5)) for l,c in zip(PHASE_LABELS_I,COLORS_I)]
        self._pw_i.setXLink(self._pw_v)
        self._plot_area.addWidget(self._pw_v,stretch=1); self._plot_area.addWidget(self._pw_i,stretch=1)
        self._win_s = float(self._cb_window.currentText())
        # Crosshair lines
        _cp = pg.mkPen(color='#FFFFFF80', width=1, style=Qt.DashLine)
        self._vline_v = pg.InfiniteLine(angle=90, movable=False, pen=_cp)
        self._vline_i = pg.InfiniteLine(angle=90, movable=False, pen=_cp)
        self._hline_v = pg.InfiniteLine(angle=0,  movable=False, pen=_cp)
        self._hline_i = pg.InfiniteLine(angle=0,  movable=False, pen=_cp)
        self._pw_v.addItem(self._vline_v, ignoreBounds=True)
        self._pw_v.addItem(self._hline_v, ignoreBounds=True)
        self._pw_i.addItem(self._vline_i, ignoreBounds=True)
        self._pw_i.addItem(self._hline_i, ignoreBounds=True)
        # Mouse-move signal proxies (throttled to 60 Hz)
        self._proxy_v = pg.SignalProxy(self._pw_v.scene().sigMouseMoved, rateLimit=60, slot=self._on_mouse_v)
        self._proxy_i = pg.SignalProxy(self._pw_i.scene().sigMouseMoved, rateLimit=60, slot=self._on_mouse_i)
 
    def _on_mode_changed(self, idx):
        online=(idx==0); sim=(idx==1); play=(idx==2)
        for w in (self._lbl_port,self._cb_port,self._btn_refresh_ports,self._lbl_baud,self._cb_baud):
            w.setVisible(online)
        for w in (self._lbl_sim_freq,self._spin_freq,self._lbl_sim_vrms,self._spin_vrms,
                  self._lbl_sim_irms,self._spin_irms,self._lbl_sim_phi,self._spin_phi):
            w.setVisible(sim)
        for w in (self._btn_pick_file,self._lbl_speed,self._spin_speed):
            w.setVisible(play)
 
    def _refresh_ports(self):
        current = self._cb_port.currentText(); self._cb_port.clear()
        ports = list_serial_ports(); self._cb_port.addItems(ports)
        if current in ports:
            self._cb_port.setCurrentText(current)
        elif "COM3" in ports:
            self._cb_port.setCurrentText("COM3")
 
    def _pick_log(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open QUAL log", str(Path.home()),
                                               "Log files (*.txt *.log *.csv);;All files (*)")
        if path: self._play_path = path; self._btn_pick_file.setText(Path(path).name)
 
    def _pick_log_file(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV log", self._log_path, "CSV files (*.csv)")
        if path:
            self._log_path = path
            self._btn_log_file.setText(Path(path).name)
            self._btn_log_file.setToolTip(path)
 
    def _on_start(self):
        self._stop_provider(); self._buf.reset()
        self._frames_total = self._frames_since = 0; self._tick_ts = time.monotonic()
        self._fs_samples_last = 0; self._fs_ts_last = time.monotonic(); self._fs_hz = 0.0
        mode = self._cb_mode.currentIndex()
        if mode == 0:
            port = self._cb_port.currentText(); baud = int(self._cb_baud.currentText())
            if not port: self._lbl_status.setText("No COM port selected"); return
            self._provider = QualSerialProvider(port, baud, self._gui_q)
        elif mode == 1:
            self._provider = QualSimulationProvider(self._gui_q, freq_hz=self._spin_freq.value(),
                v_rms_mv=self._spin_vrms.value(), i_rms_ma=self._spin_irms.value(), phi_deg=self._spin_phi.value())
        else:
            if not self._play_path: self._lbl_status.setText("No log file selected"); return
            self._provider = QualFileProvider(self._play_path, self._gui_q, speed=self._spin_speed.value())
        if self._chk_log.isChecked():
            self._logger = QualDataLogger(self._log_path, self._log_q)
            self._logger.start()
            self._btn_log_file.setText(f"Logging: {Path(self._log_path).name}")
            self._btn_log_file.setStyleSheet("color:#40FF40; font-weight:bold")
        self._provider.start(); self._timer.start()
        self._btn_start.setEnabled(False); self._btn_stop.setEnabled(True)
        self._lbl_status.setText(f"Running  [{['Online','Simulation','Playback'][mode]}]")
 
    def _on_stop(self):
        self._stop_provider(); self._timer.stop()
        self._btn_start.setEnabled(True); self._btn_stop.setEnabled(False)
        self._lbl_status.setText("Stopped")
 
    def _stop_provider(self):
        if self._provider is not None:
            self._provider.stop()
            self._provider = None
        if self._logger is not None:
            self._logger.stop()
            if self._logger.rows_written > 0:
                self._lbl_status.setText(
                    f"Stopped  |  Logged {self._logger.rows_written} rows to: {Path(self._log_path).name}")
            if self._logger.error:
                self._lbl_status.setText(f"LOG ERROR: {self._logger.error}")
                self._btn_log_file.setStyleSheet("color:#FF4040; font-weight:bold")
            else:
                self._btn_log_file.setStyleSheet("")
                self._btn_log_file.setText("Log file…")
            self._logger = None
 
    def _on_freeze(self, checked):
        self._frozen = checked
        self._btn_freeze.setText("▶ Resume" if checked else "❚❚ Freeze")
 
    def _on_window_changed(self, v): self._win_s = float(v)
 
    def _on_ugain_changed(self, v):
        self._u_gain = v
        self._pw_v.setLabel("left","Voltage",units="mV")
        self._pw_v.setTitle("Voltage  [mV]")
 
    def _on_igain_changed(self, v):
        self._i_gain = v
        self._pw_i.setLabel("left","Current",units="mA")
 
    def _on_channel_toggle(self):
        for curve, chk in zip(self._curves_v,(self._chk_u1,self._chk_u2,self._chk_u3)):
            curve.setVisible(chk.isChecked())
        for curve, chk in zip(self._curves_i,(self._chk_i1,self._chk_i2,self._chk_i3)):
            curve.setVisible(chk.isChecked())
 
    def _on_tick(self):
        new_frames = 0
        while True:
            try: frame = self._gui_q.get_nowait()
            except queue.Empty: break
            new_frames += 1; self._frames_total += 1
            self._buf.push(frame["t_s"], frame["u"], frame["i"])
            if self._logger is not None:
                try: self._log_q.put_nowait(frame)
                except queue.Full: pass
        if self._frozen or (new_frames==0 and self._buf.sample_count==0): return
        t, u_v, i_v = self._buf.view(self._win_s)
        if len(t) > 0:
            show_dots = (len(t) <= SCATTER_MAX)
            sym    = 'o' if show_dots else None
            sym_sz = 5   if show_dots else 0
            gu = self._u_gain
            for k, curve in enumerate(self._curves_v):
                if curve.isVisible():
                    curve.setData(t, u_v[k] * gu, symbol=sym, symbolSize=sym_sz,
                                  symbolPen=None, symbolBrush=COLORS_V[k])
            g = self._i_gain
            for k, curve in enumerate(self._curves_i):
                if curve.isVisible():
                    curve.setData(t, i_v[k] * g, symbol=sym, symbolSize=sym_sz,
                                  symbolPen=None, symbolBrush=COLORS_I[k])
            rms_u, rms_i = _RollingBuffer._rms_from_view(u_v, i_v)  # reuse, no second view()
        else:
            rms_u, rms_i = [0.0]*3, [0.0]*3
        now = time.monotonic(); self._frames_since += new_frames; dt = now - self._tick_ts
        if now - self._fs_ts_last >= 1.0:
            self._fs_hz = (self._buf.sample_count - self._fs_samples_last) / (now - self._fs_ts_last)
            self._fs_samples_last = self._buf.sample_count; self._fs_ts_last = now
        self._lbl_fs.setText(f"fs: {self._fs_hz:.1f} Hz")
        if dt >= 1.0:
            self._lbl_fps.setText(f"fps: {self._frames_since/dt:.0f}")
            self._frames_since = 0; self._tick_ts = now
        if self._provider is not None and hasattr(self._provider,"lines_rx"):
            self._lbl_diag.setText(f"lines: {self._provider.lines_rx} | frames: {self._provider.frames_rx}")
        else:
            self._lbl_diag.setText(f"buf: {self._buf.sample_count}")
        gu = self._u_gain
        self._lbl_rms_v.setText(f"V_rms:  L1={rms_u[0]*gu:.1f}  L2={rms_u[1]*gu:.1f}  L3={rms_u[2]*gu:.1f} mV")
        g = self._i_gain
        self._lbl_rms_i.setText(f"I_rms:  L1={rms_i[0]*g:.1f}  L2={rms_i[1]*g:.1f}  L3={rms_i[2]*g:.1f} mA")
        if self._provider is not None:
            err = getattr(self._provider,"error",None)
            if err: self._lbl_status.setText(f"Error: {err}"); self._on_stop()
 
    # ------------------------------------------------------------------
    # Crosshair / cursor readout
    # ------------------------------------------------------------------
 
    def _on_mouse_v(self, evt):
        pos = evt[0]
        if self._pw_v.sceneBoundingRect().contains(pos):
            mp = self._pw_v.plotItem.vb.mapSceneToView(pos)
            self._hline_v.setPos(mp.y())
            self._update_crosshair(mp.x())
 
    def _on_mouse_i(self, evt):
        pos = evt[0]
        if self._pw_i.sceneBoundingRect().contains(pos):
            mp = self._pw_i.plotItem.vb.mapSceneToView(pos)
            self._hline_i.setPos(mp.y())
            self._update_crosshair(mp.x())
 
    def _update_crosshair(self, x):
        self._vline_v.setPos(x)
        self._vline_i.setPos(x)
        t, u_v, i_v = self._buf.view(self._win_s)
        if len(t) < 1:
            self._lbl_cursor.setText("Cursor: —")
            return
        # Find nearest sample index
        idx = int(np.searchsorted(t, x))
        idx = max(0, min(idx, len(t) - 1))
        t_val = float(t[idx])
        g = self._i_gain; gu = self._u_gain
        u_vals = [float(u_v[k][idx]) * gu if len(u_v[k]) > idx else 0.0 for k in range(3)]
        i_vals = [float(i_v[k][idx]) * g if len(i_v[k]) > idx else 0.0 for k in range(3)]
        u_str = "  ".join(f"U{k+1}={u_vals[k]:.1f}" for k in range(3))
        i_str = "  ".join(f"I{k+1}={i_vals[k]:.1f}" for k in range(3))
        self._lbl_cursor.setText(f"t={t_val:.4f}s    {u_str} mV    {i_str} mA")
 
    def closeEvent(self, event):
        self._stop_provider(); self._timer.stop(); super().closeEvent(event)
 
 
def _separator():
    sep = QLabel("|")
    sep.setStyleSheet("color: #555; margin: 0 4px;")
    return sep
 
 
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    from PyQt5.QtGui import QPalette, QColor
    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor("#1A1A2E"))
    pal.setColor(QPalette.WindowText,      QColor("#E0E0E0"))
    pal.setColor(QPalette.Base,            QColor("#16213E"))
    pal.setColor(QPalette.AlternateBase,   QColor("#0F3460"))
    pal.setColor(QPalette.Text,            QColor("#E0E0E0"))
    pal.setColor(QPalette.Button,          QColor("#0F3460"))
    pal.setColor(QPalette.ButtonText,      QColor("#E0E0E0"))
    pal.setColor(QPalette.Highlight,       QColor("#533483"))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(pal)
    win = QualMainWindow()
    win.show()
    sys.exit(app.exec_())
 
 
if __name__ == "__main__":
    main()
 