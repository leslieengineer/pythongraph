# QUAL Waveform Viewer

Ứng dụng desktop để hiển thị sóng điện áp QUAL `U1/U2/U3` theo thời gian thực từ UART, mô phỏng nội bộ, hoặc playback từ file log.

Đây là bản release đã được rút gọn để chỉ giữ phần tính năng chính. Repo hiện không còn mã thử nghiệm, script validation cũ, hay kiến trúc hai đồ thị của bản ý tưởng trước đó.

## Phạm vi release

- Chỉ hiển thị 3 kênh điện áp `U1/U2/U3`.
- Chỉ dùng một đồ thị điện áp duy nhất.
- Có rolling buffer 120 giây để xem lại lịch sử gần.
- Có logging CSV bất đồng bộ và export snapshot buffer.
- Có chế độ xem lại lịch sử với `Go to (s)`, slider, và `Back to live`.

## Tính năng chính

- Hiển thị real-time 3 pha điện áp trên một đồ thị duy nhất.
- Hỗ trợ 3 mode:
	- `Online (COM)` đọc từ UART.
	- `Simulation` tạo sóng sin 3 pha nội bộ.
	- `Playback (log)` phát lại từ file log đã lưu.
- Tự nhận diện 2 kiểu dữ liệu ở Online:
	- ASCII legacy: `$Q,<u32_sec>,<u16_ms>,<U1>,<U2>,<U3>[,<I1>,<I2>,<I3>]`
	- Binary frame 10 byte với layout cố định: `sync + payload packed + checksum`.
- Rolling buffer tối đa 120 giây, chỉ render cửa sổ đang xem thay vì toàn bộ dữ liệu.
- Crosshair bám chuột, snap tới mẫu gần nhất, và hiển thị `t`, `U1`, `U2`, `U3` ở status bar.
- Có baseline ngang cố định tại `U = 0` để dễ quan sát mức 0 V.
- Có vạch dọc riêng cho mốc `Go to`, giúp biết ngay vị trí đang xem trong cửa sổ history.
- Có tùy chọn `Sample dots` để hiện từng mẫu khi mật độ điểm còn thấp.
- Tự tắt marker mẫu khi số điểm render quá lớn để giữ FPS.
- Hiển thị `V_rms`, `fs`, `fps`, số frame/line, và số frame bị drop nếu GUI queue bị quá tải.
- Ghi log CSV bất đồng bộ sang file.

## Thành phần release

- `main.py`: giao diện PyQt5, rolling buffer, render, history review, status bar, entry point.
- `providers.py`: Serial provider, Simulation provider, Playback provider, parse giao thức đầu vào.
- `logger.py`: logger CSV nền và export snapshot buffer.
- `requirements.txt`: dependency đã pin version cho bản release.
- `Readme.md`: tài liệu phát hành và hướng dẫn chạy.

## Yêu cầu môi trường

- Hệ điều hành khuyến nghị: Windows 10 hoặc Windows 11.
- Python khuyến nghị: **official CPython 3.12+ hoặc 3.13+**.
- Bản release này đã được cài và smoke-test với **official CPython 3.13.5 on Windows**.

Lưu ý quan trọng:

- Không nên dùng MSYS2 / MinGW Python để cài bằng `pip install -r requirements.txt`.
- Lý do là wheel chuẩn của `numpy`, `PyQt5`, `pyqtgraph` trên Windows thường được build cho CPython Windows chuẩn, không phải tag MinGW/UCRT. Khi đó `pip` có thể rơi sang build source và fail.

## Dependency đã test

Nội dung hiện tại của `requirements.txt` là các version đã được cài và smoke-test:

- `numpy==2.4.4`
- `PyQt5==5.15.11`
- `pyqtgraph==0.14.0`
- `pyserial==3.5`

## Cài đặt và chạy trên Windows

### Cách khuyến nghị: PowerShell + official CPython

Mở PowerShell tại thư mục project và chạy:

```powershell
py -3.13 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

Nếu máy của bạn dùng CPython 3.12 thay vì 3.13, có thể thay `py -3.13` bằng `py -3.12`.

### Nếu lệnh `py` không có sẵn

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

### Chạy từ Command Prompt

```bat
py -3.13 -m venv .venv
.\.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

### Chạy mà không activate venv

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## Quy trình chạy chương trình

### Bước 1. Mở ứng dụng

Sau khi cài dependency xong:

```powershell
python main.py
```

Ứng dụng sẽ mở một cửa sổ PyQt5 với:

- Hàng `Connection` ở trên cùng.
- Hàng `Options` cho cửa sổ hiển thị, zoom, logging, sample dots, và channel toggle.
- Hàng `History` cho `Go to (s)`, slider scrub, và `Back to live`.
- Một đồ thị điện áp chính.
- Status bar ở dưới cùng.

### Bước 2. Chọn mode dữ liệu

Ứng dụng có 3 mode:

#### 1. Online (COM)

- Chọn `Mode = Online (COM)`.
- Chọn `Port` từ danh sách COM.
- Nếu vừa cắm thiết bị, nhấn nút refresh `⟳` để cập nhật danh sách port.
- Chọn `Baud`.
- Baud mặc định của project là `960000`.
- Nhấn `Start` để bắt đầu đọc dữ liệu.

Khi đang chạy Online:

- `Stop` sẽ dừng provider và dừng cập nhật live.
- `Freeze` sẽ dừng cập nhật hình trên màn hình nhưng app vẫn tiếp tục hút dữ liệu vào rolling buffer.

#### 2. Simulation

- Chọn `Mode = Simulation`.
- Cấu hình `Freq (Hz)` nếu muốn thay đổi tần số nguồn giả lập.
- Cấu hình `V_rms (mV)` để thay đổi biên độ điện áp RMS.
- Cấu hình `φ (°)` nếu muốn dịch pha.
- Nhấn `Start` để chạy nguồn dữ liệu giả lập.

Mode này phù hợp để kiểm tra UI, history review, marker, và logging mà không cần phần cứng thật.

#### 3. Playback (log)

- Chọn `Mode = Playback (log)`.
- Nhấn nút `Log…` trong nhóm `Connection` để chọn file playback.
- Điều chỉnh `Speed` nếu muốn tua nhanh/chậm.
- Nhấn `Start` để phát lại theo timestamp trong file.

Lưu ý:

- Nút `Log…` trong phần `Connection` là để chọn **file playback**.
- Nút đang hiển thị tên file CSV ở hàng `Options` là để chọn **file log đầu ra CSV**.

## Điều khiển hiển thị

- `Window (s)`: độ dài cửa sổ hiển thị trên trục thời gian.
- `Y zoom (x)`: chỉ thay đổi scale trục Y để quan sát; không làm thay đổi dữ liệu gốc.
- `U1`, `U2`, `U3`: bật/tắt từng kênh điện áp.
- `Sample dots`: bật/tắt marker từng mẫu.

Marker mẫu chỉ hiện khi số điểm đang render không vượt ngưỡng nội bộ. Với cửa sổ ngắn, mỗi mẫu sẽ có chấm rõ ràng; với cửa sổ dài, ứng dụng tự quay về line-only để tránh tụt FPS.

## Xem lại lịch sử 120 giây gần nhất

Phần `History` hoạt động trên rolling buffer 120 giây gần nhất đang nằm trong RAM.

- `Go to (s)`: nhập mốc thời gian muốn xem.
- `Go`: nhảy tới mốc thời gian đã nhập.
- Slider ngang: kéo để scrub qua lịch sử trong buffer.
- `Back to live`: quay về chế độ bám live ở cuối buffer.

Các quy tắc quan trọng:

- Khi đang ở history view, dữ liệu live vẫn tiếp tục được nạp vào rolling buffer.
- Vạch dọc màu vàng là mốc `Go to` hiện tại trong cửa sổ đang xem.
- Baseline ngang màu xanh nhạt là mức `U = 0` luôn luôn hiện.
- Crosshair trắng là vị trí chuột hiện tại.
- Cursor ở status bar vẫn hiển thị `t`, `U1`, `U2`, `U3` của mẫu gần nhất đang trỏ tới.

Ý nghĩa thời gian của `Go to (s)` theo mode:

- `Simulation`: thời gian bắt đầu từ `0` khi bấm `Start`.
- `Online` với binary frame: thời gian được app tự dựng lại từ `sample_index`, cũng bắt đầu gần `0` ở đầu session.
- `Online` với ASCII legacy: app dùng `u32_sec + u16_ms / 1000` từ dữ liệu vào.
- `Playback`: app dùng timestamp đã nằm trong file log.

Giới hạn của history review:

- Chỉ xem lại được trong **120 giây gần nhất** còn nằm trong rolling buffer.
- Nếu mốc cũ hơn phạm vi buffer, app sẽ chỉ còn dữ liệu mới hơn.

## Logging CSV

- Tick `Log to CSV` để arm logging.
- Chọn file đích bằng nút hiển thị tên file CSV ở hàng `Options`.
- Nếu app đang dừng, việc chọn file CSV sẽ export ngay snapshot buffer hiện có.
- Nếu app đang chạy và logging đang bật, dữ liệu mới sẽ được ghi nền sang CSV.

Format file CSV do app ghi:

```text
t_s,U1_mV,U2_mV,U3_mV
```

Hành vi logging đã được giữ lại cho release:

- Logger append qua nhiều session.
- Header chỉ ghi khi file đang rỗng hoặc khi người dùng chọn overwrite.
- Nếu bật logging nhưng chưa có provider chạy, file CSV có thể chỉ chứa header.
- Khi dừng app rồi chọn file CSV, nếu buffer rỗng thì vẫn tạo file header-only.

## Dữ liệu đầu vào được hỗ trợ

### Hợp đồng dữ liệu nội bộ của ứng dụng

Mọi nguồn dữ liệu trong app cuối cùng đều được chuẩn hóa về cùng một frame Python nội bộ:

```python
{"t_s": float, "u": [u1, u2, u3]}
```

Quy ước của frame nội bộ:

- `t_s`: timestamp tính bằng giây, tăng đơn điệu.
- `u`: danh sách 3 giá trị kênh analog đang hiển thị, hiện UI đang đặt tên là `U1`, `U2`, `U3`.
- Đơn vị hiện tại của `u1/u2/u3` là `mV`.

Điểm quan trọng để tái dùng cho sản phẩm khác:

- App không bắt buộc dữ liệu phải đến từ đồng hồ điện.
- Điều app thực sự cần là provider phải parse nguồn vào thành đúng frame nội bộ ở trên.
- Nếu thiết bị khác vẫn có 3 kênh analog và timestamp, bạn có thể:
	- phát trực tiếp theo format ASCII `$Q,...`, hoặc
	- phát theo binary 10 byte đúng layout hiện tại, hoặc
	- sửa `providers.py` để parse giao thức riêng của thiết bị rồi trả về frame nội bộ `{"t_s": ..., "u": [...]}`.

Nói ngắn gọn: transport có thể thay đổi, nhưng contract đầu ra của parser vào GUI hiện tại là `t_s + 3 kênh u`.

### ASCII legacy

```text
$Q,<u32_sec>,<u16_ms>,<U1>,<U2>,<U3>
```

Release hiện tại chỉ dùng 3 giá trị điện áp đầu tiên.

### Binary frame 10 byte

Đây là packet nhị phân cố định dài đúng `10 byte`. Parser hiện tại trong [providers.py](providers.py#L39) và [providers.py](providers.py#L99) hiểu packet này theo đúng layout dưới đây.

#### Protocol spec cho firmware / hardware

Nếu cần tích hợp một thiết bị khác vào app mà vẫn dùng nguyên parser binary hiện tại, hãy xem đây là đặc tả packet đầu vào bắt buộc.

| Byte offset | Kích thước | Tên | Bắt buộc | Mô tả |
| --- | --- | --- | --- | --- |
| `0` | `1 byte` | `sync` | Có | Phải đúng `0xA5` |
| `1..8` | `8 byte` | `payload` | Có | Payload packed, đọc theo `little-endian` |
| `9` | `1 byte` | `checksum` | Có | XOR của toàn bộ `payload[0]..payload[7]` |

App chỉ nhận packet nếu đồng thời thỏa cả 3 điều kiện:

- byte đầu là `0xA5`
- tổng chiều dài frame là đúng `10 byte`
- checksum XOR của 8 byte payload khớp byte cuối

Bit-field của `payload` 64-bit:

| Bit | Độ rộng | Tên trường | Kiểu | Ý nghĩa |
| --- | --- | --- | --- | --- |
| `0..7` | `8 bit` | `sample_pos` | unsigned | Vị trí mẫu trong chu kỳ, hợp lệ `0..155` |
| `8..25` | `18 bit` | `U1_raw` | signed | Kênh 1, signed-18 two's complement |
| `26..43` | `18 bit` | `U2_raw` | signed | Kênh 2, signed-18 two's complement |
| `44..61` | `18 bit` | `U3_raw` | signed | Kênh 3, signed-18 two's complement |
| `62..63` | `2 bit` | `reserved` | unsigned | Chưa dùng; nên phát `0` để dễ tương thích |

Quy tắc decode ở phía app:

- `payload` được đọc bằng `int.from_bytes(packet[1:9], "little", signed=False)`
- mỗi trường `U*_raw` được giải mã theo two's complement signed-18
- giá trị thực đưa lên GUI là `U*_mV = signed18_value * 10.0`
- nếu `sample_pos >= 156`, packet bị loại
- nếu `delta sample_pos == 0` so với packet trước, packet bị xem là lặp và bị loại

Quy tắc dựng thời gian:

- App không lấy timestamp tuyệt đối từ packet binary
- App tự dựng `t_s` từ `sample_pos` với giả định `156 sample/cycle` ở lưới `50 Hz`
- tần số lấy mẫu logic hiện tại là `7800 Hz`
- công thức nội bộ:

```text
delta = (sample_pos - last_sample_pos) mod 156
total_samples += delta
t_s = total_samples / 7800.0
```

Điều này có nghĩa là một thiết bị khác không nhất thiết phải là công tơ điện, nhưng nếu muốn tương thích không cần sửa code thì nó phải tuân theo đúng các giả định sau:

- phát đều 3 kênh analog
- dùng signed-18 cho từng kênh
- scale theo `10 mV/LSB`
- dùng `sample_pos` chạy vòng `0..155`
- duy trì thứ tự packet theo thời gian thực

Checklist cho bên phát firmware:

- luôn phát đủ `10 byte/frame`
- không đổi `sync` khỏi `0xA5`
- giữ `payload` ở `little-endian`
- đặt `reserved` về `0`
- bảo đảm `sample_pos` không nhảy sai chu kỳ quá mức
- tính lại checksum XOR sau khi pack payload

Ví dụ pseudo-pack ở phía phát:

```text
payload = 0
payload |= (sample_pos & 0xFF)
payload |= ((U1_raw & 0x3FFFF) << 8)
payload |= ((U2_raw & 0x3FFFF) << 26)
payload |= ((U3_raw & 0x3FFFF) << 44)
payload_bytes = payload.to_bytes(8, "little")
checksum = payload_bytes[0] ^ payload_bytes[1] ^ ... ^ payload_bytes[7]
packet = [0xA5] + payload_bytes + [checksum]
```

Trong đó:

- `U*_raw` là giá trị signed-18 đã đổi sang biểu diễn two's complement 18 bit
- nếu nguồn dữ liệu gốc không ở đơn vị `mV`, bên phát phải tự scale trước khi pack, hoặc parser trong app phải được sửa tương ứng

#### 1. Cấu trúc tổng thể

- Byte `0`: `sync`
- Byte `1..8`: `payload` dài `8 byte`
- Byte `9`: `checksum`

Chi tiết từng phần:

- `sync` phải bằng `0xA5`.
- `payload` được đọc như một số nguyên unsigned 64-bit theo thứ tự `little-endian`.
- `checksum` là phép XOR của toàn bộ `8 byte payload`, không bao gồm byte sync.

Nếu một packet sai `sync`, sai `checksum`, hoặc không đủ `10 byte`, packet đó sẽ bị bỏ qua.

#### 2. Bit layout bên trong payload 64-bit

Sau khi lấy `payload = int.from_bytes(packet[1:9], byteorder="little", signed=False)`, các bit được giải nghĩa như sau:

- Bit `0..7`: `sample_pos`
- Bit `8..25`: `U1_raw`
- Bit `26..43`: `U2_raw`
- Bit `44..61`: `U3_raw`
- Bit `62..63`: hiện chưa dùng, có thể xem là `reserved`

Tức là packet đang mang:

- `1 byte` vị trí mẫu trong chu kỳ
- `3 x 18 bit` dữ liệu signed cho 3 kênh
- `2 bit` dự phòng ở cuối payload

#### 3. Ý nghĩa từng trường

`sample_pos`

- Là chỉ số mẫu trong một chu kỳ 50 Hz.
- Giá trị hợp lệ: `0 .. 155`.
- App hiện giả định có `156 sample / cycle`, nên tần số lấy mẫu logic là:

```text
fs = 156 * 50 = 7800 Hz
```

- Nếu `sample_pos >= 156`, packet bị coi là không hợp lệ.

`U1_raw`, `U2_raw`, `U3_raw`

- Mỗi giá trị rộng `18 bit`, có dấu.
- Parser giải mã theo two's complement signed-18.
- Sau đó nhân với scale `10 mV/LSB`.

Công thức:

```text
U_channel_mV = decode_signed18(raw_18bit) * 10.0
```

Miền giá trị lý thuyết sau scale là xấp xỉ:

- `-131072 * 10 = -1,310,720 mV`
- `+131071 * 10 = +1,310,710 mV`

#### 4. Cách ứng dụng dựng timestamp từ packet binary

Packet binary hiện tại không mang timestamp tuyệt đối theo giây. Thay vào đó app tự dựng `t_s` từ `sample_pos`.

Cách làm hiện tại:

- Packet hợp lệ đầu tiên sẽ đặt `last_sample_pos = sample_pos` và `total_samples = 0`.
- Từ packet kế tiếp, app tính:

```text
delta = (sample_pos - last_sample_pos) mod 156
```

- Nếu `delta == 0`, packet bị bỏ qua vì bị xem là mẫu lặp.
- Nếu hợp lệ, app cộng `delta` vào `total_samples`.
- Timestamp nội bộ được dựng bằng:

```text
t_s = total_samples / 7800.0
```

Hệ quả:

- `t_s` của binary mode bắt đầu gần `0` ở đầu session.
- `t_s` là thời gian tương đối, không phải wall-clock time.
- App giả định dòng packet đi theo đúng thứ tự thời gian và `sample_pos` quay vòng từ `155` về `0`.

#### 5. Ví dụ contract mà thiết bị phát phải đáp ứng

Nếu muốn một sản phẩm khác dùng lại parser binary hiện tại mà không sửa code, thiết bị đó phải phát packet thỏa các điều kiện sau:

- Mỗi frame dài đúng `10 byte`.
- Byte đầu luôn là `0xA5`.
- `payload` 8 byte dùng `little-endian`.
- Ba kênh dữ liệu được đóng gói đúng vị trí bit `8..25`, `26..43`, `44..61`.
- Mỗi kênh dùng signed-18 two's complement.
- Scale đúng `10 mV/LSB`.
- `sample_pos` chạy trong miền `0..155` và tiến đều theo chu kỳ.
- Byte cuối là XOR của `payload[0]..payload[7]`.

Nếu thiết bị khác không đáp ứng đúng contract này, có hai lựa chọn thực tế:

- Giữ nguyên GUI và chỉ sửa parser trong `providers.py` để map giao thức mới về frame nội bộ `{"t_s": float, "u": [u1, u2, u3]}`.
- Hoặc sửa cả parser lẫn UI nếu số kênh, đơn vị, hoặc logic timestamp không còn là mô hình 3 kênh hiện tại.

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

## Troubleshooting

### 1. `pip install -r requirements.txt` bị lỗi khi dùng Python của MSYS2 / MinGW

Nguyên nhân thường là wheel của `numpy` hoặc `PyQt5` không khớp tag interpreter.

Cách xử lý đúng:

- Cài official CPython for Windows.
- Tạo venv mới bằng official CPython.
- Cài lại bằng `pip install -r requirements.txt`.

### 2. Không thấy COM port

- Kiểm tra thiết bị đã được Windows nhận diện hay chưa.
- Nhấn nút refresh `⟳`.
- Đảm bảo driver serial đã cài đúng.

### 3. Playback báo không có frame hợp lệ

Kiểm tra file playback có phải một trong hai dạng sau không:

- Dòng `$Q,...`
- CSV header `t_s,U1_mV,U2_mV,U3_mV`

### 4. Status bar báo có `dropped`

Điều này nghĩa là GUI queue đã bị đầy trong lúc nhận dữ liệu. App vẫn chạy, nhưng có frame bị bỏ bớt để giữ ứng dụng gần real-time.

## Giới hạn hiện tại

- Release này chỉ hiển thị điện áp `U1/U2/U3`, không còn plot dòng điện.
- Chỉ có một đồ thị điện áp, không còn kiến trúc hai plot như bản ý tưởng cũ.
- Playback hiện nạp toàn bộ file vào bộ nhớ trước khi phát.
- Không còn bộ test release đầy đủ trong repo; validation hiện tại dựa trên smoke test và kiểm tra tĩnh.

## Kết quả audit cho release này

Các điểm đã được rà và chốt cho bản phát hành hiện tại:

- `requirements.txt` đã pin version để đảm bảo reproducible install.
- Đã thêm `.gitignore` để chặn `__pycache__`, `*.pyc`, và local venv.
- Đã smoke-test các tính năng history review theo kiểu headless:
	- nhập `Go to (s)`
	- scrub slider
	- cursor readout trong history
	- vạch dọc marker cho mốc `Go to`
	- baseline ngang tại `U = 0`

## Gợi ý đóng gói release

Nếu phát hành nội bộ, tối thiểu nên kèm theo:

- `main.py`
- `providers.py`
- `logger.py`
- `requirements.txt`
- `Readme.md`

Không nên đóng gói kèm:

- `__pycache__`
- local virtual environment (`.venv`, `.venv-cpython`)
- log CSV sinh trong quá trình test thủ công

## Đóng gói thành simulation.exe

Có thể đóng gói app này thành một file `simulation.exe` để mang sang máy Windows khác và chạy mà không cần cài Python riêng trên máy đích.

Điểm cần nói rõ:

- Điều này thực tế nghĩa là `Windows build -> chạy trên Windows khác`.
- Không có nghĩa là cùng một `simulation.exe` sẽ chạy trên macOS hoặc Linux.
- Bản build nên được tạo trên máy có cùng kiến trúc với máy đích, hiện tại là `Windows x64`.

Repo hiện đã có sẵn cấu hình build:

- `simulation.spec`: cấu hình PyInstaller.
- `build_simulation.ps1`: script PowerShell để rebuild file exe.

### Cách build

Từ thư mục project, dùng PowerShell:

```powershell
.\build_simulation.ps1
```

Script này sẽ dùng đúng interpreter đã test là `.venv-cpython\Scripts\python.exe` và gọi PyInstaller bằng file `simulation.spec`.

Nếu muốn chạy lệnh tay thay vì script:

```powershell
.\.venv-cpython\Scripts\python.exe -m PyInstaller --noconfirm --clean simulation.spec
```

### Kết quả build

Sau khi build xong, file chạy sẽ nằm tại:

```text
dist\simulation.exe
```

Trên máy hiện tại, bản one-file đã build thành công với kích thước khoảng `49.65 MB`.

### Cách phát hành sang máy khác

- Chép file `dist\simulation.exe` sang máy Windows đích.
- Chạy trực tiếp file exe đó.
- Máy đích không cần cài Python hay `pip install -r requirements.txt` nữa.

### Lưu ý thực tế khi phát hành exe

- Lần chạy đầu có thể khởi động chậm hơn vì đây là bản `one-file`.
- Windows SmartScreen hoặc antivirus có thể hiện cảnh báo vì file exe là bản tự đóng gói nội bộ, chưa ký số.
- Nếu bên nhận dùng Windows khác kiến trúc hoặc chính sách bảo mật chặt hơn, nên test trước trên đúng môi trường đích.
- Có warning liên quan `OpenGL` trong lúc build; điều này không chặn app hiện tại vì release này không dùng `pyqtgraph.opengl`.
