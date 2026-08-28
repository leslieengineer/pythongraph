"""
QUAL Waveform Viewer
====================
"""
from __future__ import annotations
 
import os
import queue
import sys
import time
import csv
from pathlib import Path
 
import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt, QTimer, QUrl, QStandardPaths
from PyQt5.QtGui import QDesktopServices, QIcon
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QSpinBox, QFormLayout,
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QSizePolicy, QSlider, QVBoxLayout, QWidget, QMessageBox, QListWidget
)
 
from logger import QualDataLogger, export_csv_snapshot, prepare_csv_log
from providers import (
    QualFileProvider, QualSerialProvider, QualSimulationProvider, list_serial_ports,
)
 
# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
 
BUFFER_SECS = 120.0
DEFAULT_SPC = 312
DEFAULT_FREQ = 50.0
MAX_SAMPLES = int(BUFFER_SECS * (DEFAULT_SPC / 2.0) * DEFAULT_FREQ * 1.2)
REFRESH_MS  = 33           
GUI_QUEUE_SECS = 1.0       
GUI_QUEUE_MAX  = int((DEFAULT_SPC / 2.0) * DEFAULT_FREQ * GUI_QUEUE_SECS)
RENDER_SOFT_LIMIT = 20_000
SAMPLE_DOT_RENDER_LIMIT = 4_000
SAMPLE_DOT_SIZE = 4
HISTORY_SLIDER_STEPS = 10_000
 
COLORS_V      = ("#FF4040", "#40FF40", "#4080FF")
PHASE_LABELS  = ("Phase 1", "Phase 2", "Phase 3")
COMPOUND_CHANNELS = (
    ("P1-2", "Coupled Phase 1-2", "#FFD866", 0, 1),
    ("P2-3", "Coupled Phase 2-3", "#FF9F1C", 1, 2),
    ("P3-1", "Coupled Phase 3-1", "#7FDBFF", 2, 0),
)
 
pg.setConfigOptions(antialias=False, background="#1A1A2E", foreground="#E0E0E0")
 
def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)
 
# ---------------------------------------------------------------------------
# Rolling buffer
# ---------------------------------------------------------------------------
class _RollingBuffer:
    def __init__(self, capacity: int):
        self._cap    = capacity
        self._t      = np.empty(capacity, dtype=np.float64)
        self._u      = np.empty((3, capacity), dtype=np.float32)
        self._fw_min = np.zeros(capacity, dtype=np.int16)
        self._fw_sec = np.zeros(capacity, dtype=np.int8)
        self._fw_ms  = np.zeros(capacity, dtype=np.int16)
        self._head = 0   
        self._size = 0   
 
    def push(self, t_s: float, u, fw_min=0, fw_sec=0, fw_ms=0):
        idx = self._head
        self._t[idx]      = t_s
        self._u[:, idx]   = u
        self._fw_min[idx] = fw_min
        self._fw_sec[idx] = fw_sec
        self._fw_ms[idx]  = fw_ms
        self._head = (self._head + 1) % self._cap
        if self._size < self._cap:
            self._size += 1
 
    def view(self, window_s: float):
        if self._size == 0:
            empty = np.empty(0, dtype=np.float64)
            return empty, [empty, empty, empty]
        cap = self._cap
        n_scan = min(self._size, max(64, int(window_s * 2.0)))
        if self._size < cap:
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
        idx = np.arange(self._head - n_scan, self._head) % cap
        t_all = self._t[idx]
        t_max = t_all[-1]
        view_start = int(np.searchsorted(t_all, t_max - window_s, side="left"))
        idx_view = idx[view_start:]
        t_rel = t_all[view_start:] - t_max + window_s
        u_v = [self._u[ph, idx_view] for ph in range(3)]
        return t_rel, u_v
 
    @staticmethod
    def rms(u_v):
        res = []
        for d in u_v:
            if len(d) == 0 or np.all(np.isnan(d)):
                res.append(0.0)
            else:
                res.append(float(np.sqrt(np.nanmean(d ** 2))))
        return res
 
    def reset(self):
        self._head = 0
        self._size = 0
 
    def all_data(self):
        if self._size == 0:
            empty = np.empty(0, dtype=np.float64)
            return empty, [empty, empty, empty]
        if self._size < self._cap:
            return self._t[:self._size].copy(), [self._u[ph, :self._size].copy() for ph in range(3)]
        idx = (np.arange(self._size) + self._head) % self._cap
        return self._t[idx].copy(), [self._u[ph, idx].copy() for ph in range(3)]
 
    def all_fw_data(self):
        empty_i = np.empty(0, dtype=np.int16)
        if self._size == 0:
            return empty_i, empty_i, empty_i
        if self._size < self._cap:
            return self._fw_min[:self._size].copy(), self._fw_sec[:self._size].copy(), self._fw_ms[:self._size].copy()
        idx = (np.arange(self._size) + self._head) % self._cap
        return self._fw_min[idx].copy(), self._fw_sec[idx].copy(), self._fw_ms[idx].copy()
 
    def time_bounds(self):
        if self._size == 0: return None, None
        if self._size < self._cap: return float(self._t[0]), float(self._t[self._size - 1])
        return float(self._t[self._head]), float(self._t[(self._head - 1) % self._cap])
 
    def latest_time(self):
        _, latest_t = self.time_bounds()
        return latest_t
 
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
        self.setWindowTitle("QUAL Waveform Viewer  — AMR")
        
        icon_file = get_resource_path("app_icon.ico")
        if os.path.exists(icon_file):
            self.setWindowIcon(QIcon(icon_file))
 
        self._gui_q = queue.Queue(maxsize=GUI_QUEUE_MAX)
        self._log_q = queue.Queue()
        self._provider = None
        self._logger = None
        self._buf = _RollingBuffer(MAX_SAMPLES)
        self._frames_total = self._frames_since = 0
        self._tick_ts = time.monotonic()
        self._frozen = False
        self._u_gain = 1.0
        self._syncing_plot_x = False
        self._global_y_min_u = float('inf')
        self._global_y_max_u = float('-inf')
        self._global_y_min_u12 = float('inf')
        self._global_y_max_u12 = float('-inf')
        self._fs_samples_last = 0
        self._fs_ts_last = time.monotonic()
        self._fs_hz = 0.0
        self._play_path = ""
        self._log_path = self._default_log_path()
        self._log_overwrite_requested = False
        
        self._latest_t = np.empty(0, dtype=np.float64)
        self._latest_t_abs = np.empty(0, dtype=np.float64)
        self._latest_u = [np.empty(0, dtype=np.float32) for _ in range(3)]
        self._view_start_t = self._view_end_t = 0.0
        
        self._history_mode = False
        self._history_target_t = None
        self._history_slider_dragging = self._history_spin_editing = False
        self._history_snapshot_dirty = True
        self._history_snapshot_t = np.empty(0, dtype=np.float64)
        self._history_snapshot_u = [np.empty(0, dtype=np.float32) for _ in range(3)]
        
        self._scenario_rules = []
 
        self._build_ui()
        self._build_plot()
        self._update_plot_labels() 
        self.resize(1300, 850)
 
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._on_tick)
 
    def _normalize_log_path(self, path: str):
        normalized = Path(path).expanduser()
        if normalized.exists() and normalized.is_dir():
            normalized = normalized / "qual_log.csv"
        if normalized.suffix.lower() != ".csv":
            normalized = normalized.with_suffix(".csv")
        return str(normalized.resolve())
 
    def _refresh_log_path_ui(self):
        self._btn_log_file.setToolTip(self._log_path)
        self._btn_open_log_folder.setToolTip(str(Path(self._log_path).resolve().parent))
        self._lbl_log_file.setToolTip(self._log_path)
 
    def _set_log_button_idle(self):
        self._btn_log_file.setText(f"📁 {Path(self._log_path).name}")
        self._refresh_log_path_ui()
        self._btn_log_file.setStyleSheet("")
 
    def _set_log_button_armed(self):
        self._btn_log_file.setText(f"⏱ Armed: {Path(self._log_path).name}")
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
        fw_min_all, fw_sec_all, fw_ms_all = self._buf.all_fw_data()
        rows_written = export_csv_snapshot(self._log_path, t_all, u_all,
                                           fw_min_all, fw_sec_all, fw_ms_all)
        if self._chk_log.isChecked():
            self._set_log_button_armed()
            self._lbl_status.setText(f"Saved {rows_written} buffered rows → {self._log_path}  |  Press Start to record")
        else:
            self._set_log_button_idle()
            self._lbl_status.setText(f"Saved {rows_written} buffered rows → {self._log_path}")
 
    # ------------------------------------------------------------------ UI
 
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(6)
        root.setContentsMargins(8, 8, 8, 6)
 
        top_layout = QHBoxLayout()
        root.addLayout(top_layout)
        
        cfg_grp = QGroupBox("Configuration")
        cfg_form = QFormLayout(cfg_grp)
        cfg_form.setContentsMargins(8, 8, 8, 8)
        
        self._spin_spc = QSpinBox()
        self._spin_spc.setRange(10, 10000)
        self._spin_spc.setValue(312)
        self._spin_spc.setToolTip("Firmware acquisition samples per cycle. The app automatically calculates the 1/2 resolution subsampled rate.")
        self._spin_spc.valueChanged.connect(self._update_window_samples)
        cfg_form.addRow("Samples/Cycle:", self._spin_spc)
        
        self._spin_grid_freq = QDoubleSpinBox()
        self._spin_grid_freq.setRange(10.0, 400.0)
        self._spin_grid_freq.setValue(50.0)
        cfg_form.addRow("Grid Freq (Hz):", self._spin_grid_freq)
        
        self._spin_adc_scale = QDoubleSpinBox()
        self._spin_adc_scale.setRange(0.0001, 1e9)
        self._spin_adc_scale.setDecimals(4)
        self._spin_adc_scale.setValue(1.0)
        self._spin_adc_scale.valueChanged.connect(self._update_plot_labels)
        cfg_form.addRow("Scale (ADC->Unit):", self._spin_adc_scale)
        top_layout.addWidget(cfg_grp)
 
        conn_grp = QGroupBox("Connection / Data")
        conn_form = QFormLayout(conn_grp)
        conn_form.setContentsMargins(8, 8, 8, 8)
        
        self._cb_mode = QComboBox()
        self._cb_mode.addItems(["Online (COM)", "Simulation", "Playback (log)"])
        self._cb_mode.currentIndexChanged.connect(self._on_mode_changed)
        conn_form.addRow("Mode:", self._cb_mode)
 
        port_box = QHBoxLayout()
        port_box.setContentsMargins(0, 0, 0, 0)
        self._cb_port = QComboBox()
        self._cb_port.setEditable(True)
        self._cb_port.addItem("COM1")
        port_box.addWidget(self._cb_port)
        self._btn_refresh = QPushButton("⟳")
        self._btn_refresh.setFixedWidth(28)
        self._btn_refresh.clicked.connect(self._refresh_ports)
        port_box.addWidget(self._btn_refresh)
        
        self._cb_baud = QComboBox()
        self._cb_baud.setEditable(True)
        self._cb_baud.addItems(["9600", "19200", "38400", "57600", "115200",
                                "230400", "460800", "921600", "960000", "2000000", "4000000"])
        self._cb_baud.setCurrentText("2000000")
        
        self._lbl_port = QLabel("Port:")
        self._lbl_baud = QLabel("Baud:")
        conn_form.addRow(self._lbl_port, port_box)
        conn_form.addRow(self._lbl_baud, self._cb_baud)
 
        self._spin_vrms = QDoubleSpinBox()
        self._spin_vrms.setRange(0.0, 1e8)
        self._spin_vrms.setValue(230_000.0)
        self._spin_vrms.setDecimals(0)
        self._spin_vrms.setSingleStep(10_000.0)
        self._lbl_vrms = QLabel("V_rms (mV):")
        
        self._spin_phi = QDoubleSpinBox()
        self._spin_phi.setRange(-180.0, 180.0)
        self._spin_phi.setValue(0.0)
        self._spin_phi.setDecimals(1)
        self._lbl_phi = QLabel("φ (°):")
        
        conn_form.addRow(self._lbl_vrms, self._spin_vrms)
        conn_form.addRow(self._lbl_phi, self._spin_phi)
 
        self._lbl_file = QLabel("Playback File:")
        
        file_box = QHBoxLayout()
        file_box.setContentsMargins(0, 0, 0, 0)
        self._btn_pick_file = QPushButton("📁 Choose File...")
        self._btn_pick_file.clicked.connect(self._pick_log)
        file_box.addWidget(self._btn_pick_file)
        
        # Nút tính năng mới để xuất ra file array C/C++
        self._btn_export_inc = QPushButton("📄 Export .inc")
        self._btn_export_inc.setToolTip("Export Playback CSV to C/C++ .inc array")
        self._btn_export_inc.clicked.connect(self._export_inc_file)
        file_box.addWidget(self._btn_export_inc)

        self._spin_speed = QDoubleSpinBox()
        self._spin_speed.setRange(0.1, 100.0)
        self._spin_speed.setValue(1.0)
        self._lbl_speed = QLabel("Speed:")
        
        conn_form.addRow(self._lbl_file, file_box)
        conn_form.addRow(self._lbl_speed, self._spin_speed)
        top_layout.addWidget(conn_grp)
 
        act_grp = QGroupBox("Actions")
        act_vbox = QVBoxLayout(act_grp)
        act_vbox.setContentsMargins(8, 8, 8, 8)
        
        ctrl_box = QHBoxLayout()
        self._btn_start = QPushButton("▶  Start")
        self._btn_start.setStyleSheet("background:#1A6E2E; color:white; font-weight:bold; font-size:13px;")
        self._btn_start.setCheckable(True)
        self._btn_start.setMinimumHeight(34)
        self._btn_start.clicked.connect(self._on_startstop)
        ctrl_box.addWidget(self._btn_start)
        
        self._btn_freeze = QPushButton("❚❚ Freeze")
        self._btn_freeze.setCheckable(True)
        self._btn_freeze.setMinimumHeight(34)
        self._btn_freeze.setVisible(False)
        self._btn_freeze.clicked.connect(self._on_freeze)
        ctrl_box.addWidget(self._btn_freeze)
        act_vbox.addLayout(ctrl_box)
        
        log_box = QHBoxLayout()
        self._chk_log = QCheckBox("Log to CSV")
        self._chk_log.stateChanged.connect(self._on_log_toggle)
        log_box.addWidget(self._chk_log)
        
        self._btn_log_file = QPushButton(f"📁 {Path(self._log_path).name}")
        self._btn_log_file.setToolTip("Change save destination")
        self._btn_log_file.clicked.connect(self._pick_log_file)
        log_box.addWidget(self._btn_log_file)
        
        self._btn_open_log_folder = QPushButton("📂")
        self._btn_open_log_folder.setFixedWidth(36)
        self._btn_open_log_folder.setToolTip("Open Directory")
        self._btn_open_log_folder.clicked.connect(self._open_log_folder)
        log_box.addWidget(self._btn_open_log_folder)
        act_vbox.addLayout(log_box)
        act_vbox.addStretch(1)
        top_layout.addWidget(act_grp)
 
        self._grp_scenario = QGroupBox("Scenario Builder (Playback Only)")
        scenario_hbox = QHBoxLayout(self._grp_scenario)
        scenario_hbox.setContentsMargins(8, 8, 8, 8)
        
        scenario_hbox.addWidget(QLabel("Start:"))
        self._spin_sc_start = QSpinBox()
        self._spin_sc_start.setRange(0, 999999999)
        scenario_hbox.addWidget(self._spin_sc_start)
        
        scenario_hbox.addWidget(QLabel("End:"))
        self._spin_sc_end = QSpinBox()
        self._spin_sc_end.setRange(0, 999999999)
        scenario_hbox.addWidget(self._spin_sc_end)
        
        self._cb_sc_phase = QComboBox()
        self._cb_sc_phase.addItems(["All", "Phase 1", "Phase 2", "Phase 3", "P1+P2", "P2+P3", "P3+P1"])
        scenario_hbox.addWidget(self._cb_sc_phase)
        
        self._cb_sc_action = QComboBox()
        self._cb_sc_action.addItems(["Scale (%)", "Cut to 0", "Add Harmonic", "Add Flicker", "Crop/Delete"])
        self._cb_sc_action.currentTextChanged.connect(self._on_sc_action_changed)
        scenario_hbox.addWidget(self._cb_sc_action)
        
        self._lbl_sc_v1 = QLabel("Val 1:")
        self._lbl_sc_v1.setMinimumWidth(60)
        scenario_hbox.addWidget(self._lbl_sc_v1)
        self._spin_sc_v1 = QDoubleSpinBox()
        self._spin_sc_v1.setRange(-1000.0, 1000.0)
        scenario_hbox.addWidget(self._spin_sc_v1)
        
        self._lbl_sc_v2 = QLabel("Val 2:")
        self._lbl_sc_v2.setMinimumWidth(60)
        scenario_hbox.addWidget(self._lbl_sc_v2)
        self._spin_sc_v2 = QDoubleSpinBox()
        self._spin_sc_v2.setRange(0.0, 1000.0)
        scenario_hbox.addWidget(self._spin_sc_v2)
        
        btn_sc_add = QPushButton("➕")
        btn_sc_add.setFixedWidth(36)
        btn_sc_add.clicked.connect(self._add_scenario_rule)
        scenario_hbox.addWidget(btn_sc_add)
        
        self._list_sc_rules = QListWidget()
        self._list_sc_rules.setMaximumHeight(40)
        scenario_hbox.addWidget(self._list_sc_rules, stretch=1)
        
        btn_sc_clear = QPushButton("🗑")
        btn_sc_clear.setFixedWidth(36)
        btn_sc_clear.clicked.connect(self._clear_scenario_rules)
        scenario_hbox.addWidget(btn_sc_clear)
        
        btn_sc_build = QPushButton("▶ Build Scenario")
        btn_sc_build.setStyleSheet("background:#7A5A00; color:#FFD866; font-weight:bold")
        btn_sc_build.clicked.connect(self._build_scenario)
        scenario_hbox.addWidget(btn_sc_build)
        
        root.addWidget(self._grp_scenario)
        self._on_sc_action_changed(self._cb_sc_action.currentText())

        disp_bar = QWidget()
        disp_vbox = QVBoxLayout(disp_bar)
        disp_vbox.setContentsMargins(0, 4, 0, 4)
        disp_vbox.setSpacing(8)
        
        disp_row1 = QHBoxLayout()
        disp_row1.addWidget(QLabel("Window (cyc):"))
        self._spin_window = QSpinBox()
        self._spin_window.setRange(1, 5000)
        self._spin_window.setValue(4)
        self._spin_window.setFixedWidth(60)
        self._spin_window.valueChanged.connect(self._update_window_samples)
        disp_row1.addWidget(self._spin_window)
        
        disp_row1.addWidget(QLabel("  Zoom (×):"))
        self._spin_ugain = QDoubleSpinBox()
        self._spin_ugain.setRange(1e-9, 1e6)
        self._spin_ugain.setValue(1.0)
        self._spin_ugain.setDecimals(4)
        self._spin_ugain.setSingleStep(0.1)
        self._spin_ugain.setFixedWidth(80)
        self._spin_ugain.valueChanged.connect(self._on_ugain_changed)
        disp_row1.addWidget(self._spin_ugain)
        
        disp_row1.addSpacing(16)
        self._chk_sample_dots = QCheckBox("Dots")
        self._chk_sample_dots.setChecked(True)
        self._chk_sample_dots.stateChanged.connect(self._on_plot_style_changed)
        disp_row1.addWidget(self._chk_sample_dots)
        
        disp_row1.addSpacing(16)
        disp_row1.addWidget(QLabel("Show:"))
        self._chk_u = []
        for label in ("P1", "P2", "P3"):
            chk = QCheckBox(label)
            chk.setChecked(True)
            chk.stateChanged.connect(self._on_channel_toggle)
            disp_row1.addWidget(chk)
            self._chk_u.append(chk)
            
        disp_row1.addSpacing(16)
        disp_row1.addWidget(QLabel("Coupled:"))
        self._chk_compound = []
        for short_label, _f, _c, _sa, _sb in COMPOUND_CHANNELS:
            chk = QCheckBox(short_label)
            chk.setChecked(True)
            chk.stateChanged.connect(self._on_channel_toggle)
            disp_row1.addWidget(chk)
            self._chk_compound.append(chk)
            
        disp_row1.addStretch(1)
        disp_vbox.addLayout(disp_row1)
        
        disp_row2 = QHBoxLayout()
        disp_row2.addWidget(QLabel("History Index:"))
        
        self._spin_history = QDoubleSpinBox()
        self._spin_history.setRange(0.0, 1.0)
        self._spin_history.setDecimals(0)
        self._spin_history.setSingleStep(100.0)
        self._spin_history.setKeyboardTracking(False)
        self._spin_history.setFixedWidth(90)
        self._spin_history.lineEdit().textEdited.connect(self._on_history_text_edited)
        self._spin_history.editingFinished.connect(self._on_history_go)
        disp_row2.addWidget(self._spin_history)
        
        self._btn_history_go = QPushButton("Go")
        self._btn_history_go.setFixedWidth(36)
        self._btn_history_go.clicked.connect(self._on_history_go)
        disp_row2.addWidget(self._btn_history_go)
        
        self._sld_history = QSlider(Qt.Horizontal)
        self._sld_history.setRange(0, HISTORY_SLIDER_STEPS)
        self._sld_history.setTracking(True)
        self._sld_history.sliderPressed.connect(self._on_history_slider_pressed)
        self._sld_history.sliderReleased.connect(self._on_history_slider_released)
        self._sld_history.valueChanged.connect(self._on_history_slider_changed)
        disp_row2.addWidget(self._sld_history, stretch=1)
        
        self._btn_back_to_live = QPushButton("⬤ Live")
        self._btn_back_to_live.setFixedWidth(60)
        self._btn_back_to_live.clicked.connect(self._on_back_to_live)
        disp_row2.addWidget(self._btn_back_to_live)
        
        self._lbl_history_state = QLabel("Live")
        self._lbl_history_state.setStyleSheet("color:#AAB2D5;")
        self._lbl_history_state.setMinimumWidth(140)
        disp_row2.addWidget(self._lbl_history_state)
        
        disp_vbox.addLayout(disp_row2)
        root.addWidget(disp_bar)
 
        self._plot_area = QVBoxLayout()
        root.addLayout(self._plot_area, stretch=1)
 
        _sb_widget = QWidget()
        _sb_widget.setStyleSheet("background:#0D0D1A; border-top:1px solid #333;")
        _sb_row = QHBoxLayout(_sb_widget)
        _sb_row.setContentsMargins(6, 4, 6, 4)
        _sb_row.setSpacing(8)
        root.addWidget(_sb_widget)
 
        def _mk_sb_lbl(text, max_w, style=""):
            lbl = QLabel(text)
            lbl.setMinimumWidth(1)
            lbl.setMaximumWidth(max_w)
            lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            if style: lbl.setStyleSheet(style)
            return lbl
 
        self._lbl_status   = _mk_sb_lbl("Stopped",              260)
        self._lbl_diag     = _mk_sb_lbl("lines: 0 | frames: 0", 280)
        self._lbl_rms_v    = _mk_sb_lbl("RMS: —",               300)
        self._lbl_fs       = _mk_sb_lbl("fs: —",                 95)
        self._lbl_fps      = _mk_sb_lbl("fps: —",                65)
        self._lbl_log_file = _mk_sb_lbl("",                      180, "color:#AAB2D5; font-family:monospace;")
        self._lbl_log_file.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._lbl_cursor   = _mk_sb_lbl("Cursor: —", 420, "color:#FFD700; font-family:monospace;")
 
        for w in (self._lbl_status, self._lbl_diag, self._lbl_rms_v, self._lbl_fs, self._lbl_fps):
            _sb_row.addWidget(w)
            _sb_row.addWidget(_sep())
        _sb_row.addStretch(1)
        _sb_row.addWidget(self._lbl_log_file)
        _sb_row.addWidget(_sep())
        _sb_row.addWidget(self._lbl_cursor)
 
        self._refresh_log_path_ui()
        self._refresh_ports()
        self._on_mode_changed(0)
        self._update_history_controls()
 
    def _get_unit_str(self):
        return "ADC" if self._spin_adc_scale.value() == 1.0 else "mV"
 
    def _update_plot_labels(self, *_args):
        unit = self._get_unit_str()
        title_main = f"Phase Values [{unit}]"
        self._pw.setTitle(title_main)
        self._pw.setLabel("left", "Value", units=unit)
        
        title_comp = f"Coupled Phase Values [{unit}]"
        self._pw_u12.setTitle(title_comp)
        self._pw_u12.setLabel("left", "Value", units=unit)
 
    def _build_plot(self):
        eff_spc = self._spin_spc.value() / 2.0
        self._win_s = float(self._spin_window.value() * eff_spc)

        self._pw = pg.PlotWidget()
        self._pw.showGrid(x=True, y=True, alpha=0.25)
        self._pw.setLabel("bottom", "Index", units="samples")
        self._pw.addLegend(offset=(10, 10))
        self._pw.setMouseEnabled(x=True, y=False)
        self._pw.getAxis('left').enableAutoSIPrefix(False)
        
        self._pw.setLimits(xMin=0.0, xMax=self._win_s)
        
        self._curve_pens = [pg.mkPen(col, width=1.5) for col in COLORS_V]
        self._curve_brushes = [pg.mkBrush(col) for col in COLORS_V]
        self._curves = [
            self._pw.plot([], [], name=lbl, pen=pen, connect="finite")
            for lbl, pen in zip(PHASE_LABELS, self._curve_pens)
        ]
        for curve in self._curves:
            curve.setClipToView(True)
            curve.setDownsampling(auto=True, method="peak")
 
        _cp = pg.mkPen(color="#FFFFFF90", width=1, style=Qt.DashLine)
        self._vline = pg.InfiniteLine(angle=90, movable=False, pen=_cp)
        self._hline = pg.InfiniteLine(angle=0,  movable=False, pen=_cp)
        self._zero_hline = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(color="#7FDBFF", width=1))
        
        _bound_pen = pg.mkPen(color="#6A6A8C", width=3)
        self._bound_start_main = pg.InfiniteLine(angle=90, movable=False, pen=_bound_pen)
        self._bound_end_main = pg.InfiniteLine(angle=90, movable=False, pen=_bound_pen)
        self._pw.addItem(self._bound_start_main, ignoreBounds=True)
        self._pw.addItem(self._bound_end_main, ignoreBounds=True)
        self._bound_start_main.setPos(0.0)
        self._bound_end_main.setPos(self._win_s)

        self._pw.addItem(self._zero_hline, ignoreBounds=True)
        self._pw.addItem(self._vline, ignoreBounds=True)
        self._pw.addItem(self._hline, ignoreBounds=True)
 
        self._history_vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(color="#FFD866", width=2, style=Qt.DashLine))
        self._history_vline.setVisible(False)
        self._pw.addItem(self._history_vline, ignoreBounds=True)
 
        self._mouse_proxy = pg.SignalProxy(self._pw.scene().sigMouseMoved, rateLimit=60, slot=self._on_mouse)
        self._plot_area.addWidget(self._pw, stretch=1)
 
        self._pw_u12 = pg.PlotWidget()
        self._pw_u12.showGrid(x=True, y=True, alpha=0.25)
        self._pw_u12.setLabel("bottom", "Index", units="samples")
        self._pw_u12.addLegend(offset=(10, 10))
        self._pw_u12.setMouseEnabled(x=True, y=False)
        self._pw_u12.getAxis('left').enableAutoSIPrefix(False)
        
        self._pw_u12.setLimits(xMin=0.0, xMax=self._win_s)
 
        self._compound_pens = [pg.mkPen(color, width=1.5) for _sl, _fl, color, _sa, _sb in COMPOUND_CHANNELS]
        self._compound_brushes = [pg.mkBrush(color) for _sl, _fl, color, _sa, _sb in COMPOUND_CHANNELS]
        self._compound_curves = [
            self._pw_u12.plot([], [], name=fl, pen=pen, connect="finite")
            for (_sl, fl, _c, _sa, _sb), pen in zip(COMPOUND_CHANNELS, self._compound_pens)
        ]
        for curve in self._compound_curves:
            curve.setClipToView(True)
            curve.setDownsampling(auto=True, method="peak")
 
        self._zero_hline_u12 = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(color="#7FDBFF", width=1))
        self._pw_u12.addItem(self._zero_hline_u12, ignoreBounds=True)
        
        self._bound_start_u12 = pg.InfiniteLine(angle=90, movable=False, pen=_bound_pen)
        self._bound_end_u12 = pg.InfiniteLine(angle=90, movable=False, pen=_bound_pen)
        self._pw_u12.addItem(self._bound_start_u12, ignoreBounds=True)
        self._pw_u12.addItem(self._bound_end_u12, ignoreBounds=True)
        self._bound_start_u12.setPos(0.0)
        self._bound_end_u12.setPos(self._win_s)

        self._vline_u12 = pg.InfiniteLine(angle=90, movable=False, pen=_cp)
        self._hline_u12 = pg.InfiniteLine(angle=0, movable=False, pen=_cp)
        self._pw_u12.addItem(self._vline_u12, ignoreBounds=True)
        self._pw_u12.addItem(self._hline_u12, ignoreBounds=True)
 
        self._history_vline_u12 = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(color="#FFD866", width=2, style=Qt.DashLine))
        self._history_vline_u12.setVisible(False)
        self._pw_u12.addItem(self._history_vline_u12, ignoreBounds=True)
 
        self._mouse_proxy_u12 = pg.SignalProxy(self._pw_u12.scene().sigMouseMoved, rateLimit=60, slot=self._on_mouse_u12)
        self._plot_area.addWidget(self._pw_u12, stretch=1)
 
        self._pw.setXRange(0.0, self._win_s, padding=0.0)
        self._pw_u12.setXRange(0.0, self._win_s, padding=0.0)
        self._pw.plotItem.sigXRangeChanged.connect(self._on_main_x_range_changed)
        self._pw_u12.plotItem.sigXRangeChanged.connect(self._on_compound_x_range_changed)
 
    def _on_mode_changed(self, idx):
        online = (idx == 0)
        sim    = (idx == 1)
        play   = (idx == 2)
        
        self._grp_scenario.setVisible(play)
        for w in (self._lbl_port, self._cb_port, self._btn_refresh, self._lbl_baud, self._cb_baud):
            w.setVisible(online)
        for w in (self._lbl_vrms, self._spin_vrms, self._lbl_phi,  self._spin_phi):
            w.setVisible(sim)
        for w in (self._lbl_file, self._btn_pick_file, self._btn_export_inc, self._lbl_speed, self._spin_speed):
            w.setVisible(play)
            
        for w in (self._chk_log, self._btn_log_file, self._btn_open_log_folder):
            w.setVisible(not play)
 
    def _on_sc_action_changed(self, action):
        v1_show = v2_show = False
        lbl_v1 = lbl_v2 = ""
        if action == "Scale (%)":
            v1_show = True; lbl_v1 = "Amp (%):"
        elif action == "Add Harmonic":
            v1_show = v2_show = True; lbl_v1 = "Amp (%):"; lbl_v2 = "Order:"
        elif action == "Add Flicker":
            v1_show = v2_show = True; lbl_v1 = "Amp (%):"; lbl_v2 = "Freq (Hz):"
            
        self._lbl_sc_v1.setText(lbl_v1); self._lbl_sc_v1.setVisible(v1_show); self._spin_sc_v1.setVisible(v1_show)
        self._lbl_sc_v2.setText(lbl_v2); self._lbl_sc_v2.setVisible(v2_show); self._spin_sc_v2.setVisible(v2_show)
        
    def _add_scenario_rule(self):
        start = self._spin_sc_start.value()
        end = self._spin_sc_end.value()
        if start >= end:
            QMessageBox.warning(self, "Error", "Start Index must be less than End Index!")
            return
        action = self._cb_sc_action.currentText()
        v1 = self._spin_sc_v1.value()
        v2 = self._spin_sc_v2.value()
        phase = self._cb_sc_phase.currentText()
        if action == "Crop/Delete" and phase != "All": phase = "All"
        self._scenario_rules.append({"start": start, "end": end, "action": action, "v1": v1, "v2": v2, "phase": phase})
        
        text = f"[{start} ➔ {end}] [{phase}] {action}"
        if action in ("Scale (%)", "Add Harmonic", "Add Flicker"): text += f" | {self._lbl_sc_v1.text()} {v1}"
        if action in ("Add Harmonic", "Add Flicker"): text += f" | {self._lbl_sc_v2.text()} {v2}"
        self._list_sc_rules.addItem(text)
        
    def _clear_scenario_rules(self):
        self._scenario_rules.clear()
        self._list_sc_rules.clear()
        
    def _build_scenario(self):
        if not self._play_path or not Path(self._play_path).exists():
            QMessageBox.warning(self, "Error", "Please select a source log file before building!")
            return
        if not self._scenario_rules:
            QMessageBox.warning(self, "Error", "No rules have been added!")
            return
            
        try:
            t_list, u1, u2, u3, fw_min, fw_sec, fw_ms = [], [], [], [], [], [], []
            with open(self._play_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    idx = float(row.get('index', row.get('t_s', 0)))
                    t_list.append(idx)
                    u1.append(float(row.get('P1_val', row.get('U1_mV', 0))))
                    u2.append(float(row.get('P2_val', row.get('U2_mV', 0))))
                    u3.append(float(row.get('P3_val', row.get('U3_mV', 0))))
                    fw_min.append(int(row.get('fw_min', 0)) if row.get('fw_min') else 0)
                    fw_sec.append(int(row.get('fw_sec', 0)) if row.get('fw_sec') else 0)
                    fw_ms.append(int(row.get('fw_ms', 0)) if row.get('fw_ms') else 0)
            
            t_arr = np.array(t_list, dtype=np.float64)
            u_arr = [np.array(u1, dtype=np.float32), np.array(u2, dtype=np.float32), np.array(u3, dtype=np.float32)]
            fw_min_arr = np.array(fw_min, dtype=np.int16)
            fw_sec_arr = np.array(fw_sec, dtype=np.int8)
            fw_ms_arr = np.array(fw_ms, dtype=np.int16)
            
            spc = self._spin_spc.value()
            eff_spc = spc / 2.0  
            grid_freq = self._spin_grid_freq.value()
            
            phase_map = {
                "All": [0, 1, 2], "Phase 1": [0], "Phase 2": [1], "Phase 3": [2],
                "P1+P2": [0, 1], "P2+P3": [1, 2], "P3+P1": [0, 2]
            }
            
            for rule in self._scenario_rules:
                start, end, action, v1, v2, phase = rule['start'], rule['end'], rule['action'], rule['v1'], rule['v2'], rule['phase']
                mask = (t_arr >= start) & (t_arr <= end)
                if not np.any(mask): continue
                    
                target_idx = phase_map.get(phase, [0, 1, 2])
                
                if action == "Scale (%)":
                    factor = v1 / 100.0
                    for i in target_idx: u_arr[i][mask] *= factor
                elif action == "Cut to 0":
                    for i in target_idx: u_arr[i][mask] = 0.0
                elif action == "Add Harmonic":
                    amp_pct = v1 / 100.0
                    order = v2
                    angle_u1 = (2 * np.pi * t_arr[mask] * order) / eff_spc
                    angles = [angle_u1, angle_u1 - order * (2 * np.pi / 3), angle_u1 + order * (2 * np.pi / 3)]
                    for i in target_idx:
                        peak_val = np.max(np.abs(u_arr[i])) if len(u_arr[i]) > 0 else 230000
                        u_arr[i][mask] += (peak_val * amp_pct) * np.sin(angles[i])
                elif action == "Add Flicker":
                    amp_pct, f_freq = v1 / 100.0, v2
                    fs = eff_spc * grid_freq
                    modulation = 1.0 + amp_pct * np.sin(2 * np.pi * f_freq * (t_arr[mask] / fs))
                    for i in target_idx: u_arr[i][mask] *= modulation
                elif action == "Crop/Delete":
                    keep_mask = ~mask
                    t_arr = np.arange(len(t_arr[keep_mask]), dtype=np.float64)
                    for i in range(3): u_arr[i] = u_arr[i][keep_mask]
                    fw_min_arr, fw_sec_arr, fw_ms_arr = fw_min_arr[keep_mask], fw_sec_arr[keep_mask], fw_ms_arr[keep_mask]
            
            default_name = str(Path(self._play_path).with_name(f"scenario_{Path(self._play_path).name}"))
            save_path, _ = QFileDialog.getSaveFileName(self, "Save Scenario CSV", default_name, "CSV files (*.csv)")
            if save_path:
                export_csv_snapshot(save_path, t_arr.tolist(), [u_arr[0].tolist(), u_arr[1].tolist(), u_arr[2].tolist()],
                                    fw_min_arr.tolist(), fw_sec_arr.tolist(), fw_ms_arr.tolist())
                self._play_path = save_path
                self._btn_pick_file.setText(f"📁 {Path(self._play_path).name}")
                QMessageBox.information(self, "Success", f"Scenario built and loaded:\n{save_path}")
        except Exception as e:
            QMessageBox.critical(self, "Build Error", str(e))
 
    def _refresh_ports(self):
        current = self._cb_port.currentText()
        self._cb_port.clear()
        ports = list_serial_ports()
        if "COM1" not in ports: ports.insert(0, "COM1")
        self._cb_port.addItems(ports)
        self._cb_port.setCurrentText(current if current in ports else "COM1")
 
    def _pick_log(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open QUAL log", str(Path.home()), "Log files (*.txt *.log *.csv);;All files (*)")
        if path:
            self._play_path = path
            self._btn_pick_file.setText(f"📁 {Path(path).name}")
 
    def _export_inc_file(self):
        if not self._play_path or not Path(self._play_path).exists():
            QMessageBox.warning(self, "Error", "Please select a valid Playback File first!")
            return
            
        default_name = str(Path(self._play_path).with_suffix(".inc"))
        save_path, _ = QFileDialog.getSaveFileName(self, "Export .inc File", default_name, "Include files (*.inc);;All files (*)")
        if not save_path:
            return
            
        try:
            output_lines = []
            with open(self._play_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
                
                # Tự động nhận diện định dạng cột (Chuẩn mới P1_val hoặc chuẩn cũ U1_mV)
                c1 = 'P1_val' if 'P1_val' in headers else ('U1_mV' if 'U1_mV' in headers else None)
                c2 = 'P2_val' if 'P2_val' in headers else ('U2_mV' if 'U2_mV' in headers else None)
                c3 = 'P3_val' if 'P3_val' in headers else ('U3_mV' if 'U3_mV' in headers else None)
                
                if not (c1 and c2 and c3):
                    QMessageBox.warning(self, "Error", f"Missing required columns in CSV (P1_val/P2_val/P3_val or U1_mV/U2_mV/U3_mV).\nFound headers: {headers}")
                    return
                
                for row in reader:
                    try:
                        # Convert float to rounded int for C++ array compatibility
                        v1 = int(round(float(row[c1])))
                        v2 = int(round(float(row[c2])))
                        v3 = int(round(float(row[c3])))
                        output_lines.append(f"    {{ {v1}, {v2}, {v3} }},\n")
                    except (ValueError, TypeError):
                        continue
            
            with open(save_path, 'w', encoding='ascii') as out_f:
                out_f.writelines(output_lines)
                
            QMessageBox.information(self, "Success", f"Exported {len(output_lines)} samples to:\n{save_path}")
            
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))
 
    def _pick_log_file(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV log", self._log_path, "CSV files (*.csv)")
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
                self._lbl_status.setText(f"CSV armed  |  {self._log_path}  |  Press Start to record")
            else:
                self._set_log_button_idle()
                self._lbl_status.setText(f"CSV path set  |  {self._log_path}")
 
    def _start_logger(self):
        if self._logger is not None: return
        self._log_q = queue.Queue()
        self._logger = QualDataLogger(self._log_path, self._log_q, truncate=self._consume_log_overwrite_request())
        self._logger.start()
        if self._provider is not None: self._provider.set_mirror_queue(self._log_q)
        self._btn_log_file.setText(f"⏺ Logging: {Path(self._log_path).name}")
        self._btn_log_file.setStyleSheet("color:#40FF40; font-weight:bold")
        self._lbl_log_file.setText(f"CSV: {Path(self._log_path).name}")
 
    def _stop_logger(self):
        stop_message = None
        if self._provider is not None: self._provider.set_mirror_queue(None)
        if self._logger is not None:
            self._logger.stop()
            if self._logger.error:
                stop_message = f"LOG ERROR: {self._logger.error}"
                self._btn_log_file.setStyleSheet("color:#FF4040; font-weight:bold")
            else:
                stop_message = f"Stopped  |  Logged {self._logger.rows_written} rows → {self._log_path}"
                self._set_log_button_armed() if self._chk_log.isChecked() else self._set_log_button_idle()
            self._logger = None
            self._log_q = queue.Queue()
        return stop_message
 
    def _on_log_toggle(self, checked):
        checked = bool(checked)
        if checked:
            try: self._prime_log_file()
            except Exception as exc:
                self._chk_log.blockSignals(True); self._chk_log.setChecked(False); self._chk_log.blockSignals(False)
                self._lbl_status.setText(f"LOG ERROR: {exc}")
                self._btn_log_file.setStyleSheet("color:#FF4040; font-weight:bold")
                self._btn_log_file.setText(f"📁 {Path(self._log_path).name}")
                return
        if self._provider is None:
            self._lbl_status.setText(f"CSV armed  |  {self._log_path}" if checked else "Stopped")
            if not checked: self._set_log_button_idle()
            return
        if checked:
            self._start_logger()
            self._lbl_status.setText(f"Running  |  Logging to: {self._log_path}")
        else:
            stop_message = self._stop_logger()
            if stop_message is not None: self._lbl_status.setText(stop_message)
 
    def _on_startstop(self, checked):
        if checked: self._on_start()
        else: self._on_stop()
 
    def _on_start(self):
        self._stop_provider()
        
        config = {
            "samples_per_cycle": self._spin_spc.value(),
            "grid_freq": self._spin_grid_freq.value(),
            "adc_scale": self._spin_adc_scale.value()
        }
        
        eff_spc = config["samples_per_cycle"] / 2.0
        max_samples = int(BUFFER_SECS * eff_spc * config["grid_freq"] * 1.2)
        self._buf = _RollingBuffer(max_samples)
        self._spin_history.setRange(0.0, float(max_samples))
        
        self._history_snapshot_dirty = True
        self._history_snapshot_t = np.empty(0, dtype=np.float64)
        self._history_snapshot_u = [np.empty(0, dtype=np.float32) for _ in range(3)]
        self._frames_total = self._frames_since = 0
        self._tick_ts = time.monotonic()
        self._fs_samples_last = 0
        self._fs_ts_last = time.monotonic()
        self._fs_hz = 0.0
        self._history_mode = False
        self._history_target_t = None
        self._latest_t = np.empty(0, dtype=np.float64)
        self._latest_t_abs = np.empty(0, dtype=np.float64)
        self._latest_u = [np.empty(0, dtype=np.float32) for _ in range(3)]
        self._view_start_t = self._view_end_t = 0.0
        self._btn_freeze.blockSignals(True); self._btn_freeze.setChecked(False); self._btn_freeze.blockSignals(False)
        self._frozen = False
        self._btn_freeze.setText("❚❚ Freeze")
        self._btn_freeze.setStyleSheet("")
        self._lbl_cursor.setText("Cursor: —")
        
        self._global_y_min_u = self._global_y_min_u12 = float('inf')
        self._global_y_max_u = self._global_y_max_u12 = float('-inf')
        
        self._update_history_controls()
 
        mode = self._cb_mode.currentIndex()
        if mode == 0:
            port = self._cb_port.currentText().strip() or "COM1"
            baud_str = self._cb_baud.currentText().strip()
            try: baud = int(baud_str)
            except ValueError:
                self._lbl_status.setText("Error: Invalid manual baud rate")
                self._btn_start.blockSignals(True); self._btn_start.setChecked(False); self._btn_start.blockSignals(False)
                return
            self._provider = QualSerialProvider(port, baud, self._gui_q, config)
        elif mode == 1:
            self._provider = QualSimulationProvider(self._gui_q, v_rms_mv=self._spin_vrms.value(), phi_deg=self._spin_phi.value(), config=config)
        else:
            if not self._play_path:
                self._lbl_status.setText("No log file selected")
                self._btn_start.blockSignals(True); self._btn_start.setChecked(False); self._btn_start.blockSignals(False)
                return
            self._provider = QualFileProvider(self._play_path, self._gui_q, speed=self._spin_speed.value(), config=config)
 
        self._provider.start()
        if self._chk_log.isChecked(): self._start_logger()
        self._timer.start()
        self._btn_start.blockSignals(True); self._btn_start.setChecked(True); self._btn_start.blockSignals(False)
        self._btn_start.setText("■  Stop")
        self._btn_start.setStyleSheet("background:#8B0000; color:white; font-weight:bold; font-size:13px;")
        self._btn_freeze.setVisible(True)
        mode_name = ['Online', 'Simulation', 'Playback'][mode]
        self._lbl_status.setText(f"Running  [{mode_name}]  |  Logging to: {self._log_path}" if self._chk_log.isChecked() else f"Running  [{mode_name}]")
 
    def _on_stop(self):
        stop_message = self._stop_provider()
        self._timer.stop()
        self._btn_start.blockSignals(True); self._btn_start.setChecked(False); self._btn_start.blockSignals(False)
        self._btn_start.setText("▶  Start")
        self._btn_start.setStyleSheet("background:#1A6E2E; color:white; font-weight:bold; font-size:13px;")
        self._btn_freeze.setChecked(False); self._btn_freeze.setText("❚❚ Freeze")
        self._btn_freeze.setStyleSheet(""); self._btn_freeze.setVisible(False)
        self._frozen = False
        self._lbl_status.setText(stop_message if stop_message else "Stopped")
 
    def _stop_provider(self):
        stop_message = None
        if self._provider is not None:
            self._provider.stop()
            self._provider = None
        pending_frames = self._drain_gui_queue()
        if pending_frames and not self._frozen:
            self._show_history_view(self._history_target_t) if (self._history_mode and self._history_target_t is not None) else self._show_live_view()
        if self._logger is not None: stop_message = self._stop_logger()
        self._update_history_controls()
        return stop_message
 
    def _on_freeze(self, checked):
        self._frozen = checked
        if checked:
            self._btn_freeze.setText("▶ Resume")
            self._btn_freeze.setStyleSheet("background:#7A5A00; color:#FFD866; font-weight:bold; border:1px solid #FFD866;")
        else:
            self._btn_freeze.setText("❚❚ Freeze")
            self._btn_freeze.setStyleSheet("")
        if not checked and self._buf.sample_count > 0:
            self._show_history_view(self._history_target_t) if (self._history_mode and self._history_target_t is not None) else self._show_live_view()
 
    def _update_window_samples(self, *_args):
        eff_spc = self._spin_spc.value() / 2.0
        self._win_s = float(self._spin_window.value() * eff_spc)
        
        self._pw.setLimits(xMin=0.0, xMax=self._win_s)
        self._pw_u12.setLimits(xMin=0.0, xMax=self._win_s)
        self._bound_end_main.setPos(self._win_s)
        self._bound_end_u12.setPos(self._win_s)

        self._pw.setXRange(0.0, self._win_s, padding=0.0)
        self._pw_u12.setXRange(0.0, self._win_s, padding=0.0)
        if self._buf.sample_count > 0:
            self._show_history_view(self._history_target_t) if (self._history_mode and self._history_target_t is not None) else self._show_live_view()
 
    def _sync_plot_x_range(self, target_plot, x_range):
        if self._syncing_plot_x: return
        self._syncing_plot_x = True
        try: target_plot.setXRange(x_range[0], x_range[1], padding=0.0)
        finally: self._syncing_plot_x = False
 
    def _on_main_x_range_changed(self, _sender, x_range): 
        self._sync_plot_x_range(self._pw_u12, x_range)
        if self._frozen or self._history_mode:
            self._update_dots_visibility()
            
    def _on_compound_x_range_changed(self, _sender, x_range): 
        self._sync_plot_x_range(self._pw, x_range)
        if self._frozen or self._history_mode:
            self._update_dots_visibility()
 
    def _on_ugain_changed(self, v):
        self._u_gain = v
        if len(self._latest_t) > 0:
            self._update_y_zoom(self._latest_u)
            self._update_u12_y_zoom(self._compound_values(self._latest_u))
 
    def _update_y_zoom(self, u_v):
        visible_data = [d for d, chk in zip(u_v, self._chk_u) if chk.isChecked() and len(d) > 0 and not np.all(np.isnan(d))]
        if not visible_data: return
        y_min = min(float(np.nanmin(d)) for d in visible_data)
        y_max = max(float(np.nanmax(d)) for d in visible_data)
        if y_min < self._global_y_min_u: self._global_y_min_u = y_min
        if y_max > self._global_y_max_u: self._global_y_max_u = y_max
        if self._global_y_min_u == float('inf'): return
        center = 0.5 * (self._global_y_min_u + self._global_y_max_u)
        half_range = max(self._global_y_max_u - center, center - self._global_y_min_u, 1.0)
        display_half_range = (half_range / max(self._u_gain, 1e-9)) * 1.05
        self._pw.setYRange(center - display_half_range, center + display_half_range, padding=0.0)
 
    @staticmethod
    def _compound_values(u_vals):
        return [u_vals[sa] - u_vals[sb] for _sl, _fl, _c, sa, sb in COMPOUND_CHANNELS]
 
    def _update_u12_y_zoom(self, compound_data):
        visible_compound_data = [d for idx, d in enumerate(compound_data) if self._chk_compound[idx].isChecked() and len(d) > 0 and not np.all(np.isnan(d))]
        if not visible_compound_data: return
        y_min = min(float(np.nanmin(d)) for d in visible_compound_data)
        y_max = max(float(np.nanmax(d)) for d in visible_compound_data)
        if y_min < self._global_y_min_u12: self._global_y_min_u12 = y_min
        if y_max > self._global_y_max_u12: self._global_y_max_u12 = y_max
        if self._global_y_min_u12 == float('inf'): return
        center = 0.5 * (self._global_y_min_u12 + self._global_y_max_u12)
        half_range = max(self._global_y_max_u12 - center, center - self._global_y_min_u12, 1.0)
        display_half_range = (half_range / max(self._u_gain, 1e-9)) * 1.05
        self._pw_u12.setYRange(center - display_half_range, center + display_half_range, padding=0.0)
 
    def _on_channel_toggle(self):
        for curve, chk in zip(self._curves, self._chk_u): curve.setVisible(chk.isChecked())
        for curve, chk in zip(self._compound_curves, self._chk_compound): curve.setVisible(chk.isChecked())
        if len(self._latest_t) > 0: self._render_plot(self._latest_t, self._latest_u)
 
    def _set_history_spin_value(self, value):
        if value < self._spin_history.minimum() or value > self._spin_history.maximum():
            self._spin_history.setRange(min(self._spin_history.minimum(), value), max(self._spin_history.maximum(), value))
        self._spin_history.blockSignals(True); self._spin_history.setValue(value); self._spin_history.blockSignals(False)
 
    def _on_history_text_edited(self, _text): self._history_spin_editing = True
 
    def _set_history_spin_range(self, min_t, max_t, preserve_text=False):
        line_edit = self._spin_history.lineEdit()
        restore_text, restore_cursor = (line_edit.text(), line_edit.cursorPosition()) if preserve_text else (None, None)
        self._spin_history.blockSignals(True); self._spin_history.setRange(min_t, max_t); self._spin_history.blockSignals(False)
        if restore_text is not None:
            line_edit.blockSignals(True); line_edit.setText(restore_text); line_edit.setCursorPosition(min(restore_cursor, len(restore_text))); line_edit.blockSignals(False)
 
    def _current_history_input_value(self):
        try: return float(self._spin_history.lineEdit().text().strip())
        except ValueError: return float(self._spin_history.value())
 
    def _mark_history_snapshot_dirty(self): self._history_snapshot_dirty = True
 
    def _get_history_snapshot(self, prefer_stale=False):
        if prefer_stale and len(self._history_snapshot_t) > 0 and self._history_snapshot_dirty: return self._history_snapshot_t, self._history_snapshot_u
        if self._history_snapshot_dirty:
            self._history_snapshot_t, self._history_snapshot_u = self._buf.all_data()
            self._history_snapshot_dirty = False
        return self._history_snapshot_t, self._history_snapshot_u
 
    @staticmethod
    def _slice_history_snapshot(t_all, u_all, window_s, focus_t):
        if len(t_all) == 0: return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64), [np.empty(0, dtype=np.float64)]*3, 0.0, 0.0, 0.0
        min_t, max_t = float(t_all[0]), float(t_all[-1])
        focus_t = float(min(max(focus_t, min_t), max_t))
        if window_s <= 0.0: window_s = max(max_t - min_t, 0.02)
        window_start, window_end = focus_t - 0.5 * window_s, focus_t + 0.5 * window_s
        if window_start < min_t: window_start, window_end = min_t, min_t + window_s
        if window_end > max_t: window_end, window_start = max_t, max_t - window_s
        window_start = max(min_t, window_start)
        left, right = int(np.searchsorted(t_all, window_start, side="left")), int(np.searchsorted(t_all, window_end, side="right"))
        if right <= left:
            nearest = max(0, min(int(np.searchsorted(t_all, focus_t, side="left")), len(t_all) - 1))
            left, right = nearest, nearest + 1
        return t_all[left:right] - window_start, t_all[left:right], [u_all[ph][left:right] for ph in range(3)], window_start, min(window_start + window_s, max_t), focus_t
 
    @staticmethod
    def _time_to_slider_value(t_s, min_t, max_t): return 0 if max_t <= min_t else int(round(min(max((t_s - min_t) / (max_t - min_t), 0.0), 1.0) * HISTORY_SLIDER_STEPS))
    @staticmethod
    def _slider_value_to_time(value, min_t, max_t): return min_t if max_t <= min_t else min_t + (float(value) / float(HISTORY_SLIDER_STEPS)) * (max_t - min_t)
 
    def _apply_view(self, t_rel, t_abs, u_v, window_start_t, window_end_t):
        self._latest_t, self._latest_t_abs, self._latest_u = t_rel, t_abs, u_v
        self._view_start_t, self._view_end_t = float(window_start_t), float(window_end_t)
 
    def _update_history_marker(self):
        if not self._history_mode or self._history_target_t is None:
            self._history_vline.setVisible(False); self._history_vline_u12.setVisible(False)
            return
        marker_x = min(max(self._history_target_t - self._view_start_t, 0.0), self._win_s)
        self._history_vline.setPos(marker_x); self._history_vline.setVisible(True)
        self._history_vline_u12.setPos(marker_x); self._history_vline_u12.setVisible(True)
 
    def _show_live_view(self):
        if self._buf.sample_count == 0: return [0.0, 0.0, 0.0]
        t_rel, u_v = self._buf.view(self._win_s)
        latest_t = self._buf.latest_time()
        if latest_t is None or len(t_rel) == 0: return [0.0, 0.0, 0.0]
        window_start_t = latest_t - self._win_s
        self._apply_view(t_rel, t_rel + window_start_t, u_v, window_start_t, latest_t)
        self._update_history_marker()
        self._update_history_controls()
        return self._render_plot(t_rel, u_v)
 
    def _show_history_view(self, target_t):
        if getattr(self._buf, "sample_count", 0) == 0: return [0.0, 0.0, 0.0]
        t_all, u_all = self._get_history_snapshot(prefer_stale=self._history_slider_dragging)
        t_rel, t_abs, u_v, window_start_t, window_end_t, focus_t = self._slice_history_snapshot(t_all, u_all, self._win_s, target_t)
        self._history_mode, self._history_target_t = True, focus_t
        self._apply_view(t_rel, t_abs, u_v, window_start_t, window_end_t)
        self._update_history_marker()
        self._update_history_controls()
        return self._render_plot(t_rel, u_v)
 
    def _update_history_controls(self):
        min_t, max_t = self._buf.time_bounds()
        has_data = min_t is not None and max_t is not None
        spin_is_editing = self._history_spin_editing or self._spin_history.hasFocus()
        self._btn_history_go.setEnabled(has_data); self._btn_back_to_live.setEnabled(has_data and self._history_mode); self._sld_history.setEnabled(has_data and max_t > min_t)
        if not has_data:
            self._lbl_history_state.setText("Live: waiting for buffer")
            if not spin_is_editing: self._set_history_spin_value(0.0)
            if not self._history_slider_dragging:
                self._sld_history.blockSignals(True); self._sld_history.setValue(HISTORY_SLIDER_STEPS); self._sld_history.blockSignals(False)
            return
        current_target = min(max(max_t if (not self._history_mode or self._history_target_t is None) else self._history_target_t, min_t), max_t)
        self._set_history_spin_range(min_t, max_t, preserve_text=spin_is_editing)
        if not spin_is_editing: self._set_history_spin_value(current_target)
        if not self._history_slider_dragging:
            self._sld_history.blockSignals(True); self._sld_history.setValue(self._time_to_slider_value(current_target, min_t, max_t)); self._sld_history.blockSignals(False)
        self._lbl_history_state.setText(f"History: {self._view_start_t:.0f} .. {self._view_end_t:.0f}" if self._history_mode else f"Live: {max_t:.0f}  |  Buffer {min_t:.0f} .. {max_t:.0f}")
 
    def _on_history_go(self):
        if self._buf.sample_count == 0:
            self._history_spin_editing = False; self._lbl_status.setText("No buffered data to review yet"); return
        self._history_spin_editing = False
        self._show_history_view(self._current_history_input_value())
        self._lbl_status.setText(f"History  |  jumped to idx={self._history_target_t:.0f}")
 
    def _on_history_slider_changed(self, value):
        min_t, max_t = self._buf.time_bounds()
        if min_t is None or max_t is None: return
        self._show_history_view(self._slider_value_to_time(value, min_t, max_t))
        self._lbl_status.setText(f"History  |  scrubbed to idx={self._history_target_t:.0f}")
 
    def _on_history_slider_pressed(self): self._history_slider_dragging = True
    def _on_history_slider_released(self): self._history_slider_dragging = False; self._update_history_controls()
 
    def _on_back_to_live(self):
        self._history_mode, self._history_target_t = False, None
        self._update_history_marker()
        if self._buf.sample_count > 0: self._show_live_view(); self._lbl_status.setText("Live view resumed")
        else: self._update_history_controls()
 
    def _drain_gui_queue(self):
        new_frames = 0
        while True:
            try: frame = self._gui_q.get_nowait()
            except queue.Empty: break
            
            delta = frame.get("delta", 1)
            
            nan_inserts = min(delta - 1, self._buf._cap // 2)
            if nan_inserts > 0:
                nan_u = [np.nan, np.nan, np.nan]
                for i in range(nan_inserts, 0, -1):
                    miss_t = frame["t_s"] - i
                    self._buf.push(miss_t, nan_u, 0, 0, 0)
            
            self._buf.push(frame["t_s"], frame["u"], fw_min=frame.get("fw_min", 0), fw_sec=frame.get("fw_sec", 0), fw_ms=frame.get("fw_ms", 0))
            self._mark_history_snapshot_dirty()
            new_frames += delta
        return new_frames
 
    def _prepare_render_view(self, t, u_v):
        if len(t) <= RENDER_SOFT_LIMIT: return t, u_v
        stride = max(1, len(t) // max(max(1, int(self._pw.width())) * 4, 4_000))
        return (t, u_v) if stride == 1 else (t[::stride], [d[::stride] for d in u_v])
 
    def _update_dots_visibility(self):
        if len(self._latest_t) == 0: return
        try:
            x_min, x_max = self._pw.viewRange()[0]
            left = int(np.searchsorted(self._latest_t, x_min))
            right = int(np.searchsorted(self._latest_t, x_max))
            show_dots = self._chk_sample_dots.isChecked() and (right - left) <= SAMPLE_DOT_RENDER_LIMIT
        except Exception:
            show_dots = False

        t_render, u_render = self._prepare_render_view(self._latest_t, self._latest_u)
        for k, curve in enumerate(self._curves):
            if curve.isVisible():
                curve.setData(t_render, u_render[k], pen=self._curve_pens[k], symbol="o" if show_dots else None, symbolSize=SAMPLE_DOT_SIZE if show_dots else 0, symbolBrush=self._curve_brushes[k] if show_dots else None, symbolPen=self._curve_pens[k] if show_dots else None)
        
        compound_render = self._compound_values(u_render)
        for idx, curve in enumerate(self._compound_curves):
            if curve.isVisible():
                curve.setData(t_render, compound_render[idx], pen=self._compound_pens[idx], symbol="o" if show_dots else None, symbolSize=SAMPLE_DOT_SIZE if show_dots else 0, symbolBrush=self._compound_brushes[idx] if show_dots else None, symbolPen=self._compound_pens[idx] if show_dots else None)

    def _render_plot(self, t, u_v):
        t_render, u_render = self._prepare_render_view(t, u_v)
        if len(t) > 0:
            try:
                x_min, x_max = self._pw.viewRange()[0]
                left = int(np.searchsorted(t_render, x_min))
                right = int(np.searchsorted(t_render, x_max))
                show_dots = self._chk_sample_dots.isChecked() and (right - left) <= SAMPLE_DOT_RENDER_LIMIT
            except Exception:
                show_dots = self._chk_sample_dots.isChecked() and len(t_render) <= SAMPLE_DOT_RENDER_LIMIT
            
            for k, curve in enumerate(self._curves):
                if curve.isVisible():
                    curve.setData(t_render, u_render[k], pen=self._curve_pens[k], symbol="o" if show_dots else None, symbolSize=SAMPLE_DOT_SIZE if show_dots else 0, symbolBrush=self._curve_brushes[k] if show_dots else None, symbolPen=self._curve_pens[k] if show_dots else None)
            compound_render = self._compound_values(u_render)
            for idx, curve in enumerate(self._compound_curves):
                if curve.isVisible():
                    curve.setData(t_render, compound_render[idx], pen=self._compound_pens[idx], symbol="o" if show_dots else None, symbolSize=SAMPLE_DOT_SIZE if show_dots else 0, symbolBrush=self._compound_brushes[idx] if show_dots else None, symbolPen=self._compound_pens[idx] if show_dots else None)
            self._update_y_zoom(u_v)
            self._update_u12_y_zoom(self._compound_values(u_v))
            return _RollingBuffer.rms(u_v)
        for curve in self._compound_curves: curve.setData([], [])
        return [0.0, 0.0, 0.0]
 
    def _on_plot_style_changed(self):
        if len(self._latest_t) > 0: self._render_plot(self._latest_t, self._latest_u)
        elif self._buf.sample_count > 0: self._show_history_view(self._history_target_t) if (self._history_mode and self._history_target_t is not None) else self._show_live_view()
 
    def _on_tick(self):
        new_frames = self._drain_gui_queue()
        rms_u = _RollingBuffer.rms(self._latest_u) if len(self._latest_t) > 0 else [0.0, 0.0, 0.0]
 
        if not self._frozen and self._buf.sample_count > 0:
            if self._history_mode and self._history_target_t is not None:
                min_t, max_t = self._buf.time_bounds()
                if min_t is not None and max_t is not None:
                    if self._history_target_t < min_t or self._history_target_t > max_t: rms_u = self._show_history_view(self._history_target_t)
                    else: self._update_history_controls()
            elif new_frames > 0 or len(self._latest_t) == 0:
                rms_u = self._show_live_view()
            else: self._update_history_controls()
        elif self._buf.sample_count > 0: self._update_history_controls()
 
        if self._provider is None and new_frames == 0 and self._buf.sample_count == 0: return
 
        now = time.monotonic()
        self._frames_since += new_frames
        dt = now - self._tick_ts
 
        if now - self._fs_ts_last >= 1.0:
            self._fs_hz, self._fs_samples_last, self._fs_ts_last = (self._buf.sample_count - self._fs_samples_last) / (now - self._fs_ts_last), self._buf.sample_count, now
        self._lbl_fs.setText(f"fs: {self._fs_hz:.1f} Hz")
 
        if dt >= 1.0:
            self._lbl_fps.setText(f"fps: {self._frames_since / dt:.0f}")
            self._frames_since, self._tick_ts = 0, now
 
        if self._provider is not None and hasattr(self._provider, "lines_rx"):
            drop_suffix = f" | dropped: {self._provider.frames_dropped}" if getattr(self._provider, "frames_dropped", 0) else ""
            if isinstance(self._provider, QualFileProvider):
                self._lbl_diag.setText(f"playback: {Path(self._play_path).name} | loaded: {self._provider.loaded_frames} | replayed: {self._provider.frames_rx}{drop_suffix}")
            elif isinstance(self._provider, QualSerialProvider):
                csum = getattr(self._provider, "checksum_errors", 0)
                sniff = getattr(self._provider, "raw_sniff", "")
                csum_str = f" | csum_err: {csum}" if csum else ""
                sniff_str = f"  hex: {sniff[:23]}" if sniff and self._provider.frames_rx == 0 else ""
                self._lbl_diag.setText(f"bytes: {self._provider.bytes_rx} | frames: {self._provider.frames_rx}{csum_str}{drop_suffix}{sniff_str}")
            else:
                self._lbl_diag.setText(f"lines: {self._provider.lines_rx} | frames: {self._provider.frames_rx}{drop_suffix}")
        else: self._lbl_diag.setText(f"buf: {self._buf.sample_count}")
 
        unit = self._get_unit_str()
        self._lbl_rms_v.setText(f"RMS:  P1={rms_u[0]:.1f}  P2={rms_u[1]:.1f}  P3={rms_u[2]:.1f} {unit}")
 
        if self._provider is not None:
            err = getattr(self._provider, "error", None)
            if err: self._lbl_status.setText(f"Error: {err}"); self._on_stop()
 
    def _cursor_sample_at_x(self, x):
        t_rel, t_abs, u_v = self._latest_t, self._latest_t_abs if len(self._latest_t_abs) == len(self._latest_t) else self._latest_t, self._latest_u
        if len(t_rel) < 1: return None
        idx = max(0, min(int(np.searchsorted(t_rel, x)), len(t_rel) - 1))
        if idx > 0 and abs(t_rel[idx - 1] - x) <= abs(t_rel[idx] - x): idx -= 1
        return float(t_rel[idx]), float(t_abs[idx]), [float(u_v[k][idx]) if len(u_v[k]) > idx else 0.0 for k in range(3)]
 
    def _set_cursor_x(self, x): self._vline.setPos(x); self._vline_u12.setPos(x)
 
    def _set_cursor_label(self, t_val, u_vals, include_phases, include_compounds):
        unit = self._get_unit_str()
        parts = [f"idx={t_val:.0f}"]
        if include_phases:
            clean_u = ["NaN" if math.isnan(u_vals[k]) else f"{u_vals[k]:.1f}" for k in range(3)]
            parts.append("  ".join(f"P{k+1}={clean_u[k]}" for k in range(3)) + f" {unit}")
        if include_compounds:
            comp_vals = self._compound_values(u_vals)
            clean_c = ["NaN" if math.isnan(v) else f"{v:.1f}" for v in comp_vals]
            compound_text = "  ".join(f"{sl}={clean_c[idx]}" for idx, (sl, _fl, _c, _sa, _sb) in enumerate(COMPOUND_CHANNELS) if self._chk_compound[idx].isChecked())
            if compound_text: parts.append(f"{compound_text} {unit}")
        self._lbl_cursor.setText("    ".join(parts))
 
    def _on_mouse(self, evt):
        if not self._pw.sceneBoundingRect().contains(evt[0]): return
        mp = self._pw.plotItem.vb.mapSceneToView(evt[0])
        x = mp.x(); self._set_cursor_x(x); self._hline.setPos(mp.y())
        sample = self._cursor_sample_at_x(x)
        if sample is None: self._lbl_cursor.setText("Cursor: —"); return
        self._set_cursor_x(sample[0]); self._set_cursor_label(sample[1], sample[2], True, True)
 
    def _on_mouse_u12(self, evt):
        if not self._pw_u12.sceneBoundingRect().contains(evt[0]): return
        mp = self._pw_u12.plotItem.vb.mapSceneToView(evt[0])
        x = mp.x(); self._set_cursor_x(x); self._hline_u12.setPos(mp.y())
        sample = self._cursor_sample_at_x(x)
        if sample is None: self._lbl_cursor.setText("Cursor: —"); return
        self._set_cursor_x(sample[0]); self._set_cursor_label(sample[1], sample[2], False, True)
 
    def closeEvent(self, event): self._stop_provider(); self._timer.stop(); super().closeEvent(event)
 
def _sep():
    lbl = QLabel("|"); lbl.setStyleSheet("color:#555; margin:0 4px;"); return lbl
 
def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    from PyQt5.QtGui import QPalette, QColor
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#1A1A2E")); pal.setColor(QPalette.WindowText, QColor("#E0E0E0"))
    pal.setColor(QPalette.Base, QColor("#16213E")); pal.setColor(QPalette.AlternateBase, QColor("#0F3460"))
    pal.setColor(QPalette.Text, QColor("#E0E0E0")); pal.setColor(QPalette.Button, QColor("#0F3460"))
    pal.setColor(QPalette.ButtonText, QColor("#E0E0E0")); pal.setColor(QPalette.Highlight, QColor("#533483"))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(pal)
    win = QualMainWindow()
    win.show()
    sys.exit(app.exec_())
 
if __name__ == "__main__":
    main()