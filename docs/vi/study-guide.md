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
thử. README nói phần lớn bị loại do **điện áp thấp** (thấp nhất khoảng 0.85 pu), 2 phương án do **điện áp cao**
(1.053 và 1.056 pu), và **không phương án nào** bị loại do quá tải. Các giá trị trong từng lần thử không được
ghi ra `results/` (chỉ có số đếm); chúng đã được tái tạo bằng cách gọi lại `plan_restoration()` trong một script
tạm: vmin thấp nhất 0.8478 pu, hai trường hợp quá áp là 1.0526 (sự cố Sw3, nhận L45 qua Sw7) và 1.056 (sự cố
L13, nhận L45 + Sw3 qua Sw7), và 0 quá tải ở cả 30 lần thử.

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

**Độ nhạy theo giả định thời gian** (tính lại bằng cùng công thức, chỉ thay thời gian; không phải kết quả
trong `results/`):

| T_auto / T_manual / T_repair (phút) | Giảm trung bình theo chiều dài |
|---|---|
| 1 / 90 / 240 (giả định của dự án) | 50.7% |
| 1 / 60 / 240 | 44.4% |
| 1 / 45 / 240 | 39.5% |
| 1 / 90 / 120 | 59.4% |
| 5 / 90 / 240 | 48.4% |

Con số này **phụ thuộc trực tiếp** vào thời gian giả định. Nó minh họa cơ chế, không phải dự báo.

### Câu thầy có thể hỏi

- **"kW·phút giảm 51%, con số đó có ý nghĩa thật không?"** Nó là hệ quả số học của ba thời gian giả định và
  của kết quả khôi phục. Thay T_manual từ 90 xuống 45 phút thì còn 39.5%. Thứ dự án thực sự chứng minh là
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

## 11. Cách tái tạo

| Lệnh | Làm gì | Thời gian |
|---|---|---|
| `.venv\Scripts\python run.py` | Toàn bộ nghiên cứu, ghi `results/` và trang báo cáo | `runtime_s` lần chạy gần nhất: 269.3 s |
| `.venv\Scripts\python scripts\error_analysis.py` | Phân tích lỗi → `results/error_analysis/` | khoảng 1 phút |
| `.venv\Scripts\python -m pytest` | 17 bài kiểm tra (15 trong `tests/test_shf.py`, 2 trong `tests/test_harness.py`) | |
| `.venv\Scripts\python harness\check.py --tests` | Kiểm tra sức khỏe dự án + pytest | khoảng 1 s + pytest |

Thứ tự bắt buộc: `run.py` trước, rồi `error_analysis.py` (nó đọc dataset và `metrics.json`).

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
- OpenDSS (EPRI) và file mô hình IEEE 123 nút: https://sourceforge.net/projects/electricdss/
- J. Glass, A. Melin, M. Starke, B. Ollis, *Chattanooga Electric Power Board Case Study: Distribution
  Automation*, ORNL/LTR-2015/444, 2016: https://www.osti.gov/biblio/1329733
- K. Chen et al., "Fault Location in Power Distribution Systems via Deep Graph Convolutional Networks," IEEE
  JSAC, 2019: https://arxiv.org/abs/1812.09464
- ANSI C84.1, Range A điện áp phục vụ 114–126 V (0.95–1.05 pu trên nền 120 V).

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
