# Tài liệu ôn tập: hiểu và bảo vệ dự án Self-Healing Feeder

Tài liệu này đi theo **lập luận khoa học** của dự án: vấn đề → câu hỏi → hệ thống thử nghiệm → phương pháp →
kết quả → giới hạn. Mỗi mục có: làm gì và vì sao, code ở đâu, ví dụ tính tay bằng số thật, và **câu thầy có
thể hỏi** kèm câu trả lời trung thực.

Muốn xem code từng file, từng hàm: đọc [module-guide.md](module-guide.md). Tài liệu này không lặp lại phần đó.

**Quy ước số.** Mọi con số lấy từ `results/` hoặc [`shf/config.py`](../../shf/config.py), hoặc tính ra từ
chúng. Số viết theo kiểu Anh (dấu chấm thập phân, dấu phẩy hàng nghìn) để khớp với file kết quả và với
`harness/facts.toml`. Câu nào trích nguyên văn README thì để trong ngoặc kép tiếng Anh.

**Nguồn chính:**

| File | Chứa gì |
|---|---|
| [`results/metrics.json`](../../results/metrics.json) | Độ chính xác, ngưỡng FPI, quãng tuần tra, tổng kết khôi phục |
| [`results/zones.csv`](../../results/zones.csv) | 10 vùng: vùng cha, kW, chiều dài dây (kft), danh sách nút |
| [`results/restoration.csv`](../../results/restoration.csv) | Kết quả khôi phục cho từng vùng sự cố |
| [`results/switching_orders.md`](../../results/switching_orders.md) | Lệnh thao tác từng bước |
| [`results/error_analysis/`](../../results/error_analysis/error_analysis.json) | Phân tích lỗi, ma trận nhầm lẫn, FNR/FPR theo vùng |

---

## 0. Chứng thực mật mã (SHA-256), Bảo mật & Tự kiểm chứng 2 lệnh (Dành cho giảng viên / hội đồng)

> **Toàn bộ là mô phỏng:** mọi thí nghiệm trong kho này chạy bằng OpenDSS, LTspice và Python (không có dữ liệu đo thực địa từ lưới điện lực, không triển khai ngoài thực tế, không có kết nối SCADA trực tiếp). Toàn bộ 52 file JSON/CSV kết quả có thể tải trực tiếp trong [`docs/data/`](../../docs/data/) và đối chiếu trên [khối Chứng thực của trang báo cáo](https://chau1912550.github.io/self-healing-feeder/#evidence).

### Tự kiểm chứng độc lập chỉ với 2 lệnh

Bất kỳ giảng viên hay người phản biện nào sau khi `git clone` đều có thể tự kiểm tra toàn bộ mã băm kết quả, mọi con số trong văn bản, liên kết, quy tắc bảo mật và bộ test tự động bằng 2 lệnh:

```bash
python -m shf.provenance          # kiểm tra toàn bộ 23 manifest SHA-256 / 51 file kết quả (0 changed, 0 missing, 0 unrecorded)
python harness/check.py --tests   # tính lại mọi con số từ results/, kiểm tra liên kết, bảo mật khóa bí mật, provenance & pytest
```

*(Trên Windows dùng `.venv\Scripts\python`, trên Linux/macOS dùng `.venv/bin/python`.)*

### Sổ cái SHA-256 & 5 kế hoạch tiền đăng ký (`research/*/PLAN.md`)

- **Chứng thực SHA-256 ([`results/provenance/`](../../results/provenance/)):** **23** file manifest bao phủ trọn vẹn **51** file kết quả (**0 changed / 0 missing / 0 unrecorded** qua [`shf/provenance.py`](../../shf/provenance.py)), lưu lệnh chạy, thời gian UTC, commit git (với bản chạy máy) và mã băm SHA-256 64 ký tự cho từng file.
- **Mô hình Tầng 1 Edge HIF-Sensor đóng băng:** `model_int8.npz` (`417` tham số, `504` byte, ngưỡng `0.982635`, kernel Kaggle `christoopherchau/ch-y-n`), SHA-256 `3ba5bd23685d7964a6cea0c94064c1e65a8bf3129d83ac129215d110218397c1` (ghi trong [`results/hif_fusion/dataset_summary.json`](../../results/hif_fusion/dataset_summary.json)).
- **Đủ 5 kế hoạch nghiên cứu tiền đăng ký (khóa giả thuyết, giả định và tiêu chí PASS/FAIL trước khi chạy):**
  1. [`research/gnn-transfer/PLAN.md`](../../research/gnn-transfer/PLAN.md) — Chuyển giao zero-shot lưới hình tia thụ động (IEEE 123-bus → 34-bus) & Stage 2 tìm từng bus.
  2. [`research/active-grid-gnn/PLAN.md`](../../research/active-grid-gnn/PLAN.md) — Lưới chủ động có DER 0–50%, đổi cấu trúc/vòng kín, HIF tới 10 kΩ, quá độ `NO_FAULT` & Split Conformal Prediction (kèm Addendum A/B1 hậu kiểm).
  3. [`research/ieee37-underground/PLAN.md`](../../research/ieee37-underground/PLAN.md) — Lưới thứ 3 chưa từng thấy: cáp ngầm đô thị IEEE 37-bus (4.8 kV, 3 dây delta không nối đất, thụ động & chủ động).
  4. [`research/multi-feeder-benchmark/PLAN.md`](../../research/multi-feeder-benchmark/PLAN.md) — Kiểm chứng đa lưới 15 xuất tuyến OpenDSS chuẩn IEEE/EPRI (3 máy ảo Kaggle song song).
  5. [`research/hif-fusion/PLAN.md`](../../research/hif-fusion/PLAN.md) — Kiến trúc 2 tầng Edge HIF-Sensor (`504 B` int8) → Graph FLISR đối chứng cặp trên 5 bề mặt hồ quang Emanuel và 7 nhiễu nền.

### Bảng tóm tắt trung thực: Ca ĐẠT (PASS) vs. Ca THẤT BẠI (FAIL) & Giới hạn

| Thí nghiệm | Môi trường chạy | Kết quả đã kiểm chứng (`results/`) | Kết luận tiền đăng ký |
|---|---|---|---|
| **FLISR chính (IEEE 123-bus, 4.16 kV)** | Local CPU | `11,448` sự cố: ML **97.7%** vs FPI **56.1%** (`100 Ω`: **98.4%** vs 8.4%; `400 Ω`: **76.5%** vs 1.0%); `259` lỗi (`237` ở ≥ 200 Ω); tuần tra **39.0 → 5.1 kft** (−87%); tie cấp lại **2,670 / 7,175 kW**; giảm kW·phút **51%** | **PASS** (mô phỏng; R tuyến tính, nguồn cứng) |
| **Khôi phục theo giờ (PJM AEP 2017)** | Kaggle / Local | `8,760` giờ: trung bình năm **44.0%** (giữ 6 giờ: **42.1%**) so với **37.2%** tải đỉnh; lưu ý: `74` trên `8,760` giờ đạt `1.0508 pu` | **PASS** (mô phỏng; dáng tải cấp vùng) |
| **Quá độ & Hồ quang LTspice** | Local LTspice | Nút 60 chạm cứng `6,119 A` RMS, đỉnh `10,067 A` (`4.9 ms`); hồ quang `400 Ω` `6.00 A` (`97.8%` thành phần 60 Hz, `18.8%` hài bậc 3, `3` mức ADC 12-bit) | **PASS** (mô phỏng mạch 1 pha Thevenin) |
| **Chuyển giao thụ động (123 → 34) + Stage 2** | Local CPU | Stage 1 zero-shot (`4,104` sự cố): GBDT **99.8%**, GNN **99.3%** vs FPI **55.5%**. Stage 2 (`top-1 / top-3`): Takagi không học (**46.9% / 69.0%** trên 123; **57.5% / 87.4%** trên 34) vượt `BusGraphGNN` (**17.8% / 38.5%** CV trên 123; **50.8% / 85.8%** zero-shot trên 34) | **PASS** (Stage 1) · **FAIL** (`BusGraphGNN` thua công thức vật lý Takagi) |
| **Đa lưới 15 xuất tuyến OpenDSS** | Kaggle 3-VM | **10/11** lưới chưa từng thấy đạt (9/9 lưới mới gồm EU-LV 50 Hz **93.3%**, IEEE 8500 **99.8%**, EPRI Ckt24 34.5 kV **99.7%**; mất 1 cảm biến EPRI Ckt7 18 zone: GNN **94.3%** > GBDT **90.5%**). **3 giới hạn ngoài phạm vi:** IEEE 342-Node (71 vòng kín), IEEE 9500-Node (không hội tụ cơ sở), CIGRE MV (không có file gốc) | **PASS** (10/11 lưới) · **3 lưới ngoài phạm vi ghi rõ** |
| **Cáp ngầm delta IEEE 37-bus (4.8 kV)** | Local CPU + Kaggle GPU | Thụ động (`5,184` sự cố): zero-shot GBDT **56.4%**, GNN **46.7%** vs FPI **43.0%** — SLG sụp xuống **22.4% / 5.6%** (FPI **0.0%**) vì dòng SLG điện dung chỉ `2.36 A` (`0.64%`) và dịch điện áp pha lành về `√3` pu (sự cố pha vẫn **100.0% / 99.7%**; CV tại chỗ **91.4% / 88.0%**). Chủ động (`6,097` sự kiện): zero-shot GBDT **55.4%**, GATv2 **46.2%** → **76.2%** ở few-shot 20% | **FAIL (`P1-Fail` SLG)** · **PARTIAL (`P2-Partial`, `A2-Partial`, GBDT `A2-Fail`)** |
| **Lưới chủ động DER + Vòng kín + Conformal (123 → 34)** | Kaggle GPU + Local | 123-bus CV (`17,847`): GATv2 **95.8%** (FPR **6.5%**) vs GBDT **93.9%** (13.9%) & FPI **40.7%**. 34-bus zero-shot (`9,491`): GBDT **83.8%** > GATv2 **77.6%** (few-shot 20% GATv2 **89.1%** > GBDT **83.1%**), cả hai chưa đạt FPR ≤ 5% (`22.1% / 25.3%`). `aps_det` bão hòa (`6.37` nhãn); `aps_rand` 95% hậu kiểm đạt **95.0%** tại chỗ nhưng **thất bại** khi giữ nguyên ngưỡng sang 34-bus (**81.4% / 91.1%**) | **PASS (`C1`)** · **PARTIAL (`C2`, `C3` hậu kiểm)** · **FAIL (conformal liên lưới)** |
| **2 tầng Edge HIF-Sensor → Graph FLISR** | Kaggle GPU | Đối chứng cặp (`60Hz_only → +Edge`, 5 bề mặt hồ quang, 7 nhiễu nền): thụ động 123 SLG `400 Ω` **78.1% → 97.7%** (GBDT) / **79.6% → 96.0%** (GNN); chủ động 123 FPR **6.5% → 1.2%** (GATv2); chủ động 34 zero-shot FPR **22.1% → 5.8%** (GBDT) / **25.3% → 9.7%** (GATv2); `aps_rand` 95% tập 1 nhãn **89.2% → 93.0%**. **Khoảng cách miền thực tế:** Tầng 1 độc lập giảm **94.7% → 56.0%** trên bản ghi hồ quang thực vật 22 kV VeHIF thật khi chưa huấn luyện lại (trích từ [`research/hif-fusion/PLAN.md`](../../research/hif-fusion/PLAN.md)) | **PASS (`H1–H4` 4/4, mô phỏng)** · **Công khai khoảng cách VeHIF & yêu cầu phần cứng ≥ 15.36 kHz** |

### Chính sách bảo mật & vệ sinh kho Git

- **Chỉ công khai trên Git:** mã nguồn mở, kế hoạch tiền đăng ký (`research/*/PLAN.md`), kết quả mô phỏng đã băm SHA-256 (`results/`, `docs/data/`), bản vẽ CAD/3D/LTspice và trang web tĩnh `docs/`.
- **Giữ tuyệt đối ngoài Git** (bảo vệ bởi [`.gitignore`](../../.gitignore), `.git/info/exclude` cục bộ và bộ quét bí mật trong [`harness/check.py`](../../harness/check.py)): mọi khóa API / token / tệp đăng nhập (`.env`, `.env.*`, `.kaggle/`, `kaggle.json`; dự án hiện dùng **0** API bên ngoài — xem [`config/apis.md`](../../config/apis.md)), tệp vận hành nội bộ (`ops/`, `CLAUDE.local.md`, `HANDOFF.md`, `inputs/private/`), tập dữ liệu tái tạo được (`data/generated/`), trọng số mô hình pickle/checkpoint (`models/`) và dữ liệu thô bên thứ ba (`data/external/`).
- **Trang GitHub Pages thuần tĩnh:** `docs/index.html` và `docs/monitor/` chạy hoàn toàn trên trình duyệt — **không có backend, không thu thập dữ liệu/tracking, không nhúng API key**.

---

## 1. Vấn đề: sự cố làm cả xuất tuyến mất điện, và chỉ báo thông thường bỏ sót sự cố trở kháng cao

### Làm gì, vì sao

Một **xuất tuyến (feeder)** là một đường dây trung áp đi ra từ trạm biến áp, cấp điện cho cả một khu vực.
Ở đầu xuất tuyến có **recloser (máy cắt tự đóng lại)**: khi có sự cố, nó cắt, thử đóng lại vài lần, và nếu sự
cố vẫn còn thì **khóa (lockout)**. Lúc đó cả xuất tuyến mất điện. Nếu không biết sự cố ở đâu, đội sửa chữa
phải **tuần tra (patrol)** toàn bộ đường dây.

Cách thông thường để thu hẹp vùng tìm là **FPI, fault passage indicator (chỉ báo dòng sự cố đi qua)**: mỗi
thiết bị trên đường dây "bật cờ" khi dòng vượt một ngưỡng cố định. Vấn đề: sự cố **chạm đất trở kháng cao**
(ví dụ dây rơi xuống đất khô, cành cây) tạo ra dòng rất nhỏ, nhỏ hơn ngưỡng.

### Ví dụ tính tay: dòng sự cố 400 Ω so với ngưỡng chạm đất

Lưới 4.16 kV là điện áp dây. Điện áp pha (pha–đất):

```
V_pha = 4160 / √3 = 2,402 V
```

Bỏ qua trở kháng đường dây và nguồn (nên đây là **giới hạn trên** của dòng), dòng sự cố 1 pha chạm đất qua
điện trở R_f:

```
I_f ≈ V_pha / R_f
R_f = 100 Ω  →  I_f ≈ 2402 / 100 = 24 A
R_f = 400 Ω  →  I_f ≈ 2402 / 400 = 6.0 A
```

Ngưỡng chạm đất của từng thiết bị (`metrics.json → fault_location.fpi_baseline.pickups_A`, số thứ hai):

| Thiết bị | Ngưỡng pha (A) | Ngưỡng chạm đất (A) | R_f lớn nhất mà 2402/R_f còn vượt ngưỡng đất |
|---|---|---|---|
| Sw1 (đầu xuất tuyến) | 1261 | 315 | 7.6 Ω |
| Sw2 | 668 | 167 | 14.4 Ω |
| L13 | 458 | 115 | 20.9 Ω |
| Sw4 | 483 | 121 | 19.8 Ω |
| Sw3 | 273 | 68 | 35.3 Ω |
| L45 | 179 | 45 | 53.4 Ω |
| L77 | 114 | 48 | 50.0 Ω |
| L68 | 165 | 41 | 58.6 Ω |
| L61 | 161 | 40 | 60.0 Ω |
| Sw5 | 129 | 32 | 75.1 Ω |

Cột cuối = 2402 / ngưỡng đất. Kết luận: **ngưỡng thấp nhất là 32 A (Sw5)**, nên sự cố 100 Ω (24 A) và
400 Ω (6 A) không làm bật cờ chạm đất ở bất kỳ thiết bị nào. Điều này khớp với kết quả FPI theo điện trở
(`fpi_baseline.slg_by_resistance`): 86.3% đúng ở 10 Ω, 53.7% ở 25 Ω, 28.4% ở 50 Ω, 8.4% ở 100 Ω, 1.0% ở 400 Ω.

So sánh thêm: ở thiết bị đầu nguồn Sw1, dòng tải đỉnh khoảng 1261 / 2 ≈ 630 A (ngưỡng pha = 2 × dòng tải
đỉnh). Sai số đo 1% của 630 A là khoảng 6.3 A, **xấp xỉ bằng cả dòng sự cố 400 Ω**. Đây là gốc rễ của bài
toán khó.

### Code và kết quả

- Ngưỡng: `shf/baseline.py → pickups()`, hệ số trong `config.py` (`FPI_PHASE_FACTOR = 2.0`,
  `FPI_GROUND_FACTOR = 0.5`, `FPI_GROUND_MARGIN = 1.2`).
- Kết quả: `metrics.json → fault_location.fpi_baseline`.

### Câu thầy có thể hỏi

- **"Sao em bỏ qua trở kháng đường dây khi tính 6 A?"** Để có giới hạn trên đơn giản. Trở kháng dây chỉ làm
  dòng nhỏ hơn, nên kết luận "không vượt ngưỡng" vẫn đúng. Trong dữ liệu mô phỏng, trung vị của 3·|ΔI0| tại
  thiết bị cấp vùng sự cố với sự cố 400 Ω là khoảng 6.7 A (tính từ `data/generated/dataset.csv.gz`), có lẫn
  nhiễu đo.
- **"Ngưỡng 2 lần tải đỉnh lấy ở đâu ra?"** Là quy tắc kinh nghiệm phổ biến, ghi là `ASSUMPTION` trong
  `config.py`. Điện lực thật chỉnh ngưỡng theo phối hợp bảo vệ, có thể thấp hơn. Ngưỡng thấp hơn sẽ bắt được
  nhiều sự cố hơn nhưng cũng báo nhầm nhiều hơn.

---

## 2. Hai câu hỏi nghiên cứu và giả thuyết

### Câu hỏi (README, đầu trang)

1. **Định vị:** chỉ dùng số đo mà recloser và dao tự động vốn đã ghi, mô hình có chỉ ra được sự cố nằm ở
   **vùng đóng cắt (switching zone)** nào không, kể cả sự cố trở kháng cao mà FPI bỏ sót?
2. **Khôi phục:** khi đã biết vùng, có thể **cô lập** vùng đó và **cấp điện lại** cho mọi vùng khác một cách
   tự động không, với điều kiện chỉ đóng dao liên lạc khi giải tích lưới cho thấy điện áp và dòng điện nằm
   trong giới hạn?

### Giả thuyết

- **H1 (định vị):** phần **thay đổi giữa trước và sau sự cố** (đại lượng gia số) mang thông tin mà độ lớn tức
  thời không có. Lý do vật lý: dòng tải bình thường lớn và thay đổi theo giờ, nên độ lớn tức thời bị dòng tải
  "che". Lấy hiệu số trước/sau thì dòng tải gần như triệt tiêu, chỉ còn phần do sự cố thêm vào.
- **H2 (khôi phục):** với lưới 4.16 kV này, giới hạn ràng buộc khi nhận tải qua dao liên lạc là **điện áp**,
  không phải dòng định mức dây. (Đây là điều được kiểm tra, không phải giả định trước: xem mục 9.)

### Cách kiểm tra H1

So sánh ba phương pháp trên **cùng một tập sự cố**: FPI thông thường, ML chỉ dùng độ lớn, ML dùng độ lớn +
đại lượng gia số. Nếu H1 đúng, khoảng cách giữa hai mô hình ML phải lớn nhất ở điện trở sự cố cao. Kết quả ở
mục 7 cho thấy đúng như vậy.

### Ví dụ: một sự cố thật trong dữ liệu

Sự cố 1 pha chạm đất 400 Ω tại nút 60 (vùng Sw2), kịch bản 0, hệ số tải 0.641 (đọc từ
`data/generated/dataset.csv.gz`; bản công bố là `docs/data/fault_dataset.csv.gz`):

| Thiết bị | Ia (A) | dIa (A) | I0 (A) | dI0 (A) |
|---|---|---|---|---|
| Sw1 | 387.96 | 7.32 | 44.29 | 3.51 |
| Sw2 | 212.78 | 4.46 | 21.98 | 3.05 |
| Sw4 (phía sau sự cố) | 164.67 | 2.65 | 18.11 | 0.52 |

Nhìn cột `Ia`: sự cố chỉ thêm vài ampe vào hàng trăm ampe, gần như không thấy. Nhìn cột `dI0`: Sw1 và Sw2
(phía trước sự cố) thấy khoảng 3 A, Sw4 (phía sau) chỉ 0.52 A. Ranh giới giữa "thấy" và "không thấy" nằm đúng
giữa Sw2 và Sw4, tức là vùng Sw2. Đó là thông tin mà giả thuyết H1 nói tới.

### Câu thầy có thể hỏi

- **"Thiết bị thật có đo được giá trị trước sự cố không?"** Recloser hiện đại lưu **bản ghi sự kiện (event
  record)** gồm vài chu kỳ trước và sau khi sự cố xảy ra, nên tự tính được hiệu số mà không cần đồng bộ thời
  gian giữa các thiết bị. Nhưng dự án **không dùng bản ghi thật**; đây là giả định về khả năng thiết bị.
- **"Câu hỏi 1 có phải chỉ là phân loại 10 lớp?"** Đúng. Mô hình không định vị đến từng mét, chỉ đến vùng.
  Đó là mức đủ để quyết định mở dao nào.

---

## 3. Hệ thống thử nghiệm: lưới IEEE 123 nút trong OpenDSS

### Làm gì, vì sao

- **IEEE 123-bus test feeder (lưới mẫu 123 nút của IEEE):** lưới phân phối mẫu công khai, 4.16 kV, có nhánh
  1 pha, 2 pha, 3 pha, bộ điều áp và tụ bù. Dùng lưới mẫu để người khác chạy lại được; lưới thật của điện lực
  là dữ liệu nhạy cảm.
- **OpenDSS:** phần mềm mô phỏng lưới phân phối của EPRI, điều khiển từ Python qua `OpenDSSDirect.py`. Nó
  giải **power flow (giải tích trào lưu công suất)** dạng phasor, ba pha không cân bằng.
- Kiểm tra mô hình chạy đúng (`metrics.json → base_case`): tải danh định 3,490 kW, công suất nguồn
  3,615.3 kW, điện áp từ 0.979 đến 1.04996 pu ở trạng thái bình thường.

### Cái gì của IEEE, cái gì là giả định

| Thành phần | Nguồn |
|---|---|
| Lưới, dây dẫn, tải, bộ điều áp, tụ bù | IEEE 123-bus (file `data/feeder/ieee123/`) |
| Dao Sw1–Sw5 (thường đóng), dao liên lạc Sw7 (151–300, thường mở) | IEEE |
| 5 dao tự động thêm vào ở đầu các đoạn L13, L45, L61, L68, L77 | **Giả định** (`config.SECTIONALIZERS`) |
| Dao liên lạc Sw9 (nút 450 → xuất tuyến bên cạnh, nguồn 4.16 kV đặt 1.03 pu sau 4,000 ft dây 336 ACSR, tải riêng không mô hình) | **Giả định** (`config.ADJACENT_FEEDER_DSS`) |
| Dòng định mức: 336,400 ACSR 530 A, 1/0 ACSR 230 A, cáp 1/0 AA 200 A, dao 600 A; khẩn cấp = 125% | **Giả định** (IEEE không cho) |
| Sw8 (54–94) | IEEE, nhưng 1 pha nên **không dùng** để khôi phục |

### Vùng và cây vùng

**Vùng (zone):** mở hết các dao, mỗi mảnh lưới còn liền nhau là một vùng, đặt tên theo dao cấp điện cho nó.
Lưới vận hành **hình tia (radial)**: điện đi một chiều từ trạm ra, nên mỗi vùng có đúng một **vùng cha**. Từ
`zones.csv` (kW danh định, chiều dài dây):

```
Sw1  (400 kW, 4.751 kft)  ← recloser đầu xuất tuyến
├── L13  (360 kW, 6.0 kft)
│   └── Sw3  (240 kW, 3.926 kft)
│       └── L45  (515 kW, 1.65 kft) ──[tie Sw7: nút 151 ↔ 300]──┐
└── Sw2  (180 kW, 3.427 kft)                                    │
    ├── L61  (370 kW, 1.525 kft)                                │
    └── Sw4  (725 kW, 6.651 kft)                                │
        ├── L68  (120 kW, 2.175 kft) ──[tie Sw9: nút 450 ↔ xuất tuyến bên cạnh]
        │   └── Sw5  (320 kW, 6.202 kft) ◄──────────────────────┘
        └── L77  (260 kW, 2.676 kft)
```

Tổng: 10 vùng, 3,490 kW, 38.983 kft dây. Có 127 nút được đặt sự cố (đếm từ cột `buses`).

### Code và kết quả

- `shf/feeder.py → load_feeder()` (nạp lưới, thêm Sw9, gán định mức), `shf/topology.py → find_zones()`
  (cắt đồ thị tại các dao, dựng cây vùng), `zone_line_length_kft()`.
- Kết quả: `results/zones.csv`, `results/figures/feeder_zones.png`.

### Câu thầy có thể hỏi

- **"Vì sao lại thêm 5 dao? Có phải để kết quả đẹp hơn không?"** Chỉ 5 dao IEEE thì vùng quá lớn, định vị
  theo vùng ít giá trị. 5 dao thêm vào là giả định, ghi rõ trong `config.py` và README. Chúng làm bài toán
  **khó hơn** cho ML (10 lớp thay vì 5) chứ không dễ hơn.
- **"Xuất tuyến bên cạnh không có tải riêng, có lạc quan không?"** Có. Giả định nó còn dư công suất, chỉ bị
  giới hạn bởi sụt áp và dòng định mức. Thực tế dao Sw9 sẽ nhận ít tải hơn.
- **"Nguồn trong mô hình thế nào?"** Rất "cứng" (trở kháng nguồn nhỏ, như trong case IEEE), nên dòng sự cố
  chạm trực tiếp lớn hơn thực tế. README ghi rõ điều này.

---

## 4. Phương pháp A: tạo tập dữ liệu sự cố

### Làm gì

Với mỗi nút, mỗi loại sự cố, mỗi điện trở và mỗi kịch bản tải (`shf/faults.py → generate()`):

1. Chọn tải ngẫu nhiên: hệ số toàn lưới đều trong `LOAD_MULT_RANGE = (0.3, 1.1)`; từng tải nhân thêm
   N(1, 0.20), cắt trong [0.3, 1.7].
2. Giải power flow **trước sự cố**, bộ điều áp được tự do chuyển nấc (`solve(controls=True)`).
3. Đọc số đo mọi thiết bị, cộng nhiễu.
4. Bật sự cố, giải lại với **nấc bộ điều áp bị khóa** (`solve(controls=False)`).
5. Đọc số đo lần nữa, cộng nhiễu, tính đặc trưng.

| Tham số | Giá trị (`config.py`) |
|---|---|
| Loại sự cố | SLG (1 pha chạm đất), LL (2 pha chạm nhau), LLG (2 pha chạm đất), 3PH (3 pha) |
| Điện trở SLG | 0.01, 1, 5, 10, 25, 50, 100, 200, 400 Ω |
| Điện trở LL/LLG/3PH | 0.01, 0.5, 2 Ω |
| Kịch bản tải mỗi trường hợp | 3 (`SCENARIOS_PER_CASE`) |
| Nhiễu đo (1 sigma) | 1% độ lớn (`NOISE_MAG`), 0.5° góc (`NOISE_ANG_DEG`) |

Kết quả (`metrics.json → dataset`): 11,448 sự cố, hội tụ 100% (`converged_share = 1.0`). Theo loại: SLG 7155,
LL 1845, LLG 1845, 3PH 603. Kiểm tra: 3PH chỉ đặt ở nút 3 pha, có 67 nút như vậy; 67 × 3 điện trở × 3 kịch bản
= 603. Đúng.

### Vì sao khóa nấc bộ điều áp

**Bộ điều áp (voltage regulator)** là máy biến áp tự ngẫu có nhiều nấc, tự chuyển nấc để giữ điện áp. Nó phản
ứng chậm: có thời gian trễ hàng chục giây, mỗi nấc mất vài giây. Bảo vệ thì tác động trong vài chu kỳ (1 chu kỳ
= 1/60 s). Vậy **trong khoảnh khắc thiết bị ghi sự cố, nấc chưa kịp đổi**. Nếu để OpenDSS tự chỉnh nấc sau
sự cố, nó sẽ "sửa" điện áp về gần bình thường, xóa mất một phần dấu hiệu sự cố mà thiết bị thật nhìn thấy.

Phương án không chọn: để nấc tự do cả hai lần. Như vậy đơn giản hơn nhưng sai vật lý về thang thời gian.

### Vì sao tải ngẫu nhiên cho mỗi sự cố

Xem mục 6 (bài học từ phiên bản đầu). Tóm tắt: nếu tải chỉ có vài mức cố định, mô hình học thuộc "dòng bình
thường" và gian lận được.

### Một dòng dữ liệu chứa gì

Mỗi dòng = một sự cố. Với **mỗi thiết bị** trong 10 thiết bị (`faults.py → features()`):

| Đặc trưng | Ý nghĩa | Bộ "full" | Bộ "magnitude" |
|---|---|---|---|
| `Ia, Ib, Ic` | độ lớn dòng 3 pha sau sự cố | có | có |
| `dIa, dIb, dIc` | \|I_sau − I_trước\| (hiệu phức, rồi lấy độ lớn) | có | |
| `I0` | độ lớn dòng thứ tự không sau sự cố | có | có |
| `dI0` | \|I0_sau − I0_trước\| | có | |
| `dI2` | \|I2_sau − I2_trước\| | có | |
| `Va, Vb, Vc` | điện áp pha (pu) | có | có |
| `dVa, dVb, dVc` | \|V\|_sau − \|V\|_trước (có dấu) | có | |

Bộ "full" có 15 × 10 = 150 cột; bộ "magnitude" có 7 × 10 = 70 cột (`model.py → feature_columns`). Cộng thêm 8
cột nhãn và thông tin (`bus, zone, ftype, phases, r, scenario, load_mult, converged`) là 158 cột, đúng với
README.

### Thành phần đối xứng (I0, I2) từ đầu

Ba dòng pha bất kỳ (không cân bằng) luôn tách được thành ba bộ cân bằng: **thứ tự thuận** (quay a-b-c),
**thứ tự nghịch** (quay a-c-b) và **thứ tự không** (ba pha cùng pha nhau). Với toán tử a = 1∠120°:

```
I0 = (Ia + Ib + Ic) / 3
I2 = (Ia + a²·Ib + a·Ic) / 3
```

(đúng như `feeder.py → device_measurement()`).

- **I0** khác 0 chỉ khi có dòng chảy về đất hoặc dây trung tính. Tổng `3·I0` gọi là **dòng dư (residual
  current)**: chính là thứ mà rơ-le chạm đất đo.
- **I2** đo độ mất cân bằng giữa các pha (sự cố LL làm I2 lớn mà I0 gần 0).

Ví dụ minh họa (số tròn, không phải từ file): ba pha cân bằng 100∠0°, 100∠−120°, 100∠120° cộng lại bằng 0, nên
I0 = 0. Thêm sự cố 400 Ω trên pha a, dòng pha a tăng thêm khoảng 6 A cùng pha: tổng = 6 A, I0 = 2 A,
3·I0 = 6 A. Chính là dòng sự cố.

Nhưng lưới IEEE 123 **không cân bằng sẵn**: tải 1 pha làm có dòng dư ngay cả khi không sự cố. Ví dụ L77: ngưỡng
chạm đất 48 A = 1.2 × dòng dư tự nhiên, suy ra dòng dư tự nhiên khoảng 40 A ở tải đỉnh. Một sự cố 6 A cộng vào
40 A dòng dư sẵn có (lại thay đổi theo tải) thì độ lớn I0 gần như không đổi. Còn **dI0** lấy hiệu trước/sau
nên khử được 40 A đó. Đây là lý do toán học của giả thuyết H1.

### Câu thầy có thể hỏi

- **"Nhiễu 1% có thực tế không?"** Là giả định về sai số biến dòng, biến áp đo lường và mạch điện tử
  (`ASSUMPTION` trong `config.py`). Nhiễu được cộng **độc lập** vào số đo trước và sau sự cố, nên hiệu số cũng
  chịu nhiễu. Điều này làm bài toán khó hơn, không dễ hơn.
- **"Điện trở sự cố tuyến tính có giống sự cố trở kháng cao thật không?"** Không. Sự cố trở kháng cao thật có
  hồ quang, phi tuyến, chập chờn theo thời gian, tạo sóng hài. Mô phỏng phasor ổn định với điện trở hằng số
  không có những thứ đó. Vì vậy độ chính xác ở 200–400 Ω là **giới hạn trên**.
- **"Sao không mô phỏng quá độ (transient)?"** Bài toán định vị theo vùng dùng giá trị phasor mà recloser
  báo về. Mô phỏng quá độ cho mười nghìn sự cố tốn hơn nhiều và cần mô hình thiết bị chi tiết. Đây là hướng mở
  rộng, không phải điều dự án đã làm.

---

## 5. Phương pháp B: hai cách định vị được so sánh

### 5a. Phương pháp cơ sở: FPI "thiết bị bật cờ sâu nhất"

`shf/baseline.py`:

1. Mỗi thiết bị bật cờ nếu `max(Ia, Ib, Ic) > ngưỡng pha` **hoặc** `3·I0 > ngưỡng đất`.
2. Ngưỡng pha = 2 × dòng pha lớn nhất lúc tải đỉnh. Ngưỡng đất = max(0.5 × dòng pha đỉnh, 1.2 × dòng dư tự nhiên).
3. Lưới hình tia: sự cố nằm sau mọi thiết bị thấy nó. Nên vùng sự cố = vùng của **thiết bị bật cờ sâu nhất**
   trong cây. Không thiết bị nào bật cờ → dự đoán `none` (tính là sai).

Ví dụ đọc ngưỡng: Sw5 có ngưỡng pha 129 A, suy ra dòng đỉnh khoảng 64.5 A; 0.5 × 64.5 ≈ 32 A, đúng bằng ngưỡng
đất 32 A. Riêng L77: ngưỡng pha 114 A → 0.5 × 57 = 28.5 A, nhưng ngưỡng đất là 48 A. Vậy ở L77 quy tắc "1.2 ×
dòng dư tự nhiên" quyết định: nhánh này tải lệch pha nhiều.

**Vì sao FPI sai với sự cố chạm đất trực tiếp (0.01 Ω chỉ đúng 29.7%, kém hơn 5 Ω là 90.3%).** Ví dụ thật:
sự cố 0.01 Ω pha a tại nút 60 (vùng Sw2), kịch bản 0 (từ dataset):

| Thiết bị | Va (pu) | Ia (A) | I0 (A) | 3·I0 (A) | Ngưỡng đất (A) | Bật cờ? |
|---|---|---|---|---|---|---|
| Sw2 (cấp vùng sự cố) | 0.61 | 3606.22 | 1200.49 | 3601 | 167 | có |
| Sw4 (phía sau) | 0.01 | 18.97 | 57.03 | 171 | 121 | **có (nhầm)** |
| L61 (phía sau) | 0.01 | 7.77 | 13.83 | 41 | 40 | **có (nhầm)** |

Điện áp pha a phía sau sự cố sập về 0.01 pu, nên tải 1 pha nối vào pha a phía sau mất tải. Dòng 3 pha phía sau
trở nên rất lệch, sinh dòng dư vượt ngưỡng, và thiết bị phía sau bật cờ dù **không có dòng sự cố đi qua**.
Quy tắc "sâu nhất" chọn Sw4 hoặc L61, tức là sai về phía hạ lưu. `error_analysis.json → fpi_error_direction`
xác nhận: lỗi của FPI chủ yếu là "no detection" (2938) và đoán **xuống phía dưới** ("further downstream" 958,
"predicted child" 405), gần như không bao giờ đoán lên trên (5 + 2).

Hệ thống thật xử lý bằng **phần tử có hướng (directional element)**: chỉ bật cờ khi dòng chạy theo hướng từ
nguồn ra. Baseline ở đây **không có** phần tử đó (README ghi rõ).

### 5b. Mô hình ML: gradient-boosted trees

`shf/model.py → make_model()`: `HistGradientBoostingClassifier(max_iter=300, learning_rate=0.1,
max_leaf_nodes=31, random_state=seed)` của scikit-learn.

**Gradient boosting từ đầu.** Một **cây quyết định (decision tree)** là chuỗi câu hỏi có/không, ví dụ "Sw4_dI0
> 1.5 A?". Một cây đơn lẻ yếu. **Boosting** xây cây nối tiếp nhau: cây thứ k học để **sửa phần sai còn lại** của
k−1 cây trước. "Gradient" nghĩa là phần sai được đo bằng đạo hàm của hàm mất mát (ở đây là log-loss cho phân
loại nhiều lớp), và mỗi cây đi một bước nhỏ theo hướng giảm mất mát.

```
điểm_lớp(x) = điểm_ban_đầu + 0.1·cây_1(x) + 0.1·cây_2(x) + ... + 0.1·cây_300(x)
P(vùng = z | x) = softmax(điểm_lớp)
```

- `learning_rate = 0.1`: mỗi cây chỉ đóng góp 10%, để nhiều cây cùng sửa dần thay vì một cây sửa quá tay.
- `max_iter = 300`: tối đa 300 vòng; với 10 lớp, mỗi vòng xây một cây cho mỗi lớp.
- `max_leaf_nodes = 31`: mỗi cây có tối đa 31 lá, giới hạn độ phức tạp.
- "Hist": giá trị mỗi cột được chia vào tối đa 255 ô (`max_bins` mặc định) trước khi tìm điểm cắt, nên rất
  nhanh.
- **Giá trị thiếu (NaN):** ở mỗi điểm cắt, thuật toán tự học nhánh nào cho NaN đi. Nhờ vậy mô hình chịu được
  khi một thiết bị không báo về.

Ví dụ trực giác với hàng nút 60 ở mục 2: một cây có thể hỏi "Sw2_dI0 > 1.5?" (có) rồi "Sw4_dI0 > 1.5?" (không)
→ dồn điểm cho vùng Sw2. Các cây sau tinh chỉnh khi tải nặng làm nhiễu che dấu hiệu.

**Phương án không chọn:**
- Mạng nơ-ron sâu / GNN (như Chen et al. 2019 trong README): cần nhiều dữ liệu hơn, khó giải thích hơn. Với
  khoảng mười nghìn dòng dữ liệu dạng bảng, gradient boosting là mốc chuẩn mạnh.
- Không chuẩn hóa dữ liệu: cây chỉ so sánh ngưỡng, nên không cần.

**Mất cảm biến (sensor dropout).** Khi huấn luyện, 15% số dòng (`DROPOUT_RATE = 0.15`) bị xóa (gán NaN) toàn
bộ 15 cột của **một** thiết bị chọn ngẫu nhiên (`sensor_dropout()`). Mô hình học cách đoán khi một thiết bị
mất liên lạc. Khi kiểm tra, lần lượt xóa từng thiết bị trên tập kiểm tra và đo lại độ chính xác.

### Câu thầy có thể hỏi

- **"Baseline của em có công bằng không, khi nó không có phần tử có hướng?"** Không hoàn toàn. Baseline là
  FPI đơn giản; sơ đồ thật thêm phần tử có hướng hoặc logic thời gian sẽ giảm lỗi chạm đất trực tiếp. Nhưng
  với sự cố 100–400 Ω, vấn đề của FPI là dòng **dưới ngưỡng** (mục 1), phần tử có hướng không giải quyết được
  điều đó.
- **"Mô hình có đọc được nhãn qua đặc trưng không?"** Đặc trưng chỉ là số đo tại 10 thiết bị. Nút sự cố, điện
  trở, loại sự cố không nằm trong đặc trưng (`feature_columns` chỉ lấy cột `<thiết bị>_<đại lượng>`).
- **"Model lưu trong `models/` có giống model trong kết quả không?"** Không hẳn. Các con số độ chính xác đến từ
  5 mô hình của cross-validation. `fit_full()` huấn luyện thêm một mô hình trên toàn bộ dữ liệu để lưu; với
  hơn 10,000 dòng, scikit-learn tự bật **dừng sớm (early stopping)** (`early_stopping='auto'`), còn mỗi fold
  CV có khoảng 9,153–9,162 dòng nên không bật. Mô hình lưu không được dùng cho số liệu nào trong README.

---

## 6. Phương pháp C: kiểm định trung thực

### GroupKFold theo nút sự cố

**Cross-validation (kiểm định chéo) 5 phần:** chia dữ liệu thành 5 phần, lần lượt lấy 1 phần làm tập kiểm tra,
4 phần huấn luyện. Mỗi dòng được dự đoán đúng một lần bởi mô hình chưa thấy nó ("out-of-fold").

**GroupKFold:** chia theo **nhóm**, ở đây nhóm = nút sự cố (`groups = df["bus"]`). Mọi dòng của một nút nằm
chung một phần. Vậy mô hình **luôn được kiểm tra trên nút chưa từng thấy**.

Vì sao chia ngẫu nhiên sẽ rò rỉ: một nút 3 pha có 144 dòng (27 SLG + 9 LL + 9 LLG + 3 3PH = 48 trường hợp,
× 3 kịch bản; đếm thực tế từ dataset là 144). Ví dụ SLG 200 Ω và SLG 400 Ω ở cùng nút, cùng pha cho số đo gần
như tỉ lệ với nhau. Nếu một dòng ở tập huấn luyện và dòng kia ở tập kiểm tra, mô hình chỉ cần "nhớ nút" chứ
không cần hiểu vật lý. Độ chính xác bị thổi phồng.

Kích thước thực tế: 127 nút → mỗi phần khoảng 25 nút; tập huấn luyện mỗi fold có 9,153–9,162 dòng.

### Bài học từ phiên bản đầu (ba mức tải)

README và chú thích trong `config.py`: phiên bản đầu chỉ dùng **ba mức tải cố định**, và mô hình đạt 99.9%
ngay cả với bộ đặc trưng chỉ có độ lớn. Với chỉ ba trạng thái trước sự cố, mô hình học thuộc dòng "bình
thường" ở mỗi thiết bị, nên bất kỳ độ lệch nào khỏi ba giá trị đó đều lộ ra sự cố. Ngoài đời tải thay đổi liên
tục, nên mẹo đó không dùng được. Ngẫu nhiên hóa tải toàn lưới và từng tải đã loại bỏ rò rỉ và tạo ra khoảng
cách thực tế giữa bộ "magnitude" (87.5%) và bộ "full" (97.7%).

Đây là câu chuyện tốt để kể: thấy một kết quả **quá đẹp**, nghi ngờ, tìm ra nguyên nhân, sửa phương pháp.

### Câu thầy có thể hỏi

- **"Nút chưa thấy nhưng nút bên cạnh thì đã thấy. Vẫn rò rỉ không gian chứ?"** Đúng, một phần. Hai nút liền
  kề trong cùng vùng cho số đo rất giống nhau, và GroupKFold theo nút không ngăn điều đó. Kiểm tra chặt hơn là
  nhóm theo đoạn đường dây hoặc theo khoảng cách. Không thể nhóm theo vùng vì vùng chính là nhãn. Đây là giới
  hạn nên nói thẳng.
- **"99.9% của bản đầu có file kết quả không?"** Không. Kết quả bản đầu không được lưu trong `results/`; con số
  đó chỉ được ghi trong README và chú thích `config.py`.
- **"Tại sao không có tập kiểm tra riêng (held-out)?"** Cross-validation dùng hết dữ liệu và mọi dòng đều được
  kiểm tra trên mô hình chưa thấy nút đó. Không có lần chỉnh siêu tham số nào dựa trên kết quả CV (siêu tham số
  cố định trong `make_model`), nên không có rò rỉ do chọn mô hình.

---

## 7. Kết quả 1: định vị

### Bảng ba phương pháp (`metrics.json → fault_location`)

| Phương pháp | Mọi sự cố | SLG 100 Ω | SLG 200 Ω | SLG 400 Ω |
|---|---|---|---|---|
| FPI thông thường | 56.1% | 8.4% | 2.3% | 1.0% |
| ML, chỉ độ lớn | 87.5% | 70.8% | 38.0% | 22.4% |
| **ML, độ lớn + gia số** | **97.7%** | **98.4%** | **93.7%** | **76.5%** |

Theo loại sự cố, ML full: 3PH 100%, LL 99.78%, LLG 99.89%, SLG 96.46%. FPI: 3PH 96.68%, LL 96.04%, LLG 62.17%,
SLG 40.8%. FPI không bật cờ ở 25.8% số sự cố (`no_device_flagged = 0.2582`).

**Đọc bảng:** khoảng cách giữa hai mô hình ML tăng theo điện trở: 27.5 điểm ở 100 Ω, 54.1 điểm ở 400 Ω. Đây là
bằng chứng cho H1: đại lượng gia số quan trọng nhất đúng ở chỗ dòng sự cố nhỏ so với dòng tải.

Hình: [`results/figures/accuracy_vs_resistance.png`](../../results/figures/accuracy_vs_resistance.png).

### Mất một cảm biến (`ml_full.missing_sensor_accuracy`)

| Thiết bị bị tắt | Độ chính xác |
|---|---|
| Sw1 | 95.5% (tốt nhất) |
| L61 | 90.9% |
| L68 | 89.6% |
| L45 | 89.5% |
| L13 | 89.0% |
| Sw5 | 88.4% |
| Sw2 | 88.0% |
| L77 | 87.8% |
| Sw3 | 87.7% |
| Sw4 | 83.2% (tệ nhất) |

Tức là 83–96%. Thú vị: mất Sw1 lại ít hại nhất. Một cách giải thích: Sw1 thấy mọi sự cố, nên nó ít giúp phân
biệt vùng; thông tin phân biệt nằm ở các thiết bị sâu hơn. Mất Sw4 hại nhất vì Sw4 là ranh giới giữa vùng Sw2 và
cả nhánh Sw4/L68/Sw5/L77. (Đây là giải thích hợp lý, chưa được kiểm chứng riêng.)

Lưu ý: test này xóa **toàn bộ** một thiết bị trên **mọi** dòng kiểm tra, còn khi huấn luyện chỉ 15% dòng bị xóa
một thiết bị. Vì vậy độ chính xác khi mất cảm biến thấp hơn 97.7%.

### Quãng đường tuần tra (`metrics.json → patrol_kft`)

**Quy tắc** (`run.py → patrol()`): nếu đoán đúng vùng, đội tuần tra **chiều dài dây của vùng đó**; nếu đoán sai
(hoặc FPI không bật cờ), đội bị tính **tuần tra toàn xuất tuyến**.

```
patrol = trung bình trên mọi sự cố của  { line_kft[vùng thật]  nếu đúng
                                        { 38.983 kft           nếu sai
```

| Trường hợp | kft |
|---|---|
| Không định vị | 39.0 kft |
| FPI | 19.5 kft |
| ML full | 5.1 kft (−87%) |

Kiểm tra bằng ma trận nhầm lẫn (`confusion_ml.csv`): lấy số dự đoán đúng của mỗi vùng (đường chéo) nhân chiều
dài vùng, cộng 259 lỗi × 38.983, chia 11,448. Kết quả 5.1274 kft, trùng với `patrol_kft.ml_full =
5.127371680642907` (đã chạy kiểm tra bằng Python).

### Câu thầy có thể hỏi

- **"97.7% trên mô phỏng có nghĩa gì cho lưới thật?"** Chỉ nói rằng trên lưới mẫu này, với các giả định về
  nhiễu, tải và sự cố tuyến tính, thông tin cần thiết **có trong** số đo. Lưới thật cần dữ liệu bản ghi sự kiện
  thật để kiểm chứng. Dự án không có dữ liệu đó.
- **"Quy tắc tuần tra có quá khắt khe hoặc quá dễ dãi không?"** Khắt khe với lỗi (sai thì phạt cả xuất tuyến),
  nhưng dễ dãi ở chỗ coi tuần tra vùng đúng là tìm ngay. Nó cũng giả định thời gian tỉ lệ với chiều dài dây.
- **"Sao không có khoảng tin cậy (confidence interval)?"** Chưa tính. Với 11,448 mẫu, sai số chuẩn của tỉ lệ
  97.7% nhỏ, nhưng các mẫu không độc lập (cùng nút), nên khoảng tin cậy đúng cần bootstrap theo nút. Đây là
  việc nên bổ sung.

---

## 8. Kết quả 2: mô hình sai ở đâu

Nguồn: `scripts/error_analysis.py` chạy lại đúng cross-validation (cùng fold, cùng seed, cùng dropout) và lưu
thêm xác suất. Số lỗi: 259 trên 11,448 = 2.3%, khớp `ml_full.accuracy` (đã kiểm tra: 11448 − 11189 = 259).

### FNR / FPR từ đầu

Mô hình luôn chọn 1 trong 10 vùng, nên "dương tính / âm tính" được tính **theo từng vùng, một-chọi-phần-còn-lại
(one-vs-rest)**:

| Ký hiệu | Nghĩa với vùng X |
|---|---|
| TP | sự cố ở X, đoán X |
| FN (bỏ sót) | sự cố ở X, đoán vùng khác |
| FP (đổ oan) | sự cố ở vùng khác, đoán X |
| TN | sự cố ở vùng khác, đoán vùng khác |

```
FNR (tỉ lệ bỏ sót)      = FN / (TP + FN)
FPR (tỉ lệ đổ oan)      = FP / (FP + TN)
Precision (độ chính xác khi đoán X) = TP / (TP + FP)
```

**Ví dụ: đọc hàng và cột Sw1 trong `confusion_ml.csv`** (hàng = vùng thật, cột = vùng đoán):

Hàng Sw1: L13 17, Sw1 1064, Sw2 24, Sw3 2, Sw4 17, Sw5 1. Tổng 1125.
- TP = 1064; FN = 17 + 24 + 2 + 17 + 1 = 61 → FNR = 61 / 1125 = 5.4%.

Cột Sw1 (các vùng khác bị đoán thành Sw1): L13 23, L45 1, L61 1, L77 1, Sw2 41, Sw3 5, Sw4 19, Sw5 2. Tổng FP = 93.
- FPR = 93 / (11448 − 1125) = 93 / 10323 = 0.9%; Precision = 1064 / (1064 + 93) = 92.0%.

Ba số này trùng với `per_zone_ml.csv` (FNR 0.0542, FPR 0.009, precision 0.9196).

| Vùng | Số sự cố | FNR | FPR | Precision |
|---|---|---|---|---|
| Sw1 | 1125 | 5.4% | 0.9% | 92.0% |
| Sw2 | 1494 | 4.5% | 0.6% | 96.2% |
| L13 | 1557 | 2.8% | 0.5% | 97.0% |
| Sw4 | 1971 | 2.6% | 0.5% | 97.8% |
| Sw3 | 981 | 1.7% | 0.1% | 98.8% |
| L45, L61, L68, Sw5, L77 | | ≤ 0.8% | ≤ 0.05% | ≥ 99.4% |

### Lỗi theo loại, điện trở, tải (`error_analysis.json`)

- **Theo loại:** 3PH 0%, LL 0.22%, LLG 0.11%, SLG 3.54%.
- **SLG theo điện trở:** 0% đến 5 Ω; 0.13% ở 10, 25, 50 Ω; 1.64% ở 100 Ω; 6.3% at 200 Ω; 23.5% at 400 Ω.
  237 (92%) are at 200 Ω or more.
- **Theo tải** (chia dòng thành 3 phần bằng nhau theo `load_mult`): 0.9% in the lightest third, 1.76% ở phần
  giữa, 4.1% in the heaviest third. Tải nặng → dòng tải lớn → nhiễu 1% lớn → che dòng sự cố nhỏ. Đây là xác
  nhận độc lập cho cơ chế "tỉ số tín hiệu/nhiễu".
- **Vị trí:** lỗi tập trung ở các vùng gần trạm (Sw1, Sw2, L13, Sw4), nơi dòng tải qua thiết bị là khoảng
  240–630 A (suy từ ngưỡng pha / 2: Sw4 483/2, Sw1 1261/2). Nhiễu 1% là 2.4–6.3 A, ngang dòng sự cố 400 Ω.

### Hướng của lỗi trong cây vùng (`ml_error_direction`)

| Quan hệ vùng đoán so với vùng thật | Số lỗi |
|---|---|
| Vùng cha (lên 1 vùng) | 101 |
| Vùng con (xuống 1 vùng) | 66 |
| Xa hơn về phía nguồn | 32 |
| Xa hơn về phía cuối | 24 |
| Nhánh không liên quan | 23 |
| Vùng anh em (cùng cha) | 13 |

- Lệch đúng 1 vùng: (101 + 66) / 259 = 64%.
- Vẫn trên cùng đường từ trạm ra: (101 + 66 + 32 + 24) / 259 = 86%.
- Nghiêng về phía nguồn: (101 + 32) / 259 = 51%. Lý do: khi sự cố quá nhỏ, thiết bị phía dưới không thấy gì,
  chỉ thiết bị đầu nguồn (Sw1, dòng lớn nhất) còn thấy thay đổi.

Ba cặp nhầm nhiều nhất: Sw2→Sw1 (41), Sw1→Sw2 (24), L13→Sw1 (23). Cả ba đều nằm quanh Sw1.

Ở ví dụ nút 60 (mục 2), `ml_errors.csv` có 5 lỗi tại nút này, phần lớn đoán Sw4 (vùng con) hoặc Sw1 (vùng cha):
đúng mô hình "lệch 1 vùng" ở trên.

### Giả thuyết đã kiểm tra và bác bỏ

Giả thuyết: sự cố **gần ranh giới vùng** (gần một dao) khó hơn, vì hai vùng kề nhau cho số đo gần giống nhau.
Kiểm tra: đếm số đoạn dây từ nút sự cố đến dao gần nhất (`hops_to_boundary`), so tỉ lệ lỗi:

| Số đoạn đến ranh giới | 0 | 1 | 2 | 3 | ≥ 4 |
|---|---|---|---|---|---|
| Tỉ lệ lỗi | 2.73% | 2.23% | 2.71% | 1.79% | 1.88% |

Không có xu hướng rõ (1.8–2.7% ở mọi khoảng cách). Giả thuyết bị bác bỏ. Yếu tố quyết định là điện trở sự cố và
mức tải, không phải vị trí trong vùng. Ghi nhận: thước đo là số đoạn dây, không phải mét.

### Đánh đổi theo ngưỡng tin cậy (`defer_low_confidence`)

Mô hình cho xác suất mỗi vùng. Trung vị xác suất lớn nhất: 1.00 với dự đoán đúng, 0.90 với dự đoán sai. Vậy có
thể **chuyển các dự đoán kém tự tin sang tuần tra thủ công**:

| Ngưỡng | Giữ lại (coverage) | Độ chính xác trên phần giữ lại | Lỗi còn lại |
|---|---|---|---|
| 0.5 | 99.85% | 97.84% | 247 |
| 0.7 | 99.1% | 98.28% | 195 |
| 0.8 | 98.61% | 98.53% | 166 |
| 0.9 | 97.86% | 98.84% | 130 |
| 0.95 | 97.19% | 99.13% | 97 |

Ở ngưỡng 0.95: chuyển 2.8% of faults sang thủ công, độ chính xác tăng to 99.1%, số lỗi giảm từ 259 to 97
(1 − 97/259 = 63%).

### So sánh với FPI theo vùng (`per_zone_fpi.csv`)

FPI đổ oan nhiều nhất cho Sw5: FPR 12.6%, precision 38.8%. Sw5 là vùng sâu nhất (cuối nhánh), nên mọi cờ nhầm do
dòng dư phía sau sự cố (mục 5a) đẩy dự đoán về đó.

### Câu thầy có thể hỏi

- **"Các xác suất có được hiệu chỉnh (calibrated) không?"** Chưa kiểm tra. Gradient boosting thường quá tự tin.
  Bảng ngưỡng chỉ dùng xác suất như **thứ hạng**, và bảng đó đo trực tiếp trên dữ liệu out-of-fold, nên vẫn hợp
  lệ; nhưng không nên đọc 0.95 là "95% chắc chắn".
- **"Lưới bình thường thì sao, mô hình có báo động nhầm không?"** Không đo. Tập dữ liệu chỉ có trường hợp có sự
  cố (README "Not measured"). Mô hình chỉ chạy sau khi recloser đã khóa, nhưng báo động nhầm trên lưới khỏe vẫn
  chưa được kiểm tra.
- **"Đoán sai vùng thì hậu quả là gì?"** Cô lập sai vùng → đóng lại → đóng vào điểm sự cố → recloser cắt lần
  nữa. Hậu quả này **không được mô phỏng**.

---

## 9. Phương pháp D + Kết quả 3: cô lập và khôi phục

### Thuật toán (`shf/restoration.py → plan_restoration()`)

Với sự cố ở vùng Zf:

1. Sw1 cắt và khóa: cả xuất tuyến mất điện.
2. **Cô lập:** mở dao cấp vào Zf và mọi dao đi ra khỏi Zf.
3. **Đóng lại Sw1:** các vùng phía trên Zf có điện lại (bỏ qua nếu Zf = Sw1).
4. Các vùng phía dưới Zf thành các **đảo mất điện**. **Tham lam (greedy):** mỗi vòng, với mỗi dao liên lạc chưa
   dùng có một đầu ở đảo tối và đầu kia có điện (hoặc là xuất tuyến bên cạnh):
   - liệt kê mọi tập vùng **liên thông** trong đảo chứa vùng ở đầu dao (`connected_subsets()`), sắp theo kW giảm
     dần;
   - thử từng tập: đặt trạng thái dao, chạy power flow, chấp nhận tập lớn nhất đạt cả ba ràng buộc;
   - trong các dao, chọn dao cấp được nhiều kW nhất; đóng nó; lặp lại cho đến khi không còn gì đạt.

**Ba ràng buộc** (`check_power_flow()`):

| Ràng buộc | Giá trị |
|---|---|
| Điện áp mọi nút đang có điện | 0.95–1.05 pu (ANSI C84.1 Range A), dung sai số `V_TOL = 0.0005` |
| Dòng mỗi đường dây | ≤ định mức khẩn cấp (125% định mức thường) |
| Hình tia | không mạch vòng (`closed_graph_has_loop()`), kiểm tra ở cấu hình cuối |

Power flow trong bước này để bộ điều áp **tự do chuyển nấc** (`solve(controls=True)`), vì khôi phục diễn ra
trong vài phút, đủ để bộ điều áp phản ứng. Ngược với lúc mô phỏng sự cố (mục 4).

**Greedy từ đầu.** Thuật toán tham lam chọn phương án tốt nhất **ở bước hiện tại** mà không xét tổ hợp các bước
sau. Ưu: nhanh, dễ giải thích cho điều độ viên. Nhược: không đảm bảo tối ưu toàn cục. Ở lưới này chỉ có 2 dao
liên lạc, nên số tổ hợp nhỏ; phương án không chọn là duyệt toàn bộ (exhaustive) hoặc tối ưu hóa nguyên hỗn hợp
(MILP), chính xác hơn nhưng phức tạp hơn nhiều cho bài toán cỡ này.

**Ví dụ chuỗi greedy, sự cố ở vùng Sw1** (`switching_orders.md`): vòng 1, Sw7 không dùng được vì cả hai đầu
(L45 và Sw5) đều tối. Sw9 từ xuất tuyến bên cạnh nhận được L68 + Sw5. Vòng 2, Sw5 đã có điện nên Sw7 dùng được:
nhận L45 từ Sw5. Kết quả 120 + 320 + 515 = 955 kW, khớp cột `kW_restored_by_tie` của hàng Sw1.

### Kết quả từng vùng (`restoration.csv`)

| Vùng sự cố | Dao liên lạc đóng | kW tải lành phía dưới | kW cấp lại qua dao | Phương án bị loại | Vmin / Vmax cuối (pu) | Giảm kW·phút |
|---|---|---|---|---|---|---|
| Sw1 | Sw9, Sw7 | 3090 | 955 | 14 / 16 | 0.9594 / 1.0045 | 9.2% |
| L13 | Sw7 | 755 | 515 | 1 / 2 | 0.9754 / 1.0497 | 56.1% |
| Sw2 | Sw7 | 1795 | 440 | 6 / 8 | 0.9561 / 1.025 | 25.5% |
| Sw3 | – | 515 | 0 | 1 / 1 | 0.9827 / 1.0504 | 49.1% |
| L45 | – | 0 | 0 | 0 / 0 | 0.9778 / 1.0486 | 60.5% |
| L61 | – | 0 | 0 | 0 / 0 | 0.9797 / 1.0464 | 68.9% |
| Sw4 | Sw7 | 700 | 440 | 0 / 2 | 0.9551 / 1.0312 | 40.5% |
| L68 | Sw7 | 320 | 320 | 0 / 1 | 0.9551 / 1.0474 | 87.5% |
| Sw5 | – | 0 | 0 | 0 / 0 | 0.9828 / 1.0448 | 72.2% |
| L77 | – | 0 | 0 | 0 / 0 | 0.9768 / 1.0467 | 76.4% |

Tổng: 2,670 kW of the 7,175 kW tải lành phía dưới được cấp lại qua dao liên lạc (37%). Lưu ý: 7,175 kW là
**tổng của 10 trường hợp**, không phải tải của lưới (lưới chỉ có 3,490 kW). Mỗi trường hợp là một sự cố riêng.

Mọi cấu hình cuối hội tụ, hình tia, không quá tải, điện áp trong giới hạn (`all_final_states_within_limits` và
`all_radial` đều `true`). Lưu ý nhỏ: hàng Sw3 có Vmax 1.0504 pu, vượt 1.05 một chút nhưng nằm trong dung sai
`V_TOL = 0.0005`; ngay trạng thái bình thường đã ở 1.04996 pu.

### Vì sao điện áp, không phải dòng định mức, là giới hạn

Thuật toán đã loại 22 phương án (README: "rejected 22 candidate pickups"), theo tổng cột `power_flow_rejected`: 14 + 1 + 6 + 1 = 22, trên 30 lần
thử. Theo các hàng tải đỉnh (mức 1.0) trong `results/hourly/by_level.csv`: 20 phương án bị loại do **điện áp
thấp**, 2 do **điện áp cao** (sự cố Sw3 và L13, đều nhận L45 qua Sw7), và **không phương án nào** bị loại do quá
tải. Điện áp của từng phương án bị loại không được ghi ra `results/`, nên ở đây không nêu con số.

Ước lượng thô vì sao dòng không phải vấn đề: phương án lớn nhất từng được thử (sự cố Sw1, nhận cả nhánh Sw2 =
1,975 kW danh định qua Sw9):

```
I ≈ P / (√3 · V) = 1975 kW / (√3 · 4.16 kV) ≈ 274 A   (hệ số công suất 1, bỏ qua sụt áp)
Định mức khẩn cấp dây trục 336 ACSR = 530 × 1.25 = 662.5 A
```

Dòng còn xa giới hạn của dây trục, nhưng đi qua 4,000 ft dây nối và cả đoạn dây dài của lưới thì sụt áp đã
quá 5%. Ở lưới 4.16 kV, điện áp thấp nên dòng lớn trên mỗi kW, và sụt áp (tỉ lệ với I·Z) tới giới hạn trước khi
nhiệt độ dây tới giới hạn. (Nhánh 1/0 có định mức khẩn cấp 287.5 A, gần hơn; power flow đã kiểm tra mọi đường
dây và không thấy quá tải.)

**Vì sao lại quá áp?** Bộ điều áp đầu nguồn có **line-drop compensation, LDC (bù sụt áp đường dây)**: nó đo
dòng và nâng điện áp đầu nguồn để bù sụt áp dự kiến tới một điểm xa. Khi một đảo được cấp từ hướng khác qua
Sw7, các nút gần đầu nguồn đã được nâng áp lại không còn sụt áp như dự kiến, nên vượt 1.05 pu.

### Chỉ số kW·phút mất điện

**Công thức** (`restoration.py → kw_minutes()`), với kW danh định của mỗi vùng (`zones.csv`) và thời gian giả
định trong `config.py`: T_auto = 1, T_manual = 90, T_repair = 240 phút.

| Vùng | Thủ công (conventional) | Tự động (automated) |
|---|---|---|
| Vùng sự cố | kW × (90 + 240) | kW × (90 + 240) |
| Vùng lành **không** cấp lại được | kW × (90 + 240) | kW × (90 + 240) |
| Vùng lành còn lại (phía trên + cấp qua dao) | kW × 90 | kW × 1 |

```
giảm (%) = 1 − automated / conventional
```

**Ví dụ tính tay 1: sự cố ở L68** (L68 = 120 kW; mọi vùng khác cộng lại 3490 − 120 = 3370 kW, đều được cấp lại):

```
conventional = 120 × 330 + 3370 × 90 = 39,600 + 303,300 = 342,900
automated    = 120 × 330 + 3370 × 1  = 39,600 +   3,370 =  42,970
giảm         = 1 − 42,970 / 342,900 = 87.5%
```

Khớp `restoration.csv`: `kWmin_conventional = 342900`, `kWmin_automated = 42970`, `kWmin_reduction_pct = 87.5`.

**Ví dụ tính tay 2: sự cố ở Sw4** (có vùng không cấp lại được): Sw4 725 kW; L77 260 kW tối đến khi sửa xong;
L68 + Sw5 = 440 kW cấp qua Sw7; phía trên còn 3490 − 725 − 260 − 440 = 2065 kW.

```
conventional = (725 + 260) × 330 + (440 + 2065) × 90 = 325,050 + 225,450 = 550,500
automated    = (725 + 260) × 330 + (440 + 2065) × 1  = 325,050 +   2,505 = 327,555
giảm         = 1 − 327,555 / 550,500 = 40.5%
```

Khớp file. Chạy lại công thức này cho cả 10 hàng bằng Python: cả 10 trùng khớp tuyệt đối.

**Trung bình theo chiều dài dây.** Giả định số sự cố mỗi dặm đều nhau, nên xác suất sự cố ở một vùng tỉ lệ với
chiều dài dây của vùng đó (`run.py`: `w = length[z] / total_kft`):

```
giảm trung bình = Σ (line_kft[z] / 38.983) × giảm[z] = 50.7%
```

(`kWmin_reduction_pct_weighted_by_line_length = 50.7`; README làm tròn: kW-minutes "fell by 51%".) Nếu lấy trung
bình không trọng số của 10 hàng thì là 54.6%. Khoảng từ 9.2% (sự cố ở vùng đầu Sw1: phần lớn tải ở phía dưới
và không cấp lại được) đến 87.5% (L68).

**Độ nhạy theo giả định thời gian:** đổi T_manual hay T_repair thì con số này đổi theo, vì nó tính thẳng từ ba thời gian giả định. Bảng độ nhạy trước đây được tính bằng một script tạm, không lưu vào `results/`, nên đã bỏ.

Con số này **phụ thuộc trực tiếp** vào thời gian giả định. Nó minh họa cơ chế, không phải dự báo.

### Câu thầy có thể hỏi

- **"kW·phút giảm 51%, con số đó có ý nghĩa thật không?"** Nó là hệ quả số học của ba thời gian giả định và
  của kết quả khôi phục. Giảm T_manual thì con số này giảm theo. Thứ dự án thực sự chứng minh là
  **vùng nào cấp lại được trong giới hạn kỹ thuật**; còn kW·phút chỉ chuyển kết quả đó ra một thước đo dễ hình
  dung. Ngoài ra: dùng kW danh định (không phải tải ngẫu nhiên), và giả định vùng đã được định vị đúng.
- **"Sao vùng không cấp lại được bị tính 330 phút ở cả hai cách?"** Giả định: nếu power flow cho thấy không dao
  nào nhận được vùng đó trong giới hạn, đội thủ công cũng không cấp lại được trước khi sửa xong. Điều này làm
  phép so sánh **thận trọng** (không thổi phồng lợi ích của tự động).
- **"Greedy có bỏ sót phương án tốt hơn không?"** Có thể về nguyên tắc. Ở đây chỉ có 2 dao liên lạc và các đảo
  nhỏ, thuật toán đã thử mọi tập liên thông trong đảo cho mỗi dao. Không chứng minh được tối ưu toàn cục, nhưng
  không gian tìm kiếm nhỏ.
- **"Kiểm tra hình tia chỉ ở cấu hình cuối?"** Đúng, `radial` được kiểm tra ở cấu hình cuối và đều `True`.
  Trong lúc thử, mỗi đảo chỉ được nối với đúng một nguồn qua một dao, nên không tạo vòng; kiểm tra cuối xác nhận
  điều đó.

---

## 10. Thảo luận và giới hạn

### Bằng chứng ủng hộ điều gì

- Trên lưới mẫu IEEE 123 nút, với nhiễu 1% / 0.5° và tải ngẫu nhiên, **đại lượng gia số trước/sau sự cố** cho
  phép xác định vùng sự cố tốt hơn hẳn chỉ dùng độ lớn, và hơn hẳn FPI đơn giản, nhất là với sự cố 100–400 Ω.
- Mô hình vẫn hoạt động khá khi mất một thiết bị.
- Lỗi có cấu trúc giải thích được bằng vật lý (tỉ số dòng sự cố / dòng tải), không phải ngẫu nhiên.
- Thuật toán khôi phục cho cấu hình cuối hợp lệ ở cả 10 trường hợp; ở lưới này điện áp là ràng buộc quyết định.

### Bằng chứng KHÔNG ủng hộ điều gì

- Không nói gì về hiệu năng trên lưới thật: không có dữ liệu thật, không triển khai ở điện lực nào, đường
  MQTT/TimescaleDB chưa chạy trọn vẹn.
- Không nói gì về báo động nhầm trên lưới khỏe, hay hậu quả khi đoán sai vùng.
- Không chứng minh greedy là tối ưu.
- kW·phút không phải dự báo thời gian mất điện thật.

### Mọi giả định và giá trị

| Giả định | Giá trị | Ở đâu |
|---|---|---|
| 5 dao tự động thêm vào | L13, L45, L61, L68, L77 | `config.SECTIONALIZERS` |
| Dao liên lạc Sw9 + xuất tuyến bên cạnh | 4.16 kV, 1.03 pu, 4,000 ft 336 ACSR, không tải riêng | `config.ADJACENT_FEEDER_DSS` |
| Dòng định mức | 530 / 230 / 200 A, dao 600 A | `LINECODE_AMPACITY`, `SWITCH_AMPACITY` |
| Định mức khẩn cấp | 125% | `EMERGENCY_FACTOR = 1.25` |
| Giới hạn điện áp | 0.95–1.05 pu, dung sai 0.0005 | `V_MIN_PU`, `V_MAX_PU`, `V_TOL` |
| Tải ngẫu nhiên | hệ số 0.3–1.1; từng tải N(1, 0.20) cắt [0.3, 1.7] | `LOAD_MULT_RANGE`, `LOAD_SPREAD` |
| Nhiễu đo | 1%, 0.5° | `NOISE_MAG`, `NOISE_ANG_DEG` |
| Sự cố | điện trở tuyến tính, phasor ổn định | `SLG_RESISTANCES`, `PHASE_RESISTANCES` |
| Ngưỡng FPI | pha 2×, đất max(0.5×, 1.2× dòng dư); không có hướng | `FPI_*` |
| Thời gian | 1 / 90 / 240 phút | `T_AUTOMATED_MIN`, `T_MANUAL_MIN`, `T_REPAIR_MIN` |
| Tỉ lệ sự cố theo chiều dài dây | đều | `run.py` (trọng số `w`) |

### Câu thầy có thể hỏi

- **"Điểm yếu lớn nhất của dự án là gì?"** Mọi thứ là mô phỏng, và sự cố trở kháng cao được mô hình bằng điện
  trở tuyến tính. Đúng chỗ ML mạnh nhất so với FPI (200–400 Ω) lại là chỗ mô phỏng xa thực tế nhất.
- **"Bước tiếp theo nên là gì?"** Kiểm tra trên bản ghi sự kiện thật hoặc dữ liệu sự cố trở kháng cao đo thực;
  thêm phần tử có hướng cho baseline để so sánh công bằng hơn; kiểm tra báo động nhầm trên lưới khỏe; mô phỏng
  hậu quả của dự đoán sai.

---

## 10b. Mở rộng: chuyển giao sang lưới mới (IEEE 34-bus & cáp ngầm IEEE 37-bus), tìm từng bus & lưới có điện mặt trời + Conformal Prediction

Bộ phân loại ở trên dùng vector 150 cột gắn cứng với tên của 10 thiết bị trên IEEE 123-bus, nên không chạy được trên xuất tuyến khác có số dao khác. Ba nghiên cứu mở rộng trong [`research/gnn-transfer/PLAN.md`](../../research/gnn-transfer/PLAN.md), [`research/active-grid-gnn/PLAN.md`](../../research/active-grid-gnn/PLAN.md) và [`research/ieee37-underground/PLAN.md`](../../research/ieee37-underground/PLAN.md) giải quyết hạn chế đó (kết quả lưu trong `results/transfer/` và `results/active_grid/`, toàn bộ là mô phỏng OpenDSS thuần túy, không có dữ liệu thực địa):

1. **Chuyển giao zero-shot trên lưới hình tia thụ động (0.01–400 Ω):** biểu diễn mỗi sự kiện thành đồ thị các vùng với đặc trưng không thứ nguyên (mức thay đổi dòng chia cho dòng tải trước sự cố, điện áp per-unit, hướng dòng công suất). Học **chỉ trên IEEE 123-bus (4.16 kV, 10 vùng, 11,448 sự cố)** rồi đem chạy thẳng sang **IEEE 34-bus chưa từng thấy (24.9 kV, 7 dao đặt theo quy tắc nhánh ≥ 5% tải cố định trước, 4,104 sự cố)**:
   - Trên IEEE 123-bus (5-fold GroupKFold theo bus): FPI đạt **55.5%**, GBDT theo nút đạt **98.3%** (mất 1 cảm biến: **89.4%**), GNN cây vùng (2 lớp) đạt **98.1%** (mất 1 cảm biến: **90.2%**).
   - Zero-shot trên IEEE 34-bus: FPI đạt **55.5%**, GBDT theo nút đạt **99.8%** (mất 1 cảm biến: **88.4%**), GNN đạt **99.3%** (mất 1 cảm biến: **85.8%**); tinh chỉnh 20% số bus: GNN đạt **98.7%** so với **96.4%** của GBDT. Lý do vật lý điểm trên 34-bus cao hơn ở 400 Ω: đo bằng OpenDSS ở tải định mức (`scripts/signal_to_load.py`), sự cố 400 Ω trên lưới 24.9 kV kéo trung vị 31.7 A, bằng 61.1% dòng đầu tuyến 51.8 A; trên lưới 4.16 kV chỉ kéo 6.2 A, bằng 1.0% của 631.5 A.
2. **Stage 2 — Tìm từng bus bên trong vùng dự đoán:** công thức điện kháng Takagi 3 pha dùng ma trận đường dây 3×3 từ OpenDSS (không cần học) đạt **46.9% top-1 / 69.0% top-3** trên 123-bus và **57.5% top-1 / 87.4% top-3** trên 34-bus, vượt xa GNN đồ thị bus (**17.8% / 38.5%** khi kiểm định GroupKFold theo bus trên 123-bus và **50.8% / 85.8%** zero-shot trên 34-bus). Các cặp bus hay nhầm nhất (`61→61s`, `160→160r`, `832→888`) đều có `ΔX1 = 0.000 Ω`: hai nhánh song song cách cảm biến đầu vùng cùng một khoảng cách điện không thể tách nếu không thêm cảm biến.
3. **Lưới chủ động có điện mặt trời (0–50% `Generator Model=7`), đổi cấu trúc/vòng kín, sự cố tới 10,000 Ω và quá độ không sự cố (`NO_FAULT`):**
   - Trên IEEE 123-bus chủ động (17,847 sự kiện): FPI tụt xuống **40.7%** (tỉ lệ cắt nhầm khi không sự cố FPR **21.2%**); GBDT theo nút đạt **93.9%** (FPR **13.9%**, mất 1 cảm biến **86.1%**); mạng chú ý đồ thị hai chiều **ActiveGridGATv2** đạt **95.8%** (giảm hơn một nửa tỉ lệ cắt nhầm xuống **6.5%**, vòng kín **94.7%**, mất 1 cảm biến **89.1%**).
   - Trên IEEE 34-bus chủ động chưa từng thấy (9,491 sự kiện, SLG tới 10,000 Ω): FPI đạt **47.6%**; zero-shot GBDT đạt **83.8%** so với **77.6%** của ActiveGridGATv2 (do bước nhảy tải +30–80% trên 34-bus có biên độ giống sự cố 2.5–10 kΩ); khi tinh chỉnh 20% (7 bus), **ActiveGridGATv2 vượt lên 89.1%** (so với **83.1%** của GBDT, mất 1 cảm biến **80.4%** vs **73.4%**); khi học tại chỗ trên 34-bus, ActiveGridGATv2 đạt **93.1%** (so với **91.8%** của GBDT).
4. **Split Conformal Prediction (đăng ký trước, rồi kiểm tra sau):** cách tính APS xác định đã đăng ký trước bị bão hòa. Ở mục tiêu 95%, mỗi tập trung bình chứa 6.37 trên 11 nhãn và phủ 100.0% số ca trên 123-bus chủ động, nên luật "chỉ tự đóng cắt khi tập có 1 nhãn" chỉ áp dụng được cho 22.6% số ca (ActiveGridGATv2). Tiêu chí C3 đạt đúng như chữ viết, nhưng độ phủ đó gần như vô nghĩa. Kiểm tra sau trên cùng xác suất và cùng cách chia bằng APS ngẫu nhiên (`scripts/active_conformal_posthoc.py`, Addendum A trong `research/active-grid-gnn/PLAN.md`) đạt đúng mục tiêu trên lưới đã học: độ phủ 95.0% với 1.09 nhãn mỗi tập; tập 1 nhãn chiếm 89.2% số ca, đúng 99.1%, và 1.1% số ca không sự cố sẽ bị cắt nhầm. Kết quả này **không** giữ được khi sang lưới 34-bus chưa thấy: ngưỡng của 123-bus chỉ phủ 81.4% (ActiveGridGATv2) và 91.1% (GBDT) so với mục tiêu 95%; hiệu chỉnh lại bằng 2 bus sự cố của lưới đó đạt trung bình 92.0% và 94.2% (tệ nhất trong 10 lần rút: 81.5% và 91.3%). Muốn có bảo chứng thì phải hiệu chỉnh bằng dữ liệu của chính lưới đang dùng; ở đây nó chỉ là cổng hỗ trợ quyết định trong mô phỏng, không phải bảo chứng cho bảo vệ rơ-le.
5. **Thử sức trên lưới thứ 3 chưa từng thấy — cáp ngầm đô thị IEEE 37-bus (4.8 kV, 3 dây delta không nối đất, [`research/ieee37-underground/PLAN.md`](../../research/ieee37-underground/PLAN.md)):**
   - **Đặc điểm vật lý và giả định:** lưới cáp ngầm đô thị nguyên bản từ OpenDSS (`data/feeder/ieee37/`, mã cáp 721–724, biến áp trạm delta-delta, bộ điều áp tam giác hở, phụ tải delta lệch pha, không có tụ bù). **Giả định có chủ đích:** không thêm máy biến áp tạo trung tính nhân tạo để đo trung thực khả năng tổng quát hóa sang hệ thống nối đất khác. Quy tắc đặt dao nhánh ≥ 5% tải (khóa trước khi chạy) chia ra **10** vùng (`D1`–`D10`) trên **36** bus 3 pha (`2,457 kW`), quét **5,184** sự cố thụ động (100% hội tụ).
   - **Vì sao độ chính xác zero-shot giảm mạnh (kết luận đăng ký trước `P1-Fail`, [`results/transfer/phase3_ieee37.json`](../../results/transfer/phase3_ieee37.json)):** vì lưới 3 dây delta không nối đất trung tính, dòng sự cố SLG chỉ khép mạch qua điện dung rải của cáp ngầm các pha lành. Ở tải định mức (`369.5 A` tại dao đầu tuyến `D1`, [`results/transfer/signal_to_load.json`](../../results/transfer/signal_to_load.json)), trung vị dòng SLG chỉ đạt **2.36 A** (**0.64%** dòng đầu tuyến) ngay cả ở `0.01 Ω` chạm trực tiếp và **2.23 A** (**0.60%**) ở `400 Ω`, kèm hiện tượng dịch trung tính (điện áp pha lành dâng về `√3` pu) — miền vật lý hoàn toàn không tồn tại trên lưới 4 dây nối đất IEEE 123-bus. Do đó:
     - **Stage 1 thụ động:** FPI đạt **43.0%** (mất 1 cảm biến **38.7%**; sự cố pha **98.2%**, SLG **0.0%**); zero-shot GBDT đạt **56.4%** (mất 1 cảm biến **48.7%**; sự cố pha **100.0%**, SLG **22.4%**); zero-shot GNN đạt **46.7%** (mất 1 cảm biến **44.2%**; sự cố pha **99.7%**, SLG **5.6%**). Cả hai đều không đạt tiêu chí `P1-Main`. Ngược lại, khi kiểm định tại chỗ 5-fold CV trên IEEE 37-bus, GBDT đạt **91.4%** (SLG **85.0%**) và GNN đạt **88.0%** (SLG **79.6%**), chứng tỏ bộ 21 đặc trưng vẫn chứa tín hiệu định vị được một khi mô hình được thấy dữ liệu lưới delta. Khi tinh chỉnh few-shot 5% / 20% (2 / 7 bus): `ZoneTreeGNN` tăng lên **51.4%** / **66.0%** mà không quên sự cố pha, còn GBDT warm-start tụt còn **45.2%** / **55.1%** do quá khớp các vùng được rút mẫu.
     - **Stage 2 tìm từng bus ([`results/transfer/phase2b_bus_ieee37.json`](../../results/transfer/phase2b_bus_ieee37.json), kết luận `P2-Partial`):** điện kháng Takagi 3 pha đạt **38.4%** top-1 / **53.4%** top-3 và `BusGraphGNN` zero-shot đạt **37.2%** / **53.9%** (so với ngẫu nhiên trong vùng **17.0%** / **42.1%**); riêng sự cố pha (`3PH/LL/LLG`), Takagi đạt **94.4%** top-3 và `BusGraphGNN` **95.2%** (so với **69.4%** ngẫu nhiên). Sự cố SLG phá vỡ giả thiết vòng chạm đất của phương trình Takagi và cáp ngầm ngắn có khoảng cách điện kháng rất nhỏ (`701→702`: `ΔX1 = 0.0599 Ω`, `728→729`: `ΔX1 = 0.0077 Ω`).
   - **Lưới chủ động & Conformal trên IEEE 37-bus (chạy trên Kaggle GPU, `results/active_grid_ieee37/`):** cấu hình đã khóa trong `shf/active_grid.py` (3 nguồn DER `Model=7` đấu delta tại `738`, `708`, `720`; dao `Tie37` nối qua biến áp delta-delta tại bus `741` cho `reconfig_tie` mở `D6` và `looped_tie`; `NO_FAULT` chia 50/50 `pv_cloud` và `load_step`, `cap_switch = 0` vì lưới không có tụ bù).
     - **Định vị vùng (kết luận đăng ký trước `A2-Partial`):** FPI đạt **44.5%** (mất 1 cảm biến **41.6%**; sự cố pha **79.4%**); zero-shot GBDT đạt **55.4%** (cắt nhầm **3.4%**, sự cố pha **93.1%**, SLG **13.2%**, mất 1 cảm biến **49.6%**); zero-shot ActiveGridGATv2 đạt **46.2%** (cắt nhầm **11.8%**, sự cố pha **88.4%**, SLG **0.2%**, mất 1 cảm biến **44.3%**). Cùng nguyên nhân vật lý như phần thụ động: dòng SLG chỉ khép qua điện dung cáp. Tinh chỉnh 20% (7 bus) đưa ActiveGridGATv2 lên **76.2%** (GBDT **62.0%**); học tại chỗ đạt **85.7%** (GATv2) và **88.3%** (GBDT).
     - **Conformal APS ngẫu nhiên ở mục tiêu 95% (đã đăng ký trước):** dùng ngưỡng của 123-bus chỉ phủ **47.4%** (ActiveGridGATv2) và **81.1%** (GBDT); hiệu chỉnh lại bằng 2 bus sự cố đạt trung bình **94.1%** và **93.9%** (tệ nhất trong 10 lần rút **86.2%** và **88.9%**). Quét cỡ tập hiệu chỉnh (50 lần rút): 5% số bus chỉ đạt trung bình **93.1%** (GATv2) và **92.8%** (GBDT), chưa qua ngưỡng; 20% số bus đạt **94.8%** trung bình / **92.6%** phân vị 10 (GATv2) và **94.6%** / **92.0%** (GBDT), nên tiêu chí `A3-Recal` đạt từ 20% số bus. Vẫn chỉ là cổng hỗ trợ quyết định trong mô phỏng, không phải bảo chứng cho bảo vệ.

   - **Kiểm chứng mở rộng trên 15 lưới phân phối chuẩn OpenDSS (chạy song song 3 máy ảo Kaggle, [`results/transfer/multi_feeder_benchmark.json`](../../results/transfer/multi_feeder_benchmark.json), [`research/multi-feeder-benchmark/PLAN.md`](../../research/multi-feeder-benchmark/PLAN.md)):** đem đúng cặp mô hình đóng băng từ IEEE 123-bus (không huấn luyện lại) chạy trên thêm 9 lưới chuẩn IEEE/EPRI khác (0.416–34.5 kV, cả 50 Hz và 60 Hz, tới 6,058 bus / 18 zone), đạt **10 trên 11 lưới chưa từng thấy**: IEEE 13-bus (**95.5%** GBDT / **89.0%** GNN vs **50.9%** FPI), lưới cáp hạ áp châu Âu **50 Hz IEEE European LV** (**93.3%** / **91.3%** vs **60.3%** FPI), **IEEE 8500-Node** (**99.8%** / **99.0%** vs **44.1%** FPI), và cả 6 lưới lớn của EPRI (Ckt5 **98.0%**/**97.6%**, Ckt7 18 zone **98.7%**/**99.2%**, Ckt24 34.5 kV **99.7%**/**98.6%**, J1 **99.2%**/**99.3%**, K1 **99.7%**/**99.6%**, M1 **99.6%**/**88.3%**). Trên cả 6 lưới EPRI lớn, `ZoneTreeGNN` đều vượt GBDT khi mất 1 cảm biến (ví dụ **94.3%** so với **90.5%** trên EPRI Ckt7 18 zone). Mạng hạ áp mạch lưới IEEE 342-Node (71 vòng kín), IEEE 9500-Node không hội tụ cơ sở trên OpenDSSDirect 0.9.4 và CIGRE MV (không có trong kho OpenDSS gốc) được ghi nhận trung thực là ngoài phạm vi.

6. **Kiến trúc 2 tầng Edge HIF-Sensor (504 B int8) → Graph FLISR cho dải 200–400 Ω và HIF lưới chủ động (mục 2d trên trang báo cáo, kế hoạch đã khóa tiêu chí trước trong [`research/hif-fusion/PLAN.md`](../../research/hif-fusion/PLAN.md)):**
   - **Động lực vật lý:** điểm yếu lớn nhất của toàn dự án ở tần số 60 Hz là sự cố SLG 200–400 Ω trên lưới 4.16 kV IEEE 123-bus (dòng 400 Ω trung vị 6.2 A, chỉ bằng 1.0% dòng đầu tuyến 631.5 A, chìm vào nền nhiễu CT 1% nên mô hình chính chỉ đạt 76.5% ở 400 Ω và 92% lỗi tập trung ở ≥ 200 Ω).
   - **Kiến trúc 2 tầng (mô-đun độc lập [`shf/hif_edge.py`](../../shf/hif_edge.py), [`shf/hif_fusion.py`](../../shf/hif_fusion.py), [`scripts/hif_fusion_run.py`](../../scripts/hif_fusion_run.py)):**
     - **Tầng 1 (Edge ESP32-S3 HIF-Sensor tại từng recloser/dao):** CT kẹp dòng dư `SCT-013-000` (2000:1, điện trở gánh 33 Ω) → lọc thông thấp Butterworth 4 bậc Sallen-Key đã kiểm chứng LTspice (`-3 dB` tại `2,045.1 Hz` trên LTspice / `2,047.9 Hz` IIR Python) → ADC 12-bit lấy mẫu ở `15.36 kHz` (256 mẫu/chu kỳ 60 Hz) → 16 đặc trưng sóng hài / bất đối xứng / biến động chu kỳ trên cửa sổ 8 chu kỳ (133.3 ms) → Tiny MLP lượng tử hóa `int8` đóng băng (`16→16→8→1`, 417 tham số / 504 byte, nạp từ `model_int8.npz` của kernel Kaggle `christoopherchau/ch-y-n`, hoặc dự phòng tất định `seed=42`) kèm bộ đếm bền `PERSIST = 3` chu kỳ cửa sổ → xuất 2 đại lượng vô hướng không phụ thuộc lưới `(p_hif, hif_alarm)`.
     - **Tầng 2 (Graph FLISR đối chứng cặp `60Hz_only` vs `60Hz_plus_edge`):** ghép `(p_hif, hif_alarm)` vào khối cảm biến của từng nút (`21 → 23` đặc trưng cho nhánh thụ động `PerNodeGBDT` / `ZoneTreeGNN`; `26 → 28` đặc trưng nút + cạnh có hướng thứ 5 `diff_p_hif` cho nhánh chủ động `ActivePerNodeGBDT` / `ActiveGridGATv2`, kết hợp cổng Split Conformal `aps_rand` 95%) trên cùng sự cố OpenDSS, cùng cách chia fold và seed, quét đủ **5 bề mặt hồ quang Emanuel** (`wet_grass`, `wet_sand`, `concrete`, `dry_grass`, `dry_asphalt`) và **7 nhiễu nền** (`none`, `load_step`, `cap_switch`, `inrush`, `motor_start`, `arc_welder`, `nonlinear_fluct`).
   - **Kết quả chạy thật trên Kaggle GPU ([`notebooks/kaggle_hif_fusion.ipynb`](../../notebooks/kaggle_hif_fusion.ipynb), nạp đúng `model_int8.npz` đóng băng từ `christoopherchau/ch-y-n`, [`results/hif_fusion/`](../../results/hif_fusion/), khớp 100% SHA-256) — đạt trọn bộ 4/4 tiêu chí đăng ký trước (`H1–H4 PASS`):**
     - **IEEE 123-bus thụ động (5-fold theo bus, 11,448 sự cố):** `PerNodeGBDT` tăng **98.2% → 99.7%** tổng thể (**87.5% → 98.0%** ở SLG 200–400 Ω, **78.1% → 97.7%** ở 400 Ω, mất 1 cảm biến **89.0% → 90.3%**); `ZoneTreeGNN` tăng **98.0% → 99.5%** (**86.4% → 97.0%** ở SLG 200–400 Ω, **79.6% → 96.0%** ở 400 Ω, mất 1 cảm biến **90.0% → 91.5%**). Trên **IEEE 34-bus thụ động zero-shot** (4,104 sự cố): cả hai giữ nguyên mức trần (`99.8% → 99.8%` GBDT, SLG 200–400 Ω `98.5% → 98.7%`; `99.4% → 99.4%` GNN, SLG 200–400 Ω `95.9% → 97.6%`).
     - **IEEE 123-bus chủ động (0–50% DER, đổi cấu trúc/vòng kín, 17,847 sự kiện):** `ActivePerNodeGBDT` tăng `93.9% → 96.8%` tổng thể (`80.2% → 90.3%` SLG 200–400 Ω, `72.5% → 86.8%` ở 400 Ω, cắt nhầm `NO_FAULT` giảm `13.9% → 3.3%`, mất 1 cảm biến `86.1% → 88.7%`); `ActiveGridGATv2` tăng `95.8% → 97.6%` (**82.2% → 90.8%** SLG 200–400 Ω, **73.5% → 87.5%** ở 400 Ω, cắt nhầm `NO_FAULT` giảm mạnh **`6.5% → 1.2%`** với cả 7 nhiễu nền đều ≤ 6.7%, mất 1 cảm biến `89.1% → 91.3%`).
     - **IEEE 34-bus chủ động zero-shot (24.9 kV, 9,491 sự kiện):** `ActivePerNodeGBDT` tăng `83.8% → 87.5%` tổng thể (`71.8% → 77.8%` trên SLG HIF 1–10 kΩ, cắt nhầm `NO_FAULT` giảm `22.1% → 5.8%`, mất 1 cảm biến `72.4% → 75.6%`); `ActiveGridGATv2` tăng `77.6% → 83.3%` (`65.3% → 70.0%` trên 1–10 kΩ, cắt nhầm giảm `25.3% → 9.7%`, mất 1 cảm biến `71.5% → 74.5%`).
     - **Split Conformal (`aps_rand` 95%, `ActiveGridGATv2`):** trên 123-bus giữ đúng độ phủ **95.0%** (`95.0%` ở 60 Hz) trong khi tỉ lệ tự động 1 nhãn tăng từ `89.2%` lên **93.0%** (đúng **98.9%**, cắt nhầm tự động `NO_FAULT` chỉ **0.5%**). Trên 34-bus chưa thấy, ngưỡng 123-bus tăng `81.4% → 84.9%` (vẫn không có bảo chứng vượt lưới) và hiệu chỉnh 5% số bus đạt trung bình `92.0%` (tệ nhất `85.4%`).
   - **Giả định & yêu cầu phần cứng (trung thực):** cả hai tầng đều là **mô phỏng thuần túy** (dạng sóng hồ quang Emanuel 2 diode và 7 loại nhiễu nền được chồng chập hài giả xác lập theo dòng dư gia số `dI_res` từ OpenDSS; bỏ qua quá độ EMTP, bão hòa lõi CT và phi tuyến ADC ESP32; dòng dư nền trước sự cố cắt trong `[1.0, 20.0] A` RMS theo dải hiệu chuẩn CT). Để triển khai ngoài thực tế **không thể dùng SCADA/RTU 60 Hz cũ** — mỗi recloser/dao cần IED hoặc nút cảm biến cỡ ESP32-S3 lấy mẫu dòng dư **≥ 15.36 kHz** sau mạch lọc chống chồng phổ ~2 kHz. Ngoài ra, dự án đồng hành `hif-sensor` đã chỉ ra khoảng cách miền đáng kể khi đưa mô hình đóng băng sang bản ghi hồ quang thực vật 22 kV thật mà không huấn luyện lại, nên kết quả mô phỏng chưa chứng minh hiệu năng lưới thật.

### Câu thầy có thể hỏi về lưới IEEE 37-bus và mục 2d HIF-Fusion

- **"Kết quả zero-shot trên IEEE 37-bus bị `P1-Fail` (56.4% / 46.7%), vậy mở rộng này có làm yếu bài báo không?"** Ngược lại, nó củng cố tính trung thực khoa học: cặp 123-bus → 34-bus dễ tạo ảo giác rằng mô hình tổng quát hóa vô điều kiện, vì cả hai đều là lưới 4 dây nối đất trên không. Thử thêm lưới cáp ngầm 3 dây delta không nối đất chỉ rõ **biên giới vật lý** nơi zero-shot vẫn giữ nguyên hiệu năng (sự cố pha `3PH/LL/LLG`: 100.0% / 99.7%, Stage-2 top-3 94.4% / 95.2%) và nơi zero-shot gãy do đổi chế độ nối đất (SLG điện dung 2.23–2.36 A + dịch trung tính `√3` pu), đồng thời chứng minh in-domain CV vẫn đạt 91.4% / 88.0% trên cùng bộ 21 đặc trưng. Toàn bộ vẫn là mô phỏng OpenDSS thuần túy, chưa phải dữ liệu thực địa.
- **"Ghép Edge HIF-Sensor ở mục 2d có phá hỏng kết quả 60 Hz cũ hay đòi hỏi thay toàn bộ hệ thống không?"** Không làm đổi bất kỳ file kết quả nào của mục 2a–2c (toàn bộ đầu ra tách riêng ở `results/hif_fusion/`). Về phần cứng, nút cảm biến chỉ truyền thêm 2 số vô hướng `(p_hif, hif_alarm)` lên bộ điều phối FLISR nên không tốn băng thông SCADA, nhưng **tại mỗi dao/recloser bắt buộc phải có IED hoặc vi điều khiển cỡ ESP32-S3 lấy mẫu ≥ 15.36 kHz** sau mạch lọc chống chồng phổ ~2 kHz — thiết bị SCADA 60 Hz cũ không cung cấp được đặc trưng sóng hài bậc cao. Dạng sóng hồ quang Emanuel và 7 tải nền vẫn là mô phỏng thuần túy, chưa phải kiểm chứng ngoài lưới thật.

---

## 11. Cách tái tạo & tự kiểm chứng

| Lệnh | Làm gì | Thời gian |
|---|---|---|
| `.venv\Scripts\python -m shf.provenance` | Kiểm tra mã băm SHA-256 của toàn bộ 23 manifest / 51 file kết quả (0 changed, 0 missing, 0 unrecorded) | < 1 s |
| `.venv\Scripts\python harness\check.py --tests` | Kiểm tra sức khỏe dự án (khớp 100% `harness/facts.toml`, liên kết, bảo mật khóa bí mật, provenance) + toàn bộ bộ `pytest` | khoảng 1 s + pytest |
| `.venv\Scripts\python run.py` | Chạy lại toàn bộ nghiên cứu chính, ghi `results/` và dựng trang báo cáo | `runtime_s` lần chạy gần nhất: 269.3 s |
| `.venv\Scripts\python scripts\error_analysis.py` | Phân tích lỗi → `results/error_analysis/` | khoảng 1 phút |

Để **tự kiểm chứng độc lập** các kết quả đã công bố, chỉ cần 2 lệnh đầu tiên (`python -m shf.provenance` và `python harness/check.py --tests`). Nếu muốn chạy lại nghiên cứu chính từ đầu, thứ tự bắt buộc là `run.py` trước rồi `error_analysis.py` (đọc dataset và `metrics.json`).

**Harness:** [`harness/facts.toml`](../../harness/facts.toml) liệt kê mỗi con số chính trong văn bản, kèm biểu
thức tính nó từ `results/`. [`harness/check.py`](../../harness/check.py) tính lại và báo lỗi nếu văn bản không
còn khớp với lần chạy mới nhất. Tài liệu này được gắn vào các fact đó, nên nếu chạy lại mà số thay đổi, check sẽ
chỉ ra dòng cần sửa. Chi tiết: [harness-guide.md](harness-guide.md).

Mọi kết quả là tất định (seed cố định `seed=0`), nên chạy lại trên cùng phiên bản thư viện cho cùng số.

### Câu thầy có thể hỏi

- **"Tôi chạy lại có ra đúng số không?"** Có, với cùng phiên bản OpenDSSDirect.py và scikit-learn (seed cố định).
  Phiên bản thư viện khác có thể làm số lệch ở chữ số cuối.

---

## 12. Tài liệu tham khảo

Theo README "References":

- IEEE PES Distribution Test Feeders: https://cmte.ieee.org/pes-testfeeders/resources/
- OpenDSS (EPRI) và file mô hình IEEE 123 nút, 34 nút, 37 nút: https://sourceforge.net/projects/electricdss/ (bản sao IEEE 37 nút: https://github.com/dss-extensions/electricdss-tst/tree/master/Version8/Distrib/IEEETestCases/37Bus)
- W. H. Kersting, "Radial distribution test feeders," *IEEE Trans. Power Systems*, vol. 6, no. 3, pp. 975–985, 1991: https://doi.org/10.1109/59.119237
- J. Glass, A. Melin, M. Starke, B. Ollis, *Chattanooga Electric Power Board Case Study: Distribution
  Automation*, ORNL/LTR-2015/444, 2016: https://www.osti.gov/biblio/1329733
- K. Chen et al., "Fault Location in Power Distribution Systems via Deep Graph Convolutional Networks," IEEE
  JSAC, 2019: https://arxiv.org/abs/1812.09464
- S. Brody, U. Alon, E. Yahav, "How Attentive are Graph Attention Networks?" (GATv2), *ICLR*, 2022:
  https://arxiv.org/abs/2105.14491
- T. Takagi et al., "Development of a New Type Fault Locator Using the One-Terminal Voltage and Current Data,"
  *IEEE Trans. PAS*, vol. PAS-101, no. 8, pp. 2892–2898, 1982: https://doi.org/10.1109/TPAS.1982.317615
- Y. Romano, M. Sesia, E. Candès, "Classification with Valid and Adaptive Coverage," *NeurIPS*, 2020:
  https://arxiv.org/abs/2006.02544
- ANSI C84.1, Range A điện áp phục vụ 114–126 V (0.95–1.05 pu trên nền 120 V).
- A. E. Emanuel et al., "High impedance fault arcing on sandy soil in 15 kV distribution feeders," *IEEE Trans.
  Power Delivery*, vol. 5, no. 2, pp. 676–686, 1990 (mô hình hồ quang 2 diode): https://doi.org/10.1109/61.53070
- A. Ghaderi, H. L. Ginn, H. A. Mohammadpour, "High impedance fault detection: A review," *Electric Power
  Systems Research*, vol. 143, pp. 376–388, 2017: https://doi.org/10.1016/j.epsr.2016.10.021
- R. P. Sallen & E. L. Key, "A Practical Method of Designing RC Active Filters," *IRE Trans. Circuit Theory*,
  vol. CT-2, no. 1, pp. 74–85, 1955 (mạch lọc chống chồng phổ Butterworth bậc 4 Sallen-Key):
  https://doi.org/10.1109/TCT.1955.6500159

---

## Bảng tóm tắt một trang: khẳng định → bằng chứng → lưu ý

Cột "Khẳng định" trích câu chữ của README (tiếng Anh) để khớp với harness.

| Khẳng định (README) | Bằng chứng | Lưu ý |
|---|---|---|
| 11,448 simulated faults, 10 zones | `metrics.json → dataset`, `base_case.zones` | 5 trong 10 dao là giả định |
| FPI 56.1%, ML magnitudes 87.5%, ML full 97.7% | `metrics.json → fault_location.*.accuracy` | Mô phỏng; nút chưa thấy nhưng nút kề đã thấy |
| SLG 100 Ω: 8.4% / 70.8% / 98.4% | `slg_by_resistance['100.0']` | Điện trở tuyến tính |
| SLG 400 Ω: 1.0% / 22.4% / 76.5% | `slg_by_resistance['400.0']` | Giới hạn trên; sự cố thật có hồ quang |
| FPI on bolted ground faults "(30% correct)" | `fpi_baseline.slg_by_resistance['0.01']` | Baseline không có phần tử có hướng |
| No flag on 25.8% of faults | `fpi_baseline.no_device_flagged` | `error_analysis.json` cho 25.66% (xem dưới) |
| One device offline: 83–96% | `ml_full.missing_sensor_accuracy` | Tệ nhất khi mất Sw4 |
| Patrol 39.0 kft → 5.1 kft (−87%) | `metrics.json → patrol_kft` | Đoán sai bị phạt cả xuất tuyến |
| all 259 errors (2.3%) | `error_analysis.json → ml_errors` | |
| 237 (92%) are at 200 Ω or more | `ml_errors_slg_200_ohm_or_more` | |
| 6.3% at 200 Ω, 23.5% at 400 Ω | `ml_slg_error_rate_by_resistance` | |
| 0.9% in the lightest vs 4.1% in the heaviest third | `ml_error_rate_by_load_tercile` | Ủng hộ cơ chế tín hiệu/nhiễu |
| Sw2→Sw1 (41), Sw1→Sw2 (24), L13→Sw1 (23) | `ml_top_confusions` | Lỗi quanh vùng đầu nguồn |
| Defer below 0.95: 2.8% of faults, accuracy to 99.1%, errors to 97 | `defer_low_confidence` | Xác suất chưa hiệu chỉnh |
| Algorithm rejected 22 candidate pickups | `restoration.csv → power_flow_rejected` | Giá trị điện áp từng lần thử không lưu trong `results/` |
| 2,670 kW of the 7,175 kW restored by ties | `metrics.json → restoration` | 7,175 là tổng 10 trường hợp |
| kW-minutes fell by 51% | `kWmin_reduction_pct_weighted_by_line_length` | Phụ thuộc trực tiếp vào thời gian giả định |
| Voltage, not ampacity, is binding | README; tái tạo bằng `plan_restoration()` | Không có cột riêng trong `results/` |

---

## Từ vựng

| Thuật ngữ | Nghĩa |
|---|---|
| Feeder (xuất tuyến) | Đường dây trung áp từ trạm ra một khu vực |
| Recloser (máy cắt tự đóng lại) | Cắt khi sự cố, thử đóng lại; khóa nếu sự cố còn |
| Lockout (khóa) | Recloser dừng thử đóng lại, xuất tuyến mất điện |
| Sectionalizer / switch (dao phân đoạn) | Dao thường đóng chia lưới thành vùng |
| Tie switch (dao liên lạc) | Dao thường mở, nối sang nguồn khác để khôi phục |
| Zone (vùng) | Phần lưới giữa các dao |
| Radial (hình tia) | Không mạch vòng; mỗi vùng có đúng một vùng cha |
| FLISR | Fault Location, Isolation and Service Restoration: định vị, cô lập, khôi phục |
| FPI | Fault passage indicator: chỉ báo dòng sự cố đi qua |
| SLG / LL / LLG / 3PH | 1 pha chạm đất / 2 pha chạm nhau / 2 pha chạm đất / 3 pha |
| High-impedance fault (sự cố trở kháng cao) | Sự cố có dòng nhỏ, khó phát hiện |
| Pickup (ngưỡng tác động) | Dòng mà thiết bị bắt đầu bật cờ |
| Residual current, 3·I0 (dòng dư) | Tổng dòng ba pha, khác 0 khi có dòng về đất hoặc tải lệch |
| I0, I2 | Thành phần thứ tự không, thứ tự nghịch |
| Incremental / superimposed (gia số) | Hiệu số sau sự cố − trước sự cố |
| Event record (bản ghi sự kiện) | Dạng sóng/phasor thiết bị lưu quanh thời điểm sự cố |
| Voltage regulator, tap (bộ điều áp, nấc) | Máy biến áp tự chuyển nấc giữ điện áp |
| LDC, line-drop compensation | Bù sụt áp: nâng điện áp đầu nguồn theo dòng |
| pu (per-unit) | Giá trị chia cho giá trị cơ sở |
| Power flow (giải tích trào lưu công suất) | Tính điện áp, dòng ở trạng thái xác lập |
| Ampacity, emergency rating | Dòng định mức, định mức khẩn cấp |
| Gradient boosting | Ghép nhiều cây quyết định, cây sau sửa sai cây trước |
| Cross-validation, GroupKFold | Kiểm định chéo; chia theo nhóm (ở đây theo nút) |
| Data leakage (rò rỉ dữ liệu) | Thông tin tập kiểm tra lọt vào huấn luyện |
| Out-of-fold | Dự đoán bởi mô hình chưa thấy dòng đó |
| FNR / FPR / Precision | Tỉ lệ bỏ sót / tỉ lệ đổ oan / độ chính xác khi đoán một vùng |
| Confusion matrix (ma trận nhầm lẫn) | Hàng = vùng thật, cột = vùng đoán |
| Coverage | Tỉ lệ sự cố được mô hình trả lời (không chuyển thủ công) |
| Greedy (tham lam) | Chọn phương án tốt nhất ở mỗi bước, không nhìn trước |
| kW-minutes (kW·phút) | Tải mất điện × thời gian mất điện |
