# Hướng dẫn hiểu dự án Self-Healing Feeder (để tự giải thích khi phỏng vấn)

Tài liệu này giải thích **từng phần của dự án bằng tiếng Việt**, theo đúng thứ tự code chạy. Mục tiêu: bạn đọc xong có thể tự trả lời mọi câu hỏi "tại sao" của người phỏng vấn. Mỗi phần có mục **"Câu hỏi có thể bị hỏi"** ở cuối.

> Dự án được xây dựng với sự hỗ trợ của AI (Claude Code). Hãy ghi đúng như vậy trong resume. Trước khi đưa vào resume, bạn nên tự chạy lại toàn bộ, đọc từng file trong `shf/`, và thử sửa một tham số để thấy kết quả thay đổi.

---

## 0. Chạy dự án & tự kiểm chứng

Để **tự kiểm chứng độc lập** toàn bộ kết quả đã công bố (23 manifest SHA-256 / 51 file kết quả Tầng 2, **23** file Tầng 1 `hif_sensor/`, mọi con số trong `harness/facts.toml`, liên kết, quy tắc bảo mật và toàn bộ **154** bài unit test + **235** bước kiểm tra):

```bash
.venv\Scripts\python -m shf.provenance          # kiểm tra 23 manifest / 51 file kết quả Tầng 2 (0 changed, 0 missing, 0 unrecorded)
.venv\Scripts\python harness/check.py --tests   # 235 kiểm tra sức khỏe dự án + 144 bài pytest Tầng 2
pushd hif_sensor && ..\.venv\Scripts\python -m hif.provenance --verify && ..\.venv\Scripts\python -m pytest -v tests/test_hif.py && popd  # kiểm tra 23 file SHA-256 + 10 bài pytest Tầng 1
```

Để cài đặt và chạy lại nghiên cứu chính từ đầu:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run.py          # chạy toàn bộ, ghi dataset vào data/generated/, model vào models/, kết quả vào results/
.venv\Scripts\python -m pytest       # chạy 144 bài kiểm thử tự động Tầng 2
.venv\Scripts\python scripts/demo_event.py --bus 60 --type SLG --r 50   # phát lại một sự cố
```

### 0b. Chứng thực SHA-256, 6 kế hoạch tiền đăng ký, bảng PASS/FAIL trung thực & Bảo mật

> **Toàn bộ mô hình lưới là mô phỏng** (OpenDSS, LTspice và Python — không có dữ liệu đo thực địa ngoài lưới, không triển khai ngoài thực tế, không có kết nối SCADA trực tiếp; riêng dự án con Tầng 1 `hif_sensor/` đánh giá thêm bản ghi sự cố thực vật VeHIF 22 kV thật đi qua mạch cảm biến và tải mô phỏng). Tất cả 52 file JSON/CSV kết quả Tầng 2 có thể tải trực tiếp từ [`docs/data/`](../../docs/data/).

- **Chứng thực mật mã ([`results/provenance/`](../../results/provenance/), [`shf/provenance.py`](../../shf/provenance.py)):** Tầng 2 có **23** file manifest ghi nhận **51** file kết quả với **0 changed / 0 missing / 0 unrecorded**; Tầng 1 có [`hif_sensor/results/provenance/manifest.json`](../../hif_sensor/results/provenance/manifest.json) ghi nhận **23** file (mạch LTspice, JSON/CSV, header C, trọng số `int8` và 12 hình) với **0 changed / 0 missing**. Mô hình Tầng 1 Edge HIF-Sensor đóng băng `model_int8.npz` (`417` tham số, `504` byte, kernel Kaggle `christoopherchau/ch-y-n`) có SHA-256 `3ba5bd23685d7964a6cea0c94064c1e65a8bf3129d83ac129215d110218397c1`, bên cạnh bản tinh chỉnh Phase 1.5 [`hif_sensor/results/model_phase15_int8.npz`](../../hif_sensor/results/model_phase15_int8.npz) (`504` byte, ngưỡng `0.924894`).
- **Toàn bộ 6 kế hoạch tiền đăng ký (khóa tiêu chí trước khi chạy):**
  1. [`research/gnn-transfer/PLAN.md`](../../research/gnn-transfer/PLAN.md) (chuyển giao thụ động 123 → 34-bus & Stage 2 tìm bus)
  2. [`research/active-grid-gnn/PLAN.md`](../../research/active-grid-gnn/PLAN.md) (lưới chủ động DER/vòng kín + Split Conformal)
  3. [`research/ieee37-underground/PLAN.md`](../../research/ieee37-underground/PLAN.md) (cáp ngầm đô thị 4.8 kV 3 dây delta IEEE 37-bus)
  4. [`research/multi-feeder-benchmark/PLAN.md`](../../research/multi-feeder-benchmark/PLAN.md) (kiểm chứng đa lưới 15 xuất tuyến OpenDSS)
  5. [`research/hif-fusion/PLAN.md`](../../research/hif-fusion/PLAN.md) (kiến trúc 2 tầng Edge HIF-Sensor → Graph FLISR)
  6. [`research/realistic-hif-sim/PLAN.md`](../../research/realistic-hif-sim/PLAN.md) (nâng cấp mô phỏng lõi thực tế: hồ quang HIF chập chờn `SLG ≥ 100 Ω`, tải độc lập theo zone + trôi tải pre/post, sai số hệ thống CT/PT + sàn nhiễu)
- **Tóm tắt trung thực PASS vs. FAIL / giới hạn:**
  - **Đạt tiêu chí (mô phỏng):** FLISR chính 123-bus (ML **91.5%** vs FPI **52.5%**, ML chỉ độ lớn **80.2%**, SLG 100 Ω **84.8%**, SLG 400 Ω **31.3%** dưới hồ quang HIF chập chờn + trôi tải + bias/sàn nhiễu CT/PT; tuần tra **39.0 → 7.3 kft** / −81%; tie khôi phục **2,670 / 7,175 kW**, giảm kW·phút **51%**); khôi phục theo giờ PJM AEP 2017 (**44.0%** / **42.1%** 6h vs **37.2%** tải đỉnh); chuyển giao thụ động 123 → 34-bus (**99.8%** GBDT / **99.3%** GNN); kiểm chứng đa lưới (**10/11** lưới chưa thấy gồm EU-LV 50 Hz **93.3%**, IEEE 8500 **99.8%**, EPRI Ckt24 34.5 kV **99.7%**, mất 1 cảm biến EPRI Ckt7 GNN **94.3%** > GBDT **90.5%**); 2 tầng Edge HIF-Sensor → Graph FLISR đạt **4/4 `H1–H4` PASS** (SLG 400 Ω 123-bus `78.1% → 97.7%` GBDT, FPR 123-bus `6.5% → 1.2%` GATv2, FPR zero-shot 34-bus `22.1% → 5.8%` GBDT).
  - **Ca thất bại & giới hạn công khai trung thực:** (a) **FAIL `P1-Fail`** trên cáp ngầm 3 dây delta không nối đất IEEE 37-bus: zero-shot GBDT **56.4%** / GNN **46.7%** (SLG sụp còn **22.4% / 5.6%** do dòng SLG điện dung chỉ `2.36 A` / `0.64%` + dịch trung tính `√3` pu; active `A2-Partial` / GBDT `A2-Fail`); (b) **FAIL** `BusGraphGNN` thua công thức vật lý Takagi ở Stage 2 (**17.8%/38.5%** vs **46.9%/69.0%** trên 123-bus); (c) **FAIL** Split Conformal không tự giữ độ phủ khi chuyển lưới (`aps_det` bão hòa `6.37` nhãn; `aps_rand` 95% giữ ngưỡng 123-bus chỉ phủ **81.4% / 91.1%** trên 34-bus và **47.4% / 81.1%** trên 37-bus); (d) **3 lưới ngoài phạm vi:** IEEE 342-Node (71 vòng kín), IEEE 9500-Node (không hội tụ cơ sở), CIGRE MV (không có file gốc); (e) **Khoảng cách miền hồ quang thật VeHIF & kết quả Phase 1.5:** mô hình Tầng 1 độc lập giảm **94.7% → 56.0%** khi chạy trực tiếp trên bản ghi hồ quang thực vật 22 kV thật mà không huấn luyện lại (trích từ [`research/hif-fusion/PLAN.md`](../../research/hif-fusion/PLAN.md)); ở Phase 1.5 ([`hif_sensor/results/phase15_vehif.json`](../../hif_sensor/results/phase15_vehif.json)), fine-tune `joint_mlp_int8` với 20% dữ liệu VeHIF nâng độ phát hiện tổng thể **53.30% → 60.22%** và dải `0–2 A` thêm **`+7.41 pp`** (**42.52% → 49.93%**), giữ báo nhầm nền thật **1.82%**, đối chứng **0.67%** và mô phỏng **93.84%** (**PASS `P1.5-B/C/D`**), nhưng **FAIL `P1.5-A`** vì chưa đạt ngưỡng `+15 pp`; đồng thời triển khai thực tế đòi hỏi nút cảm biến lấy mẫu **≥ 15.36 kHz** (60 Hz) hoặc **≥ 12.8 kHz** (50 Hz) chứ không dùng được SCADA 60 Hz cũ.
- **Bảo mật & vệ sinh kho Git:** chỉ công khai mã nguồn, kết quả mô phỏng đã băm SHA-256, kế hoạch tiền đăng ký và bản vẽ; [`.gitignore`](../../.gitignore), `.git/info/exclude` và [`harness/check.py`](../../harness/check.py) giữ ngoài Git mọi khóa API/token (`.env`, `.env.*`, `.kaggle/`, `kaggle.json`; hiện dùng **0** API bên ngoài — [`config/apis.md`](../../config/apis.md)), tệp nội bộ (`ops/`, `CLAUDE.local.md`, `HANDOFF.md`, `inputs/private/`), dữ liệu sinh ra (`data/generated/`), trọng số (`models/`) và dữ liệu thô bên thứ ba (`data/external/`). Trang GitHub Pages `docs/` thuần tĩnh, không backend, không tracking, không nhúng API key.

---

## 1. Lưới điện: IEEE 123-bus trong OpenDSS (`shf/feeder.py`)

- **IEEE 123-bus test feeder** là lưới phân phối mẫu do IEEE PES công bố để mọi người thử thuật toán trên cùng một lưới. Lưới chạy ở 4,16 kV, có 3.490 kW tải, các nhánh 1 pha, 2 pha, 3 pha, 4 bộ điều áp và tụ bù.
- **OpenDSS** là phần mềm mô phỏng lưới phân phối của EPRI. Mình điều khiển nó từ Python bằng thư viện `OpenDSSDirect.py`.
- **Lưới không cân bằng:** tải trên 3 pha khác nhau, nên dòng 3 pha khác nhau và có dòng thứ tự không (dòng dư) ngay cả khi không có sự cố. Chi tiết này quan trọng ở phần 4.
- **Kiểm tra mô hình chạy đúng:** công suất nguồn khoảng 3.615 kW và tổn thất khoảng 96 kW, khớp với kết quả tham chiếu của OpenDSS cho lưới này.

**Những gì mình tự thêm vào (đều ghi là ASSUMPTION trong `shf/config.py`):**
- **5 dao tự động** (A1–A5) đặt ở đầu các đoạn dây L13, L45, L61, L68, L77, để chia lưới thành 10 vùng.
- **Dao liên lạc Sw9** nối nút 450 sang một **xuất tuyến bên cạnh**. Xuất tuyến này được mô hình là nguồn 4,16 kV đặt ở 1,03 pu, phía sau 4.000 ft dây ACSR 336.
- **Dòng định mức dây dẫn:** ACSR 336,400 khoảng 530 A, ACSR 1/0 khoảng 230 A, cáp ngầm 1/0 AA khoảng 200 A, dao cắt 600 A. Định mức khẩn cấp lấy bằng 125% định mức thường.

**Câu hỏi có thể bị hỏi**
- *Vì sao dùng lưới mẫu IEEE mà không dùng lưới thật?* Vì dữ liệu lưới thật của điện lực là thông tin nhạy cảm (liên quan an ninh hạ tầng). Lưới mẫu IEEE cho phép người khác chạy lại và kiểm chứng kết quả.
- *Giới hạn của mô hình?* Nguồn được coi là rất cứng (trở kháng gần 0), nên dòng sự cố chạm trực tiếp lớn hơn thực tế. Nghiên cứu chính là mô phỏng miền phasor 60 Hz trong OpenDSS (chưa mô phỏng quá độ điện từ EMTP hay bão hòa lõi CT); hồ quang HIF `SLG ≥ 100 Ω` được quy đổi sang trở kháng tương đương 60 Hz chập chờn, còn điện mặt trời áp mái và vòng kín được tách sang nhánh Active-Grid ở mục 5b.

---

## 2. Vùng (zone) và cây vùng (`shf/topology.py`)

- **Vùng** = phần lưới nằm giữa các dao cắt. Nếu mở hết các dao, mỗi mảnh lưới còn liền nhau là một vùng. Mỗi vùng được đặt tên theo dao cấp điện cho nó; ví dụ vùng `Sw3` là mọi thứ phía sau dao Sw3, cho đến dao kế tiếp.
- Code dựng một **đồ thị** (thư viện networkx): nút của đồ thị là các nút điện, cạnh là đường dây và máy biến áp. Bỏ các cạnh là dao cắt đi, các mảnh liên thông còn lại chính là các vùng.
- **Cây vùng:** ở cấu hình bình thường lưới là **hình tia**, tức điện chỉ đi một chiều từ trạm ra. Vì vậy mỗi vùng có đúng một vùng "cha" ở phía nguồn.
- **Hình tia (radial):** không được đóng dao liên lạc khi lưới đang bình thường, vì sẽ tạo mạch vòng. Hàm `closed_graph_has_loop()` kiểm tra điều này, và có test tự động cho nó.

**Câu hỏi có thể bị hỏi**
- *Vì sao lưới phân phối vận hành hình tia?* Vì bảo vệ (recloser, cầu chì) được phối hợp với giả định dòng sự cố đi một chiều. Lưới hình tia cũng đơn giản và rẻ hơn.

---

## 3. Mô phỏng sự cố (`shf/faults.py`)

**Các loại sự cố được mô phỏng:**
- **SLG** (1 pha chạm đất): phổ biến nhất, ví dụ cành cây chạm dây.
- **LL** (2 pha chạm nhau).
- **LLG** (2 pha chạm đất).
- **3PH** (3 pha).

**Điện trở sự cố & hồ quang HIF (`SLG ≥ 100 Ω`, [`research/realistic-hif-sim/PLAN.md`](../../research/realistic-hif-sim/PLAN.md)):** từ 0,01 Ω (chạm trực tiếp) đến 400 Ω (sự cố **trở kháng cao**, ví dụ dây đứt rơi xuống đất khô). Với sự cố chạm đất `SLG ≥ 100 Ω` (`HIF_ARC_MIN_R = 100.0`), code quy đổi sang điện trở tương đương 60 Hz `R_eff` kết hợp hàm mô tả hồ quang 2 diode Emanuel (`Vp/Vpk ∈ [0.15, 0.45]`, bất đối xứng `Vn/Vp ∈ [1.00, 1.20]`, `Vn/Vpk ≤ 0.55`), xác suất chập chờn `45%` (`d_cond ∈ [0.35, 0.85]`) và dao động log-normal (`σ = 0.25`, kẹp `[0.60, 1.80]`, trần `R_eff ≤ 2,500 Ω`; trung vị `R_eff` đạt `204.9 / 407.8 / 841.6 Ω` ứng với danh định `100 / 200 / 400 Ω`). Sự cố trở kháng cao rất khó phát hiện vì dòng 60 Hz bị suy giảm mạnh và chìm trong nền nhiễu/trôi tải.

**Mỗi sự cố được mô phỏng 2 lần giải lưới:**
1. **Trước sự cố:** các bộ điều áp được tự do chuyển nấc.
2. **Trong sự cố:** **khóa nấc** bộ điều áp, vì bảo vệ tác động trong vài chu kỳ, còn bộ điều áp phải mất hàng chục giây mới chuyển nấc; đồng thời phụ tải có **trôi tải tự nhiên** nhẹ giữa ảnh `pre` và `post` (`0,8%` theo zone `LOAD_DRIFT_ZONE` + `1,5%` theo điểm `LOAD_DRIFT_SPOT`, kẹp `[0.90, 1.10]`).

**Phụ tải ngẫu nhiên phân cấp 3 tầng.** Mỗi trường hợp lấy hệ số tải toàn lưới đều trong `0,3–1,1`, nhân hệ số tải độc lập theo từng zone `N(1, 0,30)` kẹp `[0,45, 1,65]` (`ZONE_LOAD_SPREAD`), và từng điểm tải `N(1, 0,20)` kẹp `[0,30, 1,70]` (tích kẹp `[0,25, 2,00]`).
- Lý do: bản đầu tiên chỉ dùng 3 mức tải cố định, và mô hình đạt 99,9% ngay cả khi chỉ dùng độ lớn dòng/áp. Đó là dấu hiệu **rò rỉ dữ liệu (data leakage)**: với quá ít trạng thái tải, mô hình học thuộc được dòng điện "bình thường" là bao nhiêu.
- **Câu chuyện này rất đáng kể khi phỏng vấn.** Nó cho thấy bạn nghi ngờ một kết quả quá đẹp và đi tìm nguyên nhân.

**Nhiễu đo thực tế CT/PT:** gồm 3 lớp — (1) sai số hệ thống từng kênh CT (`1,5%` độ lớn, `0,8°` pha; kẹp `±4,5% / ±2,5°`) và PT (`0,8%`, `0,4°`; kẹp `±2,5% / ±1,5°`) giữ cố định giữa ảnh `pre` và `post` trong cùng một sự cố (lấy mẫu mới giữa các sự cố), (2) nhiễu ngẫu nhiên độc lập `1%` độ lớn và `0,5°` góc pha, và (3) sàn nhiễu cộng tính `0,5 A RMS` (`NOISE_I_FLOOR_A`) và `0,001 pu` (`NOISE_V_FLOOR_PU`) trên các pha có điện.

**Mỗi thiết bị đo (đặc trưng cho ML):**
- Độ lớn dòng 3 pha `Ia, Ib, Ic` và điện áp 3 pha `Va, Vb, Vc`.
- **Đại lượng gia số (incremental / superimposed):** `dIa = |Ia(sự cố) − Ia(trước sự cố)|`, tính bằng số phức. Đây chính là phần dòng do sự cố "thêm vào". Recloser hiện đại lưu bản ghi sự kiện có cả vài chu kỳ trước sự cố, nên thiết bị tự tính được đại lượng này mà không cần đồng bộ thời gian.
- **Thành phần thứ tự:** `I0` (thứ tự không, gần với dòng chạm đất) và `I2` (thứ tự nghịch, phản ánh mất cân bằng).

**Câu hỏi có thể bị hỏi**
- *Vì sao phải khóa nấc bộ điều áp khi mô phỏng sự cố?* Đã giải thích ở trên: bảo vệ nhanh hơn bộ điều áp rất nhiều.
- *Sự cố trở kháng cao ngoài đời có giống mô phỏng không?* Gần hơn bản điện trở tuyến tính cũ nhưng vẫn chưa giống hoàn toàn. Mô hình quy đổi hồ quang Emanuel + chu kỳ chập chờn sang `R_eff` 60 Hz nắm bắt được sự suy giảm biên độ cơ bản và phân tán dòng sự cố, nhưng **vẫn là mô phỏng phasor 60 Hz trong OpenDSS** — chưa mô phỏng quá độ EMTP, bão hòa lõi CT hay sóng hài bậc cao theo thời gian thực (phần sóng hài được tách sang cảm biến biên 15.36 kHz ở mục 5c–5d, và khoảng cách miền với bản ghi 22 kV VeHIF thật vẫn tồn tại).

---

## 4. Phương pháp cổ điển: chỉ báo dòng sự cố, FPI (`shf/baseline.py`)

**Cách hoạt động:**
- Mỗi thiết bị "bật cờ" khi dòng pha vượt **ngưỡng pha**, hoặc dòng dư `3·I0` vượt **ngưỡng chạm đất**.
- Ngưỡng pha = 2 lần dòng pha lớn nhất lúc tải đỉnh. Ngưỡng chạm đất = 0,5 lần dòng pha lúc tải đỉnh, nhưng không thấp hơn 1,2 lần dòng dư tự nhiên do tải không cân bằng.
- Vùng sự cố = vùng nằm ngay sau **thiết bị bật cờ sâu nhất**.

**Vì sao FPI sai nhiều (xem `results/metrics.json`):**
1. **Sự cố trở kháng cao:** dòng sự cố nhỏ hơn ngưỡng, nên không thiết bị nào bật cờ.
2. **Sự cố chạm đất trực tiếp lại sai nhiều hơn sự cố 5 Ω**, nghe có vẻ ngược. Lý do: khi một pha chạm đất cứng, điện áp pha đó gần như về 0, nên tải 1 pha nối vào pha đó ở **phía sau** điểm sự cố mất tải. Dòng 3 pha phía sau trở nên rất lệch, sinh ra dòng dư lớn, và thiết bị phía sau bật cờ chạm đất **nhầm**. Thuật toán chọn thiết bị sâu nhất nên đoán vùng nằm sau vùng sự cố thật.
- Ngoài đời, người ta xử lý hiện tượng thứ hai bằng **chức năng có hướng (directional)** hoặc trễ thời gian. Đây là điểm hay để nói khi phỏng vấn.

---

## 5. Mô hình ML (`shf/model.py`)

- **Thuật toán:** HistGradientBoosting của scikit-learn (cây quyết định tăng cường). Nhanh, tự xử lý được giá trị thiếu (NaN), không cần chuẩn hóa dữ liệu.
- **Kiểm định chéo theo nút (GroupKFold):** mô hình luôn được kiểm tra trên những nút **chưa từng thấy** khi huấn luyện. Nếu chia ngẫu nhiên theo dòng dữ liệu, cùng một nút với điện trở khác nhau sẽ lọt vào cả tập huấn luyện lẫn tập kiểm tra, làm độ chính xác bị thổi phồng.
- **So sánh hai bộ đặc trưng:**
  - *magnitude*: chỉ độ lớn tức thời, giống SCADA cơ bản.
  - *full*: thêm đại lượng gia số và thay đổi điện áp.
  - Kết quả cho thấy **khả năng đo của thiết bị quan trọng ngang thuật toán**.
- **Mất cảm biến:** khi huấn luyện, 15% số mẫu bị xóa ngẫu nhiên dữ liệu của một thiết bị, để mô hình học cách xử lý khi một thiết bị mất liên lạc. Khi kiểm tra, lần lượt tắt từng thiết bị và đo lại độ chính xác.

**Câu hỏi có thể bị hỏi**
- *Vì sao không dùng deep learning hay GNN?* Với khoảng 10.000 mẫu và đặc trưng dạng bảng, gradient boosting là lựa chọn cơ sở mạnh và dễ giải thích. GNN (như bài của Chen et al. 2019) là bước nâng cao tiếp theo.
- *Mô hình sai ở đâu?* Xem `results/figures/confusion_ml.png` và phần phân tích lỗi đầy đủ trong `results/error_analysis/` (chạy `scripts/error_analysis.py`). Lỗi tập trung ở các vùng trục gần trạm (Sw1, Sw2, Sw4, L13) và ở dải `SLG ≥ 100 Ω` có hồ quang chập chờn (`965/969` lỗi, trong đó `844/969` = `87%` ở `≥ 200 Ω`). Ở đó dòng tải qua các thiết bị là 240–630 A, nên sai số đo CT/PT + sàn nhiễu `0,5 A` + trôi tải pre/post lớn hơn dòng 60 Hz đã suy giảm của hồ quang 200–400 Ω (trung vị `R_eff` lên tới `407,8–841,6 Ω`). Vùng ở cuối lưới có dòng tải nhỏ, nên sự cố trở kháng cao dễ nhận ra hơn.
- *Kết quả chính?* ML đầy đủ đúng **91,5%** (ML chỉ độ lớn **80,2%**, FPI cổ điển **52,5%**). Với sự cố chạm đất 100 Ω: ML đúng **84,8%**, FPI chỉ **4,5%**; ở 400 Ω (hồ quang chập chờn + trôi tải): ML còn **31,3%**, FPI **1,6%**. Mất một cảm biến bất kỳ: ML đúng **78–88%**. Quãng dây đội phải tuần tra trung bình giảm từ **39,0 kft** xuống **7,3 kft** (**−81%**; FPI là **20,7 kft**).

---

## 5b. Chuyển giao sang lưới mới, tìm từng bus & lưới có điện mặt trời + Conformal Prediction (`shf/transfer.py`, `shf/transfer_models.py`, `shf/bus_locator.py`, `shf/active_grid.py`, `shf/active_models.py`)

- **Vấn đề:** Bộ phân loại ở mục 5 dùng bảng 150 cột gắn cứng với tên của 10 thiết bị trên IEEE 123-bus, nên không chạy được trên lưới khác có số dao khác.
- **Cách làm & kết quả chính (toàn bộ là mô phỏng OpenDSS, mục 2c trên trang báo cáo):**
  - **Chuyển giao zero-shot trên lưới hình tia thụ động (0.01–400 Ω, `results/transfer/`):** biểu diễn mỗi sự kiện thành đồ thị các zone với 21 đặc trưng không thứ nguyên mỗi nút (mức thay đổi dòng chia cho tải trước sự cố, điện áp per-unit, hướng công suất). Học **chỉ trên IEEE 123-bus (4.16 kV, 10 vùng)** rồi chạy thẳng trên **IEEE 34-bus chưa từng thấy (24.9 kV, 7 dao đặt theo quy tắc nhánh ≥ 5% tải cố định trước)**: trên 123-bus, FPI đạt **55.5%**, GBDT theo nút đạt **98.3%**, GNN cây vùng (2 lớp) đạt **98.1%**; zero-shot trên 34-bus, FPI đạt **55.5%**, GBDT theo nút đạt **99.8%**, GNN đạt **99.3%** (tinh chỉnh 20%: GNN **98.7%** vs GBDT **96.4%**). Điểm trên 34-bus cao hơn vì dòng sự cố lớn so với dòng tải: đo bằng OpenDSS ở tải định mức (`scripts/signal_to_load.py`), sự cố 400 Ω trên lưới 24.9 kV kéo trung vị 31.7 A, bằng 61.1% dòng đầu tuyến 51.8 A; trên lưới 4.16 kV chỉ kéo 6.2 A, bằng 1.0% của 631.5 A.
  - **Stage 2 — Tìm từng bus bên trong zone dự đoán (`shf/bus_locator.py`, `scripts/transfer_bus_stage.py`):** công thức điện kháng Takagi 3 pha dùng ma trận đường dây 3×3 của OpenDSS (không cần học) đạt **46.9% top-1 / 69.0% top-3** trên 123-bus và **57.5% top-1 / 87.4% top-3** trên 34-bus, vượt xa GNN đồ thị bus (**17.8% / 38.5%** CV trên 123-bus và **50.8% / 85.8%** zero-shot trên 34-bus). Các cặp bus hay nhầm nhất (`61→61s`, `160→160r`, `832→888`) có `ΔX1 = 0.000 Ω` (hai nhánh song song cùng khoảng cách điện).
  - **Lưới chủ động có điện mặt trời (0–50% `Generator Model=7`), đổi cấu trúc/vòng kín, sự cố tới 10,000 Ω và quá độ không sự cố (`NO_FAULT`, `results/active_grid/`):** trên IEEE 123-bus chủ động (17,847 sự kiện), FPI sụp xuống **40.7%** (tỉ lệ cắt nhầm FPR **21.2%**), GBDT theo nút đạt **93.9%** (FPR **13.9%**), còn mạng chú ý đồ thị hai chiều **ActiveGridGATv2** đạt **95.8%** (giảm hơn một nửa tỉ lệ cắt nhầm xuống **6.5%**, vòng kín **94.7%**, mất 1 cảm biến **89.1%**). Trên IEEE 34-bus chủ động chưa từng thấy (9,491 sự kiện, SLG tới 10,000 Ω), FPI đạt **47.6%**; ở zero-shot GBDT đạt **83.8%** so với **77.6%** của ActiveGridGATv2; khi tinh chỉnh 20% (7 bus), **ActiveGridGATv2 vượt lên 89.1%** (so với **83.1%** của GBDT), và học tại chỗ trên 34-bus đạt **93.1%** (so với **91.8%** của GBDT).
  - **Split Conformal Prediction (đăng ký trước, rồi kiểm tra sau):** cách tính APS xác định đã đăng ký trước bị bão hòa. Ở mục tiêu 95%, mỗi tập trung bình chứa 6.37 trên 11 nhãn và phủ 100.0% số ca trên 123-bus chủ động, nên luật "chỉ tự đóng cắt khi tập có 1 nhãn" chỉ áp dụng được cho 22.6% số ca (ActiveGridGATv2). Tiêu chí C3 đạt đúng như chữ viết, nhưng độ phủ đó gần như vô nghĩa. Kiểm tra sau trên cùng xác suất và cùng cách chia bằng APS ngẫu nhiên (`scripts/active_conformal_posthoc.py`, Addendum A trong `research/active-grid-gnn/PLAN.md`) đạt đúng mục tiêu trên lưới đã học: độ phủ 95.0% với 1.09 nhãn mỗi tập; tập 1 nhãn chiếm 89.2% số ca, đúng 99.1%, và 1.1% số ca không sự cố sẽ bị cắt nhầm. Kết quả này **không** giữ được khi sang lưới 34-bus chưa thấy: ngưỡng của 123-bus chỉ phủ 81.4% (ActiveGridGATv2) và 91.1% (GBDT) so với mục tiêu 95%; hiệu chỉnh lại bằng 2 bus sự cố của lưới đó đạt trung bình 92.0% và 94.2% (tệ nhất trong 10 lần rút: 81.5% và 91.3%). Muốn có bảo chứng thì phải hiệu chỉnh bằng dữ liệu của chính lưới đang dùng; ở đây nó chỉ là cổng hỗ trợ quyết định trong mô phỏng, không phải bảo chứng cho bảo vệ rơ-le.
  - **Thử sức trên lưới thứ 3 chưa từng thấy — cáp ngầm đô thị IEEE 37-bus (4.8 kV, 3 dây delta không nối đất, `research/ieee37-underground/PLAN.md`, `scripts/transfer_eval37.py`, toàn bộ là mô phỏng OpenDSS thuần túy):** quy tắc đặt dao nhánh ≥ 5% tải chia ra **10** vùng (`D1`–`D10`) trên **36** bus 3 pha, quét **5,184** sự cố thụ động (không thêm máy biến áp tạo trung tính). Vì không có trung tính nối đất, dòng sự cố SLG chỉ khép mạch qua điện dung rải của cáp ngầm: ở tải định mức (`369.5 A` đầu tuyến `D1`), trung vị dòng SLG chỉ **2.36 A** (**0.64%**) ở `0.01 Ω` và **2.23 A** (**0.60%**) ở `400 Ω`, kèm dịch điện áp pha lành về `√3` pu — chế độ vật lý mà mô hình học trên lưới 4 dây nối đất IEEE 123-bus chưa từng thấy. Do đó zero-shot thụ động không đạt tiêu chí đăng ký trước (`P1-Fail`, `results/transfer/phase3_ieee37.json`): FPI đạt **43.0%** (sự cố pha **98.2%**, SLG **0.0%**), zero-shot GBDT đạt **56.4%** (pha **100.0%**, SLG **22.4%**), zero-shot GNN đạt **46.7%** (pha **99.7%**, SLG **5.6%**); tinh chỉnh 20% giúp GNN lên **66.0%** còn GBDT warm-start tụt còn **55.1%**; kiểm định tại chỗ 5-fold CV đạt **91.4%** (GBDT, SLG **85.0%**) và **88.0%** (GNN, SLG **79.6%**). Ở Stage 2 (`results/transfer/phase2b_bus_ieee37.json`, kết luận `P2-Partial`), Takagi 3 pha đạt **38.4%** top-1 / **53.4%** top-3 và `BusGraphGNN` zero-shot đạt **37.2%** / **53.9%** (so với ngẫu nhiên trong vùng **17.0%** / **42.1%**); riêng sự cố pha đạt **94.4%** (Takagi) và **95.2%** (`BusGraphGNN`) so với **69.4%** ngẫu nhiên. Phần lưới chủ động (3 nguồn DER `Model=7` đấu delta, `Tie37` delta-delta, `NO_FAULT` không có tụ bù) đã chạy trên Kaggle GPU (`notebooks/kaggle_active_ieee37.ipynb`, `results/active_grid_ieee37/`): FPI đạt **44.5%**, zero-shot GBDT **55.4%** và ActiveGridGATv2 **46.2%** (kết luận `A2-Partial`); tinh chỉnh 20% đưa ActiveGridGATv2 lên **76.2%** (GBDT **62.0%**), học tại chỗ đạt **85.7%** (GATv2) / **88.3%** (GBDT). Conformal APS ngẫu nhiên 95%: ngưỡng 123-bus chỉ phủ **47.4%** (GATv2) và **81.1%** (GBDT); hiệu chỉnh lại bằng 2 bus đạt trung bình **94.1%** / **93.9%** (tệ nhất **86.2%** / **88.9%**), và cần khoảng 20% số bus để đạt tiêu chí đăng ký trước.

  - **Kiểm chứng đa lưới mở rộng trên 15 lưới OpenDSS (`scripts/multi_feeder_eval.py`, `results/transfer/multi_feeder_benchmark.json`, chạy song song 3 phiên Kaggle):** dùng đúng mô hình đóng băng từ IEEE 123-bus chạy zero-shot trên 9 lưới chuẩn IEEE/EPRI bổ sung đạt **10/11 lưới chưa từng thấy**, gồm lưới cáp hạ áp châu Âu 50 Hz (**93.3%** GBDT / **91.3%** GNN so với **60.3%** FPI), IEEE 8500-Node (**99.8%** / **99.0%** so với **44.1%** FPI), EPRI Ckt24 34.5 kV (**99.7%** GBDT) và cả 6 lưới EPRI lớn nơi GNN đều vượt GBDT khi mất 1 cảm biến (ví dụ **94.3%** so với **90.5%** trên EPRI Ckt7 18 zone); còn mạng mạch lưới IEEE 342-Node (71 vòng kín), IEEE 9500-Node không hội tụ cơ sở và CIGRE MV (không có file gốc) được ghi nhận rõ là ngoài phạm vi.

---

## 5c. Kiến trúc 2 tầng Edge HIF-Sensor → Graph FLISR (`shf/hif_edge.py`, `shf/hif_fusion.py`, `scripts/hif_fusion_run.py`, mục 2d)

- **Vấn đề:** Ở tần số cơ bản 60 Hz, điểm yếu lớn nhất của dự án là sự cố SLG 200–400 Ω trên lưới 4.16 kV IEEE 123-bus (dòng tuyến tính 400 Ω chỉ khoảng 6.2 A, bằng 1.0% dòng đầu tuyến 631.5 A; dưới mô phỏng hồ quang chập chờn + trôi tải + nhiễu CT/PT ở nghiên cứu chính, độ chính xác 60 Hz ở 400 Ω giảm còn 31.3% và 87% lỗi tập trung ở ≥ 200 Ω). Kế hoạch khóa tiêu chí trước nằm trong [`research/hif-fusion/PLAN.md`](../../research/hif-fusion/PLAN.md).
- **Tầng 1 — Cảm biến biên Edge HIF-Sensor (`shf/hif_edge.py`):** đóng gói độc lập đúng thông số từ dự án đồng hành `hif-sensor` tại từng recloser/dao:
  - Mạch đầu vào: CT kẹp dòng dư `SCT-013-000` (2000:1, điện trở gánh 33 Ω) → lọc thông thấp Butterworth bậc 4 hai tầng Sallen-Key (tần số cắt `-3 dB` đã kiểm chứng LTspice là **2,045.1 Hz**, mô hình IIR Python là **2,047.9 Hz**) → ADC 12-bit lấy mẫu ở **15.36 kHz** (256 mẫu/chu kỳ 60 Hz).
  - Đặc trưng & suy luận biên: tính **16 đặc trưng** sóng hài / bất đối xứng / biến động chu kỳ trên cửa sổ trượt 8 chu kỳ (133.3 ms), đưa vào mạng Tiny MLP lượng tử hóa `int8` đóng băng (`16→16→8→1`, **417 tham số / 504 byte**, nạp từ `model_int8.npz` của kernel Kaggle `christoopherchau/ch-y-n`, hoặc bản dự phòng tất định `seed=42`) kết hợp bộ đếm bền `PERSIST = 3` cửa sổ liên tiếp để xuất 2 đại lượng vô hướng không phụ thuộc lưới `(p_hif, hif_alarm)`.
- **Tầng 2 — Graph FLISR đối chứng cặp (`shf/hif_fusion.py`, `scripts/hif_fusion_run.py`):**
  - Chạy đối chứng `60Hz_only` so với `60Hz_plus_edge` trên đúng cùng tập sự cố OpenDSS, cùng cách chia fold theo bus và seed: ghép `(p_hif, hif_alarm)` vào khối cảm biến của từng nút (`21 → 23` đặc trưng cho nhánh thụ động `PerNodeGBDT` / `ZoneTreeGNN`; `26 → 28` đặc trưng nút + đặc trưng cạnh có hướng thứ 5 `diff_p_hif` cho nhánh chủ động `ActivePerNodeGBDT` / `ActiveGridGATv2`, kèm Split Conformal `aps_rand` 95%).
  - Khi tắt 1 cảm biến (`1 sensor offline`), cả kênh 60 Hz lẫn `(p_hif, hif_alarm)` của dao đó cùng bị gán `NaN` vì cùng nằm trong một IED/recloser.
  - Quét đầy đủ **5 bề mặt hồ quang Emanuel** (`wet_grass`, `wet_sand`, `concrete`, `dry_grass`, `dry_asphalt`) và **7 nhiễu nền** (`none`, `load_step`, `cap_switch`, `inrush`, `motor_start`, `arc_welder`, `nonlinear_fluct`). Đầu ra tách riêng hoàn toàn trong `results/hif_fusion/`, không đụng bất kỳ con số nào của mục 2a–2c.
- **Kết quả chạy thật trên Kaggle GPU (`results/hif_fusion/`, nạp đúng `model_int8.npz` đóng băng từ `christoopherchau/ch-y-n`, đạt 4/4 tiêu chí `H1–H4 PASS`, mô phỏng thuần túy):**
  - **Thụ động 123-bus (5-fold theo bus):** `PerNodeGBDT` tăng **98.2% → 99.7%** (SLG 200–400 Ω **87.5% → 98.0%**, 400 Ω **78.1% → 97.7%**, mất 1 cảm biến **89.0% → 90.3%**); `ZoneTreeGNN` tăng **98.0% → 99.5%** (SLG 200–400 Ω **86.4% → 97.0%**, 400 Ω **79.6% → 96.0%**, mất 1 cảm biến **90.0% → 91.5%**). Thụ động **34-bus zero-shot**: `PerNodeGBDT` giữ `99.8% → 99.8%` (SLG 200–400 Ω `98.5% → 98.7%`); `ZoneTreeGNN` giữ `99.4% → 99.4%` (`95.9% → 97.6%`).
  - **Chủ động 123-bus (DER + vòng kín + 7 nhiễu nền):** `ActivePerNodeGBDT` tăng `93.9% → 96.8%` (SLG 200–400 Ω `80.2% → 90.3%`, 400 Ω `72.5% → 86.8%`, FPR `13.9% → 3.3%`, mất 1 cảm biến `86.1% → 88.7%`); `ActiveGridGATv2` tăng `95.8% → 97.6%` (SLG 200–400 Ω `82.2% → 90.8%`, 400 Ω `73.5% → 87.5%`, FPR **`6.5% → 1.2%`**, mất 1 cảm biến `89.1% → 91.3%`).
  - **Chủ động 34-bus zero-shot (24.9 kV, 1–10 kΩ):** `ActivePerNodeGBDT` tăng `83.8% → 87.5%` (1–10 kΩ `71.8% → 77.8%`, FPR `22.1% → 5.8%`, mất 1 cảm biến `72.4% → 75.6%`); `ActiveGridGATv2` tăng `77.6% → 83.3%` (1–10 kΩ `65.3% → 70.0%`, FPR `25.3% → 9.7%`, mất 1 cảm biến `71.5% → 74.5%`).
  - **Split Conformal (`aps_rand` 95%, `ActiveGridGATv2`):** 123-bus giữ độ phủ `95.0%` (`95.0%` ở 60 Hz), tỉ lệ tự động 1 nhãn tăng `89.2% → 93.0%` (đúng `98.9%`, cắt nhầm tự động `NO_FAULT` chỉ `0.5%`); trên 34-bus chưa thấy, ngưỡng 123-bus tăng `81.4% → 84.9%` và hiệu chỉnh 5% số bus đạt trung bình `92.0%` (min `85.4%`).

**Câu hỏi có thể bị hỏi**
- *Dạng sóng hồ quang trong mục 2d có phải dữ liệu đo thật ngoài lưới không?* Không. Cả hai tầng đều là **mô phỏng**: dòng sự cố lấy từ trào lưu công suất OpenDSS, còn dạng sóng hồ quang Emanuel 5 bề mặt và 7 tải nền được tổng hợp bằng chồng chập hài giả xác lập (chưa mô phỏng quá độ EMTP, bão hòa CT hay phi tuyến ADC ESP32). Hơn nữa, trên dự án đồng hành `hif-sensor`, khi chạy mô hình đóng băng trên bản ghi hồ quang thực vật 22 kV thật mà không huấn luyện lại, tỉ lệ phát hiện giảm rõ do khác biệt miền dữ liệu, nên kết quả mô phỏng không thay thế kiểm chứng thực địa.
- *Muốn chạy kiến trúc này ngoài lưới thật thì thiết bị SCADA cũ có dùng được không?* Không. SCADA/RTU 60 Hz cũ chỉ báo biên độ/pha tần số cơ bản; triển khai thực tế đòi hỏi tại mỗi recloser/dao phải lắp IED hoặc nút cảm biến cỡ ESP32-S3 lấy mẫu dòng dư **≥ 15.36 kHz** sau mạch lọc chống chồng phổ ~2 kHz để tính tại biên rồi mới gửi 2 con số `(p_hif, hif_alarm)` về trung tâm FLISR.

---

## 5d. Dự án con Tầng 1 · Cảm biến biên HIF (`hif_sensor/`)

Tài liệu chi tiết xem tại [`hif_sensor/README.md`](../../hif_sensor/README.md), [`hif_sensor/HUONG_DAN.md`](../../hif_sensor/HUONG_DAN.md) và kế hoạch tiền đăng ký [`hif_sensor/PLAN_PHASE15.md`](../../hif_sensor/PLAN_PHASE15.md).

- **Mạch đầu vào analog 60 Hz & 50 Hz Việt Nam/Úc (`hif_sensor/circuit/`, `hif_sensor/hif/frontend.py`):** CT kẹp SCT-013-000 (2000:1) → gánh `33 Ω` (`16.5 mV/A`) → nâng áp `1.65 V` → lọc thông thấp Butterworth bậc 4 hai tầng Sallen-Key (`8.66 kΩ` / `4.42 kΩ`, LTspice `−3 dB = 2,045.1 Hz`, giảm `−46.4 dB` tại Nyquist `7.68 kHz` của `15.36 kHz` ADC 60 Hz). Khi chạy ở lưới **50 Hz** (`12.8 kHz` ADC, `256` mẫu/chu kỳ, Nyquist `6.40 kHz`, cửa sổ `160.0 ms`): giữ nguyên PCB cho suy giảm `−39.99 dB` tại Nyquist, hoặc đổi 2 điện trở `R × 1.2` sang **`10.5 kΩ`** và **`5.36 kΩ`** (giữ nguyên layout PCB & tụ) để đạt `fc = 1,688.73 Hz` và **`−46.70 dB`** tại `6.40 kHz`.
- **Phase 0 (mô phỏng, [`hif_sensor/results/metrics.json`](../../hif_sensor/results/metrics.json)):** `4,000` sự cố Emanuel (5 bề mặt, 7 nhiễu nền), `16` đặc trưng, MLP `16→16→8→1` (**417 tham số / 504 byte `int8`**, `PERSIST = 3`) đạt **94.70%** phát hiện (báo nhầm bình thường **1.49%**, trễ trung vị `5.0` chu kỳ) so với `51N` **0.51%** và hài bậc 3 **0.00%**; LOSO bề mặt chưa thấy **93.0%–98.5%** (giấu máy hàn gây **17.5%** báo nhầm).
- **Phase 1 (zero-shot VeHIF 22 kV thật, [`hif_sensor/results/real_vehif.json`](../../hif_sensor/results/real_vehif.json)):** chạy mô hình Phase 0 đóng băng trên **250** bản ghi sự cố thật (`120 s` max) + **53** bản ghi nền thật qua cảm biến và tải mô phỏng: đạt **56.0%** tổng thể (`0–1 A`: `36.2%`, `1–2 A`: `70.0%`, `2–5 A`: `94.7%`, `5–10 A`: `85.7%`, `>10 A`: `100.0%`), nền thật **0.0%** FA, đối chứng **1.2%** FA (`51N` **0.0%**, hài bậc 3 **0.4%**). Phân tích lệch miền cho thấy hồ quang thực vật 22 kV đối xứng hơn mô phỏng (`dc_ratio −0.49 IQR`, `h2_ratio −0.47 IQR`, `even_ratio −0.46 IQR`, `I3_cv −0.38 IQR`).
- **Phase 1.5 ([`hif_sensor/results/phase15_vehif.json`](../../hif_sensor/results/phase15_vehif.json), [`hif_sensor/results/c_firmware_verify.json`](../../hif_sensor/results/c_firmware_verify.json)):**
  - **Kiểm chứng firmware C bằng GCC `13.3.0` (`-O2 -Wall -Wextra -Werror`, nhị phân `17,032 B`):** `max |p_c - p_py|` lần lượt là `4.77e-7` (`6` vector Phase 0, `0.540 µs/inf`), `8.34e-7` (`100` vector Phase 0, `0.611 µs/inf`) và `1.04e-6` (`100` vector Phase 1.5 `hif_model_phase15.h` ngưỡng `0.924894`, `0.569 µs/inf`), đạt **100%** đồng thuận quyết định & `PERSIST = 3` (`P1.5-D: PASS`).
  - **50 Hz vs 60 Hz:** mô phỏng 50 Hz đạt **94.33%** (`1.67%` FA) vs 60 Hz **94.70%** (`1.49%` FA); trên `250` bản ghi VeHIF cắt `90 s`, cả 50 Hz tự nhiên và 60 Hz resample đều đạt **54.4%** (`0–2 A`: `43.09%` vs `43.62%`, nền **0.0%**).
  - **Ablation 5 nhóm đặc trưng (50 Hz tự nhiên):** `all_16` (**54.4%** thật / **94.70%** sim), `no_asymmetry_12` (**22.4%** / **40.15%**), `no_top_shift_9` (**13.2%** / **40.66%**), `harmonics_only_7` (**46.4%** / **86.62%**), `temporal_only_8` (**55.6%** thật, `0–2 A` **51.06%** / **86.11%** sim).
  - **Few-shot VeHIF 5 seed (`179` sự cố / `33` nền kiểm thử độc lập):** `zero_shot_phase0` **53.30%** (`0–2 A` **42.52%**); `head_recal_int8` giảm còn **46.59% / 46.03% / 44.80%** ở `5/10/20%`; `joint_mlp_int8` tăng lên **49.50% / 56.42% / 60.22%** (`0–2 A` **49.93%**, **`+7.41 pp`** ở `20%`, nền FA **1.82%**, đối chứng FA **0.67%**, mô phỏng **93.84%** / FA **1.53%**). Đạt **`P1.5-B/C/D: PASS`**, nhưng **`P1.5-A: FAIL`** (`+7.41 pp < +15 pp`). Chưa lắp mạch PCB vật lý để đo ngoài lab.

---

## 6. Cô lập và khôi phục (`shf/restoration.py`)

**Trình tự** (giống FLISR của EPB hay Duke):
1. Recloser đầu xuất tuyến Sw1 cắt và khóa (lockout).
2. Mở dao cấp điện cho vùng sự cố và các dao đi ra khỏi vùng đó (**cô lập**).
3. Đóng lại Sw1: các vùng phía trên vùng sự cố có điện lại.
4. Các vùng phía sau tạo thành các "đảo" mất điện. Với mỗi dao liên lạc, thử đóng để cấp điện cho cả đảo; nếu không đạt thì thử các phần nhỏ hơn. **Chỉ chấp nhận phương án khi giải tích lưới cho thấy:**
   - mọi nút đang có điện nằm trong **0,95–1,05 pu** (ANSI C84.1 Range A);
   - không dây nào vượt **định mức khẩn cấp**;
   - lưới vẫn **hình tia**.
5. **Tham lam (greedy):** mỗi vòng, chọn dao liên lạc nào cấp lại được nhiều kW nhất.

**Chỉ số kW·phút mất điện:** so sánh cách làm thủ công (đội đi tuần tra 90 phút rồi mới thao tác) với tự động (khoảng 1 phút). Vùng sự cố phải chờ sửa chữa 240 phút trong cả hai trường hợp. Các con số thời gian này là **giả định**, nên khi trình bày hãy nói rõ.

**Câu hỏi có thể bị hỏi**
- *Vì sao phải chạy giải tích lưới trước khi đóng dao liên lạc?* Vì nguồn bên kia có thể không đủ khả năng: điện áp cuối đường dây tụt dưới 0,95 pu, hoặc dây bị quá tải. Thuật toán đã loại 22 phương án: phần lớn do điện áp thấp (thấp nhất 0,85 pu), 2 phương án do điện áp cao. Không phương án nào bị loại vì quá tải dây; với lưới 4,16 kV này, **điện áp mới là giới hạn quyết định**.
- *Có khi nào điện áp lại quá cao không?* Có. Khi sự cố ở vùng Sw3, phương án cấp lại vùng L45 qua dao Sw7 bị loại vì điện áp lên 1,053 pu, do bộ điều áp đầu nguồn có bù sụt áp đường dây (LDC) đẩy điện áp lên.
- *Kết quả chính?* Cả 10 trường hợp đều cho cấu hình cuối hợp lệ (điện áp trong giới hạn, không quá tải, vẫn hình tia). Dao liên lạc cấp lại được 2.670 trên 7.175 kW tải lành bị mất điện phía sau vùng sự cố (37%); phần còn lại không cấp được mà vẫn giữ điện áp trong giới hạn. Tính theo giả định thời gian, kW·phút mất điện giảm trung bình 51%.
- *Sự cố lúc 3 giờ sáng và lúc 6 giờ chiều có khôi phục giống nhau không?* Không. `scripts/hourly_restoration.py` chạy lại khôi phục cho từng vùng sự cố ở mọi mức tải, ghi lý do mỗi phương án bị loại (thấp áp, quá áp, quá tải, không hội tụ), rồi gắn từng giờ của tải vùng AEP (PJM, dữ liệu Kaggle) năm 2017 vào mức tải tương ứng. Tính cả năm, tie cấp lại được **44.0%** phần tải lành bị mất điện nếu xét đúng giờ sự cố, so với 37.2% khi tính ở tải đỉnh; nếu phương án phải giữ được tới khi sửa xong (6 giờ) thì còn **42.1%**. Ngày hè điển hình: 50.0% nếu sự cố lúc 03:00, chỉ 36.7% lúc 17:00; ngày đông điển hình: 46.0% lúc 02:00, 39.3% lúc 08:00. Lý do: về đêm tải nhẹ nên điện áp sụt ít hơn trên đường tie dài. Mọi phương án bị loại đều do điện áp, không phương án nào bị loại vì dòng điện. Giả định: mọi tải đi theo cùng một hình dạng tải của cả vùng (mượt hơn một feeder thật), tải danh định IEEE là đỉnh năm, tụ bù giữ cố định, feeder bên cạnh vẫn không có tải riêng. Khi trình bày, nói rõ 2 điểm: quyết định của L13 và Sw3 nằm sát giới hạn 1,05 pu (khoảng một nấc bộ điều áp) nên bật tắt giữa các mức tải sát nhau; và 74 trên 8,760 giờ rơi vào mức tải có trạng thái lên tới 1.0508 pu, vượt nhẹ giới hạn. Kết quả ở mục 4b của trang báo cáo.
- *Nếu ML đoán sai vùng thì sao?* Thuật toán sẽ cô lập sai vùng, và sự cố lại được cấp điện, khiến recloser cắt lần nữa. Hệ thống thật cần kiểm tra thêm, ví dụ đóng thử từng bước. Đây là phần cải tiến tiếp theo.

---

## 7. SCADA giả lập (`shf/scada.py`, `scripts/demo_event.py`, `scada/`)

- `scripts/demo_event.py` phát lại một sự cố theo từng bước thời gian và tạo các bản tin JSON giống thiết bị gửi về trung tâm điều độ.
- **Không có broker MQTT:** bản tin được ghi ra `results/demo_event.jsonl`.
- **Có broker** (`--mqtt localhost`): bản tin được đẩy lên các topic `shf/ieee123/<thiết bị>` và `shf/ieee123/events`.
- `scada/ingest.py` nghe MQTT và ghi vào **TimescaleDB** (bảng `device_readings`, `flisr_events`). Hai phần MQTT và TimescaleDB này nối với hệ thống SmartGrid Monitor bạn đã có.
- `scada/docker-compose.yml` chạy Mosquitto và TimescaleDB trên máy.
- **Lưu ý trung thực:** phần đẩy MQTT và ghi TimescaleDB **chưa được chạy thử** trên máy này vì không có Docker. Mới chỉ kiểm tra chế độ ghi file JSONL.

---

## 8. Trang báo cáo hợp nhất 3 tab (`shf/dashboard.py` → `docs/index.html` & `docs/hif-sensor/index.html`)

- **Kiến trúc 3 tab thống nhất trên GitHub Pages:** thanh điều hướng trên cùng kết nối 3 tab dùng chung phông chữ `system-ui`, nền giấy ấm `#f9f9f7`, nút đổi ngôn ngữ **EN / VI** (`shf-lang`) và giao diện sáng/tối (`shf-theme`):
  1. **Tab 1 — Tầng 2 · Lưới FLISR (`docs/index.html`):** https://chau1912550.github.io/self-healing-feeder/?lang=vi (mô hình 3D IEEE 123-bus, định vị lỗi, phân tích lỗi, khôi phục, mục 2c/2d, 17 câu Hỏi đáp).
  2. **Tab 2 — Tầng 1 · Cảm biến HIF ESP32 ([`docs/hif-sensor/index.html`](../../docs/hif-sensor/index.html)):** do `python -m shf.dashboard` tự động gọi `hif_sensor/scripts/build_dashboard.py` để dựng cùng lúc với trang chính, hiển thị LTspice 50/60 Hz, Phase 0, Phase 1 VeHIF, Phase 1.5 (ablation, few-shot, kiểm chứng C GCC) và bảng SHA-256 `23` file.
  3. **Tab 3 — Phòng điều khiển Monitor ([`docs/monitor/README.md`](../../docs/monitor/README.md)):** 40 ca diễn lại theo vai trò (cộng thêm tài liệu học tập tại `docs/study/`).
- **Mở trên mạng:** https://chau1912550.github.io/self-healing-feeder/?lang=vi (GitHub Pages, miễn phí, không cần cài gì, xem được trên điện thoại).
- **Hai ngôn ngữ:** nút **EN / VI** ở góc trên đổi toàn bộ chữ, nhãn biểu đồ và chú thích. Thêm `?lang=vi` hoặc `?lang=en` vào link để gửi đúng ngôn ngữ.
- **Tiện ích đọc hiểu:** ô *Tóm lại* đầu mỗi mục; từ gạch chân chấm chấm có định nghĩa khi rê chuột hoặc chạm; mục *Thuật ngữ* (19 từ); mục *Hỏi đáp* 15 câu có ô tìm kiếm (gõ không dấu vẫn được), lọc theo chủ đề, mở tất cả, sao chép link từng câu; thanh trên cùng nhảy tới từng mục; nút ◐ đổi giao diện tự động / sáng / tối; in ra giấy sẽ tự mở hết câu trả lời.
- **Nhân vật hướng dẫn (kiểu heyclicky):** nhấp vào bất kỳ thẻ, biểu đồ, bảng nào (hoặc nút **?** ở góc của nó). Nhân vật bay tới, vẽ khoanh quanh thành phần đó và mở khung giải thích 3 ý: *Đây là gì / Đọc thế nào / Vì sao quan trọng*. Nút Trước / Tiếp (hoặc phím ← →) đi qua cả 15 thành phần, Esc để đóng. Gửi link có `?explain=heat` (hoặc `tile-acc`, `chart-res`…) thì người nhận mở ra là thấy giải thích ngay phần đó.
- **Tour 30 giây** ở đầu trang: hình vẽ gọn một tuyến điện tự chạy 5 bước (sự cố → mất điện → mô hình chỉ ra zone → cô lập và cấp điện lại → đội sửa đi thẳng tới chỗ lỗi), số liệu lấy từ lần chạy mới nhất, cuối cùng gợi ý đọc tiếp theo thứ tự nào. Có nút Tạm dừng / Xem lại, hoặc nhấp vào từng bước.
- **Chế độ giải thích luôn bật** cho mọi người xem, không có nút tắt.
- **Nút Monitor** (màu cam, trên cùng trang) mở trang giám sát theo vai trò ở `docs/monitor/`: điều độ viên, đội hiện trường, kỹ sư, quản lý, mỗi vai trò có khung *How to handle* riêng. Nút có dạng ô vuông, dòng nhỏ bên dưới ghi *Tự xử lý sự cố*. Ngay dưới tour 30 giây có **thẻ Giám sát**: nói Monitor là gì, 3 bước dùng, và lưu ý đây chỉ là demo. Trong trang Monitor có thanh *How to use* (ẩn được, bấm *How to use* để hiện lại).
- **Mô hình 3D** (`shf/dashboard.py`, dữ liệu từ `results/feeder_geometry.json` do `python -m shf.report` tạo): trụ gỗ có xà và sứ, mỗi pha một dây, máy biến áp trên trụ, cột tải theo kW, recloser, dao (dao thêm vào có ăng-ten), dao liên lạc mở (lưỡi đỏ dựng lên), bộ điều áp, tụ bù, trạm nguồn. Kéo để xoay; nhấp vào zone hay thiết bị thì phần đó nổi lên và được giải thích; nút *Đi qua các zone*; bật/tắt nhãn zone, thiết bị, số bus; xem *Bản đồ 2D*. Thư viện three.js chỉ tải khi cuộn tới phần này.
- **Lớp "Lỗi của model"** (dữ liệu: `results/error_analysis/per_bus_ml.csv` do `scripts/error_analysis.py` tạo): cột đỏ ở mỗi bus có sự cố bị đoán sai (cao = nhiều, đỏ đậm = tỉ lệ cao), chấm xanh ở bus không sai lần nào, mũi tên từ zone thật tới zone bị đoán nhầm. Nhấp vào cột hoặc mũi tên để xem số liệu, kể cả bộ chỉ báo truyền thống sai bao nhiêu ở cùng bus đó.
- **Lớp "Diễn lại sự cố":** nhấp vào bất kỳ đường dây nào (hoặc chọn "Một sự cố bị đoán sai") để xem 6 bước: sự cố → Sw1 cắt hẳn, cả tuyến tắt → model đoán zone (mũi tên cam nếu sai, kèm lý do) → mở dao cô lập → đóng lại Sw1 → đóng tie cấp điện lại. Mỗi dao có đèn: xanh = đóng, đỏ = mở. Bước 4–6 luôn dựa trên zone thật, vì nghiên cứu chưa mô phỏng hậu quả của việc đoán sai.
- **Dữ liệu & phương pháp:** toàn bộ dữ liệu 11,448 sự cố và mọi file kết quả được chép vào `docs/data/` khi dựng trang, kèm bảng ý nghĩa từng cột, công thức và 9 bước tư duy.
- **Sửa câu hỏi đáp, thuật ngữ hoặc lời giải thích:** nội dung nằm trong `shf/dashboard_text.py` (`FAQ`, `GLOSSARY`, `EXPLAIN`; mỗi mục có bản tiếng Anh và tiếng Việt). Các số là chỗ `{ten}`, tự lấy từ kết quả mới nhất nên không bị lệch số.
- **Mở trên máy:** bấm đúp vào `docs/index.html`. Đây là 1 file duy nhất, không cần server hay internet.
- **Cập nhật:** `run.py` tự dựng lại trang ở bước cuối; `scripts/error_analysis.py` cũng vậy. Muốn dựng lại riêng: `python -m shf.dashboard` (khoảng 1 giây). Push lên GitHub thì sau khoảng 1 phút trang trên mạng tự cập nhật.
- **Cách đọc:**
  - *Run checks*: **Pass** = đạt giới hạn, **Watch** = điểm yếu đã biết, **Fail** = phải sửa trước khi dùng số liệu. Nếu chạy lại `run.py` mà quên chạy `error_analysis.py`, trang báo phân tích lỗi đã cũ.
  - *Fault location*: độ chính xác của 3 phương pháp theo điện trở sự cố. Rê chuột (hoặc chạm) vào điểm để xem số.
  - *Error analysis*: FNR = tỉ lệ sự cố của zone bị bỏ sót, FPR = tỉ lệ zone bị đổ lỗi nhầm. Ma trận nhầm lẫn: hàng là zone thật, cột là zone dự đoán, ô càng xanh đậm càng nhiều lỗi.
  - *Restoration*: mỗi zone sự cố, tie nào được đóng, cấp lại bao nhiêu kW, điện áp có nằm trong 0,95–1,05 pu không.
- **Ảnh chụp trong README** nằm ở `docs/images/`. Khi giao diện thay đổi nhiều thì chụp lại cho khớp.

---

## 10. Làm việc với các phần mềm khác (`workflow.toml`)

Không con số nào được gõ tay: mọi file trong `results/` đều có "giấy khai sinh" trong `results/provenance/` (23 manifest cho 51 file kết quả: lệnh đã chạy, thời điểm UTC, commit git, mã băm SHA-256 của từng file; tự kiểm chứng nhanh bằng `python -m shf.provenance` và `python harness/check.py --tests`). Health check báo lỗi ngay nếu bất kỳ file kết quả nào bị sửa sau khi chạy.

Lõi nghiên cứu chạy bằng Python + OpenDSS. Mỗi phần mềm khác chỉ giữ một việc, mỗi việc một thư mục:

| Thư mục | Phần mềm | Làm gì |
|---|---|---|
| `cad/` | AutoCAD | Bản vẽ 2D: sơ đồ một sợi của tuyến và 10 zone, sơ đồ đi dây bàn thử |
| `mech/` | SolidWorks | Mô hình 3D thiết bị: recloser và tủ điều khiển; xuất `.glb` cho trang 3D |
| `spice/` | LTspice | Mạch theo thời gian mà OpenDSS không làm: DC lệch của dòng sự cố, hồ quang, mạch đo CT |
| `hmi/` | Factory IO | Bảng điều khiển ảo nói chuyện với lõi qua Modbus TCP |
| `exports/` | tất cả | File xuất mà trang báo cáo đọc: PDF, SVG, DXF, GLB, STEP, CSV |

Sơ đồ một sợi bắt đầu từ `python scripts/export_oneline_dxf.py`: lệnh này vẽ `cad/feeder_oneline.dxf` từ `results/` (mỗi zone một layer, dao là block có thuộc tính tên, sẵn khổ A3 có khung tên); sau đó `python scripts/autocad_export.py --register` cho AutoCAD (bản dòng lệnh `accoreconsole`) tự lưu `.dwg`, in PDF và PNG vào `exports/` rồi đăng ký; làm tay trong AutoCAD cũng được. Health check báo lỗi nếu file DXF cũ hơn kết quả. Mạch LTspice cũng làm như vậy: `python scripts/spice_run.py --register` lấy trở kháng Thevenin tại bus 60 và dòng tải trước sự cố từ OpenDSS, viết 3 file `.asc` vào `spice/` (dòng sự cố có và không có DC lệch; CT → điện trở gánh → lọc RC → diode kẹp → chân ADC 3,3 V; sự cố chạm đất trở kháng cao có hồ quang theo mô hình hai diode của Emanuel và cộng sự 1990, so với điện trở cố định 100 Ω và 400 Ω có cùng dòng hiệu dụng), chạy LTspice ở chế độ nền, xuất dạng sóng ra `exports/` và ghi số liệu vào `results/spice/summary.json`. Giả định: mạch tương đương một pha, CT lý tưởng 1000:1 (không bão hoà), ADC 12 bit lấy 32 mẫu mỗi chu kỳ, ước lượng pha bằng DFT một chu kỳ; điện áp hồ quang bằng 30% (nửa chu kỳ dương) và 33% (nửa chu kỳ âm) điện áp đỉnh pha, là giả định để minh hoạ chứ không lấy từ đo đạc. Kết quả chính (mục 2b trên trang báo cáo): với cùng dòng hiệu dụng như sự cố điện trở cố định 400 Ω, hồ quang chỉ có 97.8% dòng ở tần số 60 Hz so với điện trở cố định, thêm hài bậc 3 khoảng 18.8% mà mô phỏng sự cố không có; dù dạng sóng nào thì dòng này cũng chỉ bằng 1.2% dòng tải đầu tuyến trước sự cố và chỉ chiếm 3 mức của ADC 12 bit, khớp với điểm yếu 400 Ω của model. Thiết bị 3D làm bằng SolidWorks: `python scripts/solidworks_build.py --part all --register` điều khiển SolidWorks qua COM API, dựng 6 mẫu chung (recloser, dao tự động có ăng-ten, bộ điều áp, giàn tụ, máy biến áp trên cột, máy biến áp trạm; kích thước minh hoạ trong các bảng `*_MM` của `config.py`, không phải thiết kế của hãng nào), lưu `mech/<tên>.sldprt` và xuất `exports/<tên>.glb` (cho trang 3D), `.step`, `.png`. Trang 3D chỉ dùng file `.glb` còn mới, thay cho hình vẽ đơn giản; lưỡi dao vẫn vẽ bằng code để phần phát lại sự cố mở được. Mỗi thiết bị có thêm một bản vẽ kỹ thuật A3 (`python scripts/export_drawings.py --register`): ba hình chiếu (đứng, cạnh, bằng) có ghi kích thước, bảng thông số, ghi chú và khung tên, vẽ từ đúng các khối của mô hình SolidWorks rồi cho AutoCAD xuất DWG, PDF và PNG; trang báo cáo có link tới các bản PDF ngay dưới hình 3D. Mô hình chỉ để minh hoạ, không phép tính nào dùng tới. Bảng điều khiển ESP32 mô phỏng trong Wokwi (thư mục `board/`): mỗi dao một đèn RGB xếp theo cây zone, đèn LOCKOUT, màn hình LCD, nút FAULT / CLOSE TIES / RESET và núm chọn điện trở sự cố. `python scripts/panel_bridge.py` chạy nghiên cứu trên máy (sự cố OpenDSS, model tìm zone, kế hoạch khôi phục) và điều khiển bảng qua MQTT; vì Wokwi miễn phí chỉ ra được internet nên hai bên gặp nhau ở một MQTT broker công cộng, dữ liệu chỉ là trạng thái mô phỏng. Hai công tắc gạt để thử hỏng hóc: SENSOR OFFLINE (một dao chọn ngẫu nhiên không gửi số đo, giống phép thử thiếu cảm biến của nghiên cứu; model dùng 9 dao còn lại vì đã được huấn luyện cho trường hợp này, và LCD hiện tỉ lệ đúng mà nghiên cứu đo được khi thiếu đúng cảm biến đó) và SWITCH STUCK (dao đầu tiên được lệnh mở bị kẹt, nên zone phía bên kia của nó cũng bị cắt cùng, các dao xa hơn mở thay; đây là luật dự phòng đơn giản, không mô phỏng thời gian). Khi không gạt công tắc nào, kế hoạch khôi phục giống hệt kết quả nghiên cứu. Xem thử ngay trên trình duyệt, không cần cài gì: https://wokwi.com/projects/481240462876979201 (bấm nút Start màu xanh; nếu không có máy chạy nghiên cứu, sau 15 giây board tự phát lại các ca sự cố đã ghi từ nghiên cứu). Đây là board mô phỏng, chưa phải phần cứng thật. Mỗi file làm trong phần mềm khác được ghi một mục `[[asset]]` trong `workflow.toml` (file gốc, file xuất, hỗ trợ phần nào của báo cáo). Xuất xong thì chạy `python scripts/register_export.py <id>`; health check sẽ báo lỗi nếu file gốc bị sửa mà chưa xuất lại. Các phần này là công cụ mô phỏng và trình bày, không phải thiết bị hay số liệu thực địa.

## 9. Từ vựng nhanh (Anh – Việt)

| Thuật ngữ | Nghĩa |
|---|---|
| FLISR (Fault Location, Isolation, Service Restoration) | định vị sự cố, cô lập, khôi phục cấp điện |
| Recloser / lockout | máy cắt tự đóng lại / trạng thái cắt hẳn sau các lần đóng lại không thành công |
| Sectionalizing switch / tie switch | dao phân đoạn (thường đóng) / dao liên lạc (thường mở) |
| Fault passage indicator (FPI) | thiết bị chỉ báo dòng sự cố đi qua |
| High-impedance fault | sự cố trở kháng cao |
| Superimposed / incremental quantity | đại lượng gia số (phần thay đổi do sự cố gây ra) |
| Zero / negative sequence current | dòng thứ tự không / thứ tự nghịch |
| Cold load pickup | dòng khởi động khi đóng lại phụ tải sau mất điện dài |
| ANSI C84.1 Range A | dải điện áp cung cấp chuẩn 114–126 V (0,95–1,05 pu) |
| Emergency rating | định mức dòng khẩn cấp (cho phép quá tải ngắn hạn) |
