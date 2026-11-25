# Cảm biến AI phát hiện sự cố trở kháng cao (HIF) — Giai đoạn 0, 1 & 1.5

Bài học + hướng dẫn vận hành. Các giai đoạn mô phỏng (Phase 0), thử trên dữ liệu VeHIF thật (Phase 1), điều chỉnh miền + kiểm tra 50/60 Hz + kiểm chứng firmware C bằng GCC (Phase 1.5) đều đã hoàn tất; **lắp mạch PCB vật lý và đo thực tế tại phòng thí nghiệm vẫn là bước phần cứng tiếp theo** (chưa thực hiện).

## 1. Bài toán (nói được trong phỏng vấn)
- Dây trung thế đứt rơi xuống cỏ khô, cát hay nhựa đường chỉ kéo vài ampe. Rơ-le quá dòng (51N) cài ngưỡng cao hơn dòng tải bình thường nên **không thấy**. Dây vẫn có điện, dễ gây cháy hoặc điện giật.
- Dự án feeder 123-bus đã chứng minh điều này: sự cố 400 Ω chỉ kéo khoảng 6 A, bộ chỉ báo sự cố chỉ bắt được 1%.
- Ý tưởng: sự cố HIF tạo **hồ quang**, và hồ quang để lại "dấu vân tay" trong dạng sóng: méo không đối xứng (có sóng hài chẵn và thành phần DC), sóng hài bậc 3 lớn, và **mỗi chu kỳ một khác** (ngẫu nhiên). Một mô hình AI nhỏ chạy ngay trên chip có thể học nhận ra dấu vân tay đó.

## 2. Phần Circuit Design: mạch đầu vào ([`circuit/`](circuit/ltspice_results.json), [`hif/frontend.py`](hif/frontend.py))
Đường đi tín hiệu: dòng điện → kẹp CT → điện trở burden → nâng mức lên 1.65 V → lọc chống răng cưa → ADC của ESP32-S3.

| Bước | Giá trị | Vì sao |
|---|---|---|
| Kẹp CT SCT-013-000 | 2000:1 | Kẹp ngoài dây, không chạm dây điện. 30 A sơ cấp → 15 mA thứ cấp |
| Burden (biến dòng thành áp) | 33 Ω → **16.5 mV/A** | V = I·R = 15 mA × 33 Ω ≈ 0.5 V rms. Toàn thang ±1.65 V ↔ ±100 A đỉnh, dư chỗ cho dòng khởi động |
| Nâng mức (VREF) | 1.65 V, cầu phân áp 10k/10k + op-amp đệm | ADC chỉ đọc áp dương 0–3.3 V, nên phải "đẩy" sóng AC lên giữa thang |
| Lọc chống răng cưa (60 Hz US & 50 Hz VN/Úc) | Butterworth bậc 4, fc ≈ 2 kHz, hai tầng Sallen-Key | Giữ cố định 256 mẫu/chu kỳ: **60 Hz** lấy mẫu **15,360 Hz** (Nyquist **7,680 Hz**, cửa sổ 8 chu kỳ **133.33 ms**); **50 Hz Việt Nam/Úc** lấy mẫu **12,800 Hz** (Nyquist **6,400 Hz**, cửa sổ 8 chu kỳ **160.0 ms**). Trên cùng PCB giảm **39.99 dB** ở Nyquist 50 Hz; nếu đổi 2 điện trở `R × 1.2` sang **10.5 kΩ** và **5.36 kΩ** (giữ nguyên layout PCB & tụ) thì `fc = 1,688.73 Hz`, giảm **46.70 dB** ở 6.4 kHz. |
| Bảo vệ ADC | 100 Ω + 2.2 nF, diode Schottky kẹp về 0 V và 3.3 V | Xung sét hoặc đóng cắt không làm cháy chân ADC |
| Op-amp | MCP6004 (4 op-amp, rail-to-rail, nguồn 3.3 V) | Dùng 1 cái cho VREF, 2 cái cho 2 tầng lọc |

**Công thức Sallen-Key (khuếch đại = 1, hai điện trở bằng nhau R):**
- Tần số riêng: f0 = 1 / (2π · R · √(C1·C2))
- Hệ số phẩm chất: Q = ½ · √(C1/C2). C1 là tụ hồi tiếp, C2 là tụ xuống mass.
- Butterworth bậc 4 cần hai tầng có Q = 0.541 và Q = 1.307.
- Tầng 1 (60 Hz): C1 = 10 nF, C2 = 8.2 nF → Q = 0.552, R = 8.66 kΩ (`10.5 kΩ` cho bản 50 Hz `R×1.2`).
- Tầng 2 (60 Hz): C1 = 47 nF, C2 = 6.8 nF → Q = 1.314, R = 4.42 kΩ (`5.36 kΩ` cho bản 50 Hz `R×1.2`).
- Mẹo: chọn tụ theo giá trị bán sẵn (E12) trước, rồi mới tính R (E96 có nhiều giá trị hơn).

**Kết quả LTspice** ([`circuit/ltspice_results.json`](circuit/ltspice_results.json), hình [`results/figures/front_end_bode.png`](results/figures/front_end_bode.png)):
- Tần số cắt −3 dB: **2,045.1 Hz** (mục tiêu 2,000 Hz; mô hình IIR Python là **2,047.93 Hz**).
- Ở chế độ 60 Hz: tại Nyquist 7.68 kHz giảm **46.4 dB** (Python **46.34 dB**), tại 15.36 kHz giảm **70.6 dB**.
- Ở 60 Hz: 16.5 mV/A, trễ pha **4.38°**. Từ 60 Hz tới 1 kHz phẳng trong ~0.12–0.13 dB.
- Với 30 A rms + 15% sóng hài bậc 3 + nhiễu 9 kHz: chân ADC dao động **1.043–2.257 V** (trung bình 1.650 V), không bị cắt đỉnh.

## 3. Mô phỏng sự cố ([`hif/waveforms.py`](hif/waveforms.py))
- **Mô hình hồ quang Emanuel**: hai diode với hai nguồn áp Vp, Vn và hai điện trở Rp, Rn. Hồ quang chỉ dẫn khi điện áp vượt Vp (bán kỳ dương) hoặc vượt −Vn (bán kỳ âm). Vp ≠ Vn nên dạng sóng không đối xứng.
- Mỗi bán kỳ các thông số bị xáo ngẫu nhiên 3–12%; có chu kỳ hồ quang tắt hẳn; dòng tăng dần lúc mới chạm đất.
- 5 loại bề mặt: cỏ ướt, cát ướt, bê tông, cỏ khô, nhựa đường khô. Nhựa đường khô kéo dòng nhỏ nhất nên khó nhất.
- 7 loại tình huống **bình thường** dễ gây báo nhầm: tải bước, đóng tụ bù, dòng xung kích máy biến áp (inrush), khởi động động cơ, máy hàn hồ quang, tải điện tử dao động, và không có gì.
- Lưu ý trung thực: các khoảng thông số Phase 0 là **giả định**, không phải số đo ngoài hiện trường.

## 4. Phần Embedded + AI ([`hif/features.py`](hif/features.py), [`train_kaggle.py`](train_kaggle.py), [`firmware/hif_infer.c`](firmware/hif_infer.c))
- Mỗi chu kỳ (256 mẫu) chạy FFT, sau đó gom 8 chu kỳ gần nhất thành **16 đặc trưng**: tỉ lệ sóng hài bậc 2, 3, 5, sóng hài chẵn, thành phần DC, độ lệch đỉnh dương/âm, độ biến thiên `I3_cv` / `I1_cv`, độ "rung" pha `ph3_jitter`, độ khác nhau giữa các chu kỳ `cycle_diff`, xu hướng và liên hài.
- Mô hình là MLP rất nhỏ `16 → 16 → 8 → 1` (**417 tham số** chính xác, **504 byte** với trọng số lượng tử **int8** và bias/scale `float32`).
- Chống báo nhầm: chỉ báo động khi `PERSIST = 3` cửa sổ liên tiếp vượt ngưỡng (cùng ý tưởng bộ định thời rơ-le).
- So sánh với 2 cách truyền thống (cùng ngân sách báo nhầm ~1% khi hiệu chỉnh): rơ-le quá dòng chạm đất (`51N`, ngưỡng `48.33 A` đỉnh) và ngưỡng sóng hài bậc 3 (`13.81 A` đỉnh).
- **Kiểm chứng firmware C bằng GCC `13.3.0`** (`-O2 -Wall -Wextra -Werror`, [`results/c_firmware_verify.json`](results/c_firmware_verify.json)): đã biên dịch và chạy thật [`firmware/hif_infer.c`](firmware/hif_infer.c) + [`firmware/test_infer.c`](firmware/test_infer.c) (file nhị phân **17,032 byte**):
  - Header Phase 0 ([`firmware/hif_model.h`](firmware/hif_model.h), ngưỡng `0.982635`): trên 6 vector chuẩn `max |p_c - p_py| = 4.77e-7` (`0.54 µs/lần`); trên 100 vector mở rộng `max = 8.34e-7` (`0.61 µs/lần`).
  - Header Phase 1.5 ([`firmware/hif_model_phase15.h`](firmware/hif_model_phase15.h), ngưỡng `0.924894`): trên 100 vector `max = 1.04e-6` (`0.57 µs/lần`).
  - Cả 3 bộ kiểm tra đều đạt **100%** trùng khớp quyết định với Python và vượt qua bài kiểm tra máy trạng thái `PERSIST = 3` (`P1.5-D: PASS`).

## 5. Kết quả Phase 0 đã chạy trên Kaggle & cách kiểm tra tại máy ([`results/metrics.json`](results/metrics.json))
- **Kết quả Phase 0 hoàn tất (4,000 sự cố mô phỏng, `212,000` cửa sổ, `seed = 42`):**
  - Mô hình `int8`: phát hiện **94.70%** (`396` ca HIF), báo nhầm lúc bình thường **1.49%** (`404` ca), trễ trung vị **5.0 chu kỳ** (`p90 = 9.6`), `AUC = 0.9888` (`0.9939` ở `float32`), trùng quyết định `int8/float` **98.37%**.
  - Theo bề mặt: cát ướt **98.5%**, bê tông **97.7%**, cỏ ướt **95.5%**, cỏ khô **92.3%**, nhựa đường khô **90.7%**.
  - Đối chứng truyền thống: `51N` chỉ bắt được **0.51%** (báo nhầm **1.73%**); sóng hài bậc 3 bắt được **0.00%** (báo nhầm **0.74%**).
  - Kiểm tra độ tổng quát: bỏ từng bề mặt (LOSO) đạt **93.0%–98.5%**; nhưng **khi giấu máy hàn (`arc_welder`) khỏi tập train thì báo nhầm 17.5%** (so với **0.0%** khi đã học) — hạn chế cần nói thẳng.
- **Tái lập & kiểm tra nội bộ trên máy:**
  - Nếu sửa mã nguồn trước khi chạy lại trên Kaggle: `python scripts/build_notebook.py` rồi chạy [`kaggle/hif_phase0.ipynb`](kaggle/hif_phase0.ipynb).
  - Kiểm tra toàn vẹn **23** file kết quả/hình ảnh bằng SHA-256 và chạy **10** bài test tự động:
    ```bash
    python -m hif.provenance --verify      # Verified 23 files: 0 changed, 0 missing
    python -m pytest -v tests/test_hif.py   # 10 passed
    ```
    *(Nếu chạy từ trong `self-healing-feeder/hif_sensor/`, dùng `..\.venv\Scripts\python` để không bị `pytest.ini` ở thư mục gốc chặn `testpaths`.)*

## 6. Giai đoạn phần cứng tiếp theo (chưa thực hiện — cần linh kiện, ~50–80 USD)
- Linh kiện dự kiến: ESP32-S3 DevKit, kẹp CT SCT-013-000, MCP6004, điện trở/tụ theo bảng ở mục 2, breadboard.
- Việc cần làm khi có mạch thật: lắp mạch và đo đáp ứng tần số bằng oscilloscope tại lab so với LTspice; phát lại dạng sóng mô phỏng/VeHIF qua card âm thanh vào mạch (HIL); ghi tải sinh hoạt thật trong nhà; viết firmware ESP-IDF (`ADC DMA → FFT → 16 đặc trưng → hif_update()`).

## 7. Phase 1: kiểm tra zero-shot trên dữ liệu thật VeHIF 22 kV ([`results/real_vehif.json`](results/real_vehif.json))
- Bộ dữ liệu: **983** lần thử sự cố cây chạm dây (**900** bản ghi hợp lệ) + **53** bản ghi nền thật trên lưới **22 kV, 50 Hz** tại Úc (Gomes & Ozansoy, *IEEE TPWRD* 2022, CC0).
- Ranh giới thật vs mô phỏng: dòng sự cố và dòng nền là **đo thật**, sau đó cho đi qua **cảm biến CT/LPF/ADC mô phỏng** cộng với **dòng tải nền mô phỏng**; mô hình là trọng số Phase 0 đóng băng hoàn toàn (`thr = 0.982635`).
- **Kết quả Phase 1 (`250` bản ghi sự cố cắt tối đa `120 s` + `53` bản ghi nền):**
  - Phát hiện **56.0%** trên 250 sự cố thật (`0–1 A`: **36.2%**, `1–2 A`: **70.0%**, `2–5 A`: **94.7%**, `5–10 A`: **85.7%**, `>10 A`: **100.0%**), tỉ lệ báo động ở lần đối chứng không sự cố **1.2%**.
  - Trên **53 bản ghi nền thật**: báo nhầm **0.0%**.
  - Đối chứng truyền thống trên cùng 250 bản ghi: `51N` **0.0%**, sóng hài bậc 3 **0.4%**.
  - **Chẩn đoán độ lệch đặc trưng (`feature_shift_real_vs_sim`):** hồ quang cây chạm dây 22 kV đối xứng hơn và ít nhảy ngẫu nhiên giữa các chu kỳ hơn nhiều so với mô phỏng Emanuel (`dc_ratio −0.49 IQR`, `h2_ratio −0.47 IQR`, `even_ratio −0.46 IQR`, `I3_cv −0.38 IQR`, `ph3_jitter −0.38 IQR`).

## 8. Phase 1.5: 50 Hz Việt Nam, Ablation, Few-shot VeHIF & Kiểm chứng C ([`results/phase15_vehif.json`](results/phase15_vehif.json))

Thực hiện theo kế hoạch tiền đăng ký [`PLAN_PHASE15.md`](PLAN_PHASE15.md) bằng [`phase15_vehif_adaptation.py`](phase15_vehif_adaptation.py) trên Kaggle:

1. **So sánh cặp 50 Hz (VN/Úc) vs 60 Hz (US) trên `250` bản ghi VeHIF (cắt tối đa `90 s`):**
   - Dữ liệu mô phỏng: **94.33%** (`1.67%` FA trên `600` ca 50 Hz) so với **94.70%** (`1.49%` FA trên `800` ca 60 Hz).
   - Trên `250` bản ghi VeHIF thật (`90 s`): cả **50 Hz tự nhiên** và **60 Hz resample** đều đạt **54.4%** tổng thể (`0–2 A`: **43.09%** ở 50 Hz vs **43.62%** ở 60 Hz; đối chứng FA **1.2%**; `53` bản ghi nền FA **0.0%**).
2. **Loại bỏ từng nhóm đặc trưng (Ablation zero-shot 50 Hz tự nhiên):**
   - `all_16`: mô phỏng **94.70%** / VeHIF **54.4%** (`0–2 A`: **43.09%**).
   - `no_asymmetry_12` (bỏ nhóm bất đối xứng): sụp xuống **40.15%** / **22.4%** (`0–2 A`: **22.34%**).
   - `no_top_shift_9` (bỏ 7 đặc trưng lệch mạnh nhất): sụp xuống **40.66%** / **13.2%** (`0–2 A`: **12.23%**).
   - `harmonics_only_7`: **86.62%** / **46.4%** (`0–2 A`: **31.38%**).
   - `temporal_only_8`: **86.11%** (FA **2.48%**) / **55.6%** (`0–2 A`: **51.06%**, đối chứng FA **0.4%**, nền FA **0.0%**).
3. **Thích nghi Few-shot VeHIF không rò rỉ dữ liệu (5 seed, `60%` test độc lập theo ID bản ghi = `179` sự cố / `33` nền):**
   - `zero_shot_phase0`: **53.30% ± 1.68%** tổng thể (`0–2 A`: **42.52% ± 1.97%**, đối chứng FA **1.12%**, nền FA **0.00%**, mô phỏng **94.70%**).
   - `head_recal_int8` (chỉ hiệu chỉnh lớp đầu ra): tụt còn **46.59%** (`5%` / `15` bản ghi), **46.03%** (`10%` / `30` bản ghi), **44.80%** (`20%` / `60` bản ghi; `0–2 A`: **37.19%**).
   - `joint_mlp_int8` (fine-tune toàn mạng giữ nguyên kích thước `504 B` `int8`): tăng dần lên **49.50%** (`5%`), **56.42%** (`10%`), và **60.22% ± 10.47%** (`20%` / `60` bản ghi; dải `0–2 A` tăng **42.52% → 49.93% ± 11.87%**, tức **+7.41 điểm %**; dải `0–1 A` tăng **31.02% → 41.63%**; nền FA **1.82%**, đối chứng FA **0.67%**, giữ được **93.84%** mô phỏng với FA **1.53%**).
4. **Đánh giá trung thực 4 tiêu chí tiền đăng ký (`PLAN_PHASE15.md`):**
   - **`P1.5-A` (Tăng dải `0–2 A` thêm `≥ +15 điểm %`):** **KHÔNG ĐẠT (`FAIL`, `pass: false`)** — chỉ đạt **`+7.41 điểm %`** (`42.52% → 49.93%`).
   - **`P1.5-B` (Báo nhầm nền thật & đối chứng `≤ 3.0%`):** **ĐẠT (`PASS`, `pass: true`)** — nền thật **1.82%**, đối chứng **0.67%**.
   - **`P1.5-C` (Không quên kiến thức mô phỏng: `≥ 88%` phát hiện, `≤ 3%` FA):** **ĐẠT (`PASS`, `pass: true`)** — **93.84%** phát hiện, **1.53%** FA.
   - **`P1.5-D` (C khớp Python `< 1e-5` & `100%` quyết định):** **ĐẠT (`PASS`, `pass: true`)** — tối đa **`1.04e-6`**.
