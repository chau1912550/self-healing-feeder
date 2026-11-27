# 16 Câu hỏi Phản biện & Phỏng vấn (Hệ thống 2 tầng FLISR + Cảm biến HIF ESP32)

> Tài liệu chuẩn bị bảo vệ đồ án / phỏng vấn kỹ sư Hệ thống điện & AI Nhúng. Mọi con số dưới đây đều đối chiếu trực tiếp từ `results/` và `hif_sensor/results/`, phân định rạch ròi giữa **dữ liệu đo thật** (VeHIF 22 kV, PJM AEP 8.760 giờ) và **mô phỏng** (OpenDSS, LTspice, tải nền).

---

## Phần 1 · Bài toán & Kiến trúc 2 tầng

### 1. Vì sao rơ-le quá dòng chạm đất 51N truyền thống gần như "mù" trước sự cố trở kháng cao (HIF)?
- Trên lưới phân phối `4,16 kV` (IEEE 123-bus), pha chạm đất qua điện trở `400 Ω` chỉ kéo dòng trung vị **`6,2 A`** (`1,0%` dòng tải đầu tuyến `631,5 A`); khi cộng thêm suy giảm hồ quang Emanuel và tắt/mồi chập chờn (Nhánh 10), dòng 60 Hz hiệu dụng còn thấp hơn nữa.
- Ngưỡng tác động 51N buộc phải cài cao hơn dòng mất cân bằng tải bình thường (trong nghiên cứu là `48,3 A` đỉnh ở Tầng 1 và `0,5×` tải đỉnh ở Tầng 2). Vì vậy trên bộ mô phỏng Nhánh 10 (`results/metrics.json`), bộ chỉ báo truyền thống (FPI) chỉ bắt được **`1,6%`** sự cố `400 Ω` trên IEEE 123-bus (và **`0,5%`** ở Tầng 1 mô phỏng), đồng thời bỏ trống hoàn toàn không bật cờ ở **`23,1%`** tổng số sự cố.

### 2. Tại sao phải chia hệ thống thành 2 tầng (Tầng 1 cảm biến biên + Tầng 2 GNN/GBDT toàn tuyến)?
- Ở tốc độ lấy mẫu SCADA truyền thống (`60 Hz`), dòng `6,2 A` nằm gọn trong nhiễu đo `1%` (`~6,3 A` tại đầu tuyến); khi mô phỏng thực tế hơn ở Nhánh 10 (hồ quang chập chờn, trôi tải `pre/post`, sai số hệ thống CT/PT và sàn nhiễu `0,5 A`), độ chính xác `ml_full` 60 Hz tại SLG `400 Ω` tụt chỉ còn **`31,3%`** (tổng thể `91,5%`, `results/metrics.json`), và **`844/969` (`87,1%`)** tổng số lỗi rơi vào dải **`SLG ≥ 200 Ω`** (`results/error_analysis/error_analysis.json`).
- Đẩy dạng sóng `15,36 kHz` từ 10 nút về trung tâm vừa tốn băng thông vừa trễ. Giải pháp 2 tầng xử lý FFT + mạng **Tiny MLP `504 B` int8** đóng băng ngay tại nút biên (`hif_sensor/`), chỉ gửi 2 đại lượng gọn `(p_hif, hif_alarm)` lên Tầng 2 (`shf/hif_fusion.py`):
  - **Trên nền 60 Hz sạch cũ (`results/hif_fusion/`):** đạt trọn **4/4 tiêu chí `H1–H4`**: SLG `400 Ω` thụ động 123-bus tăng **`78,1% → 97,7%`** (`PerNodeGBDT`) / **`79,6% → 96,0%`** (`ZoneTreeGNN`); trên lưới chủ động DER `400 Ω`, `ActiveGridGATv2` tăng **`73,5% → 87,5%`** đồng thời kéo báo nhầm `NO_FAULT` từ **`6,5% → 1,2%`**.
  - **Đối chứng Trước/Sau trên bộ thực tế Nhánh 10 (`results/hif_fusion_realistic/summary.json`, v2 có phân dòng sóng hài Kirchhoff + khóa liên động 52a dao mở):** ghép **`+Edge` `15,36 kHz`** (`504 B` int8 đóng băng) kéo SLG `400 Ω` Passive 123-bus từ **`35,0% → 91,5%`** (`ml_full`), **`35,6% → 91,3%`** (`PerNodeGBDT`), **`36,9% → 90,8%`** (`ZoneTreeGNN`); trên Passive 34-bus zero-shot, `PerNodeGBDT` tăng **`98,4% → 99,6%`** tổng thể và **`90,6% → 97,8%`** ở SLG `200–400 Ω` (`86,5% → 96,2%` ở `400 Ω`); trên Active 123-bus, `ActiveGridGATv2` kéo SLG `400 Ω` từ **`41,5% → 72,8%`** và giảm `NO_FAULT` FPR từ **`10,8% → 5,1%`** (Conformal 95% giữ cắt nhầm tự động ở **`1,0%`**).
  - **Kết quả tiêu chí tiền đăng ký (`R1–R4`, báo cáo trung thực đầy đủ):** **`R1: PASS`** (hồi phục SLG `400 Ω` & `200–400 Ω` Passive 123-bus, không tụt pha / trở kháng thấp quá `0,5` đ%), **`R2: PASS`** (hồi phục nhóm hồ quang chập chờn và giữ `≥ 93,5%` trên đủ 5 bề mặt Emanuel), **`R3: PARTIAL`** (gồm **`R3a: PASS`** trên Passive 34-bus zero-shot nhờ sửa phân dòng Kirchhoff kéo `PerNodeGBDT` lên `99,6%` tổng thể / `97,8%` SLG `200–400 Ω`, trong khi `ZoneTreeGNN` vẫn tụt `95,8% → 93,8%` ở 0-shot và phục hồi lên `98,6%` ở 20% few-shot; và **`R3b: PARTIAL`** vì dù Active 34-bus zero-shot `+30,3 / +25,1` đ% và Conformal `aps_rand` 95% trên 123-bus đều đạt, khi gỡ đường tắt dao mở/hạ lưu thì argmax thô trên Active 123-bus còn vượt trần `12,0%` ở các nhiễu tải lớn `GATv2 motor_start 21,2% / load_step 20,6%` và `GBDT load_step 27,8% / motor_start 24,0% / arc_welder 22,9%`), và **`R4: FAIL`** (`8/9` cặp vượt chuẩn khi mất 1 cảm biến đồng thời 60 Hz + Edge kể cả `Passive 34 GBDT 87,3% → 88,2%`, chỉ duy nhất `passive_34_gnn` lố ngưỡng `−1,00` đ% đúng `0,02` đ% tại `83,2% → 82,2%`).
  - **Giới hạn trung thực:** Toàn bộ dạng sóng hồ quang Emanuel và tải nền ghép vào vẫn là **mô phỏng 100%** (chưa kiểm chứng ngoài lưới điện lực thật), và khoảng cách miền của chính mô hình `504 B` int8 đóng băng trên dữ liệu chạm cây thật **VeHIF `22 kV`** (**`94,7% → 56,0%`**, `hif_sensor/results/real_vehif.json`) vẫn giữ nguyên.

### 3. Hệ thống đã dùng những dữ liệu thực tế nào, và phần nào vẫn là mô phỏng?
- **Dữ liệu đo thật:**
  1. **VeHIF 22 kV, 50 Hz** (Gomes & Ozansoy, *IEEE TPWRD* 2022, CC0): `983` thí nghiệm sự cố chạm cây ngoài lưới thật (`900` hợp lệ) + `53` bản ghi nền thật.
  2. **PJM AEP 2017** (CC0): `8.760` giờ phụ tải MW thực tế trọn năm cho bài toán khôi phục theo mùa.
  3. **15 lưới chuẩn thực tế IEEE & EPRI** (IEEE 13/34/37/123/8500-Node, EU-LV 50 Hz, EPRI Ckt5/7/24/J1/K1/M1).
- **Phần mô phỏng (nêu rõ, không phóng đại):** Toàn bộ lưới OpenDSS, mạch LTspice, tải nền tuyến dây ghép vào VeHIF, hồ quang Emanuel và bảng điều khiển ESP32 trên Wokwi đều là mô phỏng — chưa lắp mạch thật trên lưới đang mang điện và chưa nối SCADA vận hành tại điện lực.

---

## Phần 2 · Tầng 1: Phần cứng CT/LPF, 50 Hz Việt Nam & Dữ liệu thật VeHIF 22 kV

### 4. Thiết kế mạch đầu vào Analog (CT + lọc Sallen-Key) giải quyết rủi ro kỹ thuật gì?
- Kẹp CT `SCT-013-000` (`2000:1`) nối điện trở burden `33 Ω` cho độ lợi `16,5 mV/A` (toàn thang `±100 A` đỉnh trên dải `0–3,3 V` nâng áp `VREF = 1,65 V`), đủ biên dự phòng cho dòng khởi động động cơ mà không bão hòa ADC.
- Mạch lọc thông thấp **Butterworth bậc 4 Sallen-Key** 2 tầng (`MCP6004`, kiểm chứng LTspice 26.1.1: `−3 dB` tại **`2.045,1 Hz`**, suy giảm **`−46,4 dB`** tại Nyquist `7,68 kHz`, trễ pha `4,38°` ở 60 Hz) chặn nhiễu đóng cắt inverter `8–20 kHz` gập xuống dải sóng hài (aliasing). Diode Schottky kẹp bảo vệ chân ADC ESP32-S3; mô phỏng quá độ `30 A rms + 15% hài bậc 3 + nhiễu 9 kHz` giữ áp chân ADC sạch trong **`1,043–2,257 V`**.

### 5. Đem mạch từ lưới Mỹ 60 Hz sang lưới Việt Nam 50 Hz có phải vẽ lại PCB không?
- **Không cần vẽ lại PCB.** Để giữ đúng `256` mẫu/chu kỳ, ADC chỉ đổi tần số lấy mẫu từ `15.360 Hz` (60 Hz) sang **`12.800 Hz`** (50 Hz, Nyquist `6.400 Hz`, cửa sổ 8 chu kỳ `160,0 ms`).
- Nếu giữ nguyên linh kiện (`fc = 2.047,9 Hz`), suy giảm chống răng cưa tại Nyquist 50 Hz giảm nhẹ còn **`−39,99 dB`** (vẫn phủ tới hài bậc `40`, trễ pha giảm còn `3,64°`). Nếu muốn khôi phục đúng chuẩn `> 46 dB`, chỉ cần thay 2 điện trở chuẩn E96 theo tỉ lệ `R × 1,2` (`8,66 kΩ → 10,5 kΩ` và `4,42 kΩ → 5,36 kΩ`), đưa `fc = 1.688,7 Hz` và suy giảm Nyquist lên **`−46,70 dB`** mà giữ nguyên 100% mạch in và tụ điện.
- Chạy đối cặp 250 bản ghi VeHIF thật (`90 s`) ở 50 Hz gốc và 60 Hz resample cho kết quả đồng nhất **`54,4%`** (nền `0,0%`), mô phỏng đạt **`94,3%`** (50 Hz) vs **`94,7%`** (60 Hz).

### 6. Vì sao mô hình Phase 0 tụt từ `94,7%` (mô phỏng) xuống `56,0%` khi chạy zero-shot trên VeHIF 22 kV thật?
- Phân tích dịch chuyển đặc trưng (`hif_sensor/results/real_vehif.json`) chỉ rõ nguyên nhân vật lý: mô hình Emanuel giả định dây rơi xuống đất có điện áp đánh thủng hai bán kỳ chênh mạnh (`Vp ≠ Vn`), sinh ra DC và sóng hài chẵn rất lớn.
- Ngược lại, sự cố chạm cành cây thật ở dải `0–2 A` có dạng dòng rò nhiệt/cacbon hóa đối xứng và đều hơn nhiều (`dc_ratio` lệch **`−0,49 IQR`**, `h2_ratio` **`−0,47 IQR`**, `even_ratio` **`−0,46 IQR`**, `I3_cv` **`−0,38 IQR`**). Ở dải `2–5 A`, mô hình vẫn bắt tới **`94,7%`** (và `0,0%` báo nhầm trên cả `53` bản ghi nền thật), nhưng dải `0–1 A` (`n = 138`) chỉ đạt **`36,2%`**.

### 7. Phase 1.5 (Feature Ablation & Few-Shot VeHIF) cho ra phát hiện khoa học trung thực nào?
- **Khảo sát bỏ nhóm đặc trưng (zero-shot):** nhóm chỉ dùng độ dao động theo thời gian **`temporal_only_8`** (`I3_cv, I1_cv, ph3_jitter, cycle_diff, even_std, h3_trend, I1_trend, interharm`) đạt tới **`51,1%`** trên VeHIF thật `0–2 A` (vượt `all_16` `43,1%` tới `+8,0 pp` mà chưa thấy bản ghi thật nào, nền `0,0%`), chứng minh dao động ngẫu nhiên giữa các chu kỳ bền vững qua miền dữ liệu hơn tỉ lệ sóng hài tĩnh.
- **Thích ứng Few-Shot tách tuyệt đối theo ID bản ghi (300 bản ghi, 5 seed, chốt chặn FA `≤ 1%` mô phỏng & `≤ 2%` đối chứng):**
  - Chỉ chỉnh lớp cuối (`head_recal_int8`) bị giảm còn `44,8%` (lớp ẩn đóng băng phụ thuộc quá mạnh vào bất đối xứng Emanuel).
  - Tinh chỉnh toàn mạng `joint_mlp_int8` (20% = `60` bản ghi thật, giữ nguyên đúng **`504 B` int8**) nâng phát hiện VeHIF tổng từ **`53,3% → 60,2%`**, dải `0–2 A` từ **`42,5% → 49,9%`** (`+7,41 pp`; riêng `0–1 A` từ `31,0% → 41,6%`, `2–5 A` `94,7%`, `5–10 A` `90,2%`), đồng thời giữ an toàn nền thật `1,82%` / đối chứng `0,67%` (**`P1.5-B: PASS`**) và mô phỏng `93,84%` / FA `1,53%` (**`P1.5-C: PASS`**).
  - **Đánh giá trung thực (`P1.5-A: FAIL`):** mức tăng `+7,41 pp` chưa đạt ngưỡng tiền đăng ký `+15 pp`, phản ánh giới hạn vật lý thực sự khi tách dòng rò `< 1 A` dưới tải mất cân bằng `1–20 A` chỉ bằng mạng `504 B`.

### 8. Làm sao chứng minh code C nhúng không chỉ là "mã minh họa" mà chạy khớp Python?
- Toàn bộ chuỗi firmware C99 (`hif_sensor/firmware/hif_dsp.c` + `hif_infer.c` + `test_infer.c` + `test_dsp.c`) được biên dịch nghiêm ngặt bằng **`gcc 13.3.0 -O2 -Wall -Wextra -Werror -lm`** (0 cảnh báo).
- Kiểm chứng khớp bit (`P1.5-D: PASS`) trên 3 bộ vector (`6` chính thức Phase 0, `100` mở rộng Phase 0, `100` mở rộng Phase 1.5 `hif_model_phase15.h`): sai số xác suất lớn nhất chỉ **`4,77×10⁻⁷`** đến **`1,04×10⁻⁶`**, đồng thuận quyết định vượt ngưỡng **`100%`**, kiểm đúng máy trạng thái duy trì `3` cửa sổ (`hif_update`/`hif_reset`), tốc độ máy chủ **`0,540–0,611 µs/lần`**. Workflow GitHub Actions `.github/workflows/verify.yml` tự biên dịch lại công khai trên Linux mỗi lần push.

---

## Phần 3 · Tầng 2: Định vị FLISR, Chuyển lưới (IEEE 34/37 & 15 lưới), DER, Conformal & Khôi phục

### 9. Tại sao dùng `GroupKFold` theo nút sự cố thay vì chia ngẫu nhiên `train_test_split`?
- Nếu chia ngẫu nhiên theo sự kiện, cùng một nút (bus) có mặt ở cả tập train và tập test với các mức điện trở khác nhau — mô hình sẽ học thuộc đặc trưng nút đó (data leakage). `GroupKFold` theo `fault_bus` buộc mô hình luôn phải dự đoán trên **những bus chưa từng thấy khi huấn luyện**. Ngoài ra, việc ngẫu nhiên hóa tải từng kịch bản (`0,3–1,1×` toàn lưới ± `20%` từng nút) cũng loại bỏ rò rỉ học thuộc dòng tải nền.

### 10. Vì sao mô hình chuyển sang IEEE 34-bus đạt `99,8%` nhưng sang cáp ngầm IEEE 37-bus lại thất bại (`P1-Fail`)?
- **IEEE 34-bus (24,9 kV, nối đất):** ở `400 Ω`, dòng sự cố trung vị đạt `31,7 A` (`61,1%` dòng đầu tuyến `51,8 A`), tín hiệu rất rõ nên GBDT đạt **`99,8%`** và GNN đạt **`99,3%`** zero-shot.
- **IEEE 37-bus (4,8 kV, cáp ngầm 3 dây delta không nối đất):** không có dây trung tính nối đất tại trạm, nên sự cố SLG chỉ khép mạch qua điện dung rò của cáp ngầm các pha lành — dòng sự cố thậm chí khi chạm trực tiếp `0,01 Ω` chỉ đạt trung vị **`2,36 A`** (`0,64%` dòng đầu tuyến `369,5 A`), còn điện áp pha lành dâng về `√3 pu`. Chế độ vật lý này không tồn tại trong tập huấn luyện 4 dây nối đất 123-bus, khiến SLG zero-shot sụp xuống **`22,4%`** (GBDT) / **`5,6%`** (GNN; FPI `0,0%`), trong khi sự cố giữa các pha (`3PH/LL/LLG`) vẫn đạt **`100,0% / 99,7%`**. Khi huấn luyện tại lưới (5-fold CV), mô hình đạt **`91,4% / 88,0%`**, chứng minh 21 đặc trưng vẫn chứa đủ thông tin khi có dữ liệu lưới delta.

### 11. Khi nào GNN (`ZoneTreeGNN` / `ActiveGridGATv2`) thực sự vượt GBDT?
- Trên lưới hình tia thụ động đủ cảm biến, `PerNodeGBDT` ngang hoặc nhỉnh hơn GNN (`98,3%` vs `98,1%` trên 123-bus; `99,8%` vs `99,3%` trên 34-bus).
- GNN thắng rõ trong **2 tình huống khó**:
  1. **Mất 1 cảm biến trên lưới lớn:** trên cả 6/6 lưới quy mô điện lực của EPRI, `ZoneTreeGNN` vượt GBDT khi mất 1 cảm biến (ví dụ EPRI Ckt7 18 vùng: **`94,3%`** vs **`90,5%`**) nhờ truyền thông điệp đồ thị suy ngược từ vùng lân cận.
  2. **Lưới chủ động có 0–50% DER inverter (`Model=7`), mạch vòng & nhiễu `NO_FAULT`:** `ActiveGridGATv2` đạt **`95,8%`** vs `93,9%` của GBDT trên 123-bus, đồng thời cắt một nửa tỉ lệ cắt nhầm `NO_FAULT` (**`6,5%`** vs `13,9%`), và vượt trội khi thích ứng 20% few-shot trên 34-bus (**`89,1%`** vs `83,1%`) và 37-bus (**`76,2%`** vs `62,0%`).

### 12. Vì sao Stage-2 `BusGraphGNN` thua công thức vật lý Takagi?
- Công thức điện kháng Takagi 3 pha (dùng trực tiếp ma trận tổng trở 3×3 của OpenDSS, **0 bước huấn luyện**) đạt **`46,9%` top-1 / `69,0%` top-3** trên 123-bus và **`57,5% / 87,4%`** trên 34-bus, vượt xa `BusGraphGNN` (`17,8% / 38,5%` CV trên 123-bus). Các cặp bus hay nhầm nhất (`61→61s`, `160→160r`, `832→888`) có `ΔX1 = 0,000 Ω` — nhánh rẽ song song cùng khoảng cách điện về mặt vật lý không thể phân biệt chỉ bằng 1 cảm biến đầu vùng. Đây là bằng chứng trung thực rằng không nên ép ML thay vật lý ở chỗ vật lý giải chính xác hơn.

### 13. Split Conformal Prediction giúp ích gì cho vận hành an toàn, và giới hạn của nó là gì?
- Thay vì ép mô hình lúc nào cũng đoán 1 vùng, `aps_rand` (mục tiêu phủ `95%`) chỉ cho phép tự động đóng cắt khi tập dự đoán chỉ có đúng 1 nhãn (singleton), còn khi không chắc chắn sẽ trả về nhiều vùng để giao nhân viên kiểm tra.
- Trên lưới huấn luyện 123-bus (`+Edge ActiveGridGATv2`), độ phủ đạt đúng **`95,0%`**, tỷ lệ tự động 1 nhãn tăng từ `89,2%` lên **`93,0%`** (độ đúng trên tập 1 nhãn **`98,9%`**, cắt nhầm `NO_FAULT` tự động chỉ **`0,5%`**).
- **Giới hạn trung thực:** ngưỡng hiệu chuẩn `q̂` của 123-bus **không tự bảo toàn độ phủ 95%** khi chuyển zero-shot sang lưới mới (`81,4%` trên 34-bus, `47,4%` trên 37-bus; cần hiệu chỉnh trên lưới đích, đạt chuẩn từ `20%` số bus trên 37-bus).

### 14. Trong bài toán khôi phục cấp điện, giới hạn nào thực sự chặn việc đóng thêm dao liên lạc?
- **Điện áp (ANSI C84.1 Range A: `0,95–1,05 pu`), không phải dòng mang tải đường dây.** Trên 10 tình huống sự cố lúc tải đỉnh, thuật toán loại **`22` phương án ứng viên**: `20` do thấp áp cuối nhánh liên lạc, `2` do **quá áp** (bù sụt áp của bộ điều áp đầu tuyến), và **`0` do quá tải dây dẫn**.
- Khi ánh xạ qua `8.760` giờ phụ tải thực tế PJM AEP 2017, tỷ lệ phụ tải lành được cấp lại tăng từ **`37,2%`** (giả định tải đỉnh) lên **`44,0%`** trung bình cả năm (**`42,1%`** nếu buộc giữ an toàn suốt 6 giờ sửa chữa; ban đêm `03:00` mùa hè đạt **`50,0%`** vs cao điểm `17:00` chỉ **`36,7%`**).

### 15. Giảng viên có thể tự kiểm chứng độ trung thực và bảo mật của dự án bằng cách nào?
- Chỉ cần clone repo và chạy đúng **2 dòng lệnh** (cũng chạy tự động trên GitHub Actions `.github/workflows/verify.yml`):
  1. `python -m shf.provenance` — tính lại toàn bộ **26 manifest / 60 file SHA-256** (`0 changed, 0 missing, 0 unrecorded`), cộng thêm `python -m hif.provenance --verify` (`23/23` file Tầng 1).
  2. `python harness/check.py --tests` — tự tính lại toàn bộ con số trong `README.md` / `docs/` từ `results/` qua `harness/facts.toml`, kiểm tra mọi liên kết, chặn cụm từ phóng đại, quét rò rỉ thông tin cá nhân/bí mật (`scripts/privacy_audit.py`), và chạy toàn bộ bộ kiểm thử `pytest`.

### 16. Khi xin được dữ liệu sự cố thật (COMTRADE) từ điện lực thì đưa vào hệ thống như thế nào?
- **COMTRADE là gì & đổi sang đặc trưng model:** COMTRADE (IEEE C37.111, `.cfg`/`.dat`/`.cff`) là file dạng sóng sự cố do rơ-le/recloser lưu lại. Module [`shf/comtrade.py`](../../shf/comtrade.py) đọc chuẩn 1999 & 2013 (`ASCII`, `BINARY`, `BINARY32`, `FLOAT32`, `.cff`, 50/60 Hz, tỷ số CT/PT), trích phasor trước/trong sự cố bằng DFT 1 chu kỳ rồi đổi đúng sang bộ đặc trưng các mô hình đang dùng: **15** đặc trưng/thiết bị (`150` cột cho Tầng 2 GBDT), **21** đặc trưng/nút chuyển lưới, **26** đặc trưng/nút lưới chủ động, và **16** đặc trưng Tầng 1 HIF khi đủ tần số lấy mẫu và độ dài ≥ 8 chu kỳ.
- **Chạy 1 lệnh không cần sửa code ([`data/comtrade_samples/README.md`](../../data/comtrade_samples/README.md)):** `.venv\Scripts\python scripts/comtrade_ingest.py <file.cfg hoặc thư_mục_sự_cố> --v-base-kv <kV>` (kèm `--channel-map <file.json>` nếu tên kênh khác chuẩn).
- **Kết quả kiểm chứng & giới hạn trung thực ([`results/comtrade/summary.json`](../../results/comtrade/summary.json)):** Đã kiểm tra đạt **11/11** mẫu — **5/5** bản ghi COMTRADE công khai mã nguồn mở (MIT / CC0-1.0 từ lưới ngoài) và **6/6** bản ghi vòng kín mô phỏng: **3/3** sự cố OpenDSS 10 thiết bị khớp dự đoán trên cả 3 mô hình (Tier-2 GBDT, Transfer GBDT, Transfer GNN; sai số tương đối đặc trưng Tầng 2 tối đa `0.012%`), **2/2** mẫu LTspice khớp trong `0.0001%` / `0.0%`, và **1/1** mẫu HIF Tầng 1 khớp `p_hif` với sai số `0.0` (sai số đặc trưng tối đa `1.1e-05`). **Giới hạn:** chưa có dữ liệu sự cố thực địa từ lưới điện lực; toàn bộ mô hình đều huấn luyện trên mô phỏng, và 1 file đơn lẻ chỉ điền **15/150** đặc trưng Tầng 2 nên không đủ định vị toàn tuyến (thử nghiệm minh họa: 1 thiết bị đoán nhầm `L77` ở `42.05%`, đủ 10 thiết bị khôi phục đúng `Sw2` ở `99.86%`).
