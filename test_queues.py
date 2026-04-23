import queue
import time
from providers import _BaseProvider

class MockProvider(_BaseProvider):
    def _run(self):
        pass
    def push_external(self, frame):
        self._push(frame)

def validate_queues():
    max_gui = 3
    gui_q = queue.Queue(maxsize=max_gui)
    log_q = queue.Queue()
    
    provider = MockProvider(gui_q, log_q=log_q)
    
    # Push 5 frames to a GUI queue of size 3
    for i in range(5):
        provider.push_external({"t_s": float(i), "u": [0.0, 0.0, 0.0]})
    
    print(f"GUI Queue size: {gui_q.qsize()}")
    print(f"Log Queue size: {log_q.qsize()}")
    print(f"Frames dropped: {provider.frames_dropped}")
    
    gui_items = []
    while not gui_q.empty():
        gui_items.append(gui_q.get())
    
    print(f"GUI first t_s: {gui_items[0]['t_s'] if gui_items else 'N/A'}")
    print(f"GUI last t_s: {gui_items[-1]['t_s'] if gui_items else 'N/A'}")

if __name__ == "__main__":
    validate_queues()
