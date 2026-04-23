import os
import queue
import time
from logger import QualDataLogger

def test_logger_error_reuse():
    log_file = 'test_error_reuse.csv'
    if os.path.exists(log_file):
        os.remove(log_file)

    shared_queue = queue.Queue()
    
    print('--- Step 1: Start Logger 1 and Inject Error ---')
    logger1 = QualDataLogger(log_file, shared_queue)
    logger1.start()
    thread1 = getattr(logger1, '_thread', None)
    
    # Inject item that causes error in write operation
    # writer.writerow(123) will fail because 123 is not iterable
    shared_queue.put(123)
    
    time.sleep(1)
    # The thread should have crashed
    print(f'Logger 1 alive (crashed?): {thread1.is_alive() if thread1 else 'N/A'}')
    
    # Now call stop() - if stop() puts a None, and it was never consumed...
    logger1.stop()
    print(f'Queue size after stop: {shared_queue.qsize()}')

    print('\n--- Step 2: Start Logger 2 with same queue ---')
    logger2 = QualDataLogger(log_file, shared_queue)
    logger2.start()
    thread2 = getattr(logger2, '_thread', None)
    
    time.sleep(1)
    is_alive = thread2.is_alive() if thread2 else False
    print(f'Logger 2 alive: {is_alive}')
    
    logger2.stop()
    
    if os.path.exists(log_file):
        with open(log_file, 'r') as f:
            lines = f.readlines()
            print(f'Log file lines: {len(lines)}')

    if os.path.exists(log_file):
        os.remove(log_file)

if __name__ == '__main__':
    test_logger_error_reuse()
