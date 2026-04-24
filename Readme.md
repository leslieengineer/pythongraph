# QUAL Waveform Viewer

Real-time voltage waveform viewer cho dữ liệu QUAL từ Sagemcom AMR qua UART, mô phỏng nội bộ, hoặc playback từ file log.

Project hiện tập trung vào 3 kênh điện áp `U1/U2/U3`. Các phần test, script validation, và mã cũ đã được loại khỏi bundle release này để giữ repo gọn cho phát hành.

## Tính năng chính

- Hiển thị real-time 3 pha điện áp trên một đồ thị duy nhất.
- Hỗ trợ 3 mode:
	- `Online (COM)` đọc từ UART.
	- `Simulation` tạo sóng sin 3 pha nội bộ.
	- `Playback (log)` phát lại từ file log đã lưu.
- Tự nhận diện 2 kiểu dữ liệu ở Online:
	- ASCII legacy: `$Q,<u32_sec>,<u16_ms>,<U1>,<U2>,<U3>[,<I1>,<I2>,<I3>]`
	- Binary frame 10 byte của firmware Nucleo.
- Rolling buffer tối đa 120 giây, chỉ render cửa sổ thời gian đang chọn.
- Crosshair bám chuột và snap tới mẫu gần nhất.
- Hiển thị `V_rms`, `fs`, `fps`, số frame/line trong status bar.
- Ghi log CSV bất đồng bộ sang file.
- Có tùy chọn `Sample dots` để hiện mỗi mẫu là một chấm khi mật độ điểm còn thấp.
- Tự tắt marker mẫu khi số điểm render quá lớn để tránh tụt hiệu năng.

## Cấu trúc release

- `main.py`: giao diện PyQt5, rolling buffer, render, trạng thái ứng dụng.
- `providers.py`: Serial provider, Simulation provider, Playback provider.
- `logger.py`: logger CSV nền và xuất snapshot buffer.
- `requirements.txt`: dependency tối thiểu để chạy ứng dụng.
- `Readme.md`: tài liệu phát hành.

## Yêu cầu môi trường

- Python 3.12 đã được dùng trong workspace hiện tại.
- Các package Python cần có:
	- `numpy`
	- `pyqtgraph`
	- `PyQt5`
	- `pyserial`

Lệnh cài đặt nhanh:

```bash
python -m pip install -r requirements.txt
```

Hoặc cài trực tiếp:

```bash
python -m pip install numpy pyqtgraph PyQt5 pyserial
```

## Cách chạy

```bash
python main.py
```

## Hướng dẫn sử dụng nhanh

### 1. Online (COM)

- Chọn `Mode = Online (COM)`.
- Chọn `Port` và `Baud`.
- Baud mặc định của project là `960000`.
- Nhấn `Start` để bắt đầu đọc dữ liệu từ thiết bị.

### 2. Simulation

- Chọn `Mode = Simulation`.
- Cấu hình `Freq`, `V_rms`, `phi` nếu cần.
- Nhấn `Start` để chạy nguồn dữ liệu giả lập.

### 3. Playback (log)

- Chọn `Mode = Playback (log)`.
- Nhấn `Log…` để chọn file phát lại.
- Điều chỉnh `Speed` nếu muốn tua nhanh/chậm.
- Nhấn `Start` để phát lại theo timestamp trong file.

## Điều khiển hiển thị

- `Window (s)`: chọn độ dài cửa sổ hiển thị.
- `Y zoom (x)`: chỉ thay đổi độ phóng trục Y để quan sát, không đổi giá trị dữ liệu thật.
- `U1`, `U2`, `U3`: ẩn/hiện từng kênh.
- `Sample dots`: bật/tắt marker từng mẫu.

Marker mẫu chỉ hiện khi số điểm đang render không vượt ngưỡng nội bộ. Với cửa sổ ngắn, mỗi mẫu sẽ có chấm rõ ràng; với cửa sổ dài, ứng dụng tự quay về line-only để giữ FPS.

## Logging CSV

- Tick `Log to CSV` để arm logging.
- Chọn file đích bằng nút tên file CSV.
- Nếu app đang dừng, chọn file CSV sẽ xuất ngay snapshot buffer hiện có.
- Nếu app đang chạy và logging bật, dữ liệu mới sẽ được ghi nền sang CSV.

Format file CSV do app ghi:

```text
t_s,U1_mV,U2_mV,U3_mV
```

## Dữ liệu đầu vào được hỗ trợ

### ASCII legacy

```text
$Q,<u32_sec>,<u16_ms>,<U1>,<U2>,<U3>
```

App chỉ dùng 3 giá trị điện áp đầu tiên cho release hiện tại.

### Binary frame 10 byte

```text
Byte 0 : 0xA5
Byte 1..8 : payload 64-bit little-endian
	- bit 0..7   : sample_index (0..155)
	- bit 8..25  : U1 signed 18-bit, 10 mV/LSB
	- bit 26..43 : U2 signed 18-bit, 10 mV/LSB
	- bit 44..61 : U3 signed 18-bit, 10 mV/LSB
Byte 9 : XOR checksum của bytes 1..8
```

### Playback file

App hỗ trợ playback từ:

- Dòng ASCII legacy bắt đầu bằng `$Q,`
- Hoặc CSV đã được app export với header `t_s,U1_mV,U2_mV,U3_mV`

## Hành vi quan trọng

- Logger CSV append qua nhiều session; header chỉ ghi khi file đang rỗng hoặc khi người dùng chọn overwrite.
- Nếu bật logging nhưng chưa có provider chạy, file CSV có thể chỉ chứa header.
- Khi dừng app rồi chọn file CSV, buffer hiện tại được export ngay; nếu không có mẫu nào thì vẫn tạo file header-only.

## Giới hạn hiện tại

- Release này chỉ hiển thị điện áp `U1/U2/U3`, không còn plot dòng điện.
- Chỉ có một đồ thị điện áp, không còn kiến trúc hai plot như bản ý tưởng cũ.
- Playback hiện nạp toàn bộ file vào bộ nhớ trước khi phát.
- Chưa có bộ test release riêng đi kèm bundle hiện tại.

## Gợi ý đóng gói release

Nếu phát hành nội bộ, tối thiểu nên kèm theo:

- `main.py`
- `providers.py`
- `logger.py`
- `requirements.txt`
- `Readme.md`
- Môi trường Python hoặc hướng dẫn cài dependency ở trên
