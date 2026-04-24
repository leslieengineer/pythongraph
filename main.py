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
    QPushButton, QSlider, QStatusBar, QVBoxLayout, QWidget,
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
SAMPLE_DOT_RENDER_LIMIT = 4_000
SAMPLE_DOT_SIZE = 4
HISTORY_SLIDER_STEPS = 2_000

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

    def time_bounds(self):
        if self._size == 0:
            return None, None

        if self._size < self._cap:
            return float(self._t[0]), float(self._t[self._size - 1])

        oldest_idx = self._head
        newest_idx = (self._head - 1) % self._cap
        return float(self._t[oldest_idx]), float(self._t[newest_idx])

    def latest_time(self):
        _, latest_t = self.time_bounds()
        return latest_t

    def view_around(self, window_s: float, focus_t: float):
        if self._size == 0:
            empty = np.empty(0, dtype=np.float64)
            return empty, empty, [empty, empty, empty], 0.0, 0.0, 0.0

        t_all, u_all = self.all_data()
        min_t = float(t_all[0])
        max_t = float(t_all[-1])
        focus_t = float(min(max(focus_t, min_t), max_t))

        if window_s <= 0.0:
            window_s = max(max_t - min_t, 0.02)

        half_window = 0.5 * window_s
        window_start = focus_t - half_window
        window_end = focus_t + half_window

        if window_start < min_t:
            window_start = min_t
            window_end = min_t + window_s
        if window_end > max_t:
            window_end = max_t
            window_start = max_t - window_s
        window_start = max(min_t, window_start)

        left = int(np.searchsorted(t_all, window_start, side="left"))
        right = int(np.searchsorted(t_all, window_end, side="right"))
        if right <= left:
            nearest = int(np.searchsorted(t_all, focus_t, side="left"))
            nearest = max(0, min(nearest, len(t_all) - 1))
            left = nearest
            right = nearest + 1

        t_view = t_all[left:right]
        t_rel = t_view - window_start
        u_v = [u_all[ph][left:right] for ph in range(3)]
        return t_rel, t_view, u_v, window_start, min(window_start + window_s, max_t), focus_t

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
        self._latest_t_abs = np.empty(0, dtype=np.float64)
        self._latest_u = [
            np.empty(0, dtype=np.float32),
            np.empty(0, dtype=np.float32),
            np.empty(0, dtype=np.float32),
        ]
        self._view_start_t = 0.0
        self._view_end_t = 0.0
        self._history_mode = False
        self._history_target_t = None
        self._history_slider_dragging = False
        self._history_spin_editing = False
        self._history_snapshot_dirty = True
        self._history_snapshot_t = np.empty(0, dtype=np.float64)
        self._history_snapshot_u = [
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

        self._chk_sample_dots = QCheckBox("Sample dots")
        self._chk_sample_dots.setChecked(True)
        self._chk_sample_dots.setToolTip(
            "Show one dot per rendered sample when the visible point count is low enough")
        self._chk_sample_dots.stateChanged.connect(self._on_plot_style_changed)
        opt_row.addWidget(self._chk_sample_dots)

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

        hist_row = QHBoxLayout()
        hist_row.addWidget(QLabel("Go to (s):"))

        self._spin_history = QDoubleSpinBox()
        self._spin_history.setRange(0.0, BUFFER_SECS)
        self._spin_history.setDecimals(4)
        self._spin_history.setSingleStep(0.01)
        self._spin_history.setKeyboardTracking(False)
        self._spin_history.setFixedWidth(96)
        self._spin_history.lineEdit().textEdited.connect(self._on_history_text_edited)
        self._spin_history.editingFinished.connect(self._on_history_go)
        hist_row.addWidget(self._spin_history)

        self._btn_history_go = QPushButton("Go")
        self._btn_history_go.clicked.connect(self._on_history_go)
        hist_row.addWidget(self._btn_history_go)

        self._btn_back_to_live = QPushButton("Back to live")
        self._btn_back_to_live.clicked.connect(self._on_back_to_live)
        hist_row.addWidget(self._btn_back_to_live)

        self._sld_history = QSlider(Qt.Horizontal)
        self._sld_history.setRange(0, HISTORY_SLIDER_STEPS)
        self._sld_history.setTracking(True)
        self._sld_history.sliderPressed.connect(self._on_history_slider_pressed)
        self._sld_history.sliderReleased.connect(self._on_history_slider_released)
        self._sld_history.valueChanged.connect(self._on_history_slider_changed)
        hist_row.addWidget(self._sld_history, stretch=1)

        self._lbl_history_state = QLabel("Live: waiting for buffer")
        self._lbl_history_state.setStyleSheet("color:#AAB2D5; padding-left:8px;")
        hist_row.addWidget(self._lbl_history_state)

        root.addLayout(hist_row)

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
        self._update_history_controls()

    # ------------------------------------------------------------------ Plot

    def _build_plot(self):
        self._pw = pg.PlotWidget(title="Voltage  [mV]")
        self._pw.showGrid(x=True, y=True, alpha=0.25)
        self._pw.setLabel("left", "U", units="mV")
        self._pw.setLabel("bottom", "Time", units="s")
        self._pw.addLegend(offset=(10, 10))

        self._curve_pens = [pg.mkPen(col, width=1.5) for col in COLORS_V]
        self._curve_brushes = [pg.mkBrush(col) for col in COLORS_V]
        self._curves = [
            self._pw.plot([], [], name=lbl, pen=pen)
            for lbl, pen in zip(PHASE_LABELS, self._curve_pens)
        ]
        for curve in self._curves:
            curve.setClipToView(True)
            curve.setDownsampling(auto=True, method="peak")

        # Crosshair lines
        _cp = pg.mkPen(color="#FFFFFF90", width=1, style=Qt.DashLine)
        self._vline = pg.InfiniteLine(angle=90, movable=False, pen=_cp)
        self._hline = pg.InfiniteLine(angle=0,  movable=False, pen=_cp)

        zero_pen = pg.mkPen(color="#7FDBFF", width=1)
        self._zero_hline = pg.InfiniteLine(angle=0, movable=False, pen=zero_pen)
        self._zero_hline.setPos(0.0)

        self._pw.addItem(self._zero_hline, ignoreBounds=True)
        self._pw.addItem(self._vline, ignoreBounds=True)
        self._pw.addItem(self._hline, ignoreBounds=True)

        history_pen = pg.mkPen(color="#FFD866", width=2, style=Qt.DashLine)
        self._history_vline = pg.InfiniteLine(angle=90, movable=False, pen=history_pen)
        self._history_vline.setVisible(False)
        self._pw.addItem(self._history_vline, ignoreBounds=True)

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
                self._chk_log.blockSignals(True)
                self._chk_log.setChecked(False)
                self._chk_log.blockSignals(False)
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
        self._history_snapshot_dirty = True
        self._history_snapshot_t = np.empty(0, dtype=np.float64)
        self._history_snapshot_u = [
            np.empty(0, dtype=np.float32),
            np.empty(0, dtype=np.float32),
            np.empty(0, dtype=np.float32),
        ]
        self._frames_total = self._frames_since = 0
        self._tick_ts = time.monotonic()
        self._fs_samples_last = 0
        self._fs_ts_last = time.monotonic()
        self._fs_hz = 0.0
        self._history_mode = False
        self._history_target_t = None
        self._latest_t = np.empty(0, dtype=np.float64)
        self._latest_t_abs = np.empty(0, dtype=np.float64)
        self._latest_u = [
            np.empty(0, dtype=np.float32),
            np.empty(0, dtype=np.float32),
            np.empty(0, dtype=np.float32),
        ]
        self._view_start_t = 0.0
        self._view_end_t = 0.0
        self._btn_freeze.blockSignals(True)
        self._btn_freeze.setChecked(False)
        self._btn_freeze.blockSignals(False)
        self._frozen = False
        self._btn_freeze.setText("❚❚ Freeze")
        self._lbl_cursor.setText("Cursor: —")
        self._update_history_controls()

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
            if self._history_mode and self._history_target_t is not None:
                self._show_history_view(self._history_target_t)
            else:
                self._show_live_view()
        if self._logger is not None:
            stop_message = self._stop_logger()
        self._update_history_controls()
        return stop_message

    def _on_freeze(self, checked):
        self._frozen = checked
        self._btn_freeze.setText("▶ Resume" if checked else "❚❚ Freeze")
        if not checked and self._buf.sample_count > 0:
            if self._history_mode and self._history_target_t is not None:
                self._show_history_view(self._history_target_t)
            else:
                self._show_live_view()

    def _on_window_changed(self, v):
        self._win_s = float(v)
        self._pw.setXRange(0.0, self._win_s, padding=0.0)
        if self._buf.sample_count > 0:
            if self._history_mode and self._history_target_t is not None:
                self._show_history_view(self._history_target_t)
            else:
                self._show_live_view()

    def _on_ugain_changed(self, v):
        self._u_gain = v
        if len(self._latest_t) > 0:
            self._update_y_zoom(self._latest_u)

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
        if len(self._latest_t) > 0:
            self._render_plot(self._latest_t, self._latest_u)

    def _set_history_spin_value(self, value):
        if value < self._spin_history.minimum() or value > self._spin_history.maximum():
            self._spin_history.setRange(
                min(self._spin_history.minimum(), value),
                max(self._spin_history.maximum(), value),
            )
        self._spin_history.blockSignals(True)
        self._spin_history.setValue(value)
        self._spin_history.blockSignals(False)

    def _on_history_text_edited(self, _text):
        self._history_spin_editing = True

    def _set_history_spin_range(self, min_t, max_t, preserve_text=False):
        line_edit = self._spin_history.lineEdit()
        restore_text = None
        restore_cursor = None
        if preserve_text:
            restore_text = line_edit.text()
            restore_cursor = line_edit.cursorPosition()

        self._spin_history.blockSignals(True)
        self._spin_history.setRange(min_t, max_t)
        self._spin_history.blockSignals(False)

        if restore_text is not None:
            line_edit.blockSignals(True)
            line_edit.setText(restore_text)
            line_edit.setCursorPosition(min(restore_cursor, len(restore_text)))
            line_edit.blockSignals(False)

    def _current_history_input_value(self):
        text = self._spin_history.lineEdit().text().strip()
        try:
            return float(text)
        except ValueError:
            return float(self._spin_history.value())

    def _mark_history_snapshot_dirty(self):
        self._history_snapshot_dirty = True

    def _get_history_snapshot(self, prefer_stale=False):
        if prefer_stale and len(self._history_snapshot_t) > 0 and self._history_snapshot_dirty:
            return self._history_snapshot_t, self._history_snapshot_u

        if self._history_snapshot_dirty:
            if hasattr(self._buf, "all_data"):
                t_all, u_all = self._buf.all_data()
            elif hasattr(self._buf, "get_all"):
                t_all, u_all = self._buf.get_all()
            else:
                raise AttributeError("buffer must provide all_data() or get_all()")
            self._history_snapshot_t = t_all
            self._history_snapshot_u = u_all
            self._history_snapshot_dirty = False
        return self._history_snapshot_t, self._history_snapshot_u

    @staticmethod
    def _slice_history_snapshot(t_all, u_all, window_s, focus_t):
        if len(t_all) == 0:
            empty = np.empty(0, dtype=np.float64)
            return empty, empty, [empty, empty, empty], 0.0, 0.0, 0.0

        min_t = float(t_all[0])
        max_t = float(t_all[-1])
        focus_t = float(min(max(focus_t, min_t), max_t))

        if window_s <= 0.0:
            window_s = max(max_t - min_t, 0.02)

        half_window = 0.5 * window_s
        window_start = focus_t - half_window
        window_end = focus_t + half_window

        if window_start < min_t:
            window_start = min_t
            window_end = min_t + window_s
        if window_end > max_t:
            window_end = max_t
            window_start = max_t - window_s
        window_start = max(min_t, window_start)

        left = int(np.searchsorted(t_all, window_start, side="left"))
        right = int(np.searchsorted(t_all, window_end, side="right"))
        if right <= left:
            nearest = int(np.searchsorted(t_all, focus_t, side="left"))
            nearest = max(0, min(nearest, len(t_all) - 1))
            left = nearest
            right = nearest + 1

        t_view = t_all[left:right]
        t_rel = t_view - window_start
        u_v = [u_all[ph][left:right] for ph in range(3)]
        return t_rel, t_view, u_v, window_start, min(window_start + window_s, max_t), focus_t

    @staticmethod
    def _time_to_slider_value(t_s, min_t, max_t):
        if max_t <= min_t:
            return 0
        ratio = (t_s - min_t) / (max_t - min_t)
        ratio = min(max(ratio, 0.0), 1.0)
        return int(round(ratio * HISTORY_SLIDER_STEPS))

    @staticmethod
    def _slider_value_to_time(value, min_t, max_t):
        if max_t <= min_t:
            return min_t
        ratio = float(value) / float(HISTORY_SLIDER_STEPS)
        return min_t + ratio * (max_t - min_t)

    def _apply_view(self, t_rel, t_abs, u_v, window_start_t, window_end_t):
        self._latest_t = t_rel
        self._latest_t_abs = t_abs
        self._latest_u = u_v
        self._view_start_t = float(window_start_t)
        self._view_end_t = float(window_end_t)

    def _update_history_marker(self):
        if not self._history_mode or self._history_target_t is None:
            self._history_vline.setVisible(False)
            return

        marker_x = self._history_target_t - self._view_start_t
        marker_x = min(max(marker_x, 0.0), self._win_s)
        self._history_vline.setPos(marker_x)
        self._history_vline.setVisible(True)

    def _show_live_view(self):
        if self._buf.sample_count == 0:
            return [0.0, 0.0, 0.0]

        t_rel, u_v = self._buf.view(self._win_s)
        latest_t = self._buf.latest_time()
        if latest_t is None or len(t_rel) == 0:
            return [0.0, 0.0, 0.0]

        window_start_t = latest_t - self._win_s
        t_abs = t_rel + window_start_t
        self._apply_view(t_rel, t_abs, u_v, window_start_t, latest_t)
        self._update_history_marker()
        self._update_history_controls()
        return self._render_plot(t_rel, u_v)

    def _show_history_view(self, target_t):
        if getattr(self._buf, "sample_count", 0) == 0:
            return [0.0, 0.0, 0.0]

        t_all, u_all = self._get_history_snapshot(prefer_stale=self._history_slider_dragging)
        t_rel, t_abs, u_v, window_start_t, window_end_t, focus_t = self._slice_history_snapshot(
            t_all,
            u_all,
            self._win_s,
            target_t,
        )
        self._history_mode = True
        self._history_target_t = focus_t
        self._apply_view(t_rel, t_abs, u_v, window_start_t, window_end_t)
        self._update_history_marker()
        self._update_history_controls()
        return self._render_plot(t_rel, u_v)

    def _update_history_controls(self):
        min_t, max_t = self._buf.time_bounds()
        has_data = min_t is not None and max_t is not None
        spin_is_editing = self._history_spin_editing or self._spin_history.hasFocus()

        self._btn_history_go.setEnabled(has_data)
        self._btn_back_to_live.setEnabled(has_data and self._history_mode)
        self._sld_history.setEnabled(has_data and max_t > min_t)

        if not has_data:
            self._lbl_history_state.setText("Live: waiting for buffer")
            if not spin_is_editing:
                self._set_history_spin_value(0.0)
            if not self._history_slider_dragging:
                self._sld_history.blockSignals(True)
                self._sld_history.setValue(HISTORY_SLIDER_STEPS)
                self._sld_history.blockSignals(False)
            return

        current_target = max_t if (not self._history_mode or self._history_target_t is None) else self._history_target_t
        current_target = min(max(current_target, min_t), max_t)

        self._set_history_spin_range(min_t, max_t, preserve_text=spin_is_editing)

        if not spin_is_editing:
            self._set_history_spin_value(current_target)

        if not self._history_slider_dragging:
            self._sld_history.blockSignals(True)
            self._sld_history.setValue(self._time_to_slider_value(current_target, min_t, max_t))
            self._sld_history.blockSignals(False)

        if self._history_mode:
            self._lbl_history_state.setText(
                f"History: {self._view_start_t:.4f}s .. {self._view_end_t:.4f}s")
        else:
            self._lbl_history_state.setText(
                f"Live: {max_t:.4f}s  |  Buffer {min_t:.4f}s .. {max_t:.4f}s")

    def _on_history_go(self):
        if self._buf.sample_count == 0:
            self._history_spin_editing = False
            self._lbl_status.setText("No buffered data to review yet")
            return
        self._history_spin_editing = False
        self._show_history_view(self._current_history_input_value())
        self._lbl_status.setText(f"History  |  jumped to t={self._history_target_t:.4f}s")

    def _on_history_slider_changed(self, value):
        min_t, max_t = self._buf.time_bounds()
        if min_t is None or max_t is None:
            return
        target_t = self._slider_value_to_time(value, min_t, max_t)
        self._show_history_view(target_t)
        self._lbl_status.setText(f"History  |  scrubbed to t={self._history_target_t:.4f}s")

    def _on_history_slider_pressed(self):
        self._history_slider_dragging = True

    def _on_history_slider_released(self):
        self._history_slider_dragging = False
        self._update_history_controls()

    def _on_back_to_live(self):
        self._history_mode = False
        self._history_target_t = None
        self._update_history_marker()
        if self._buf.sample_count > 0:
            self._show_live_view()
            self._lbl_status.setText("Live view resumed")
        else:
            self._update_history_controls()

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
            self._mark_history_snapshot_dirty()
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

    def _should_show_sample_dots(self, t_render):
        return self._chk_sample_dots.isChecked() and len(t_render) <= SAMPLE_DOT_RENDER_LIMIT

    def _render_plot(self, t, u_v):
        t_render, u_render = self._prepare_render_view(t, u_v)
        if len(t) > 0:
            show_sample_dots = self._should_show_sample_dots(t_render)
            for k, curve in enumerate(self._curves):
                if curve.isVisible():
                    curve.setData(
                        t_render,
                        u_render[k],
                        pen=self._curve_pens[k],
                        symbol="o" if show_sample_dots else None,
                        symbolSize=SAMPLE_DOT_SIZE if show_sample_dots else 0,
                        symbolBrush=self._curve_brushes[k] if show_sample_dots else None,
                        symbolPen=self._curve_pens[k] if show_sample_dots else None,
                    )
            self._update_y_zoom(u_v)
            return _RollingBuffer.rms(u_v)
        return [0.0, 0.0, 0.0]

    def _on_plot_style_changed(self):
        if len(self._latest_t) > 0:
            self._render_plot(self._latest_t, self._latest_u)
        elif self._buf.sample_count > 0:
            if self._history_mode and self._history_target_t is not None:
                self._show_history_view(self._history_target_t)
            else:
                self._show_live_view()

    # ------------------------------------------------------------------ Timer tick

    def _on_tick(self):
        new_frames = self._drain_gui_queue()

        rms_u = _RollingBuffer.rms(self._latest_u) if len(self._latest_t) > 0 else [0.0, 0.0, 0.0]

        if not self._frozen and self._buf.sample_count > 0:
            if self._history_mode and self._history_target_t is not None:
                min_t, max_t = self._buf.time_bounds()
                if min_t is not None and max_t is not None:
                    if self._history_target_t < min_t or self._history_target_t > max_t:
                        rms_u = self._show_history_view(self._history_target_t)
                    else:
                        self._update_history_controls()
            elif new_frames > 0 or len(self._latest_t) == 0:
                rms_u = self._show_live_view()
            else:
                self._update_history_controls()
        elif self._buf.sample_count > 0:
            self._update_history_controls()

        if self._provider is None and new_frames == 0 and self._buf.sample_count == 0:
            return

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
            drop_suffix = ""
            if getattr(self._provider, "frames_dropped", 0):
                drop_suffix = f" | dropped: {self._provider.frames_dropped}"
            if isinstance(self._provider, QualFileProvider):
                self._lbl_diag.setText(
                    f"playback: {Path(self._play_path).name} | loaded: {self._provider.loaded_frames} | replayed: {self._provider.frames_rx}{drop_suffix}")
            else:
                self._lbl_diag.setText(
                    f"lines: {self._provider.lines_rx} | frames: {self._provider.frames_rx}{drop_suffix}")
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
        t_rel = self._latest_t
        t_abs = self._latest_t_abs if len(self._latest_t_abs) == len(self._latest_t) else self._latest_t
        u_v = self._latest_u
        if len(t_rel) < 1:
            self._lbl_cursor.setText("Cursor: —")
            return

        idx = int(np.searchsorted(t_rel, x))
        idx = max(0, min(idx, len(t_rel) - 1))
        if idx > 0 and abs(t_rel[idx - 1] - x) <= abs(t_rel[idx] - x):
            idx -= 1

        self._vline.setPos(float(t_rel[idx]))
        t_val = float(t_abs[idx])
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
