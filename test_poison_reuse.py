import os
import queue
import time
from logger import QualDataLogger

def test_logger_poison_reuse():
    log_file = 'test_poison.csv'
    if os.path.exists(log_file):
        os.remove(log_file)

    shared_queue = queue.Queue()
    
    print('--- Step 1: Start and Stop Logger 1 ---')
    logger1 = QualDataLogger(log_file, shared_queue)
    logger1.start()
    thread1 = getattr(logger1, '_thread', None)
    print(f'Logger 1 alive: {thread1.is_alive() if thread1 else 'N/A'}')
    
    # Stopping should put a None (poison pill) in the queue
    logger1.stop()
    time.sleep(1)
    print(f'Logger 1 alive after stop: {thread1.is_alive() if thread1 else 'N/A'}')
    
    # Check if queue has something (the poison pill)
    print(f'Queue size after stop: {shared_queue.qsize()}')

    print('\n--- Step 2: Start Logger 2 with same queue ---')
    logger2 = QualDataLogger(log_file, shared_queue)
    logger2.start()
    thread2 = getattr(logger2, '_thread', None)
    
    # Wait for it to process the leftovers
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
    test_logger_poison_reuse()
