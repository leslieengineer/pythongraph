import sys
import os
import time
from pathlib import Path
from PyQt5.QtWidgets import QApplication
from main import QualMainWindow

def run_test(test_name, stop_method):
    print(f"--- Running {test_name} ---")
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    
    win = QualMainWindow()
    # Set to Simulation (index 1 based on ["Online (COM)", "Simulation", "Playback (log)"])
    win._cb_mode.setCurrentIndex(1)
    
    win._chk_log.setChecked(True)
    
    csv_path = os.path.join(os.getcwd(), f"test_log_{test_name}.csv")
    if os.path.exists(csv_path):
        os.remove(csv_path)
    
    win._log_path = csv_path
    
    print(f"Log path set to: {win._log_path}")
    
    # Start the process
    win._on_start()
    
    # Process events for 0.75 seconds
    start_time = time.time()
    while time.time() - start_time < 0.75:
        app.processEvents()
        time.sleep(0.05)
    
    if stop_method == "on_stop":
        print("Calling _on_stop()...")
        win._on_stop()
    elif stop_method == "close":
        print("Closing window...")
        win.close()
    
    # Give a moment for file flush/close
    time.sleep(0.5)
    
    # Check results
    exists = os.path.exists(csv_path)
    size = os.path.getsize(csv_path) if exists else 0
    lines = 0
    if exists:
        try:
            with open(csv_path, "r") as f:
                content = f.readlines()
                lines = len(content)
        except Exception as e:
            print(f"Error reading file: {e}")
    
    rows_written = -1
    # Check if win._logger has rows_written
    if hasattr(win, "_logger") and win._logger:
        rows_written = getattr(win._logger, "rows_written", -1)
    
    print(f"Results for {test_name}:")
    print(f"  File path: {csv_path}")
    print(f"  Exists: {exists}")
    print(f"  Size: {size}")
    print(f"  Lines: {lines}")
    print(f"  Logger rows_written: {rows_written}")
    
    # Cleanup for next test
    win.deleteLater()
    app.processEvents()

if __name__ == "__main__":
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    try:
        run_test("StopButton", "on_stop")
        run_test("WindowClose", "close")
    except Exception as e:
        print(f"Exception: {e}")
        import traceback
        traceback.print_exc()
