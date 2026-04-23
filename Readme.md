# QUAL Waveform Viewer — Yêu cầu dự án

Real-time oscilloscope 3 pha bằng Python, nhận dữ liệu đo lường qua UART từ thiết bị Sagemcom AMR.

---

## Dữ liệu & Giao thức

- [x] Online UART hiện hỗ trợ 2 kiểu transport:
	- ASCII legacy: `$Q,<u32_sec>,<u16_ms>,<U1>,<U2>,<U3>,<I1>,<I2>,<I3>`
	- Binary frame cố định 9 byte cho firmware Nucleo-L476RG
- [x] Format binary 10 byte/frame:

```text
Byte 0 : 0xA5                  ; sync
Byte 1..8 : payload 64-bit little-endian
	- bit 0..7   : sample_index (0..155)
	- bit 8..25  : U1 signed 18-bit, đơn vị 10 mV/LSB
	- bit 26..43 : U2 signed 18-bit, đơn vị 10 mV/LSB
	- bit 44..61 : U3 signed 18-bit, đơn vị 10 mV/LSB
	- bit 62..63 : reserved = 0
Byte 9 : XOR checksum của bytes 1..8
```

- [x] App Python tự nhận diện ASCII hay binary ở Online (COM), nên vẫn tương thích log/playback cũ
- [x] Baudrate mặc định: **960000** (USART1 / CLI port)
- [x] 156 mẫu mỗi chu kỳ (~7800 mẫu/giây ở 50 Hz)
- [x] Với ASCII: parse timestamp từ `u32_sec` + `u16_ms` → trục X đơn vị giây (độ chính xác ms)
- [x] Với binary: không gửi timestamp mỗi frame; app tái dựng thời gian từ `sample_index` và tốc độ 7800 Hz (~128.205 µs/mẫu)
- [x] Đọc UART trên thread riêng (không block giao diện)

---

## Vì sao Binary giảm payload?

- [x] ASCII gửi số dưới dạng text nên mỗi giá trị điện áp 6 chữ số như `229936` đã tốn 6 byte, chưa tính dấu âm nếu có
- [x] ASCII còn mang theo phần dư thừa mỗi frame: `$Q,`, các dấu phẩy, timestamp `sec,ms`, và `\r\n`
- [x] Binary mới đóng gói `sample_index` + 3 giá trị signed 18-bit vào payload 64-bit; vẫn đủ dải đo nhưng không còn bị kẹp như `int16`
- [x] Binary bỏ timestamp lặp lại ở từng frame; chỉ cần `sample_index` 0..155 rồi app tự nội suy thời gian theo 7800 Hz
- [x] Với UART 8N1, mỗi byte trên dây thực tế tiêu tốn khoảng 10 bit
- [x] ASCII cũ thường rơi vào khoảng 30 đến 40 byte/frame => khoảng 2.34 đến 3.12 Mbit/s ở 7800 frame/s, vượt xa 960000 baud
- [x] Binary mới cố định 10 byte/frame => khoảng 780 kbit/s ở 7800 frame/s, vẫn nằm dưới 960000 baud
- [x] Đổi lại, binary không còn dễ đọc bằng mắt thường trên serial terminal và cần sync/checksum để bắt lỗi khung

---

## Hiển thị đồ thị

- [x] Hiển thị đủ **156 điểm mỗi chu kỳ** (không skip mẫu)
- [ ] ~~2 đồ thị riêng biệt: **Điện áp (U1, U2, U3)** và **Dòng điện (I1, I2, I3)**~~ 
=> Chỉ cần hiển thị điện áp.
- [x] 3 pha hiển thị đan xen nhau dạng sóng sin =>> sóng sin hay không là do dữ liệu đầu vào
- [x] Trục X: thời gian (s); với ASCII độ chính xác **millisecond**, với binary app tái dựng thời gian theo sample index ở 7800 Hz
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

- [x] `providers.py`: `QualSerialProvider`, `QualSimulationProvider`, `QualFileProvider`, `list_serial_ports`
- [x] `QualSerialProvider` tự nhận diện ASCII legacy và binary transport trên cùng COM port
- [x] `logger.py`: `QualDataLogger` — ghi CSV bất đồng bộ qua queue riêng
