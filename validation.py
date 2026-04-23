import sys
from PyQt5.QtWidgets import QApplication
from main import QualMainWindow
import time

app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

window = QualMainWindow()

# Report window combo options
window_cb = window._cb_window
options = [window_cb.itemText(i) for i in range(window_cb.count())]
current_text = window_cb.currentText()
print(f"Window options: {options}")
print(f"Current window: {current_text}")

# Target options verification
targets = ["0.02", "0.04", "0.10", "0.20"]
found_targets = [t for t in targets if t in options]
print(f"Found targets: {found_targets}")

# Set Simulation mode
window._cb_mode.setCurrentIndex(1)
print(f"Mode set to: {window._cb_mode.currentText()}")

# Start
window._on_start()

def process(duration):
    start = time.time()
    while time.time() - start < duration:
        app.processEvents()
        time.sleep(0.01)

process(0.6)

rms_v = window._lbl_rms_v.text()
y_range = window._pw.viewRange()[1]
print(f"Initial - RMS: {rms_v}, Y-range: {y_range}")

# Set ugain to 0.1
window._spin_ugain.setValue(0.1)
process(0.3)
rms_v_01 = window._lbl_rms_v.text()
y_range_01 = window._pw.viewRange()[1]
print(f"Ugain 0.1 - RMS: {rms_v_01}, Y-range: {y_range_01}")

# Set ugain to 10.0
window._spin_ugain.setValue(10.0)
process(0.3)
rms_v_10 = window._lbl_rms_v.text()
y_range_10 = window._pw.viewRange()[1]
print(f"Ugain 10.0 - RMS: {rms_v_10}, Y-range: {y_range_10}")

window._on_stop()
# app.quit() # Not strictly needed here
