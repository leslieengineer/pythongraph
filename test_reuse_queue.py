import os
import csv
import queue
import time
from logger import QualDataLogger

def test_logger_reuse():
    log_file = 'test_reuse.csv'
    if os.path.exists(log_file):
        os.remove(log_file)

    shared_queue = queue.Queue()
    
    print('Starting first logger...')
    # From previous error, QualDataLogger(path, queue) works.
    logger1 = QualDataLogger(log_file, shared_queue)
    
    # Check if it has a .thread attribute or if start() returns one
    logger1.start()
    
    # Try to find the thread object to check liveness
    thread1 = getattr(logger1, '_thread', None)
    
    # Inject invalid item
    shared_queue.put(123) 
    
    time.sleep(1)
    if thread1:
        print(f'Logger 1 thread alive: {thread1.is_alive()}')
    
    logger1.stop()
    
    print('Starting second logger...')
    logger2 = QualDataLogger(log_file, shared_queue)
    logger2.start()
    thread2 = getattr(logger2, '_thread', None)
    
    time.sleep(1)
    if thread2:
        print(f'Logger 2 thread alive: {thread2.is_alive()}')
    else:
        print('Logger 2 thread not found')
    
    logger2.stop()
    
    if os.path.exists(log_file):
        with open(log_file, 'r') as f:
            lines = f.readlines()
            print(f'Log file lines: {len(lines)}')

    if os.path.exists(log_file):
        os.remove(log_file)

if __name__ == '__main__':
    test_logger_reuse()
