"""
QUAL Waveform Viewer
====================
Real-time oscilloscope for Sagemcom AMR QUAL voltage samples via CLI UART.

Modes:  Online (COM) | Simulation | Playback (log)
UART:   USART1 (CLI) at 960000 baud
Format: ASCII $Q,<u32_sec>,<u16_ms>,<U1_mV>,<U2_mV>,<U3_mV>[,<I1>,<I2>,<I3>]
    or 10-byte binary frames from the Nucleo simulator

Architecture:
  Provider thread → gui_q → GUI timer (33 ms) → _RollingBuffer → PlotWidget
  Provider thread → log_q → Logger thread → CSV file
"""
from __future__ import annotations

import queue
import sys
import time
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt, QTimer, QUrl, QStandardPaths
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QStatusBar, QVBoxLayout, QWidget,
)

from logger import QualDataLogger, export_csv_snapshot, prepare_csv_log
from providers import (
    QualFileProvider, QualSerialProvider, QualSimulationProvider,
    list_serial_ports,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BUFFER_SECS = 120.0
QUAL_FS_HZ  = 156          # samples per second *per phase* (approx)
MAX_SAMPLES = int(BUFFER_SECS * QUAL_FS_HZ * 50 * 1.2)  # 7800 samp/s × 120 s × 1.2
REFRESH_MS  = 33           # ~30 FPS
GUI_QUEUE_SECS = 1.0       # keep the GUI near real-time instead of building long delay
GUI_QUEUE_MAX  = int(QUAL_FS_HZ * 50 * GUI_QUEUE_SECS)
RENDER_SOFT_LIMIT = 20_000

WINDOW_OPTS = ("0.02", "0.04", "0.10", "0.20", "0.50", "1", "3", "5", "10", "30", "60", "120")
DEFAULT_WIN = "0.20"

COLORS_V      = ("#FF4040", "#40FF40", "#4080FF")
PHASE_LABELS  = ("U1 (L1)", "U2 (L2)", "U3 (L3)")

pg.setConfigOptions(antialias=False, background="#1A1A2E", foreground="#E0E0E0")


# ---------------------------------------------------------------------------
# Rolling buffer — fixed-size NumPy circular buffer
# ---------------------------------------------------------------------------

class _RollingBuffer:
    """O(1) push, O(window) view.  No per-tick masking of the full buffer."""

    def __init__(self, capacity: int):
        self._cap  = capacity
        self._t    = np.empty(capacity, dtype=np.float64)
        self._u    = np.empty((3, capacity), dtype=np.float32)
        self._head = 0   # next write position
        self._size = 0   # number of valid samples

    # ------------------------------------------------------------------
    def push(self, t_s: float, u):
        idx = self._head
        self._t[idx]    = t_s
        self._u[:, idx] = u
        self._head = (self._head + 1) % self._cap
        if self._size < self._cap:
            self._size += 1

    # ------------------------------------------------------------------
    def view(self, window_s: float):
        """Return (t_rel, [u1, u2, u3]) covering the last *window_s* seconds.

        t_rel is relative: 0 = start of window, window_s = now.
        Uses only as many samples as needed — no full-buffer scan.
        """
        if self._size == 0:
            empty = np.empty(0, dtype=np.float64)
            return empty, [empty, empty, empty]

        cap = self._cap
        # How many samples fit in the window (with a 2× safety margin)
        n_scan = min(self._size, max(64, int(window_s * QUAL_FS_HZ * 50 * 2.0)))

        if self._size < cap:
            # Buffer not yet full: data lives in [0 .. size-1] sequentially
            start = max(0, self._size - n_scan)
            t_all = self._t[start:self._size]
            t_max = t_all[-1]
            view_start = int(np.searchsorted(t_all, t_max - window_s, side="left"))
            t_view = t_all[view_start:]
            t_rel = t_view - t_max + window_s
            u_v = [self._u[ph, start + view_start:self._size] for ph in range(3)]
            return t_rel, u_v

        start = self._head - n_scan
        if start >= 0:
            t_all = self._t[start:self._head]
            t_max = t_all[-1]
            view_start = int(np.searchsorted(t_all, t_max - window_s, side="left"))
            t_view = t_all[view_start:]
            t_rel = t_view - t_max + window_s
            u_v = [self._u[ph, start + view_start:self._head] for ph in range(3)]
            return t_rel, u_v

        # Full circular buffer with wraparound.
        idx = np.arange(self._head - n_scan, self._head) % cap
        t_all = self._t[idx]
        t_max = t_all[-1]
        view_start = int(np.searchsorted(t_all, t_max - window_s, side="left"))
        idx_view = idx[view_start:]
        t_rel = t_all[view_start:] - t_max + window_s
        u_v = [self._u[ph, idx_view] for ph in range(3)]
        return t_rel, u_v

    # ------------------------------------------------------------------
    @staticmethod
    def rms(u_v):
        return [
            float(np.sqrt(np.mean(d ** 2))) if len(d) else 0.0
            for d in u_v
        ]

    def reset(self):
        self._head = 0
        self._size = 0

    def all_data(self):
        if self._size == 0:
            empty = np.empty(0, dtype=np.float64)
            return empty, [empty, empty, empty]

        if self._size < self._cap:
            t_all = self._t[:self._size].copy()
            u_all = [self._u[ph, :self._size].copy() for ph in range(3)]
            return t_all, u_all

        idx = (np.arange(self._size) + self._head) % self._cap
        t_all = self._t[idx].copy()
        u_all = [self._u[ph, idx].copy() for ph in range(3)]
        return t_all, u_all

    @property
    def sample_count(self):
        return self._size


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class QualMainWindow(QMainWindow):
    @staticmethod
    def _default_log_path():
        desktop_dir = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
        base_dir = Path(desktop_dir) if desktop_dir else Path.home()
        return str((base_dir / "qual_log.csv").resolve())

    def __init__(self):
        super().__init__()
        self.setWindowTitle("QUAL Waveform Viewer  —  Sagemcom AMR")
        self.resize(1280, 680)

        self._gui_q   = queue.Queue(maxsize=GUI_QUEUE_MAX)
        self._log_q   = queue.Queue()
        self._provider = None
        self._logger   = None

        self._buf           = _RollingBuffer(MAX_SAMPLES)
        self._frames_total  = 0
        self._frames_since  = 0
        self._tick_ts       = time.monotonic()
        self._frozen        = False
        self._u_gain        = 1.0

        self._fs_samples_last = 0
        self._fs_ts_last      = time.monotonic()
        self._fs_hz           = 0.0

        self._play_path = ""
        self._log_path  = self._default_log_path()
        self._log_overwrite_requested = False
        self._latest_t = np.empty(0, dtype=np.float64)
        self._latest_u = [
            np.empty(0, dtype=np.float32),
            np.empty(0, dtype=np.float32),
            np.empty(0, dtype=np.float32),
        ]

        self._build_ui()
        self._build_plot()

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._on_tick)

    @staticmethod
    def _normalize_log_path(path: str):
        normalized = Path(path).expanduser()
        if normalized.exists() and normalized.is_dir():
            normalized = normalized / "qual_log.csv"
        if normalized.suffix.lower() != ".csv":
            normalized = normalized.with_suffix(".csv")
        return str(normalized.resolve())

    def _refresh_log_path_ui(self):
        self._btn_log_file.setToolTip(self._log_path)
        self._btn_open_log_folder.setToolTip(str(Path(self._log_path).resolve().parent))
        self._lbl_log_file.setText(f"CSV: {self._log_path}")

    def _set_log_button_idle(self):
        self._btn_log_file.setText(Path(self._log_path).name)
        self._refresh_log_path_ui()
        self._btn_log_file.setStyleSheet("")

    def _set_log_button_armed(self):
        self._btn_log_file.setText(f"Armed: {Path(self._log_path).name}")
        self._refresh_log_path_ui()
        self._btn_log_file.setStyleSheet("color:#FFD866; font-weight:bold")

    def _open_log_folder(self):
        log_dir = Path(self._log_path).resolve().parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))

    def _consume_log_overwrite_request(self):
        overwrite = self._log_overwrite_requested
        self._log_overwrite_requested = False
        return overwrite

    def _prime_log_file(self):
        prepare_csv_log(self._log_path, overwrite=self._consume_log_overwrite_request())
        self._set_log_button_armed()

    def _export_buffer_to_csv(self):
        self._consume_log_overwrite_request()
        t_all, u_all = self._buf.all_data()
        rows_written = export_csv_snapshot(self._log_path, t_all, u_all)
        if self._chk_log.isChecked():
            self._set_log_button_armed()
            self._lbl_status.setText(
                f"Saved {rows_written} buffered rows → {self._log_path}  |  Press Start to record")
        else:
            self._set_log_button_idle()
            self._lbl_status.setText(f"Saved {rows_written} buffered rows → {self._log_path}")

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(4)
        root.setContentsMargins(6, 6, 6, 4)

        # ── Connection group ──────────────────────────────────────────
        conn_grp = QGroupBox("Connection")
        conn_row = QHBoxLayout(conn_grp)

        conn_row.addWidget(QLabel("Mode:"))
        self._cb_mode = QComboBox()
        self._cb_mode.addItems(["Online (COM)", "Simulation", "Playback (log)"])
        self._cb_mode.currentIndexChanged.connect(self._on_mode_changed)
        conn_row.addWidget(self._cb_mode)

        # Online widgets
        self._lbl_port = QLabel("Port:")
        conn_row.addWidget(self._lbl_port)
        self._cb_port = QComboBox()
        self._cb_port.setMinimumWidth(90)
        conn_row.addWidget(self._cb_port)

        self._btn_refresh = QPushButton("⟳")
        self._btn_refresh.setFixedWidth(28)
        self._btn_refresh.clicked.connect(self._refresh_ports)
        conn_row.addWidget(self._btn_refresh)

        self._lbl_baud = QLabel("Baud:")
        conn_row.addWidget(self._lbl_baud)
        self._cb_baud = QComboBox()
        for b in ("9600", "19200", "38400", "57600", "115200",
                  "230400", "460800", "921600", "960000", "2000000", "3000000"):
            self._cb_baud.addItem(b)
        self._cb_baud.setCurrentText("960000")
        conn_row.addWidget(self._cb_baud)

        # Simulation widgets
        self._lbl_freq = QLabel("Freq (Hz):")
        conn_row.addWidget(self._lbl_freq)
        self._spin_freq = QDoubleSpinBox()
        self._spin_freq.setRange(40.0, 70.0)
        self._spin_freq.setValue(50.0)
        self._spin_freq.setSingleStep(0.1)
        self._spin_freq.setDecimals(1)
        conn_row.addWidget(self._spin_freq)

        self._lbl_vrms = QLabel("V_rms (mV):")
        conn_row.addWidget(self._lbl_vrms)
        self._spin_vrms = QDoubleSpinBox()
        self._spin_vrms.setRange(0.0, 1e8)
        self._spin_vrms.setValue(230_000.0)
        self._spin_vrms.setDecimals(0)
        self._spin_vrms.setSingleStep(10_000.0)
        conn_row.addWidget(self._spin_vrms)

        self._lbl_phi = QLabel("φ (°):")
        conn_row.addWidget(self._lbl_phi)
        self._spin_phi = QDoubleSpinBox()
        self._spin_phi.setRange(-180.0, 180.0)
        self._spin_phi.setValue(0.0)
        self._spin_phi.setDecimals(1)
        conn_row.addWidget(self._spin_phi)

        # Playback widgets
        self._btn_pick_file = QPushButton("Log…")
        self._btn_pick_file.clicked.connect(self._pick_log)
        conn_row.addWidget(self._btn_pick_file)

        self._lbl_speed = QLabel("Speed:")
        conn_row.addWidget(self._lbl_speed)
        self._spin_speed = QDoubleSpinBox()
        self._spin_speed.setRange(0.1, 100.0)
        self._spin_speed.setValue(1.0)
        self._spin_speed.setDecimals(1)
        conn_row.addWidget(self._spin_speed)

        conn_row.addStretch(1)

        self._btn_start = QPushButton("▶  Start")
        self._btn_start.setStyleSheet("background:#1A6E2E; color:white; font-weight:bold")
        self._btn_start.clicked.connect(self._on_start)
        conn_row.addWidget(self._btn_start)

        self._btn_stop = QPushButton("■  Stop")
        self._btn_stop.setStyleSheet("background:#6E1A1A; color:white; font-weight:bold")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._on_stop)
        conn_row.addWidget(self._btn_stop)

        self._btn_freeze = QPushButton("❚❚ Freeze")
        self._btn_freeze.setCheckable(True)
        self._btn_freeze.clicked.connect(self._on_freeze)
        conn_row.addWidget(self._btn_freeze)

        root.addWidget(conn_grp)

        # ── Options row ───────────────────────────────────────────────
        opt_row = QHBoxLayout()

        opt_row.addWidget(QLabel("Window (s):"))
        self._cb_window = QComboBox()
        for wv in WINDOW_OPTS:
            self._cb_window.addItem(wv)
        self._cb_window.setCurrentText(DEFAULT_WIN)
        self._cb_window.currentTextChanged.connect(self._on_window_changed)
        self._cb_window.setFixedWidth(60)
        opt_row.addWidget(self._cb_window)

        opt_row.addWidget(QLabel("Y zoom (×):"))
        self._spin_ugain = QDoubleSpinBox()
        self._spin_ugain.setRange(1e-9, 1e6)
        self._spin_ugain.setValue(1.0)
        self._spin_ugain.setDecimals(6)
        self._spin_ugain.setToolTip("Chi anh huong do phong dai truc Y de quan sat, khong doi gia tri do that")
        self._spin_ugain.valueChanged.connect(self._on_ugain_changed)
        opt_row.addWidget(self._spin_ugain)

        self._chk_log = QCheckBox("Log to CSV")
        self._chk_log.stateChanged.connect(self._on_log_toggle)
        opt_row.addWidget(self._chk_log)

        self._btn_log_file = QPushButton(Path(self._log_path).name)
        self._btn_log_file.setToolTip(self._log_path)
        self._btn_log_file.clicked.connect(self._pick_log_file)
        opt_row.addWidget(self._btn_log_file)

        self._btn_open_log_folder = QPushButton("Open")
        self._btn_open_log_folder.setToolTip(str(Path(self._log_path).resolve().parent))
        self._btn_open_log_folder.clicked.connect(self._open_log_folder)
        opt_row.addWidget(self._btn_open_log_folder)

        # Channel toggles (U only — I not used)
        self._chk_u = []
        for label in ("U1", "U2", "U3"):
            chk = QCheckBox(label)
            chk.setChecked(True)
            chk.stateChanged.connect(self._on_channel_toggle)
            opt_row.addWidget(chk)
            self._chk_u.append(chk)

        opt_row.addStretch(1)
        root.addLayout(opt_row)

        # Plot placeholder
        self._plot_area = QVBoxLayout()
        root.addLayout(self._plot_area, stretch=1)

        # ── Status bar ────────────────────────────────────────────────
        self._sb = QStatusBar()
        self.setStatusBar(self._sb)

        self._lbl_status = QLabel("Stopped")
        self._lbl_diag   = QLabel("lines: 0 | frames: 0")
        self._lbl_rms_v  = QLabel("V_rms: —")
        self._lbl_fs     = QLabel("fs: —")
        self._lbl_fps    = QLabel("fps: —")
        self._lbl_log_file = QLabel("")
        self._lbl_log_file.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._lbl_log_file.setStyleSheet("color:#AAB2D5; padding:0 8px; font-family:monospace;")

        for w in (self._lbl_status, self._lbl_diag,
                  self._lbl_rms_v, self._lbl_fs, self._lbl_fps):
            self._sb.addWidget(w)
            self._sb.addWidget(_sep())

        self._sb.addPermanentWidget(self._lbl_log_file, 1)
        self._lbl_cursor = QLabel("Cursor: —")
        self._lbl_cursor.setStyleSheet(
            "color:#FFD700; padding:0 8px; font-family:monospace;")
        self._sb.addPermanentWidget(self._lbl_cursor)

        self._refresh_log_path_ui()

        self._refresh_ports()
        self._on_mode_changed(0)

    # ------------------------------------------------------------------ Plot

    def _build_plot(self):
        self._pw = pg.PlotWidget(title="Voltage  [mV]")
        self._pw.showGrid(x=True, y=True, alpha=0.25)
        self._pw.setLabel("left", "U", units="mV")
        self._pw.setLabel("bottom", "Time", units="s")
        self._pw.addLegend(offset=(10, 10))

        self._curves = [
            self._pw.plot([], [], name=lbl, pen=pg.mkPen(col, width=1.5))
            for lbl, col in zip(PHASE_LABELS, COLORS_V)
        ]
        for curve in self._curves:
            curve.setClipToView(True)
            curve.setDownsampling(auto=True, method="peak")

        # Crosshair lines
        _cp = pg.mkPen(color="#FFFFFF90", width=1, style=Qt.DashLine)
        self._vline = pg.InfiniteLine(angle=90, movable=False, pen=_cp)
        self._hline = pg.InfiniteLine(angle=0,  movable=False, pen=_cp)
        self._pw.addItem(self._vline, ignoreBounds=True)
        self._pw.addItem(self._hline, ignoreBounds=True)

        # Mouse proxy (throttled 60 Hz)
        self._mouse_proxy = pg.SignalProxy(
            self._pw.scene().sigMouseMoved,
            rateLimit=60,
            slot=self._on_mouse,
        )

        self._plot_area.addWidget(self._pw, stretch=1)
        self._win_s = float(self._cb_window.currentText())
        self._pw.setXRange(0.0, self._win_s, padding=0.0)

    # ------------------------------------------------------------------ Mode

    def _on_mode_changed(self, idx):
        online = (idx == 0)
        sim    = (idx == 1)
        play   = (idx == 2)
        for w in (self._lbl_port, self._cb_port, self._btn_refresh,
                  self._lbl_baud, self._cb_baud):
            w.setVisible(online)
        for w in (self._lbl_freq, self._spin_freq,
                  self._lbl_vrms, self._spin_vrms,
                  self._lbl_phi,  self._spin_phi):
            w.setVisible(sim)
        for w in (self._btn_pick_file, self._lbl_speed, self._spin_speed):
            w.setVisible(play)

    def _refresh_ports(self):
        current = self._cb_port.currentText()
        self._cb_port.clear()
        ports = list_serial_ports()
        self._cb_port.addItems(ports)
        if current in ports:
            self._cb_port.setCurrentText(current)
        elif "COM3" in ports:
            self._cb_port.setCurrentText("COM3")

    def _pick_log(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open QUAL log", str(Path.home()),
            "Log files (*.txt *.log *.csv);;All files (*)")
        if path:
            self._play_path = path
            self._btn_pick_file.setText(Path(path).name)

    def _pick_log_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save CSV log", self._log_path, "CSV files (*.csv)")
        if path:
            normalized_path = self._normalize_log_path(path)
            self._log_overwrite_requested = Path(normalized_path).exists()
            self._log_path = normalized_path
            if self._provider is not None and self._logger is not None:
                self._stop_logger()
                self._start_logger()
                self._lbl_status.setText(f"Running  |  Logging to: {self._log_path}")
            elif self._provider is None:
                self._export_buffer_to_csv()
            elif self._chk_log.isChecked():
                self._prime_log_file()
                self._lbl_status.setText(
                    f"CSV armed  |  {self._log_path}  |  Press Start to record")
            else:
                self._set_log_button_idle()
                self._lbl_status.setText(f"CSV path set  |  {self._log_path}")

    def _start_logger(self):
        if self._logger is not None:
            return
        self._log_q = queue.Queue()
        self._logger = QualDataLogger(
            self._log_path,
            self._log_q,
            truncate=self._consume_log_overwrite_request(),
        )
        self._logger.start()
        if self._provider is not None:
            self._provider.set_mirror_queue(self._log_q)
        self._btn_log_file.setText(f"Logging: {Path(self._log_path).name}")
        self._btn_log_file.setStyleSheet("color:#40FF40; font-weight:bold")
        self._btn_log_file.setToolTip(self._log_path)

    def _stop_logger(self):
        stop_message = None
        if self._provider is not None:
            self._provider.set_mirror_queue(None)
        if self._logger is not None:
            self._logger.stop()
            if self._logger.error:
                stop_message = f"LOG ERROR: {self._logger.error}"
                self._btn_log_file.setStyleSheet("color:#FF4040; font-weight:bold")
            else:
                stop_message = (
                    f"Stopped  |  Logged {self._logger.rows_written} rows → {self._log_path}")
                if self._chk_log.isChecked():
                    self._set_log_button_armed()
                else:
                    self._set_log_button_idle()
            self._logger = None
            self._log_q = queue.Queue()
        return stop_message

    def _on_log_toggle(self, checked):
        checked = bool(checked)
        if checked:
            try:
                self._prime_log_file()
            except Exception as exc:
                self._lbl_status.setText(f"LOG ERROR: {exc}")
                self._btn_log_file.setStyleSheet("color:#FF4040; font-weight:bold")
                self._btn_log_file.setText(Path(self._log_path).name)
                self._btn_log_file.setToolTip(self._log_path)
                return
        if self._provider is None:
            if checked:
                self._lbl_status.setText(
                    f"CSV armed  |  {self._log_path}  |  Press Start to record")
            else:
                self._set_log_button_idle()
                self._lbl_status.setText("Stopped")
            return
        if checked:
            self._start_logger()
            self._lbl_status.setText(f"Running  |  Logging to: {self._log_path}")
        else:
            stop_message = self._stop_logger()
            if stop_message is not None:
                self._lbl_status.setText(stop_message)

    # ------------------------------------------------------------------ Start/Stop

    def _on_start(self):
        self._stop_provider()
        self._buf.reset()
        self._frames_total = self._frames_since = 0
        self._tick_ts = time.monotonic()
        self._fs_samples_last = 0
        self._fs_ts_last = time.monotonic()
        self._fs_hz = 0.0

        mode = self._cb_mode.currentIndex()
        if mode == 0:
            port = self._cb_port.currentText()
            baud = int(self._cb_baud.currentText())
            if not port:
                self._lbl_status.setText("No COM port selected")
                return
            self._provider = QualSerialProvider(port, baud, self._gui_q)
        elif mode == 1:
            self._provider = QualSimulationProvider(
                self._gui_q,
                freq_hz=self._spin_freq.value(),
                v_rms_mv=self._spin_vrms.value(),
                phi_deg=self._spin_phi.value(),
            )
        else:
            if not self._play_path:
                self._lbl_status.setText("No log file selected")
                return
            self._provider = QualFileProvider(
                self._play_path, self._gui_q, speed=self._spin_speed.value())

        self._provider.start()
        if self._chk_log.isChecked():
            self._start_logger()
        self._timer.start()
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        mode_name = ['Online', 'Simulation', 'Playback'][mode]
        if self._chk_log.isChecked():
            self._lbl_status.setText(
                f"Running  [{mode_name}]  |  Logging to: {self._log_path}")
        else:
            self._lbl_status.setText(f"Running  [{mode_name}]")

    def _on_stop(self):
        stop_message = self._stop_provider()
        self._timer.stop()
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        if stop_message is not None:
            self._lbl_status.setText(stop_message)
        else:
            self._lbl_status.setText("Stopped")

    def _stop_provider(self):
        stop_message = None
        if self._provider is not None:
            self._provider.stop()
            self._provider = None
        pending_frames = self._drain_gui_queue()
        if pending_frames and not self._frozen:
            self._latest_t, self._latest_u = self._buf.view(self._win_s)
        if self._logger is not None:
            stop_message = self._stop_logger()
        return stop_message

    def _on_freeze(self, checked):
        self._frozen = checked
        self._btn_freeze.setText("▶ Resume" if checked else "❚❚ Freeze")

    def _on_window_changed(self, v):
        self._win_s = float(v)
        self._pw.setXRange(0.0, self._win_s, padding=0.0)

    def _on_ugain_changed(self, v):
        self._u_gain = v

    def _update_y_zoom(self, u_v):
        visible_data = [
            data for data, chk in zip(u_v, self._chk_u)
            if chk.isChecked() and len(data) > 0
        ]
        if not visible_data:
            return

        y_min = min(float(np.min(data)) for data in visible_data)
        y_max = max(float(np.max(data)) for data in visible_data)
        center = 0.5 * (y_min + y_max)
        half_range = max(y_max - center, center - y_min, 1.0)
        display_half_range = (half_range / max(self._u_gain, 1e-9)) * 1.05
        self._pw.setYRange(center - display_half_range, center + display_half_range, padding=0.0)

    def _on_channel_toggle(self):
        for curve, chk in zip(self._curves, self._chk_u):
            curve.setVisible(chk.isChecked())

    def _drain_gui_queue(self):
        new_frames = 0
        while True:
            try:
                frame = self._gui_q.get_nowait()
            except queue.Empty:
                break
            new_frames += 1
            self._frames_total += 1
            self._buf.push(frame["t_s"], frame["u"])
        return new_frames

    def _prepare_render_view(self, t, u_v):
        if len(t) <= RENDER_SOFT_LIMIT:
            return t, u_v
        plot_width = max(1, int(self._pw.width()))
        target_points = max(plot_width * 4, 4_000)
        stride = max(1, len(t) // target_points)
        if stride == 1:
            return t, u_v
        return t[::stride], [d[::stride] for d in u_v]

    # ------------------------------------------------------------------ Timer tick

    def _on_tick(self):
        new_frames = self._drain_gui_queue()

        if self._frozen or (new_frames == 0 and self._buf.sample_count == 0):
            return

        t, u_v = self._buf.view(self._win_s)
        self._latest_t = t
        self._latest_u = u_v
        t_render, u_render = self._prepare_render_view(t, u_v)

        if len(t) > 0:
            for k, curve in enumerate(self._curves):
                if curve.isVisible():
                    curve.setData(t_render, u_render[k])
            self._update_y_zoom(u_v)
            rms_u = _RollingBuffer.rms(u_v)
        else:
            rms_u = [0.0, 0.0, 0.0]

        # ── Status bar updates ────────────────────────────────────────
        now = time.monotonic()
        self._frames_since += new_frames
        dt = now - self._tick_ts

        if now - self._fs_ts_last >= 1.0:
            elapsed = now - self._fs_ts_last
            self._fs_hz = (self._buf.sample_count - self._fs_samples_last) / elapsed
            self._fs_samples_last = self._buf.sample_count
            self._fs_ts_last = now
        self._lbl_fs.setText(f"fs: {self._fs_hz:.1f} Hz")

        if dt >= 1.0:
            self._lbl_fps.setText(f"fps: {self._frames_since / dt:.0f}")
            self._frames_since = 0
            self._tick_ts = now

        if self._provider is not None and hasattr(self._provider, "lines_rx"):
            if isinstance(self._provider, QualFileProvider):
                self._lbl_diag.setText(
                    f"playback: {Path(self._play_path).name} | loaded: {self._provider.loaded_frames} | replayed: {self._provider.frames_rx}")
            else:
                self._lbl_diag.setText(
                    f"lines: {self._provider.lines_rx} | frames: {self._provider.frames_rx}")
        else:
            self._lbl_diag.setText(f"buf: {self._buf.sample_count}")

        self._lbl_rms_v.setText(
            f"V_rms:  L1={rms_u[0]:.1f}  L2={rms_u[1]:.1f}  L3={rms_u[2]:.1f} mV")

        if self._provider is not None:
            err = getattr(self._provider, "error", None)
            if err:
                self._lbl_status.setText(f"Error: {err}")
                self._on_stop()

    # ------------------------------------------------------------------ Crosshair

    def _on_mouse(self, evt):
        pos = evt[0]
        if not self._pw.sceneBoundingRect().contains(pos):
            return
        mp = self._pw.plotItem.vb.mapSceneToView(pos)
        x  = mp.x()
        self._vline.setPos(x)
        self._hline.setPos(mp.y())

        # Snap to nearest sample
        t = self._latest_t
        u_v = self._latest_u
        if len(t) < 1:
            self._lbl_cursor.setText("Cursor: —")
            return

        idx   = int(np.searchsorted(t, x))
        idx   = max(0, min(idx, len(t) - 1))
        t_val = float(t[idx])
        u_vals = [
            float(u_v[k][idx]) if len(u_v[k]) > idx else 0.0
            for k in range(3)
        ]
        u_str = "  ".join(f"U{k+1}={u_vals[k]:.1f}" for k in range(3))
        self._lbl_cursor.setText(f"t={t_val:.4f}s    {u_str} mV")

    # ------------------------------------------------------------------ Close

    def closeEvent(self, event):
        self._stop_provider()
        self._timer.stop()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sep():
    lbl = QLabel("|")
    lbl.setStyleSheet("color:#555; margin:0 4px;")
    return lbl


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

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
