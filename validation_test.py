import os
import sys
from unittest.mock import MagicMock

# Set environment variable for offscreen QT
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

try:
    from PyQt5.QtWidgets import QApplication
    from main import QualMainWindow
except ImportError as e:
    print(f'Import Error: {e}')
    sys.exit(1)

app = QApplication([])

def test_validation():
    workspace = r'C:\Users\lesli\WS\pythongraph'
    window = QualMainWindow()
    
    # 1) Check _normalize_log_path
    norm_path = window._normalize_log_path(workspace)
    print(f'Normalized path: {norm_path}')
    is_csv = norm_path.lower().endswith('.csv')
    is_qual_log = norm_path.lower().endswith('qual_log.csv')
    print(f'Ends with .csv: {is_csv}')
    print(f'Ends with qual_log.csv: {is_qual_log}')

    # 2) _log_path to path without extension and toggle log
    picked_name = os.path.join(workspace, 'picked_name')
    expected_file = picked_name + '.csv'
    if os.path.exists(expected_file):
        os.remove(expected_file)
        
    window._log_path = picked_name
    # _on_log_toggle seems to be a slot for a checkable button
    window._on_log_toggle(True) 
    
    file_exists = os.path.exists(expected_file)
    print(f'File {expected_file} exists: {file_exists}')

    # 3) Check status text and _lbl_log_file text
    # Note: status bar might be updated via a signal or direct call. 
    # QStatusBar.currentMessage() returns the message.
    abs_path = os.path.abspath(expected_file)
    status_text = window.statusBar().currentMessage()
    lbl_text = window._lbl_log_file.text()
    
    print(f'Status text contains path: {abs_path.lower() in status_text.lower()}')
    print(f'Label text contains path: {abs_path.lower() in lbl_text.lower()}')
    
    # Clean up
    if file_exists:
        try:
            window._on_log_toggle(False) # Stop logging
            # Give it a moment to close files if it's asynchronous, but here it's likely sync
            if hasattr(window, '_csv_file') and window._csv_file:
                 window._csv_file.close()
            os.remove(expected_file)
        except Exception as e:
            print(f'Cleanup error: {e}')

if __name__ == '__main__':
    try:
        test_validation()
        print('Validation completed without runtime errors.')
    except Exception as e:
        print(f'Runtime Error during validation: {e}')
        import traceback
        traceback.print_exc()
