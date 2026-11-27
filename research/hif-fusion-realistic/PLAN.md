# Kế hoạch nghiên cứu tiền đăng ký (Pre-Registered): Ghép 2 tầng Edge HIF-Sensor (15.36 kHz, 504 B int8) trên mô phỏng hồ quang chập chờn & nhiễu thực tế (Nhánh 10)

Trạng thái: **Đã chạy hoàn tất toàn bộ 5 nhánh trên Kaggle GPU (`christoopherchau/shf-hif-fusion-realistic-t66-gpu` v2, `quick_mode=false`, `2,001.6 s`, `cuda`), lưu đủ `results/hif_fusion_realistic/*.json` & khóa SHA-256 tại `results/provenance/hif_fusion_realistic.json` và đã điền số liệu thật vào Mục 7. Kết quả tự chấm tiền đăng ký bản v2 (hậu kiểm sau v1 nhờ sửa 2 lỗi vật lý phân dòng Kirchhoff + khóa liên động 52a): `R1: PASS`, `R2: PASS`, `R3a: PASS`, `R3b: PARTIAL` (`R3: PARTIAL`), `R4: FAIL` (`8/9` cặp đạt).**  
Yêu cầu gốc: **T-56** (Chuỗi nhiệm vụ: `T-64` khóa kế hoạch → `T-65` lõi mô phỏng `shf/hif_edge.py` & `shf/hif_fusion.py` → `T-66` chạy pipeline & provenance → `T-67` cập nhật mục `2d` trang báo cáo EN/VI → `T-68` đồng bộ tài liệu EN/VI & `harness/facts.toml` → `T-69` viết test & kiểm định tổng thể).  
**Tuyên bố phạm vi trung thực:** Toàn bộ nghiên cứu trong kế hoạch này là **mô phỏng 100%** (OpenDSS miền phasor 60 Hz kết hợp dạng sóng hồ quang Emanuel 2-diode và nhiễu nền mô phỏng ở 122.88 kHz / ADC 15.36 kHz). Không có dữ liệu hiện trường trên lưới vận hành, không có thử nghiệm phần cứng mang điện, không có kết nối SCADA vận hành thực tế.

Tài liệu tham chiếu trực tiếp:
- Quy tắc trung thực & vận hành: `AGENTS.md`, `CLAUDE.md`, `CLAUDE.local.md`
- Thiết kế mô phỏng hồ quang chập chờn + tải theo zone/trôi tải + nhiễu CT/PT (Nhánh 10): `research/realistic-hif-sim/PLAN.md`
- Thiết kế & kết quả HIF-Fusion trên nền 60 Hz sạch cũ (đóng băng, **không sửa**): `research/hif-fusion/PLAN.md`, `results/hif_fusion/*.json`
- Mã nguồn liên quan: `shf/config.py`, `shf/faults.py`, `shf/model.py`, `shf/hif_edge.py`, `shf/hif_fusion.py`, `scripts/hif_fusion_run.py`
- Mô hình Tầng 1 đóng băng: `hif_sensor/results/model_int8.npz` (manifest `hif_sensor/results/provenance/manifest.json`)

---

## 1. Động lực khoa học & số liệu nền đã xác thực (đọc trực tiếp từ `results/`)

Sau khi nâng cấp lõi mô phỏng sự cố chính của **Nhánh 10** (`shf/faults.py`, kết quả chạy thật trong `results/metrics.json` và `results/error_analysis/error_analysis.json`, `11,448` sự cố trên IEEE 123-bus `4.16 kV`, `converged_share = 100.0%`, `GroupKFold` 5-fold theo bus), các mô hình định vị thuần phasor 60 Hz suy giảm mạnh ở dải sự cố chạm đất trở kháng cao (SLG `100–400 Ω`):

1. **Hiệu năng 60 Hz thuần dưới hồ quang chập chờn + tải theo zone/trôi tải + nhiễu CT/PT (`results/metrics.json`, `results/error_analysis/error_analysis.json`):**
   - `fpi_baseline`: tổng thể **`52.5%`** (`0.5254`), không cờ thiết bị `23.1%` (`0.2307`), SLG `100 Ω = 4.5%`, SLG `200 Ω = 2.0%`, SLG `400 Ω = 1.6%`, quãng đường tuần tra `20.7 kft` (so với `39.0 kft` không định vị).
   - `ml_magnitude_only`: tổng thể **`80.2%`** (`0.8017`), `3PH = 100.0%`, `LL = 99.8%`, `LLG = 100.0%`, SLG `100 Ω = 22.3%`, SLG `200 Ω = 14.2%`, SLG `400 Ω = 13.3%`.
   - `ml_full` (150 đặc trưng biên độ + biến thiên `pre/post` đặc thù 10 thiết bị): tổng thể **`91.5%`** (`0.9154`), `3PH = 99.7%`, `LL = 100.0%`, `LLG = 100.0%`, `SLG 0.01–25 Ω = 100.0%`, `SLG 50 Ω = 99.8%`, nhưng tụt mạnh xuống **`84.8%`** ở `SLG 100 Ω`, **`62.5%`** ở `SLG 200 Ω`, và chỉ còn **`31.3%`** (`0.3132`) ở **`SLG 400 Ω`**; mất 1 cảm biến đạt `78.0%–87.9%` (trung bình **`83.2%`**); quãng đường tuần tra tăng lên `7.3 kft`.
   - Phân tích lỗi (`results/error_analysis/error_analysis.json`): trong tổng số **`969` lỗi** (`8.5%`) của `ml_full`, có tới **`844` lỗi (`87.1%`)** nằm ở `SLG >= 200 Ω` (tỷ lệ lỗi: `100 Ω = 15.2%`, `200 Ω = 37.5%`, `400 Ω = 68.7%`); lỗi tăng theo tải (`nhẹ 6.2%`, `vừa 8.6%`, `nặng 10.6%`).

2. **Nguyên nhân vật lý của trần 60 Hz (`results/transfer/signal_to_load.json` và `research/realistic-hif-sim/PLAN.md`):**
   - Trên IEEE 123-bus `4.16 kV` (dòng đầu tuyến định mức `631.5 A` tại `Sw1`), SLG `400 Ω` tuyến tính vốn chỉ kéo trung vị **`6.16 A`** (`0.97%` dòng đầu tuyến). Khi chịu thêm suy giảm thành phần cơ bản Emanuel ($\kappa_{\text{arc}} \approx 0.606$) và tắt/mồi chập chờn ($d_{\text{cond}} \in [0.35, 0.85]$), điện trở hiệu dụng $R_{\text{eff}}$ bị đẩy lên tới `660–2,500 Ω`, kéo dòng 60 Hz xuống chỉ còn `~1–4 A` — chìm sâu dưới trôi tải nền `pre/post` (`0.8%` theo zone + `1.5%` theo điểm $\approx 1\text{–}3\text{ A}$ trên nhánh tải `100–350 A`), sai số hệ thống CT (`1.5%` biên độ, `0.8°` góc pha) và sàn nhiễu cộng tính `NOISE_I_FLOOR_A = 0.5 A`.

3. **Đối chứng với nghiên cứu HIF-Fusion nền 60 Hz sạch cũ (`results/hif_fusion/*.json` — giữ nguyên, không sửa):**
   - Ở thí nghiệm cũ (`research/hif-fusion/PLAN.md`, Kaggle GPU 2026-11-24, không có `sample_arc_resistance`, không trôi tải `pre/post`, không bias CT/PT hay sàn nhiễu `0.5 A`), ghép Tầng 1 `504 B int8` đã kéo:
     - Passive IEEE 123-bus (`11,448` sự cố): `PerNodeGBDT` SLG `400 Ω` từ `78.1% → 97.7%` (`+19.6 điểm %`), `ZoneTreeGNN` từ `79.6% → 96.0%` (`+16.4 điểm %`).
     - Active IEEE 123-bus (`17,847` sự cố hội tụ): `ActivePerNodeGBDT` SLG `400 Ω` từ `72.5% → 86.8%` (`NO_FAULT` FPR `13.9% → 3.3%`), `ActiveGridGATv2` từ `73.5% → 87.5%` (`NO_FAULT` FPR `6.5% → 1.2%`).
     - Active IEEE 34-bus 0-shot (`9,491` sự cố hội tụ): `ActivePerNodeGBDT` tổng thể `83.8% → 87.5%` (SLG `1–10 kΩ`: `71.8% → 77.8%`, FPR `22.1% → 5.8%`), `ActiveGridGATv2` tổng thể `77.6% → 83.3%` (SLG `1–10 kΩ`: `65.3% → 70.0%`, FPR `25.3% → 9.7%`).

**Câu hỏi nghiên cứu trung tâm (T-56):** Khi đưa **đúng kiến trúc 2 tầng Edge HIF-Sensor (`15.36 kHz`, `504 B int8` đóng băng) → Graph FLISR** vào chính môi trường khắc nghiệt của Nhánh 10 (nơi FLISR 60 Hz thuần gãy xuống `31.3%` ở SLG `400 Ω`, và **đồng thời** Tầng 1 cũng phải chịu dòng dư `dI_res` suy giảm thực sự theo `r_eff` và chu kỳ tắt/mồi đồng bộ với `arc_duty`), kiến trúc 2 tầng hồi phục độ chính xác được bao nhiêu mà không làm tụt sự cố pha/trở kháng thấp và không tăng báo giả `NO_FAULT`?

### Bảng đối chứng số liệu nền đã xác thực (từ `results/`, chi tiết đầy đủ Nhánh 10 mới xem Mục 7)

| Nhánh & mô hình | Nguồn `results/` | Tổng thể | SLG `100 Ω` | SLG `200 Ω` | SLG `400 Ω` | SLG `200–400 Ω` (hoặc `1–10 kΩ`) | `NO_FAULT` FPR | Mất 1 cảm biến (mean) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **Nhánh 10 (60 Hz thực tế)** — `fpi_baseline` | `results/metrics.json` | `52.5%` | `4.5%` | `2.0%` | `1.6%` | — | — | — |
| **Nhánh 10 (60 Hz thực tế)** — `ml_magnitude_only` | `results/metrics.json` | `80.2%` | `22.3%` | `14.2%` | `13.3%` | — | — | `72.6%` (`67.7%–76.6%`) |
| **Nhánh 10 (60 Hz thực tế)** — `ml_full` (150 feat) | `results/metrics.json` | `91.5%` | `84.8%` | `62.5%` | **`31.3%`** | — | — | `83.2%` (`78.0%–87.9%`) |
| Nền sạch cũ Passive 123 — `PerNodeGBDT` (`60Hz` → `+Edge`) | `results/hif_fusion/passive_ieee123.json` | `98.2% → 99.7%` | `99.4% → 99.1%` | `96.9% → 98.2%` | `78.1% → 97.7%` | `87.5% → 98.0%` | — | `89.0% → 90.3%` |
| Nền sạch cũ Passive 123 — `ZoneTreeGNN` (`60Hz` → `+Edge`) | `results/hif_fusion/passive_ieee123.json` | `98.0% → 99.5%` | `99.0% → 98.9%` | `93.2% → 98.1%` | `79.6% → 96.0%` | `86.4% → 97.0%` | — | `90.0% → 91.5%` |
| Nền sạch cũ Passive 34 0-shot — `PerNodeGBDT` (`60Hz` → `+Edge`) | `results/hif_fusion/passive_ieee34.json` | `99.8% → 99.8%` | `100.0% → 100.0%` | `99.6% → 99.6%` | `97.4% → 97.8%` | `98.5% → 98.7%` | — | `88.1% → 88.0%` |
| Nền sạch cũ Passive 34 0-shot — `ZoneTreeGNN` (`60Hz` → `+Edge`) | `results/hif_fusion/passive_ieee34.json` | `99.4% → 99.4%` | `99.6% → 100.0%` | `97.4% → 97.8%` | `94.4% → 97.4%` | `95.9% → 97.6%` | — | `86.1% → 85.9%` |
| Nền sạch cũ Active 123 — `ActivePerNodeGBDT` (`60Hz` → `+Edge`) | `results/hif_fusion/active_ieee123.json` | `93.9% → 96.8%` | `93.9% → 95.2%` | `87.9% → 93.8%` | `72.5% → 86.8%` | `80.2% → 90.3%` | `13.9% → 3.3%` | `86.1% → 88.7%` |
| Nền sạch cũ Active 123 — `ActiveGridGATv2` (`60Hz` → `+Edge`) | `results/hif_fusion/active_ieee123.json` | `95.8% → 97.6%` | `95.8% → 96.0%` | `90.8% → 94.2%` | `73.5% → 87.5%` | `82.2% → 90.8%` | `6.5% → 1.2%` | `89.1% → 91.3%` |
| Nền sạch cũ Active 34 0-shot — `ActivePerNodeGBDT` (`60Hz` → `+Edge`) | `results/hif_fusion/active_ieee34.json` | `83.8% → 87.5%` | `85.8% → 86.7%` | — | `84.8% → 86.3%` | `71.8% → 77.8%` | `22.1% → 5.8%` | `72.4% → 75.6%` |
| Nền sạch cũ Active 34 0-shot — `ActiveGridGATv2` (`60Hz` → `+Edge`) | `results/hif_fusion/active_ieee34.json` | `77.6% → 83.3%` | `87.3% → 87.8%` | — | `81.8% → 86.7%` | `65.3% → 70.0%` | `25.3% → 9.7%` | `71.5% → 74.5%` |
| **Thí nghiệm mới (Nhánh 10 thực tế + Edge 15.36 kHz, bản v2)** | `results/hif_fusion_realistic/` | **Đã hoàn tất (xem đầy đủ Mục 7 bên dưới)** | `ml_full 97.6%` / `GBDT 99.0%` / `GNN 97.9%` | `96.5%` / `96.6%` / `95.7%` | **`91.5%` / `91.3%` / `90.8%`** | `94.0%` / `94.0%` / `93.3%` | `A123 GATv2 5.1%` | `90.3%` / `89.6%` / `90.6%` |

---

## 2. Kiến trúc 2 tầng & bộ mô hình đối chứng ghép cặp (khóa siêu tham số)

Mọi phép đo đều là **đối chứng ghép cặp (paired ablation)** trên **cùng tập sự cố OpenDSS thực tế, cùng 5 fold `GroupKFold` theo bus vật lý, cùng cấu hình mạng và cùng `seed`** giữa:
- **`60Hz_only` (thực tế Nhánh 10):** chỉ dùng đặc trưng phasor 60 Hz (chịu đủ hồ quang `r_eff`, tải theo zone/trôi tải, sai số hệ thống CT/PT và sàn nhiễu `0.5 A` / `0.001 pu`).
- **`60Hz_plus_edge` (thực tế Nhánh 10 + Tầng 1 Edge):** bổ sung 2 kênh vô hướng không phụ thuộc lưới `(p_hif, hif_alarm)` từ mô hình Tầng 1 đóng băng vào khối cảm biến trực tuyến của từng thiết bị đóng cắt.

### 2.1 Mô hình Tầng 1 đóng băng (`hif_sensor/results/model_int8.npz`)

- **Tệp đóng băng duy nhất (bắt buộc xác minh SHA-256 trước khi chạy):**
  - Đường dẫn cục bộ trong repo: `hif_sensor/results/model_int8.npz` (trùng khớp byte-for-byte với bản Kaggle `christoopherchau/ch-y-n/results/model_int8.npz`).
  - **SHA-256 khóa cứng:** `3ba5bd23685d7964a6cea0c94064c1e65a8bf3129d83ac129215d110218397c1` (khớp `hif_sensor/results/provenance/manifest.json` và `results/hif_fusion/dataset_summary.json`).
  - **Kiến trúc & kích thước:** `16 → 16 → 8 → 1` (`ReLU` ẩn, `sigmoid` đầu ra), `StandardScaler` gộp vào lớp 1, lượng tử hóa đối xứng theo lớp `int8`: **`417` tham số / `504` bytes** (`392 B` trọng số `int8` + `100 B` bias `float32` + `12 B` hệ số scale `float32`).
  - **Ngưỡng & logic duy trì đóng băng:** `thr = 0.9826354515050169`, `PERSIST = 3` cửa sổ `K = 8` chu kỳ liên tiếp (`133.3 ms`), xuất ra `p_hif = max_{k: ends[k] >= start_cycle} min(p[k-2], p[k-1], p[k]) ∈ [0, 1]` và `hif_alarm = 1.0 if p_hif > thr else 0.0`.
  - **Mạch đầu vào mô phỏng (`shf/hif_edge.py`):** CT kẹp `SCT-013-000` (`2000:1`), điện trở gánh `R_BURDEN = 33.0 Ω` (`16.5 mV/A`), bias `VREF = 1.65 V`, kẹp Schottky `[-0.3 V, 3.6 V]`, bộ lọc Butterworth bậc 4 Sallen-Key (`-3 dB` tại `2,045.1 Hz` LTspice / `2,047.9 Hz` Python IIR), ADC `12-bit` tại **`FS_ADC = 15,360 Hz` (`15.36 kHz`)** với nhiễu cộng `ADC_NOISE_LSB = 1.5` LSB.
  - **Hiệu năng tham chiếu độc lập (mô phỏng, từ `hif_sensor/results/metrics.json`):** `94.7%` phát hiện HIF (`0–1 A: 89.6%`, `1–2 A: 92.0%`, `2–5 A: 97.4%`, `5–10 A: 96.3%`, `>10 A: 97.2%`), `1.5%` báo giả nền (`none 0.0%`, `load_step 1.8%`, `cap_switch 0.0%`, `inrush 4.8%`, `motor_start 3.4%`, `arc_welder 0.0%`, `nonlinear_fluct 0.0%`).
  - **Quy tắc bất biến:** Trọng số và ngưỡng `thr` của `model_int8.npz` **tuyệt đối không được huấn luyện lại hay chỉnh ngưỡng** trên dữ liệu OpenDSS IEEE 123-bus hoặc IEEE 34-bus.

### 2.2 Các mô hình Tầng 2 (giữ nguyên siêu tham số đã khóa — không tinh chỉnh hậu nghiệm)

| Nhánh | Mô hình | Đầu vào `60Hz_only` | Đầu vào `60Hz_plus_edge` | Siêu tham số khóa cứng | Mục đích đối chứng |
|---|---|---:|---:|---|---|
| Passive 123-bus (`11,448` sự cố) | `fpi` | phasor 60 Hz | — (sàn 60 Hz) | Pickup `shf/config.py` (`FPI_*`) | Sàn bảo vệ truyền thống |
| Passive 123-bus (`11,448` sự cố) | `ml_full` (`HistGradientBoostingClassifier`, đặc thù 10 thiết bị) | **`150`** đặc trưng (15/thiết bị × 10, khớp `shf/model.py`) | **`170`** đặc trưng (`150` + `20` kênh `d_p_hif`, `d_hif_alarm`) | `max_iter=300, lr=0.1, max_leaf_nodes=31, dropout=0.15` (`shf/model.py`) | **Đối chứng 1–1 trực tiếp** với mốc `31.3%` SLG `400 Ω` / `91.5%` tổng thể trong `results/metrics.json` |
| Passive 123-bus → 34-bus (`4,104` sự cố) | `PerNodeGBDT` (độc lập lưới) | `21` đặc trưng/nút (`17` điện + `4` cấu trúc cây) | `23` đặc trưng/nút (`19` điện gồm `p_hif, hif_alarm` + `4` cây) | `max_iter=300, lr=0.1, max_leaf_nodes=31, dropout=0.15` | Học cây theo nút + tổng hợp cha/con 1-hop, chuyển giao 0-shot/few-shot |
| Passive 123-bus → 34-bus (`4,104` sự cố) | `ZoneTreeGNN` (độc lập lưới) | `21` đặc trưng/nút | `23` đặc trưng/nút | `2` lớp, `hidden=64, dropout=0.1, lr=2e-3, wd=1e-4, epochs=40, batch=256, sensor_dropout=0.15` | GNN truyền tin hai chiều trên cây zone |
| Active 123-bus (`~17.9k`) → 34-bus (`~9.6k`) | `ActivePerNodeGBDT` | `26` đặc trưng/nút (`21` điện + `5` trạng thái lưới) | `28` đặc trưng/nút (`23` điện + `5` lưới) + thống kê `max/mean(p_hif), sum(hif_alarm)` cho bộ phân loại `NO_FAULT` | `max_iter=300, lr=0.05, max_leaf_nodes=63, dropout=0.15` | Lưới chủ động `0–50%` DER `Model=7`, tái cấu trúc/vòng kín, 7 nhiễu nền `NO_FAULT` |
| Active 123-bus → 34-bus | `ActiveGridGATv2` + Split Conformal `aps_rand` (`90%/95%`) | `26` nút + `4` cạnh | `28` nút + `5` cạnh (thêm `diff_p_hif = p_hif(u) - p_hif(v)`) | `2` lớp, `hidden=64, heads=4, dropout=0.1, lr=2e-3, wd=1e-4, epochs=45, batch=256, sensor_dropout=0.15`, `U_SEED=12345` | GNN chú ý có hướng trên đồ thị tổng quát + cổng quyết định Conformal `aps_rand` 95% |

---

## 3. Cơ chế ghép vật lý trung thực (`ASSUMPTION`) & luật chống gian lận

Mọi giả định dưới đây là **mô phỏng (`ASSUMPTION`)**, được khóa cứng trước khi T-65 lập trình và **tuyệt đối cấm ăn gian bằng dòng tuyến tính sạch hay chu kỳ dẫn hoàn hảo**.

### 3.1 Lõi OpenDSS 60 Hz chế độ thực tế (`realistic=True`) — tái sử dụng đúng cơ chế Nhánh 10

Khi gọi `sweep_passive_fusion(..., realistic=True)` và `sweep_active_fusion(..., realistic=True)` trong `shf/hif_fusion.py`, mỗi sự cố sử dụng đúng 3 hàm vật lý của Nhánh 10 trong `shf/faults.py` và hằng số trong `shf/config.py`:

1. **Hồ quang chập chờn cho chạm đất trở kháng cao (`sample_arc_resistance()`):**
   - Áp dụng cho mọi sự cố `SLG` thỏa `r_nom >= HIF_ARC_MIN_R (100.0 Ω)` (trên IEEE 34-bus `24.9 kV`, áp dụng cùng điều kiện `SLG` có `r_nom >= 100.0 Ω` khi dòng sự cố nằm trong vùng hồ quang, hoặc mọi `SLG >= 400 Ω` và `100 Ω` nhánh `4.16 kV` thỏa `I_fault <= 45 A` sau giải OpenDSS).
   - Lấy mẫu $\gamma_p \sim \text{Uniform}(0.15, 0.45)$, $u_{\text{asym}} \sim \text{Uniform}(1.00, 1.20)$, $\gamma_n = \text{clip}(\gamma_p \cdot u_{\text{asym}}, 0.15, 0.55)$, $\kappa_{\text{arc}} = \frac{1}{2}[k_1(\gamma_p) + k_1(\gamma_n)]$, chu kỳ dẫn chập chờn $d_{\text{cond}} \sim \text{Uniform}(0.35, 0.85)$ với xác suất `HIF_INTERMITTENT_PROB = 0.45` (và `1.0` với xác suất `0.55`), biến thiên tiếp xúc log-normal $m_R = \text{clip}(\exp(\mathcal{N}(0, 0.25^2)), 0.60, 1.80)$.
   - Điện trở hiệu dụng 60 Hz đưa vào OpenDSS `Edit Fault.F ... r={r_eff}`:
     $$R_{\text{eff}} = \text{clip}\!\left(\frac{R_{\text{nom}} \cdot m_R}{\kappa_{\text{arc}} \cdot d_{\text{cond}}},\ 0.5 \cdot R_{\text{nom}},\ R_{\text{eff,max}}(R_{\text{nom}})\right)$$
   - **Khóa bảo toàn vật lý theo cấp điện áp (`ASSUMPTION` cho T-65):** Trên IEEE 123-bus (`4.16 kV`, $R_{\text{nom}} \le 400\ \Omega$) và Passive IEEE 34-bus ($R_{\text{nom}} \le 400\ \Omega$), dùng nguyên `sample_arc_resistance()` với $R_{\text{eff,max}} = \texttt{HIF\_R\_EFF\_MAX} = 2500.0\ \Omega$ (khớp 100% `shf/faults.py`). Riêng trên Active IEEE 34-bus (`24.9 kV`, nơi $R_{\text{nom}} \in \{1000, 2500, 5000, 10000\}\ \Omega$), trần kẹp phải mở rộng theo tỷ lệ `max(config.HIF_R_EFF_MAX, 6.25 * r_nom)` (giữ đúng tỷ lệ `2500 / 400 = 6.25×` của lưới `4.16 kV`) để tránh kẹp ngược sự cố `5–10 kΩ` xuống `2.5 kΩ` làm dễ hóa bài toán giả tạo.
   - Ghi đủ các cột chẩn đoán vào tệp `.npz`: `r` (danh định), `r_eff`, `arc_kappa`, `arc_duty`, `is_arcing`, `realistic_mode = True`.

2. **Tải phân cấp theo zone & trôi tải tự nhiên `pre → post` (`sample_load_factors(..., realistic=True)`):**
   - Ánh xạ từng phụ tải điểm về zone của nó qua `feeder.load_buses(base)` và `grid.bus_zone`.
   - Trước sự cố (`controls=True`): $m_{\text{feeder}} \sim \text{Uniform}(0.3, 1.1)$, $m_{\text{zone}}(z) \sim \text{clip}(\mathcal{N}(1, 0.30^2), 0.45, 1.65)$, $m_{\text{spot}}(\ell) \sim \text{clip}(\mathcal{N}(1, 0.20^2), 0.30, 1.70)$, $f_{\text{pre}}(\ell) = \text{clip}(m_{\text{zone}} \cdot m_{\text{spot}}, 0.25, 2.00)$.
   - Sau sự cố (`controls=False`, khóa nấc điều áp): $f_{\text{post}}(\ell) = f_{\text{pre}}(\ell) \cdot \text{clip}(1 + \delta_{\text{zone}} + \delta_{\text{spot}}, 0.90, 1.10)$ với `LOAD_DRIFT_ZONE = 0.008` (`0.8%`), `LOAD_DRIFT_SPOT = 0.015` (`1.5%`).
   - Trên sự kiện `NO_FAULT` của nhánh Active realistic (`cap_switch`, `pv_cloud`, `load_step`), áp dụng cùng nền trôi tải `f_post` (riêng `load_step` nhân bước nhảy tải cục bộ `1.30–1.80×` lên trên `f_post`) để nhiễu nền cũng chịu độ trôi thực tế.

3. **Sai số hệ thống CT/PT + nhiễu ngẫu nhiên + sàn nhiễu cộng tính (`sample_ct_pt_bias` + `faults._perturb`):**
   - Mỗi sự cố lấy mẫu một bộ bias hệ thống cố định giữa `pre` và `post` cho từng thiết bị và từng pha (`CT_BIAS_MAG = 1.5%` kẹp `±4.5%`, `CT_BIAS_ANG_DEG = 0.8°` kẹp `±2.5°`, `PT_BIAS_MAG = 0.8%` kẹp `±2.5%`, `PT_BIAS_ANG_DEG = 0.4°` kẹp `±1.5°`).
   - Cộng thêm nhiễu ngẫu nhiên độc lập `NOISE_MAG = 1.0%`, `NOISE_ANG_DEG = 0.5°` và sàn nhiễu phức cộng tính trên pha có điện: **`NOISE_I_FLOOR_A = 0.5 A`**, **`NOISE_V_FLOOR_PU = 0.001 pu`**.
   - **Đối chứng 1–1 với `ml_full` (`results/metrics.json`):** Trong `sweep_passive_fusion('ieee123', ..., realistic=True)`, ngoài tensor đồ thị `X` kích thước `(E, 10, 23)`, lưu thêm ma trận `X_ml_full` kích thước `(E, 150)` theo đúng thứ tự cột của `shf/model.py:feature_columns(..., kind='full')` tính từ đúng cặp `(post, pre)` có bias & sàn nhiễu, để T-66 đánh giá trực tiếp `ml_full` (`150` feat vs `170` feat `+Edge`) trên **cùng tập sự cố** và kiểm tra đối chiếu với mốc `31.3%` SLG `400 Ω` / `91.5%` tổng thể của `results/metrics.json`.

### 3.2 Cơ chế ghép trung thực sang Tầng 1 Edge HIF-Sensor (không gian lận dòng hay chu kỳ)

Để đảm bảo Tầng 1 **không ăn gian** dưới bất kỳ hình thức nào khi ghép với Nhánh 10, khóa cứng 4 quy tắc vật lý sau (`ASSUMPTION`):

1. **Dòng dư đưa vào Tầng 1 phải là dòng đã suy giảm theo `r_eff` — và tách sạch phần dòng sự cố với phần trôi tải 60 Hz (chống rò hồ quang giả sang nhánh lành):**
   - Trong chế độ `realistic=True`, giữa `pre_clean` (tải `f_pre`) và `post_clean` (tải `f_post` + sự cố `r_eff`) có cả thành phần **dòng sự cố đã suy giảm theo `r_eff`** lẫn thành phần **trôi tải 60 Hz tuyến tính**.
   - Nếu nhân toàn bộ `|I_res(post_clean) - I_res(pre_clean)|` với dạng sóng hồ quang Emanuel, nhánh lành có trôi tải `1–2 A` sẽ vô tình nhận "hồ quang giả" (sai vật lý). Ngược lại, nếu giải OpenDSS ở `r_nom` sạch để cấp cho Tầng 1 thì là **ăn gian biên độ**.
   - **Giải pháp tách vật lý chính xác trong OpenDSS (bắt buộc cho T-65):** Với mọi sự cố ở chế độ `realistic=True` có khả năng phát hồ quang (`ftype == "SLG"` và `r_nom >= 100 Ω`), sau khi giải `pre_clean` (`f_pre`, `controls=True`), đặt tải `f_post` và giải thêm một bước ngắn `post_drift_clean` (`Fault.F enabled=no`, `controls=False`), sau đó mới đóng `Fault.F` với **`r = r_eff`** (`controls=False`) để thu `post_clean` và `i_fault = fault_current_rms("Fault.F")`:
     - **Dòng dư sự cố đã suy giảm theo `r_eff`:**
       $$\Delta I_{\text{res,fault}}(d) = \left| I_{\text{res}}^{\text{post}}(d) - I_{\text{res}}^{\text{post,drift}}(d) \right|$$
       Giá trị này bằng đúng dòng chia sự cố thực đã bị suy giảm bởi $\kappa_{\text{arc}} \cdot d_{\text{cond}} / m_R$ dọc theo đường dòng sự cố, và xấp xỉ `0 A` (`< 0.05 A`) trên mọi nhánh lành rẽ song song hoặc phía sau điểm sự cố.
     - **Dòng dư trôi tải tuyến tính 60 Hz:**
       $$\Delta I_{\text{res,drift}}(d) = \left| I_{\text{res}}^{\text{post,drift}}(d) - I_{\text{res}}^{\text{pre}}(d) \right|$$
       được tiêm vào dạng sóng sơ cấp của thiết bị `d` dưới dạng bước nhảy hình sin 60 Hz thuần tuyến tính (từ `t >= t0`) — **không bao giờ** nhân với dạng sóng hồ quang Emanuel.
     - Trên các sự cố không hồ quang (`3PH`, `LL`, `LLG`, `SLG` trở kháng thấp hoặc `I_fault > 45 A`) và `NO_FAULT`, không tiêm hồ quang Emanuel; toàn bộ `dI_res(d)` là bước nhảy 60 Hz tuyến tính kèm nhiễu nền tương ứng.
     - Đặc trưng 60 Hz của Tầng 2 (`X_60hz` và `X_ml_full`) vẫn tính hoàn toàn từ `(post, pre)` đã nhiễu hóa (gồm cả `f_post` drift + `r_eff` fault + bias CT/PT + sàn nhiễu), **không hề** dùng `post_drift_clean` (không rò rỉ thông tin).

2. **Đồng bộ mức tắt/mồi hồ quang `arc_duty` vào bộ sinh dạng sóng Emanuel (`shf/hif_edge.py:_arc`):**
   - Bổ sung tham số tùy chọn `arc_duty: float | None = None` vào `he._arc(t, t0, rng, s, arc_duty=None)` và truyền xuống từ `synthesize_event_edge()`:
     - Khi `arc_duty is None` (mặc định, `realistic=False`): giữ nguyên 100% mã cũ `p_off = rng.uniform(0.0, 0.3)` để không làm thay đổi bất kỳ kết quả hay unit test cũ nào.
     - Khi `arc_duty is not None` (`realistic=True`): đồng bộ xác suất mất mồi chu kỳ với tỷ lệ dẫn đã lấy mẫu ở OpenDSS:
       $$p_{\text{off}} = \text{clip}\!\left(1.0 - d_{\text{cond}},\ 0.0,\ 0.65\right)$$
       Cụ thể: với nhóm hồ quang chập chờn (`arc_duty ∈ [0.35, 0.85]`, 45% sự cố hồ quang), hồ quang tắt ngẫu nhiên `15%–65%` số chu kỳ; với nhóm hồ quang liên tục (`arc_duty == 1.0`, 55% sự cố), `p_off = 0.0` (vẫn giữ nguyên dao động `VP, VN, RP, RN` từng nửa chu kỳ `sig ∈ [0.03, 0.12]` và đường bao khởi phát mũ `env`).
     - **Chuẩn hóa năng lượng an toàn khi `p_off` cao:** Chuẩn hóa dạng sóng `i_arc_unit = arc_raw / rms_ref` dùng `rms_tail` trên `20` chu kỳ cuối (nếu `rms_tail <= 1e-9` do tình cờ toàn bộ `20` chu kỳ cuối tắt hết khi `p_off = 0.65`, dự phòng bằng `rms_post` trên toàn miền `t >= t0`; nếu vẫn `<= 1e-9` thì `i_arc_unit = 0`). Sau đó nhân `i_arc_d(t) = ΔI_res,fault(d) * i_arc_unit(t)`: biên độ RMS hiệu dụng của hồ quang đưa vào mạch CT/LPF/ADC đúng bằng dòng sự cố đã suy giảm theo `r_eff` (chỉ còn `~1–4 A` ở SLG `400 Ω`), đồng thời vẫn phải vượt qua bộ đếm `PERSIST = 3` liên tiếp dưới các khoảng tắt chu kỳ thực tế.

3. **Nền dòng dư cục bộ, 5 bề mặt Emanuel và 7 nhiễu nền:**
   - Giữ nguyên chuẩn khớp với `research/hif-fusion/PLAN.md` §3.1–§3.2: dòng dư nền tại mỗi thiết bị đóng cắt đang đóng neo theo `clip(I_res_pre(d), 1.0, 20.0) A RMS` (`make_base_residual`, chứa sóng hài bậc 3/5/7/9, nhiễu băng rộng `0.02–0.2 A`, xác suất `30%` nhiễu chuyển mạch inverter `8–20 kHz`); thiết bị đang mở mang `0 A` (ADC chỉ thấy bias + nhiễu `1.5` LSB).
   - 5 bề mặt Emanuel lấy mẫu đều trên mọi sự cố hồ quang (`wet_grass`, `wet_sand`, `concrete`, `dry_grass`, `dry_asphalt`).
   - 7 nhiễu nền (`none`, `load_step`, `cap_switch`, `inrush`, `motor_start`, `arc_welder`, `nonlinear_fluct`): xác suất `FAULT_DISTURBANCE_PROB = 0.25` độc lập trên từng thiết bị đóng cắt trong sự cố (tiêm nhiễu khó vào cả thiết bị nhánh lành), và ánh xạ cân bằng đầy đủ cả 7 lớp trên các sự kiện `NO_FAULT` nhánh Active.

4. **Tường lửa chống rò rỉ dữ liệu & tương thích ngược:**
   - `find_model_npz()` trong `shf/hif_edge.py` ưu tiên tìm `hif_sensor/results/model_int8.npz` và kiểm tra SHA-256 trùng khớp `3ba5bd23685d7964a6cea0c94064c1e65a8bf3129d83ac129215d110218397c1`.
   - `realistic=False` là mặc định trong `sweep_passive_fusion()` và `sweep_active_fusion()`, bảo toàn 100% tương thích ngược cho `tests/test_hif_fusion.py` và `scripts/hif_fusion_run.py`.
   - `PassiveFusionDataset` và `ActiveFusionDataset` đọc tương thích ngược được cả tệp `.npz` cũ (thiếu `r_eff`, `arc_kappa`, `arc_duty`, `X_ml_full`) lẫn tệp `.npz` realistic mới.
   - Tầng 2 chỉ huấn luyện trên IEEE 123-bus (`GroupKFold` 5-fold theo bus vật lý); IEEE 34-bus chỉ mở đánh giá ở bước 0-shot / few-shot (`5%`, `20%` tách bus) / hiệu chuẩn Conformal tách bus.

---

## 4. Tiêu chí nghiệm thu tiền đăng ký `R1–R4` (`PASS` / `PARTIAL` / `FAIL`)

Mọi tiêu chí dưới đây được **khóa cứng trước khi chạy** và chấm tự động bởi `scripts/hif_fusion_realistic_run.py` trên **cùng tập sự cố thực tế Nhánh 10** (`60Hz_plus_edge` so với `60Hz_only` ghép cặp). Mọi kết quả `PARTIAL` hoặc `FAIL` phải được giữ nguyên và báo cáo trung thực — tuyệt đối không tinh chỉnh ngược siêu tham số, ngưỡng hay độ mạnh nhiễu để "đẩy" sang `PASS`.

### R1 — Mức hồi phục SLG `400 Ω` và SLG `200–400 Ω` trên IEEE 123-bus thực tế (Passive, 5-fold GroupKFold, đủ `11,448` sự cố)

Áp dụng cho bộ 3 mô hình đối chứng `{ml_full, PerNodeGBDT, ZoneTreeGNN}`:
- **`PASS`:**
  1. Ít nhất một trong 3 mô hình `{ml_full, PerNodeGBDT, ZoneTreeGNN}` tăng độ chính xác **SLG `400 Ω`** tối thiểu **`+25.0` điểm %** so với bản `60Hz_only` thực tế ghép cặp của chính nó **VÀ** đạt tối thiểu **`65.0%`** tuyệt đối ở SLG `400 Ω` **VÀ** tăng tổ hợp **SLG `200–400 Ω`** tối thiểu **`+15.0` điểm %**; **VÀ**
  2. Cả 3 mô hình `{ml_full, PerNodeGBDT, ZoneTreeGNN}` đều tăng **SLG `400 Ω`** tối thiểu **`+15.0` điểm %** so với bản `60Hz_only` thực tế ghép cặp; **VÀ**
  3. **Không** có mô hình nào trong 3 mô hình bị tụt độ chính xác quá **`0.5` điểm %** (`delta >= -0.005`) trên nhóm **sự cố pha (`3PH / LL / LLG`)** hoặc nhóm **SLG trở kháng thấp (`0.01–50 Ω`)** (đồng thời ghi nhận chỉ số `0.01–100 Ω` để đối chiếu với bảng cũ).
- **`PARTIAL`:**
  - Ít nhất một mô hình tăng **SLG `400 Ω`** trong khoảng **`+10.0` đến `< +25.0` điểm %** (hoặc tăng `≥ +25.0` điểm % nhưng dưới `65.0%` tuyệt đối, hoặc chỉ 1–2 mô hình đạt `≥ +15.0` điểm %) và tăng **SLG `200–400 Ω`** tối thiểu **`+5.0` điểm %**, đồng thời **không** mô hình nào tụt pha hoặc SLG trở kháng thấp (`0.01–50 Ω`) quá **`0.5` điểm %**.
- **`FAIL`:**
  - Mức tăng **SLG `400 Ω`** tốt nhất `< +10.0` điểm %, **HOẶC** bất kỳ mô hình nào bị tụt sự cố pha (`3PH/LL/LLG`) hoặc SLG trở kháng thấp (`0.01–50 Ω`) quá **`0.5` điểm %**.

### R2 — Độ bền theo nhóm hồ quang chập chờn (`arc_duty < 1.0`) vs liên tục (`arc_duty == 1.0`) và đủ 5 bề mặt Emanuel (IEEE 123-bus thực tế)

Bắt buộc ghi phân rã trên toàn bộ sự cố hồ quang (`is_arcing == True`, `SLG 100–400 Ω`) và riêng dải `SLG 200–400 Ω` theo: (a) hai nhóm `intermittent` (`arc_duty < 1.0`) vs `continuous` (`arc_duty == 1.0`), và (b) cả 5 bề mặt `wet_grass`, `wet_sand`, `concrete`, `dry_grass`, `dry_asphalt`.
- **`PASS`:**
  - Với ít nhất một mô hình đồ thị (`PerNodeGBDT` hoặc `ZoneTreeGNN`), `+Edge` tăng độ chính xác nhóm **hồ quang chập chờn (`arc_duty < 1.0`)** tối thiểu **`+15.0` điểm %** so với `60Hz_only` thực tế ghép cặp **VÀ** giữ độ chính xác tối thiểu **`75.0%`** trên **từng bề mặt trong đủ 5 bề mặt Emanuel** (`min_surface_acc >= 0.750`, bao gồm cả `dry_asphalt`).
- **`PARTIAL`:**
  - `+Edge` tăng nhóm **hồ quang chập chờn (`arc_duty < 1.0`)** từ **`+5.0` đến `< +15.0` điểm %**, **HOẶC** tăng `≥ +15.0` điểm % nhưng có ít nhất một bề mặt nằm trong khoảng `60.0%` đến `< 75.0%` (vẫn cao hơn `60Hz_only` thực tế).
- **`FAIL`:**
  - Nhóm **hồ quang chập chờn (`arc_duty < 1.0`)** tăng `< +5.0` điểm % (hoặc giảm) so với `60Hz_only` thực tế, **HOẶC** có bề mặt dưới `60.0%` mà không cải thiện so với `60Hz_only` thực tế.

### R3 — Chuyển giao 0-shot sang IEEE 34-bus thực tế & Lưới chủ động DER / `NO_FAULT` (7 nhiễu nền) + Conformal `aps_rand` 95%

Chia rõ thành 2 cổng con `R3a` (Passive 34-bus) và `R3b` (Active 123-bus + 34-bus + Conformal) để báo cáo trung thực từng phần:

- **Cổng con `R3a` — Passive IEEE 34-bus thực tế (0-shot & few-shot `5%`/`20%`, `4,104` sự cố):**
  - **`PASS`:** Ít nhất một mô hình (`PerNodeGBDT` hoặc `ZoneTreeGNN`) ở chế độ 0-shot `+Edge` cải thiện **SLG `200–400 Ω`** trên IEEE 34-bus thực tế (hoặc giữ trong phạm vi `≤ 0.5` điểm % nếu `60Hz_only` thực tế đã đạt `≥ 95.0%`) **VÀ** độ chính xác tổng thể 0-shot không tụt quá `0.5` điểm % so với `60Hz_only` thực tế.
  - **`PARTIAL`:** Tổng thể 0-shot không tụt quá `0.5` điểm %, nhưng mức tăng SLG `200–400 Ω` còn khiêm tốn (`< +3.0` điểm % khi `60Hz_only < 95.0%`).
  - **`FAIL`:** `+Edge` làm tụt tổng thể 0-shot quá `0.5` điểm % hoặc làm tụt SLG `200–400 Ω` trên IEEE 34-bus thực tế.

- **Cổng con `R3b` — Active thực tế (IEEE 123-bus & IEEE 34-bus, `0–50%` DER `Model=7`, tái cấu trúc/vòng kín, 7 nhiễu nền `NO_FAULT`, Conformal `aps_rand` 95% `U_SEED = 12345`):**
  - **`PASS`:**
    1. *Active IEEE 123-bus thực tế:* Ít nhất một mô hình (`ActivePerNodeGBDT` hoặc `ActiveGridGATv2`) tăng **SLG `400 Ω`** tối thiểu **`+15.0` điểm %** so với `60Hz_only` thực tế, giảm `NO_FAULT` FPR tổng thể xuống **`≤ 6.0%`** (và thấp hơn `60Hz_only`), đồng thời giữ FPR **`≤ 12.0%`** trên **từng lớp trong đủ 7 nhiễu nền** (`none`, `load_step`, `cap_switch`, `inrush`, `motor_start`, `arc_welder`, `nonlinear_fluct`).
    2. *Active IEEE 34-bus thực tế 0-shot:* Ít nhất một mô hình tăng HIF SLG `1,000–10,000 Ω` tối thiểu **`+5.0` điểm %** và giảm `NO_FAULT` FPR tổng thể tối thiểu **`5.0` điểm %** so với `60Hz_only` thực tế.
    3. *Conformal `aps_rand` 95% (`U_SEED = 12345`):* Không suy biến (tập `90%` và `95%` khác nhau; độ phủ cross-conformal IEEE 123-bus nằm trong **`92.0%–98.0%`**); `+Edge` giữ nguyên hoặc tăng tỷ lệ singleton (`|C| = 1`) với độ chính xác singleton **`≥ 98.0%`** và tỷ lệ cắt nhầm tự động `NO_FAULT` **`≤ 2.0%`**; trên IEEE 34-bus báo cáo đủ cả `q̂` đóng băng từ 123-bus (nêu rõ **không có bảo đảm tính hoán vị / exchangeability**) lẫn hiệu chuẩn lại tách bus `5%` và `20%` (`10` lần rút, không huấn luyện lại trọng số).
  - **`PARTIAL`:** Active 123-bus tăng SLG `400 Ω` (`≥ +5.0` điểm %), giảm `NO_FAULT` FPR tổng thể và giữ độ phủ Conformal 123-bus trong `92.0%–98.0%`, nhưng một chỉ tiêu phụ (ví dụ 1 nhiễu khó `inrush`/`arc_welder` vượt `12.0%`, hoặc mức tăng 34-bus active 0-shot `< +5.0` điểm %) chưa đạt ngưỡng `PASS`.
  - **`FAIL`:** `NO_FAULT` FPR tăng lên so với `60Hz_only` thực tế trên một trong hai lưới, **HOẶC** Conformal 123-bus suy biến / độ phủ rơi ra ngoài `92.0%–98.0%`, **HOẶC** mức tăng SLG `400 Ω` trên Active 123-bus `< +5.0` điểm %.
  - **`NOT_RUN_YET` (luật trung thực phần cứng):** Nếu T-66 chạy cục bộ trên CPU không đủ thời gian hoàn thành trọn nhánh Active GATv2 và phải bàn giao phần Active sang `notebooks/kaggle_hif_fusion_realistic.ipynb` chạy trên Kaggle GPU, cổng `R3b` bắt buộc ghi trạng thái `"NOT_RUN_YET"` trong `summary.json` — và tổng kết `R3` **không được phép** ghi `PASS` cho tới khi cả `R3a` và `R3b` đều chạy thật và đạt `PASS`.

### R4 — Chịu lỗi mất 1 cảm biến (`1 sensor offline`, xóa đồng thời 60 Hz + Edge)

Về mặt vật lý, cảm biến Edge HIF-Sensor nằm trong cùng nút IED/recloser với mạch đo CT/PT 60 Hz. Do đó khi mô phỏng mất 1 cảm biến tại thiết bị `d` (cả trong `15%` sensor dropout lúc huấn luyện lẫn đánh giá `1 sensor offline`), **toàn bộ kênh điện 60 Hz VÀ hai kênh `(p_hif, hif_alarm)` của thiết bị `d` bị đặt về `NaN` đồng thời** (chỉ giữ nguyên kênh cấu trúc/trạng thái lưới).
- **`PASS`:**
  1. Trên **mọi** cặp `(nhánh, lưới, mô hình)` đã chạy thật (`ml_full`, `PerNodeGBDT`, `ZoneTreeGNN` trên Passive 123/34; và `ActivePerNodeGBDT`, `ActiveGridGATv2` trên Active 123/34 khi có), `+Edge` **không** làm giảm `missing_sensor_mean` quá **`1.0` điểm %** (`delta >= -0.010`) so với `60Hz_only` thực tế ghép cặp; **VÀ**
  2. Trên Passive IEEE 123-bus thực tế, `+Edge` cải thiện dương `missing_sensor_mean` tổng thể **VÀ** cải thiện `missing_sensor_slg_200_400_mean` tối thiểu **`+5.0` điểm %** so với `60Hz_only` thực tế cho ít nhất một mô hình đồ thị và cho `ml_full`.
- **`PARTIAL`:** Không cặp nào giảm quá `1.0` điểm %, và `missing_sensor_slg_200_400_mean` trên Passive 123-bus thực tế tăng trong khoảng `+1.0` đến `< +5.0` điểm %.
- **`FAIL`:** Có ít nhất một cặp bị tụt `missing_sensor_mean` quá `1.0` điểm %, **HOẶC** `missing_sensor_slg_200_400_mean` trên Passive 123-bus thực tế tăng `< +1.0` điểm % (hoặc giảm).

---

## 5. Đường dẫn cô lập, hợp đồng tệp đầu ra & ma trận bàn giao (T-65 → T-69)

### 5.1 Tường lửa cô lập tuyệt đối

**Cấm tuyệt đối ghi đè hoặc chỉnh sửa:**
- `results/hif_fusion/*` và `results/provenance/hif_fusion.json` (bảng HIF-Fusion nền 60 Hz sạch cũ)
- `results/metrics.json`, `results/error_analysis/*`, `results/transfer/*`, `results/active_grid/*`, `results/active_grid_ieee37/*`
- `data/generated/hif_fusion_*.npz`, `data/generated/transfer_*.npz`, `data/generated/active_*.npz`

### 5.2 Danh mục đường dẫn mới cô lập

| Thành phần | Đường dẫn cô lập | Task phụ trách | Ghi chú hợp đồng |
|---|---|---|---|
| Kế hoạch tiền đăng ký | `research/hif-fusion-realistic/PLAN.md` | **T-64** (file này) | Khóa tiêu chí `R1–R4` và cơ chế ghép trước khi chạy |
| Lõi ghép thực tế | `shf/hif_edge.py`, `shf/hif_fusion.py` | **T-65** | Giữ mặc định `realistic=False`, `arc_duty=None`; thêm `hif_sensor/results/model_int8.npz` vào `find_model_npz()` |
| Dữ liệu sinh ra (git-ignored) | `data/generated/hif_fusion_realistic_{passive,active}_{ieee123,ieee34}.npz`, `data/generated/hif_fusion_realistic_probs.npz` | **T-65 / T-66** | Chứa đủ `r_eff`, `arc_kappa`, `arc_duty`, `realistic_mode`, và `X_ml_full` `(E, 150)` cho passive 123-bus |
| Script chạy & Kaggle notebook | `scripts/hif_fusion_realistic_run.py`, `notebooks/kaggle_hif_fusion_realistic.ipynb` | **T-66** | Xác minh SHA-256 `model_int8.npz`, chạy `quick_mode=False`, tự chấm `R1–R4` |
| Kết quả JSON cô lập | `results/hif_fusion_realistic/{dataset_summary,passive_ieee123,passive_ieee34,active_ieee123,active_ieee34,conformal_hif,summary}.json` | **T-66** | Chỉ sinh từ script thật; ghi rõ `"simulation_only": true`, `"quick_mode": false`, `"tier1_model_sha256"`, và `"status": "NOT_RUN_YET"` cho nhánh nào chưa chạy (nếu có) |
| Bản ghi nguồn gốc SHA-256 | `results/provenance/hif_fusion_realistic.json` | **T-66** | Ghi qua `shf.provenance.record("hif_fusion_realistic", ...)`, xác thực bởi `python -m shf.provenance` |
| Trang báo cáo & bản công bố | `shf/dashboard.py`, `shf/dashboard_text.py`, `docs/index.html`, `docs/data/hif_fusion_realistic_*.json`, `docs/study/` | **T-67** | Bổ sung bảng Trước/Sau Nhánh 10 vào mục `2d` (EN/VI), giữ nguyên 100% bảng `2d` cũ |
| Tài liệu EN/VI & kiểm định sự thật | `README.md`, `docs/vi/study-guide.md`, `docs/vi/module-guide.md`, `harness/facts.toml`, `harness/check.py` | **T-68** | Nạp namespace `hif_real_*`, bổ sung `[[fact]]` mới mà giữ nguyên 100% `[[fact]]` cũ |
| Kiểm thử đơn vị & tổng kiểm định | `tests/test_hif_fusion_realistic.py` | **T-69** | Kiểm tra `realistic=False/True`, blanking đồng thời 60 Hz + Edge, SHA-256, bảo toàn `results/hif_fusion/`, chạy toàn bộ provenance + `harness/check.py --tests` + Tier-1 + privacy audit |

---

## 6. Cam kết trung thực & giới hạn vật lý

Theo đúng quy định tại `CLAUDE.local.md` và `AGENTS.md`:

1. **Báo cáo trung thực kể cả khi mức tăng thấp hơn bản sạch cũ hoặc gặp `PARTIAL`/`FAIL`:** Trong chế độ thực tế Nhánh 10, dòng sự cố hồ quang SLG `400 Ω` bị suy giảm mạnh theo `r_eff` xuống còn `~1–4 A` kèm tắt/mồi `arc_duty ∈ [0.35, 0.85]` và nền trôi tải. Do đó độ chính xác sau khi ghép `+Edge` nhiều khả năng sẽ **thấp hơn** mức `97.7%` / `96.0%` của bản 60 Hz sạch cũ — điều này hoàn toàn tự nhiên về vật lý và phải được công bố nguyên vẹn đúng như JSON sinh ra.
2. **Không bao giờ bịa số hay làm tròn chệch nguồn:** Mọi con số đưa vào `PLAN.md` (Mục 7 sau T-66), trang báo cáo (`T-67`), và tài liệu (`T-68`) phải truy xuất trực tiếp từ `results/hif_fusion_realistic/*.json` đã qua kiểm tra SHA-256 `shf.provenance`. Bất kỳ nhánh nào chưa chạy xong phải ghi nguyên trạng `"chưa chạy"` / `"NOT_RUN_YET"`.
3. **Toàn bộ là mô phỏng 100% — chưa phải kiểm chứng ngoài lưới thực:** Dạng sóng hồ quang Emanuel 2-diode, 7 nhiễu nền, tải phân cấp theo zone, sai số CT/PT và siêu vị sóng hài bán tĩnh đều là mô hình mô phỏng — bỏ qua quá độ điện từ EMTP, sóng lan truyền, bão hòa lõi CT và độ phi tuyến thực của ADC ESP32.
4. **Khoảng cách miền đã biết giữa mô phỏng và hồ quang thực tế (`hif_sensor/results/real_vehif.json`):** Khi đưa chính tệp `model_int8.npz` đóng băng này (không huấn luyện lại) chạy trên `250` bản ghi sự cố chạm cây thực `22 kV 50 Hz` VeHIF (qua cảm biến và tải mô phỏng), tỷ lệ phát hiện giảm từ **`94.7%`** (Emanuel mô phỏng) xuống **`56.0%`** (`36.2%` ở `0–1 A`, `70.0%` ở `1–2 A`, `94.7%` ở `2–5 A`, `85.7%` ở `5–10 A`; báo giả trên `53` bản ghi nền `0.0%`) do dịch phân bố đặc trưng (`dc_ratio -0.49`, `h2_ratio -0.47`, `even_ratio -0.46` IQR). Do đó kết quả hồi phục tốt trên mô phỏng Emanuel Nhánh 10 **chỉ là bằng chứng kỹ thuật trong mô phỏng**, chưa chứng minh độ chính xác ngoài hiện trường nếu chưa có dữ liệu dao động ký sự cố thực từ điện lực.
5. **Yêu cầu phần cứng triển khai:** Khác với FLISR 60 Hz thuần chỉ cần SCADA/RTU truyền thống, kiến trúc 2 tầng này đòi hỏi thiết bị IED biên (hoặc nút cảm biến cỡ ESP32-S3 + mạch lọc chống răng cưa `fc ≈ 2 kHz`) lấy mẫu dòng dư tại **`≥ 15.36 kHz`** ngay tại từng recloser/cầu dao đóng cắt.

---

## 7. Kết quả thực nghiệm (đã chạy trên Kaggle GPU v2 — xác thực SHA-256)

Toàn bộ pipeline `scripts/hif_fusion_realistic_run.py` đã chạy hoàn tất (`quick_mode = false`, `seed = 0`, `simulation_only = true`, `realistic_mode = true`) trên Kaggle GPU (`christoopherchau/shf-hif-fusion-realistic-t66-gpu` v2, thiết bị `cuda`, `torch 2.11.0+cu130`, `sklearn 1.6.1`, `numpy 2.1.3`, tổng thời gian `2,001.6 s`). Bản v2 sửa hai lỗi mô hình hóa vật lý thuần túy trong `shf/hif_fusion.py` (không đụng ngưỡng tiền đăng ký hay siêu tham số): **(1) Phân dòng sóng hài hồ quang đúng định luật Kirchhoff** (`passive_arc_path_mask`, `active_arc_path_mask`) — chỉ các dao đóng nằm trên đường về trạm–điểm sự cố mới nhận dạng sóng hồ quang Emanuel; các dao hạ lưu khỏe mạnh có lệch `0.06–0.65 A` do sụt áp 60 Hz trên tải ZIP/tụ giữ nguyên bước nhảy 60 Hz tuyến tính (loại bỏ `44.0%` báo động giả hạ lưu trên 24.9 kV IEEE 34-bus); và **(2) Khóa liên động tiếp điểm phụ 52a IEEE C37.2** (`interlock_open_switches=True`) — dao liên lạc đang mở (`0 A` sơ cấp) trả về `(p_hif=0.0, hif_alarm=0.0)` thay vì đưa nhiễu Gaussian `1.5 LSB` của ADC qua mạng MLP Tầng 1 vốn hiệu chuẩn trên dòng mang điện `1–20 A` (loại bỏ `100.0%` báo động giả trên dao liên lạc mở). Tệp Tầng 1 đóng băng `hif_sensor/results/model_int8.npz` (`417` tham số / `504 B`, `thr = 0.9826354515050169`) khớp 100% mã băm SHA-256 `3ba5bd23685d7964a6cea0c94064c1e65a8bf3129d83ac129215d110218397c1`, và toàn bộ 7 tệp đầu ra trong `results/hif_fusion_realistic/` đã được khóa tại `results/provenance/hif_fusion_realistic.json` (`0 changed / 0 missing`). **Toàn bộ số liệu dưới đây là mô phỏng 100%** (OpenDSS + dạng sóng hồ quang 2 diode Emanuel 5 bề mặt + 7 tải nền mô phỏng + trôi tải + sai số CT/PT).

### 7.1 Passive IEEE 123-bus thực tế (`11,448` sự cố, `2,385` hồ quang: `983` chập chờn / `1,402` liên tục; 5-fold GroupKFold theo bus)

Nguồn: `results/hif_fusion_realistic/passive_ieee123.json`.

| Mô hình & cấu hình | Tổng thể | Pha (`3PH/LL/LLG`) | SLG `0.01–50 Ω` | SLG `100 Ω` | SLG `200 Ω` | SLG `400 Ω` | SLG `200–400 Ω` | Mất 1 cảm biến (mean) | Mất 1 CB · SLG `200–400 Ω` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `fpi` (sàn 60 Hz) | `54.9%` | `74.2%` | `63.8%` | `5.9%` | `1.0%` | `0.0%` | `0.5%` | `50.1%` | `0.5%` |
| `ml_full` (`60Hz_only`, 150 feat) | `91.7%` | `99.8%` | `100.0%` | `85.5%` | `61.1%` | `35.0%` | `48.0%` | `83.4%` | `40.9%` |
| **`ml_full` (`60Hz_plus_edge`, 170 feat)** | **`98.9%`** (`+7.2 đ%`) | `99.7%` | `100.0%` | `97.6%` | `96.5%` | **`91.5%`** (`+56.5 đ%`) | **`94.0%`** (`+45.9 đ%`) | **`90.3%`** (`+6.9 đ%`) | **`84.2%`** (`+43.2 đ%`) |
| `PerNodeGBDT` (`60Hz_only`, 21 feat) | `92.1%` | `100.0%` | `100.0%` | `89.3%` | `61.8%` | `35.6%` | `48.7%` | `83.1%` | `43.5%` |
| **`PerNodeGBDT` (`60Hz_plus_edge`, 23 feat)** | **`99.1%`** (`+6.9 đ%`) | `100.0%` | `99.9%` | `99.0%` | `96.6%` | **`91.3%`** (`+55.7 đ%`) | **`94.0%`** (`+45.3 đ%`) | **`89.6%`** (`+6.4 đ%`) | **`82.7%`** (`+39.3 đ%`) |
| `ZoneTreeGNN` (`60Hz_only`, 21 feat) | `92.2%` | `100.0%` | `100.0%` | `86.9%` | `63.8%` | `36.9%` | `50.3%` | `84.5%` | `45.9%` |
| **`ZoneTreeGNN` (`60Hz_plus_edge`, 23 feat)** | **`98.9%`** (`+6.7 đ%`) | `100.0%` | `99.9%` | `97.9%` | `95.7%` | **`90.8%`** (`+54.0 đ%`) | **`93.3%`** (`+43.0 đ%`) | **`90.6%`** (`+6.1 đ%`) | **`84.9%`** (`+39.0 đ%`) |

*(Ghi chú đối chiếu với `results/metrics.json`: `ml_full 60Hz_only` trên cùng cơ chế Nhánh 10 đạt `91.7%` tổng thể và `35.0%` SLG `400 Ω`, rất sát mốc `91.5%` / `31.3%` của `run.py`, chênh lệch nhẹ do luồng RNG độc lập của `sweep_passive_fusion`. Không có mô hình nào tụt quá `0.06` điểm % trên sự cố pha hay SLG `0.01–50 Ω`; dải SLG `0.01–100 Ω` tăng `+1.33` đến `+1.72` điểm %.)*

### 7.2 Phân rã theo chế độ hồ quang chập chờn vs. liên tục và 5 bề mặt Emanuel (Passive IEEE 123-bus thực tế)

Nguồn: `results/hif_fusion_realistic/passive_ieee123.json` (`2,385` sự cố hồ quang `SLG 100–400 Ω`: `983` chập chờn `arc_duty < 1.0`, `1,402` liên tục `arc_duty == 1.0`; riêng `SLG 200–400 Ω`: `657` chập chờn, `933` liên tục).

| Mô hình & cấu hình | Chập chờn (`is_arcing`, `n=983`) | Liên tục (`is_arcing`, `n=1,402`) | Chập chờn (`200–400 Ω`, `n=657`) | Liên tục (`200–400 Ω`, `n=933`) | `wet_grass` | `wet_sand` | `concrete` | `dry_grass` | `dry_asphalt` | Min 5 bề mặt |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `ml_full` (`60Hz_only`) | `48.9%` | `68.7%` | `34.1%` | `57.9%` | `60.3%` | `63.5%` | `57.0%` | `61.9%` | `59.9%` | `57.0%` |
| **`ml_full` (`+Edge`)** | **`95.2%`** (`+46.3 đ%`) | **`95.2%`** (`+26.5 đ%`) | `94.1%` | `93.9%` | `94.8%` | `95.1%` | `94.2%` | `95.3%` | `96.5%` | `94.2%` |
| `PerNodeGBDT` (`60Hz_only`) | `51.4%` | `69.8%` | `36.1%` | `57.6%` | `63.0%` | `63.1%` | `61.1%` | `63.0%` | `60.8%` | `60.8%` |
| **`PerNodeGBDT` (`+Edge`)** | **`95.9%`** (`+44.6 đ%`) | **`95.4%`** (`+25.6 đ%`) | `94.5%` | `93.6%` | `95.2%` | `95.1%` | `94.2%` | `96.1%` | `97.6%` | `94.2%` |
| `ZoneTreeGNN` (`60Hz_only`) | `52.4%` | `69.6%` | `39.0%` | `58.3%` | `64.9%` | `61.6%` | `60.0%` | `63.6%` | `62.3%` | `60.0%` |
| **`ZoneTreeGNN` (`+Edge`)** | **`95.1%`** (`+42.7 đ%`) | **`94.6%`** (`+25.0 đ%`) | `93.9%` | `92.8%` | **`94.1%`** | **`93.6%`** | **`93.5%`** | **`95.9%`** | **`96.7%`** | **`93.5%`** |

### 7.3 Passive IEEE 34-bus thực tế (0-shot & few-shot `5%`/`20%`, `4,104` sự cố, `578` hồ quang)

Nguồn: `results/hif_fusion_realistic/passive_ieee34.json` (`FPI`: tổng thể `52.8%`, SLG `200–400 Ω` `72.5%`, SLG `400 Ω` `63.3%`, mất 1 cảm biến `46.8%`).

| Chế độ & mô hình | Tổng thể (`60Hz` → `+Edge`) | SLG `100 Ω` (`60Hz` → `+Edge`) | SLG `200 Ω` (`60Hz` → `+Edge`) | SLG `400 Ω` (`60Hz` → `+Edge`) | SLG `200–400 Ω` (`60Hz` → `+Edge`) | Mất 1 cảm biến (`60Hz` → `+Edge`) |
|---|---|---|---|---|---|---|
| Zero-shot · `PerNodeGBDT` | **`98.4% → 99.6%`** (`+1.2 đ%`) | `96.3% → 100.0%` | `94.8% → 99.3%` | **`86.5% → 96.2%`** (`+9.7 đ%`) | **`90.6% → 97.8%`** (`+7.1 đ%`) | **`87.3% → 88.2%`** (`+0.9 đ%`) |
| Zero-shot · `ZoneTreeGNN` | `95.8% → 93.8%` (`−2.0 đ%`) | `90.3% → 89.1%` | `82.8% → 74.2%` | `74.5% → 64.0%` (`−10.5 đ%`) | `78.6% → 69.1%` (`−9.6 đ%`) | `83.2% → 82.2%` (`−1.02 đ%`) |
| Few-shot `5%` (2 bus, 10 lần) · `PerNodeGBDT` | `94.3% → 92.0%` | — | — | — | `83.1% → 90.0%` | `78.0% → 75.4%` |
| Few-shot `5%` (2 bus, 10 lần) · `ZoneTreeGNN` | `96.9% → 96.8%` | — | — | — | `87.8% → 91.8%` | `83.6% → 84.1%` |
| Few-shot `20%` (7 bus, 10 lần) · `PerNodeGBDT` | `98.3% → 98.0%` | — | — | — | `92.4% → 95.4%` | `85.3% → 84.7%` |
| Few-shot `20%` (7 bus, 10 lần) · `ZoneTreeGNN` | **`97.7% → 98.6%`** (`+0.9 đ%`) | — | — | — | **`88.2% → 93.2%`** (`+5.0 đ%`) | **`87.6% → 88.2%`** (`+0.6 đ%`) |

**Phân tích vật lý về đảo chiều `R3a: FAIL → PASS` và giới hạn còn lại của `ZoneTreeGNN` trên Passive 34-bus zero-shot:** Ở bản v1, bất kỳ dao nào có `|ΔI_res| ≥ 0.05 A` đều bị bơm sóng hài hồ quang Emanuel, làm các dao hạ lưu khỏe mạnh sau điểm sự cố trên 24.9 kV IEEE 34-bus (`D3, D4, D6, D7` khi sự cố tại `D1`, có `0.06–0.65 A` thuần do sụt áp 60 Hz trên tải ZIP/tụ) phát báo động giả `44.0%`. Khi sửa đúng định luật Kirchhoff (`passive_arc_path_mask` chỉ bơm hồ quang trên đường trạm–sự cố), `PerNodeGBDT` lập tức đảo chiều từ `FAIL` sang **`PASS`** mạnh mẽ (`98.4% → 99.6%` tổng thể, `90.6% → 97.8%` ở `200–400 Ω`, `86.5% → 96.2%` ở `400 Ω`, mất 1 cảm biến `87.3% → 88.2%`, SLG `200–400 Ω` mất 1 CB `+9.5` đ%). Riêng `ZoneTreeGNN` vẫn giảm ở chế độ zero-shot (`95.8% → 93.8%`; mất 1 CB `83.2% → 82.2%`, lố ngưỡng `−1.00` đ% của `R4` đúng `0.02` đ%) do trọng số truyền tin học ở 4.16 kV phụ thuộc mạnh vào tín hiệu `(p_hif, hif_alarm)`, nhưng tinh chỉnh few-shot 20% (7 bus) phục hồi ngay lên `98.6%` vs `97.7%` (`93.2%` vs `88.2%` ở `200–400 Ω`).

### 7.4 Active IEEE 123-bus (`17,862` sự kiện) & Active IEEE 34-bus thực tế (`9,487` sự kiện)

Nguồn: `results/hif_fusion_realistic/active_ieee123.json` (`15,170` sự cố + `2,692` `NO_FAULT`, `3,180` hồ quang: `1,477` chập chờn / `1,703` liên tục) và `results/hif_fusion_realistic/active_ieee34.json` (`8,038` sự cố + `1,449` `NO_FAULT`, `2,804` hồ quang: `1,305` chập chờn / `1,499` liên tục).

| Lưới & mô hình | Tổng thể (`60Hz` → `+Edge`) | SLG `400 Ω` (`60Hz` → `+Edge`) | SLG `200–400 Ω` hoặc `1–10 kΩ` (`60Hz` → `+Edge`) | `NO_FAULT` FPR (`60Hz` → `+Edge`) | Mất 1 cảm biến (`60Hz` → `+Edge`) |
|---|---|---|---|---|---|
| Active 123 · `fpi` | `39.2%` | `0.1%` | `0.7%` | `23.2%` | `37.7%` |
| Active 123 · `ActivePerNodeGBDT` | `87.6% → 93.6%` (`+5.9 đ%`) | `36.3% → 69.2%` (`+32.8 đ%`) | `46.6% → 76.3%` (`+29.7 đ%`) | `18.5% → 8.5%` (`−10.0 đ%`) | `79.9% → 85.0%` (`+5.1 đ%`) |
| Active 123 · `ActiveGridGATv2` | `90.6% → 94.9%` (`+4.4 đ%`) | `41.5% → 72.8%` (`+31.3 đ%`) | `52.7% → 79.3%` (`+26.6 đ%`) | `10.8% → 5.1%` (`−5.7 đ%`) | `84.2% → 88.5%` (`+4.2 đ%`) |
| Active 34 (0-shot) · `fpi` | `43.5%` | `51.3%` | `12.7%` (`1–10 kΩ`) | `16.1%` | `40.8%` |
| Active 34 (0-shot) · `ActivePerNodeGBDT` | `69.6% → 78.2%` (`+8.6 đ%`) | `72.9% → 85.4%` (`+12.5 đ%`) | **`27.3% → 57.5%`** (`+30.3 đ%`) | `29.7% → 22.6%` (`−7.2 đ%`) | `60.8% → 67.2%` (`+6.4 đ%`) |
| Active 34 (0-shot) · `ActiveGridGATv2` | `70.7% → 77.6%` (`+6.8 đ%`) | `70.0% → 77.3%` (`+7.3 đ%`) | **`29.8% → 54.9%`** (`+25.1 đ%`) | `17.3% → 17.4%` (`+0.1 đ%`) | `64.0% → 68.6%` (`+4.6 đ%`) |
| Active 34 (20% few-shot, 5 lần) · `ActivePerNodeGBDT` | `70.2% → 78.6%` (`+8.4 đ%`) | — | `24.0% → 59.3%` (`1–10 kΩ`) | `19.9% → 17.5%` | `61.8% → 68.4%` |
| Active 34 (20% few-shot, 5 lần) · `ActiveGridGATv2` | **`78.5% → 84.9%`** (`+6.3 đ%`) | — | **`40.9% → 64.5%`** (`1–10 kΩ`) | `21.3% → 11.7%` | `71.0% → 76.9%` |

**`NO_FAULT` FPR chi tiết trên đủ 7 nhiễu nền (Active IEEE 123-bus, `+Edge`):**
- `ActiveGridGATv2` (`FPR` tổng thể `5.1%`, giảm `−5.7 đ%` so với `10.8%` ở 60 Hz): `none 0.1%`, `cap_switch 0.3%`, `nonlinear_fluct 4.0%`, `inrush 6.7%`, `arc_welder 11.7%`, **`load_step 20.6%`**, **`motor_start 21.2%`** (2 lớp vượt trần tiền đăng ký `≤ 12.0%` trên argmax thô).
- `ActivePerNodeGBDT` (`FPR` tổng thể `8.5%`, giảm `−10.0 đ%` so với `18.5%` ở 60 Hz): `none 2.9%`, `cap_switch 3.8%`, `nonlinear_fluct 5.9%`, `inrush 7.3%`, **`arc_welder 22.9%`**, **`motor_start 24.0%`**, **`load_step 27.8%`** (3 lớp vượt trần `≤ 12.0%` trên argmax thô).
- **Nhận định khoa học trung thực:** Khi gỡ hai sai lệch mô phỏng của bản v1 (dao liên lạc mở báo giả `100.0%` và dao hạ lưu khỏe mạnh bị bơm sóng hài giả), mô hình không còn tận dụng được đường tắt nhân tạo để tách `NO_FAULT` khỏi HIF chập chờn `1–3 A`, nên độ chồng lấn thực chất giữa bước tải `1.3–1.8×` / khởi động động cơ và HIF trở kháng cao trên lưới DER chủ động lộ rõ ở argmax thô (`R3b` nhận **`PARTIAL`**). Khi đi qua cổng an toàn **Split Conformal 95%**, tỉ lệ cắt nhầm tự động `NO_FAULT` vẫn được chặn ở **`0.3%` (`GBDT`) / `1.0%` (`GATv2`)**.

### 7.5 Split Conformal Prediction (`aps_rand`, `U_SEED = 12345`, `results/hif_fusion_realistic/conformal_hif.json`)

Tập `90%` và `95%` tách biệt rõ (không suy biến: trên 123-bus `+Edge GATv2`, độ phủ `90.0%` với cỡ tập `1.00` vs `95.0%` với cỡ tập `1.10`):

| Mô hình & cấu hình (mục tiêu `95%`) | 123-bus độ phủ | 123-bus cỡ tập | 123-bus 1 nhãn (`|C|=1`) | 123-bus đúng trên 1 nhãn | 123-bus cắt nhầm `NO_FAULT` | 34-bus `q̂` từ 123 *(không bảo đảm hoán vị)* | 34-bus hiệu chuẩn `5%` (mean / min) | 34-bus hiệu chuẩn `20%` (mean / min) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `ActivePerNodeGBDT` (`60Hz_only`) | `95.0%` | `1.99` | `70.3%` | `99.5%` | `0.2%` | `81.0%` | `94.0% / 90.7%` | `94.9% / 92.3%` |
| `ActivePerNodeGBDT` (`+Edge`) | `95.0%` | `1.37` | `79.6%` | `99.2%` | `0.3%` | `85.1%` | `93.3% / 89.4%` | `94.7% / 91.2%` |
| `ActiveGridGATv2` (`60Hz_only`) | `95.0%` | `1.58` | `82.3%` | `98.7%` | `1.2%` | `80.3%` | `94.1% / 90.7%` | `94.3% / 89.8%` |
| **`ActiveGridGATv2` (`+Edge`)** | **`95.0%`** | **`1.10`** | **`89.7%`** (`+7.4 đ%`) | **`98.3%`** | **`1.0%`** | `81.4%` | `92.8% / 82.7%` | `94.0% / 87.3%` |

### 7.6 Bảng tự chấm tiêu chí tiền đăng ký `R1–R4` (`results/hif_fusion_realistic/summary.json`)

| Tiêu chí | Kết luận | Bằng chứng chính (từ `results/hif_fusion_realistic/summary.json`) |
|---|---|---|
| **`R1`** (Hồi phục SLG `400 Ω` & `200–400 Ω` Passive 123-bus) | **`PASS`** | Cả 3 mô hình tăng `+54.0` đến `+56.5` điểm % ở SLG `400 Ω` (`ml_full 35.0% → 91.5%`, `GBDT 35.6% → 91.3%`, `GNN 36.9% → 90.8%`), tăng `+43.0` đến `+45.9` điểm % ở SLG `200–400 Ω`; độ tụt pha & SLG `0.01–50 Ω` tối đa `0.06` điểm % (`≤ 0.5` điểm %). |
| **`R2`** (Chập chờn vs. liên tục & 5 bề mặt Emanuel) | **`PASS`** | Hồ quang chập chờn (`arc_duty < 1.0`) tăng `+42.7` đến `+46.3` điểm % (`ml_full 48.9% → 95.2%`, `GBDT 51.4% → 95.9%`, `GNN 52.4% → 95.1%`); bề mặt thấp nhất đạt `94.2%` (`ml_full`), `94.2%` (`GBDT`), `93.5%` (`GNN`) — vượt xa sàn `75.0%`. |
| **`R3a`** (Passive 34-bus zero-shot) | **`PASS`** | Sửa phân dòng Kirchhoff đảo chiều `R3a` sang **`PASS`**: `PerNodeGBDT` tăng `98.4% → 99.6%` (`+1.2` đ%, SLG `200–400 Ω` `90.6% → 97.8%`, `400 Ω` `86.5% → 96.2%`); `ZoneTreeGNN` vẫn tụt 0-shot `95.8% → 93.8%` (`−2.0` đ%) nhưng phục hồi ở 20% few-shot (`97.7% → 98.6%`). |
| **`R3b`** (Active 123/34 + 7 nhiễu nền + Conformal `aps_rand` 95%) | **`PARTIAL`** | Active 34-bus 0-shot đạt mạnh (`+30.3 / +25.1` đ% ở `1–10 kΩ`, overall `+8.6 / +6.8` đ%); Conformal 123-bus đạt (`95.0%` phủ, `82.3% → 89.7%` 1 nhãn, `98.3%` đúng, `1.0%` cắt nhầm); Active 123-bus SLG `400 Ω` tăng `+32.8 / +31.3` đ% & FPR tổng thể `8.5% / 5.1%`, nhưng argmax thô còn vượt trần `12.0%` trên nhiễu tải lớn (`GATv2 motor_start 21.2% / load_step 20.6%`, `GBDT load_step 27.8% / motor_start 24.0% / arc_welder 22.9%`). |
| **`R3` tổng hợp** (`R3a` ∧ `R3b`) | **`PARTIAL`** | Tăng hạng trung thực từ `FAIL` lên **`PARTIAL`** vì `R3a: PASS` và `R3b: PARTIAL`. |
| **`R4`** (Chịu lỗi mất 1 cảm biến đồng thời 60 Hz + Edge) | **`FAIL`** | `8/9` cặp vượt chuẩn (`+6.1` đến `+6.9` đ% tổng thể và `+39.0` đến `+43.2` đ% SLG `200–400 Ω` trên Passive 123; `Passive 34 GBDT 87.3% → 88.2%` `+0.9` đ%; `+4.2` đến `+6.4` đ% trên Active 123/34), chỉ duy nhất `passive_34_gnn` lố ngưỡng cứng `−1.00` đ% đúng `0.02` đ% (`83.2% → 82.2%`, `−1.02` đ%). |

**Nhắc lại giới hạn trung thực:** Kết quả hồi phục `+54.0` đến `+56.5` điểm % tại SLG `400 Ω` trên IEEE 123-bus thực tế và `+9.7` điểm % zero-shot trên IEEE 34-bus (`PerNodeGBDT`) là **bằng chứng kỹ thuật mạnh trong môi trường mô phỏng** (Emanuel 2-diode + phân dòng Kirchhoff + khóa liên động 52a + tải nền mô phỏng + trôi tải + bias CT/PT), **không phải** kiểm chứng ngoài lưới điện lực thật; khoảng cách miền VeHIF 22 kV của chính mô hình Tầng 1 đóng băng (`94.7% → 56.0%` trong `hif_sensor/results/real_vehif.json`) vẫn giữ nguyên hiệu lực.
