import os
import queue
import time
from logger import QualDataLogger

def test_logger_normal_lifecycle():
    log_file = 'test_normal.csv'
    if os.path.exists(log_file):
        os.remove(log_file)

    shared_queue = queue.Queue()
    
    # 1. Start logger
    logger = QualDataLogger(log_file, shared_queue)
    logger.start()
    thread = getattr(logger, '_thread', None)
    
    time.sleep(1)
    print(f'Logger alive after start: {thread.is_alive() if thread else 'Unknown'}')
    
    # 2. Put valid data
    shared_queue.put(['col1', 'col2'])
    time.sleep(0.5)
    
    # 3. Stop
    logger.stop()
    time.sleep(0.5)
    print(f'Logger alive after stop: {thread.is_alive() if thread else 'Unknown'}')
    
    if os.path.exists(log_file):
        with open(log_file, 'r') as f:
            lines = f.readlines()
            print(f'Log file lines: {len(lines)}')

    if os.path.exists(log_file):
        os.remove(log_file)

if __name__ == '__main__':
    test_logger_normal_lifecycle()
