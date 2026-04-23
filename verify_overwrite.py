import sys, os, time
from PyQt5.QtWidgets import QApplication
from main import QualMainWindow

app = QApplication(sys.argv)
win = QualMainWindow()
win._cb_mode.setCurrentIndex(0) # Online (COM)
win._cb_port.setCurrentText('COM6')
win._cb_baud.setCurrentText('960000')

csv_path = os.path.abspath('overwrite_test.csv')
win._log_path = csv_path
win._chk_log.setChecked(True)
win._request_overwrite = True 

print(f'Starting logging to {csv_path}...')
win._on_start()

start_time = time.time()
while time.time() - start_time < 1.5:
    app.processEvents()
    time.sleep(0.1)

win._on_stop()
