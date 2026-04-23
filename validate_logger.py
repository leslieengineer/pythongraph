import queue
import os
from logger import QualDataLogger

def validate_logger():
    log_q = queue.Queue()
    log_file = "temp_validation.csv"
    if os.path.exists(log_file):
        os.remove(log_file)
    logger = QualDataLogger(log_file, log_q)
    logger.start()
    
    num_frames = 100
    for i in range(num_frames):
        log_q.put({"t_s": i * 0.01, "u": [100.0, 200.0, 300.0]})
    
    logger.stop()
    
    with open(log_file, 'r') as f:
        lines = f.readlines()
        
    print(f"Rows written count (internal): {logger.rows_written}")
    print(f"File line count (including header): {len(lines)}")
    print(f"File size: {os.path.getsize(log_file)} bytes")
    
    if os.path.exists(log_file):
        os.remove(log_file)

if __name__ == '__main__':
    validate_logger()
