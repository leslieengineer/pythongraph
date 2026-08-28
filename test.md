# 🧪 QUAL Waveform Viewer — Production Verification Test Cases
# 🧪 Bảng Kiểm Thử Xác Thực Sản Phẩm (Production)

---

## 1. Global Configuration & Dynamic Units Test / Cấu Hình Chung & Kiểm Tra Đơn Vị Động
- [ ] **TC-01: Scale = 1.0 (Raw ADC Mode / Chế độ ADC thô)**
  - **EN:** Enter `Scale (ADC->Unit) = 1.0000`[cite: 9, 10]. Verify that the two plot titles update to `Phase Values [ADC]` and `Coupled Phase Values [ADC]`. Verify that the Y-axis label and the `RMS` status readout show the `ADC` unit[cite: 9, 10].
  - **VI:** Nhập `Scale (ADC->Unit) = 1.0000`[cite: 9, 10]. Kiểm tra tiêu đề 2 đồ thị đổi thành `Phase Values [ADC]` và `Coupled Phase Values [ADC]`. Kiểm tra nhãn trục Y và chỉ số `RMS` ở thanh trạng thái hiển thị đúng đơn vị `ADC`[cite: 9, 10].
- [ ] **TC-02: Scale != 1.0 (Physical Unit Mode / Chế độ Đơn Vị Vật Lý)**
  - **EN:** Enter `Scale (ADC->Unit) = 100.0` (or any value other than 1.0)[cite: 9, 10]. Verify that plot titles, Y-axis labels, RMS status, and cursor readouts switch to `mV`[cite: 9, 10]. Ensure **no unintended SI prefixes** (like `kmV`) appear on the Y-axis.
  - **VI:** Nhập `Scale (ADC->Unit) = 100.0` (hoặc giá trị bất kỳ khác 1.0)[cite: 9, 10]. Tiêu đề đồ thị, nhãn trục Y, RMS và chỉ số Cursor phải chuyển sang đơn vị `mV`[cite: 9, 10]. Đảm bảo **không xuất hiện tiền tố lạ** như `kmV` trên trục Y.
- [ ] **TC-03: Subsampling 1/2 Verification / Xác Thực Lấy Mẫu Giảm 1/2 (Window Scaling)**
  - **EN:** Set `Samples/Cycle = 312`[cite: 9, 10] and `Window (cyc) = 4`[cite: 9]. Verify that the graph X-axis range automatically scales from `0` to `624` samples ($4 \times \frac{312}{2}$).
  - **VI:** Cấu hình `Samples/Cycle = 312`[cite: 9, 10], `Window (cyc) = 4`[cite: 9]. Trục X trên biểu đồ phải tự động khớp giới hạn từ `0` đến `624` mẫu ($4 \times \frac{312}{2}$).

---

## 2. Mode: Online (COM) & UART Protocol Test / Chế Độ Online & Giao Thức UART
- [ ] **TC-04: Port & Baud Rate Initialization / Khởi Tạo Cổng & Tốc Độ Baud**
  - **EN:** Launch the app; verify default port is `COM1` and default baud rate is `2000000`[cite: 9]. Click `⟳` (Refresh) to update available serial ports[cite: 9]. Verify manual port and baud input works as expected[cite: 9].
  - **VI:** Mở ứng dụng; kiểm tra cổng mặc định là `COM1` và baudrate mặc định là `2000000`[cite: 9]. Nhấn nút `⟳` (Refresh) để cập nhật lại danh sách cổng[cite: 9]. Đảm bảo có thể tự nhập cổng COM hoặc Baud rate tùy ý[cite: 9].
- [ ] **TC-05: 13-Byte Binary Protocol Parsing / Giải Mã Gói Nhị Phân 13-Byte (`0xA5`)**
  - **EN:** Connect hardware sending the 13-byte frame with `0xA5` sync byte[cite: 10]. Click `▶ Start`[cite: 9, 10]. Verify that waveforms render continuously and smoothly[cite: 10]. Ensure `frames` and `bytes` on the status bar increment steadily with zero `csum_err`[cite: 2, 7].
  - **VI:** Kết nối phần cứng và gửi frame 13-byte có mã đồng bộ `0xA5`[cite: 10]. Nhấn `▶ Start`[cite: 9, 10]: Đồ thị vẽ sóng liên tục, ổn định[cite: 10]. Chỉ số `frames` và `bytes` trên thanh trạng thái tăng đều đặn, không có lỗi `csum_err`[cite: 2, 7].
- [ ] **TC-06: Asynchronous CSV Logging / Ghi Log CSV Bất Đồng Bộ**
  - **EN:** Check `Log to CSV` and click `📁` to set the output file[cite: 9, 10]. Click `▶ Start`[cite: 9, 10]; verify the button text changes to `⏺ Logging: <filename>` and status bar confirms recording[cite: 2, 7]. Click `■ Stop`[cite: 9, 10] and inspect the CSV header:
    `index,fw_min,fw_sec,fw_ms,P1_val,P2_val,P3_val,rms_P1_val,...`[cite: 10]
    Click `📂` to verify it opens the directory containing the log file[cite: 9].
  - **VI:** Tích chọn `Log to CSV` và nhấn `📁` để chọn file lưu[cite: 9, 10]. Nhấn `▶ Start`[cite: 9, 10]; kiểm tra nút chuyển sang `⏺ Logging: <filename>` và thanh trạng thái báo đang ghi[cite: 2, 7]. Nhấn `■ Stop`[cite: 9, 10] và mở file kiểm tra đúng định dạng header:
    `index,fw_min,fw_sec,fw_ms,P1_val,P2_val,P3_val,rms_P1_val,...`[cite: 10]
    Nhấn nút `📂` để đảm bảo mở đúng thư mục chứa log[cite: 9].

---

## 3. Mode: Simulation Test / Chế Độ Mô Phỏng (Simulation)
- [ ] **TC-07: Parameter Control & Waveform Rendering / Điều Khiển Tham Số & Vẽ Sóng**
  - **EN:** Switch to `Mode = Simulation`[cite: 9, 10]. Verify that Online controls (`Port`, `Baud`, `Log to CSV`) and Playback controls (`Playback File`, `Speed`) are hidden[cite: 2, 7]. Click `▶ Start`[cite: 9, 10]; verify 3 balanced sine waves with $120^\circ$ phase shift appear[cite: 10]. Adjust `V_rms (mV)` and `φ (°)` to verify real-time amplitude and phase angle updates[cite: 9, 10].
  - **VI:** Chuyển `Mode = Simulation`[cite: 9, 10]. Đảm bảo các trường Online (`Port`, `Baud`, `Log to CSV`) và Playback (`Playback File`, `Speed`) tự động ẩn[cite: 2, 7]. Nhấn `▶ Start`[cite: 9, 10]; kiểm tra 3 sóng sin lệch pha $120^\circ$ xuất hiện chuẩn xác[cite: 10]. Thay đổi `V_rms (mV)` và `φ (°)` để kiểm tra biên độ và pha cập nhật tức thì[cite: 9, 10].

---

## 4. Mode: Playback & Scenario Builder Test / Chế Độ Phát Lại & Tạo Kịch Bản Lỗi
- [ ] **TC-08: Log Loading & Replay Speed / Nạp File Log & Tốc Độ Phát**
  - **EN:** Switch to `Mode = Playback (log)`[cite: 9, 10]. Click `📁 Choose File...` and select a valid CSV log[cite: 9, 10]. Verify the file name appears on the button[cite: 2, 7]. Click `▶ Start`[cite: 9, 10]; verify smooth playback at $f_s = \frac{\text{SPC}}{2} \times \text{Freq}$. Set `Speed = 2.0` and verify the replay runs twice as fast[cite: 9].
  - **VI:** Chuyển `Mode = Playback (log)`[cite: 9, 10]. Nhấn `📁 Choose File...` và chọn file log CSV hợp lệ[cite: 9, 10]. Tên file hiển thị gọn gàng trên nút bấm[cite: 2, 7]. Nhấn `▶ Start`[cite: 9, 10]; kiểm tra dữ liệu phát lại mượt mà theo $f_s = \frac{\text{SPC}}{2} \times \text{Freq}$. Đổi `Speed = 2.0` để kiểm tra tốc độ tua nhanh gấp đôi[cite: 9].
- [ ] **TC-09: Scenario Mutation (Scale & Cut to 0 / Co Giãn & Cắt Về 0)**
  - **EN:** Enter `Start = 1000`, `End = 2000`, `Phase = Phase 1`, `Action = Scale (%)`, `Val 1 = 20`[cite: 9]. Click `➕` to add rule[cite: 9]. Click `▶ Build Scenario`[cite: 9, 10] and save the generated file. Verify the new file loads automatically, and replaying it shows a 20% voltage sag on Phase 1[cite: 9].
  - **VI:** Nhập `Start = 1000`, `End = 2000`, `Phase = Phase 1`, `Action = Scale (%)`, `Val 1 = 20`[cite: 9]. Nhấn `➕` để thêm quy tắc[cite: 9]. Nhấn `▶ Build Scenario`[cite: 9, 10] và lưu file mới. Đảm bảo file tự động load vào và khi phát lại thấy sụt áp 20% trên Phase 1[cite: 9].
- [ ] **TC-10: Scenario Mutation (Add Harmonic & Flicker / Bơm Sóng Hài & Flicker)**
  - **EN:** Add rules for `Add Harmonic` (Order = 3) or `Add Flicker` (Freq = 5Hz)[cite: 9]. Build the scenario and verify mathematically correct waveform distortion upon replay[cite: 9].
  - **VI:** Thêm quy tắc `Add Harmonic` (Order = 3) hoặc `Add Flicker` (Freq = 5Hz)[cite: 9]. Build kịch bản và kiểm tra sóng bị biến dạng đúng công thức toán học[cite: 9].

---

## 5. Timeline & History Review Test / Thanh Dòng Thời Gian & Xem Lại Lịch Sử
- [ ] **TC-11: Full-Width 10,000-Step Timeline Slider / Thanh Trượt 10,000 Bước Toàn Chiều Rộng**
  - **EN:** During running, stopping, or freezing, verify the timeline slider stretches across the full window width. Drag the slider to scrub through buffer history; verify `History: <start> .. <end>` state displays and movement is ultra-smooth without jumping. Verify the yellow vertical marker (`History VLine`) accurately indicates the scrub position[cite: 2, 5, 7].
  - **VI:** Khi đang chạy, dừng hoặc freeze, thanh trượt Timeline phải dãn rộng toàn bộ chiều ngang cửa sổ. Kéo thanh trượt để tua lịch sử bộ đệm; kiểm tra trạng thái `History: <start> .. <end>` hiển thị mượt mà, không bị giật/nhảy vọt. Vạch dọc màu vàng (`History VLine`) phải chỉ đúng vị trí đang tua[cite: 2, 5, 7].
- [ ] **TC-12: Direct Go-to Index / Nhảy Trực Tiếp Đến Index**
  - **EN:** Enter a target sample index into `History Index` and click `Go`[cite: 9, 10]. Verify the view jumps immediately to center around the requested sample[cite: 2, 5, 7].
  - **VI:** Nhập một số index vào ô `History Index` và nhấn nút `Go`[cite: 9, 10]. Đồ thị phải nhảy ngay lập tức đến vùng chứa index đó[cite: 2, 5, 7].
- [ ] **TC-13: Return to Live / Quay Lại Luồng Trực Tiếp**
  - **EN:** Click `⬤ Live`[cite: 9, 10]. Verify history mode exits and the plot returns to tracking incoming real-time samples[cite: 5, 9].
  - **VI:** Nhấn nút `⬤ Live`[cite: 9, 10]. Biểu đồ phải thoát chế độ History và bám sát luồng dữ liệu thời gian thực mới nhất[cite: 5, 9].

---

## 6. Graph Interaction & Measurement Test / Tương Tác Đồ Thị & Đo Đạc Con Trỏ
- [ ] **TC-14: Channel Visibility Toggles / Ẩn/Hiện Kênh Đo**
  - **EN:** Check / uncheck `P1`, `P2`, `P3` and `P1-2`, `P2-3`, `P3-1` checkboxes[cite: 10]. Verify corresponding traces toggle visibility instantly on both plots[cite: 2, 7].
  - **VI:** Bỏ tích / Tích chọn các ô `P1`, `P2`, `P3` và `P1-2`, `P2-3`, `P3-1`[cite: 10]. Các đường sóng tương ứng phải ẩn/hiện tức thì trên biểu đồ[cite: 2, 7].
- [ ] **TC-15: Auto & Manual Y-Zoom / Thu Phóng Trục Y**
  - **EN:** Increase `Zoom (×)` to `2.0` or `5.0`; verify Y-axis visually scales without altering raw data[cite: 3, 9]. When large spikes appear, ensure Y-axis auto-expands[cite: 3, 9]. When signal drops, ensure Y-axis **does not shrink automatically** (prevents erratic zooming)[cite: 3, 9].
  - **VI:** Tăng `Zoom (×)` lên `2.0` hoặc `5.0`; kiểm tra trục Y phóng to trực quan mà không sửa đổi dữ liệu gốc[cite: 3, 9]. Khi có xung áp lớn, trục Y tự mở rộng[cite: 3, 9]. Khi điện áp giảm, trục Y **không được tự co rút đột ngột** (chống giật màn hình)[cite: 3, 9].
- [ ] **TC-16: Precision Cursor Snapping / Bắt Điểm Con Trỏ Chuột Chính Xác**
  - **EN:** Move mouse across plots; verify white crosshair tracks the nearest sample point[cite: 5]. Verify the `Cursor` readout on the status bar displays the exact index and instantaneous values: `idx=... P1=... P2=... P3=...`[cite: 10].
  - **VI:** Rê chuột trên 2 biểu đồ; con trỏ chữ thập trắng phải bám dính vào điểm mẫu gần nhất[cite: 5]. Nhãn `Cursor` ở góc phải thanh trạng thái phải hiển thị chính xác index và giá trị tức thời: `idx=... P1=... P2=... P3=...`[cite: 10].