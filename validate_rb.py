import time
import numpy as np
from main import _RollingBuffer, QUAL_FS_HZ

def benchmark_rolling_buffer():
    fs = QUAL_FS_HZ * 50
    duration = 120
    capacity = int(duration * fs * 1.2)
    rb = _RollingBuffer(capacity)
    
    print(f"Pre-filling buffer with {duration}s of data ({fs} Hz)...")
    t_arr = np.linspace(0, duration, duration * fs)
    u_arr = np.random.randn(3, duration * fs).astype(np.float32)
    
    for i in range(len(t_arr)):
        rb.push(t_arr[i], u_arr[:, i])
    
    print("Benchmarking view()...")
    for win in [10, 120]:
        start = time.perf_counter()
        iters = 100
        for _ in range(iters):
            rb.view(win)
        avg_ms = (time.perf_counter() - start) * 1000 / iters
        print(f"Window {win}s: Average view() time: {avg_ms:.4f} ms")

if __name__ == '__main__':
    benchmark_rolling_buffer()
