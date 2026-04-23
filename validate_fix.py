import os
import time
import queue
from pathlib import Path
from main import QualMainWindow
from PyQt5.QtWidgets import QApplication

def test_cases():
    app = QApplication([])
    
    print('--- Case 1: Error Recovery Test ---')
    window1 = QualMainWindow()
    log_file1 = str(Path('test1_fail.csv').resolve())
    if os.path.exists(log_file1): os.remove(log_file1)
    
    window1._log_path = log_file1
    window1._chk_log.setChecked(True)
    
    # Start logger
    window1._start_logger()
    time.sleep(0.5)
    
    # Poison the queue with invalid data
    window1._log_q.put(123)
    time.sleep(0.5)
    
    # Stop
    window1._stop_logger()
    
    # Try second session with new file
    log_file2 = str(Path('test1_recovery.csv').resolve())
    if os.path.exists(log_file2): os.remove(log_file2)
    window1._log_path = log_file2
    
    window1._start_logger()
    for i in range(5):
        window1._log_q.put(['test', i, 0.1, 0.2, 0.3])
    time.sleep(1)
    window1._stop_logger()
    
    recovery_lines = 0
    if os.path.exists(log_file2):
        with open(log_file2, 'r') as f:
            recovery_lines = len(f.readlines())
    
    print(f'Case 1: Recovery Log Lines: {recovery_lines}')
    
    print('\n--- Case 2: Normal Manual Log Test ---')
    window2 = QualMainWindow()
    log_file3 = str(Path('test2_normal.csv').resolve())
    if os.path.exists(log_file3): os.remove(log_file3)
    window2._log_path = log_file3
    window2._chk_log.setChecked(True)
    
    window2._start_logger()
    for i in range(10):
        window2._log_q.put(['normal', i, 1.1, 1.2, 1.3])
    time.sleep(1)
    window2._stop_logger()
    
    normal_lines = 0
    if os.path.exists(log_file3):
        with open(log_file3, 'r') as f:
            normal_lines = len(f.readlines())
            
    print(f'Case 2: Normal Log Lines: {normal_lines}')
    
    # Cleanup
    for f in [log_file1, log_file2, log_file3]:
        if os.path.exists(f): os.remove(f)
        
    app.quit()
    return recovery_lines, normal_lines

if __name__ == '__main__':
    try:
        rec, norm = test_cases()
        print(f'\nSummary: Recovery Lines={rec}, Normal Lines={norm}')
        if rec > 1:
            print('FIX STATUS: Fresh-queue fix is WORKING.')
        else:
            print('FIX STATUS: FAILED/NOT RECOVERED (header-only or no file).')
    except Exception as e:
        print(f'Validation script error: {e}')
        import traceback
        traceback.print_exc()
