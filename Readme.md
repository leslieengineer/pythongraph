# QUAL Waveform Viewer — Yêu cầu dự án

Real-time oscilloscope 3 pha bằng Python, nhận dữ liệu đo lường qua UART từ thiết bị Sagemcom AMR.

---

## Dữ liệu & Giao thức

- [x] Nhận dữ liệu UART format: `$Q,<u32_sec>,<u16_ms>,<U1>,<U2>,<U3>,<I1>,<I2>,<I3>`
=>> nhưng I1, I2, I3 không care, chỉ lấy đến `$Q,<u32_sec>,<u16_ms>,<U1>,<U2>,<U3>,`; nhưng cũng chấp nhận message đầy đủ `$Q,<u32_sec>,<u16_ms>,<U1>,<U2>,<U3>,<I1>,<I2>,<I3>`, chỉ có điều là không quan tâm I1, I2, I3
- [x] Baudrate mặc định: **960000** (USART1 / CLI port)
- [x] 156 mẫu mỗi chu kỳ (~7800 mẫu/giây ở 50 Hz)
- [x] Parse đúng timestamp từ `u32_sec` + `u16_ms` → trục X đơn vị giây (độ chính xác ms)
- [x] Đọc UART trên thread riêng (không block giao diện)

---

## Hiển thị đồ thị

- [x] Hiển thị đủ **156 điểm mỗi chu kỳ** (không skip mẫu)
- [ ] ~~2 đồ thị riêng biệt: **Điện áp (U1, U2, U3)** và **Dòng điện (I1, I2, I3)**~~ 
=> Chỉ cần hiển thị điện áp.
- [x] 3 pha hiển thị đan xen nhau dạng sóng sin =>> sóng sin hay không là do dữ liệu đầu vào
- [x] Trục X: thời gian (s), độ chính xác **millisecond** (3 chữ số thập phân)
- [x] Trục Y điện áp: đơn vị **mV**, độ chính xác milivolt
- [ ] ~~Trục Y dòng điện: đơn vị **mA**, độ chính xác milliamp~~ => loại bỏ 
- [ ] ~~Hiển thị chấm tròn (scatter dots) trên điểm khi số điểm ít (dưới ngưỡng SCATTER_MAX)~~ =>> mỗi chu kì(20ms) là 156 mẫu, tương đương 156 điểm, khá là dày đặc 
- [ ] 2 trục X đồng bộ nhau (X-link giữa 2 plot)
- [x] Theme tối kiểu oscilloscope chuyên nghiệp

---

## Cửa sổ trượt (Sliding Window)

- [x] Chỉ hiển thị dữ liệu trong **N giây gần nhất**
- [x] N tùy chọn: `1, 3, 5, 10, 30, 60, 120` giây (dropdown)
- [x] Dữ liệu cũ hơn N giây tự động loại bỏ khỏi bộ nhớ (rolling buffer)
- [x] Buffer tối đa 120 giây (~27.000 mẫu × 1.5 = MAX_SAMPLES)
=>> Lưu ý phần oldcode.py đã không làm tốt việc này
---

## Crosshair & Tương tác chuột

- [x] Đường crosshair (dấu thập) bám theo con trỏ trên cả 2 đồ thị
- [x] Khi di chuột, hiển thị giá trị: `t=x.xxxs  U1=... U2=... U3= mV  I1=... mA`
- [x] Đọc giá trị tại điểm gần nhất trên dữ liệu thực (snap to nearest sample)
- [x] Crosshair đồng bộ giữa 2 plot (di chuột trên 1 plot thì cả 2 cập nhật X)
=>> Lưu ý code oldcode.py cũng chưa hiển thị được giá trị mỗi điểm khi trỏ tới
---

## Bảng điều khiển (Control Panel)

- [x] **Mode selector**: Online (COM) | Simulation | Playback (log file)
- [x] **Online mode**: chọn COM port, baudrate, nút refresh danh sách port
- [x] **Simulation mode**: tuỳ chỉnh Freq (Hz), V_rms (mV), I_rms (mA), φ (°)
- [x] **Playback mode**: chọn file log, tuỳ chỉnh tốc độ phát lại (Speed)
- [x] Nút **▶ Start** / **■ Stop** / **❚❚ Freeze / ▶ Resume**
- [x] **Gain U** (mV→mV) và **Gain I** (mA→mA) tuỳ chỉnh hệ số khuếch đại
- [x] Toggle hiển thị từng kênh: **U1 U2 U3 I1 I2 I3** (checkbox)
- [x] **Log to CSV**: checkbox bật/tắt, nút chọn đường dẫn file

---

## Status Bar

- [x] Trạng thái: Stopped / Running [mode] / Error
- [x] Số dòng nhận / số frame: `lines: x | frames: x`
- [x] **V_rms**: L1=... L2=... L3=... mV =>> lưu ý là hiển thị đúng giá trị nhận được từ uart, đơn vị là V nhưng giá trị đúng tới mV.
- [ ] **I_rms**: L1=... L2=... L3=... mA
- [x] Tần số lấy mẫu thực tế: `fs: x.x Hz`
- [x] Tốc độ cập nhật giao diện: `fps: x`
- [x] Cursor readout ở góc phải status bar (màu vàng, monospace)

---

## Hiệu năng & Kiến trúc

- [x] Không lag khi chạy liên tục (rolling buffer giới hạn bộ nhớ)
- [x] Timer refresh ~33ms (~30 FPS)
- [x] Dùng NumPy array cho render (không dùng list Python thuần)
- [ ] Không vẽ scatter dots khi số điểm lớn (tắt symbol khi > SCATTER_MAX)
- [x] Dùng `queue.Queue` tách biệt luồng đọc dữ liệu và luồng vẽ

---

## Modules phụ trợ

- [ ] `providers.py`: `QualSerialProvider`, `QualSimulationProvider`, `QualFileProvider`, `list_serial_ports`
- [ ] `logger.py`: `QualDataLogger` — ghi CSV bất đồng bộ qua queue riêng
