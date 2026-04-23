import queue
from providers import _BaseProvider

class MockProvider(_BaseProvider):
    def _run(self):
        pass
    def push_external(self, frame):
        self._push(frame)

def validate_queue_drop():
    max_size = 5
    gui_q = queue.Queue(maxsize=max_size)
    provider = MockProvider(gui_q)
    
    # Fill queue
    for i in range(max_size):
        provider.push_external({"t_s": i, "u": [0,0,0]})
    
    print(f"Queue size after filling: {gui_q.qsize()}")
    
    # Push one more - should trigger drop of oldest (t_s: 0)
    new_frame = {"t_s": 99, "u": [1,1,1]}
    provider.push_external(new_frame)
    
    print(f"Frames dropped: {provider.frames_dropped}")
    print(f"Queue size after overflow: {gui_q.qsize()}")
    
    items = []
    while not gui_q.empty():
        items.append(gui_q.get())
    
    print(f"First item t_s: {items[0]['t_s']}")
    print(f"Last item t_s: {items[-1]['t_s']}")

if __name__ == '__main__':
    validate_queue_drop()
