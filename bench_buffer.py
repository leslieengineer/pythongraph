import time
import numpy as np
from main import _RollingBuffer, MAX_SAMPLES, QUAL_FS_HZ

def benchmark():
    # Setup
    fs = QUAL_FS_HZ * 50  # 7800 Hz
    duration = 120
    capacity = MAX_SAMPLES
    buf = _RollingBuffer(capacity)
    
    # Simulation: Push 120s of data
    # To speed up insertion for the benchmark, we can do it in chunks if we modify push, 
    # but let's stick to the actual push method to be realistic, or just fill the arrays.
    # Actually, let's just fill it manually to simulate a full buffer.
    buf._size = capacity
    buf._head = 0
    # Fill with 120s worth of 'seconds'
    buf._t[:] = np.linspace(0, duration, capacity)
    buf._u[0, :] = np.random.rand(capacity).astype(np.float32)
    buf._u[1, :] = np.random.rand(capacity).astype(np.float32)
    buf._u[2, :] = np.random.rand(capacity).astype(np.float32)
    
    print(f"Buffer filled: {buf._size} samples (~{duration}s at {fs} Hz)")

    # Benchmark view()
    for win in [10, 120]:
        # Heat up
        buf.view(win)
        
        n_iters = 50
        start = time.perf_counter()
        for _ in range(n_iters):
            t_rel, u_v = buf.view(float(win))
        end = time.perf_counter()
        
        avg_ms = (end - start) / n_iters * 1000
        print(f"view({win}s): {avg_ms:.3f} ms (returned {len(t_rel)} samples)")

if __name__ == '__main__':
    benchmark()
