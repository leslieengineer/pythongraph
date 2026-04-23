import sys
import time
import queue
from pathlib import Path
from PyQt5.QtWidgets import QApplication
from main import QualMainWindow

def scenario_1(app):
    print("Scenario 1: Enable Log while stopped, fresh CSV path")
    win = QualMainWindow()
    csv_path = Path("scenario1.csv").resolve()
    if csv_path.exists(): csv_path.unlink()
    win._log_path = str(csv_path)
    win._cb_mode.setCurrentIndex(1)
    win._chk_log.setChecked(True)
    for _ in range(10):
        app.processEvents()
        time.sleep(0.1)
    exists = csv_path.exists()
    line_count = len(csv_path.read_text().splitlines()) if exists else 0
    status = win._lbl_status.text()
    log_btn_text = win._btn_log_file.text()
    print(f"Exists: {exists}")
    print(f"Lines: {line_count}")
    print(f"Status: {status}")
    print(f"Log Button: {log_btn_text}")
    win.close()

def scenario_2(app):
    print("\nScenario 2: Simulation Start then Stop")
    win = QualMainWindow()
    csv_path = Path("scenario2.csv").resolve()
    if csv_path.exists(): csv_path.unlink()
    win._log_path = str(csv_path)
    win._cb_mode.setCurrentIndex(1)
    win._chk_log.setChecked(True)
    win._on_start()
    start_t = time.time()
    while time.time() - start_t < 2:
        app.processEvents()
        time.sleep(0.01)
    win._on_stop()
    app.processEvents()
    exists = csv_path.exists()
    line_count = len(csv_path.read_text().splitlines()) if exists else 0
    status = win._lbl_status.text()
    rows_gt_1 = line_count > 1
    print(f"Exists: {exists}")
    print(f"Lines: {line_count}")
    print(f"Status: {status}")
    print(f"Rows > 1: {rows_gt_1}")
    win.close()

def scenario_3(app):
    print("\nScenario 3: Start Simulation first, enable Log while running, Stop")
    win = QualMainWindow()
    csv_path = Path("scenario3.csv").resolve()
    if csv_path.exists(): csv_path.unlink()
    win._log_path = str(csv_path)
    win._cb_mode.setCurrentIndex(1)
    win._on_start()
    time.sleep(0.5)
    app.processEvents()
    win._chk_log.setChecked(True)
    start_t = time.time()
    while time.time() - start_t < 2:
        app.processEvents()
        time.sleep(0.01)
    win._on_stop()
    app.processEvents()
    exists = csv_path.exists()
    line_count = len(csv_path.read_text().splitlines()) if exists else 0
    print(f"Exists: {exists}")
    print(f"Lines: {line_count}")
    win.close()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    try:
        scenario_1(app)
        scenario_2(app)
        scenario_3(app)
    except Exception:
        import traceback
        traceback.print_exc()
