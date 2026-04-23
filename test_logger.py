import queue
import os
import time
from logger import QualDataLogger

def test_logger():
    path = "test_log.csv"
    if os.path.exists(path):
        os.remove(path)
    
    q = queue.Queue()
    logger = QualDataLogger(path, q)
    logger.start()
    
    # Push 10 frames
    for i in range(10):
        q.put({"t_s": float(i), "u": [1.0, 2.0, 3.0]})
    
    time.sleep(0.5) # Allow some time for processing
    logger.stop()
    
    if os.path.exists(path):
        size = os.path.getsize(path)
        with open(path, 'r') as f:
            lines = f.readlines()
        print(f"File created: {path}")
        print(f"File size: {size} bytes")
        print(f"Rows (including header): {len(lines)}")
        if len(lines) > 1:
            print(f"First data row: {lines[1].strip()}")
    else:
        print("File NOT created")

if __name__ == '__main__':
    test_logger()
