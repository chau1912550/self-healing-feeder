# Hướng dẫn hiểu dự án Self-Healing Feeder (để tự giải thích khi phỏng vấn)

Tài liệu này giải thích **từng phần của dự án bằng tiếng Việt**, theo đúng thứ tự code chạy. Mục tiêu: bạn đọc xong có thể tự trả lời mọi câu hỏi "tại sao" của người phỏng vấn. Mỗi phần có mục **"Câu hỏi có thể bị hỏi"** ở cuối.

> Dự án được xây dựng với sự hỗ trợ của AI (Claude Code). Hãy ghi đúng như vậy trong resume. Trước khi đưa vào resume, bạn nên tự chạy lại toàn bộ, đọc từng file trong `shf/`, và thử sửa một tham số để thấy kết quả thay đổi.

---

## 0. Chạy dự án

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run.py          # chạy toàn bộ, ghi dataset vào data/generated/, model vào models/, kết quả vào results/
.venv\Scripts\python -m pytest       # 15 bài kiểm tra
.venv\Scripts\python scripts/demo_event.py --bus 60 --type SLG --r 50   # phát lại một sự cố
```

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
- *Giới hạn của mô hình?* Nguồn được coi là rất cứng (trở kháng gần 0), nên dòng sự cố lớn hơn thực tế. Không mô phỏng quá độ, hồ quang, hay điện mặt trời áp mái.

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

**Điện trở sự cố:** từ 0,01 Ω (chạm trực tiếp) đến 400 Ω (sự cố **trở kháng cao**, ví dụ dây đứt rơi xuống đất khô). Sự cố trở kháng cao rất khó phát hiện vì dòng sự cố nhỏ hơn cả dòng tải.

**Mỗi sự cố được mô phỏng 2 lần giải lưới:**
1. **Trước sự cố:** các bộ điều áp được tự do chuyển nấc.
2. **Trong sự cố:** **khóa nấc** bộ điều áp, vì bảo vệ tác động trong vài chu kỳ, còn bộ điều áp phải mất hàng chục giây mới chuyển nấc.

**Phụ tải ngẫu nhiên.** Mỗi trường hợp có hệ số tải toàn lưới ngẫu nhiên từ 0,3 đến 1,1, và mỗi điểm tải dao động thêm ±20%.
- Lý do: bản đầu tiên chỉ dùng 3 mức tải cố định, và mô hình đạt 99,9% ngay cả khi chỉ dùng độ lớn dòng/áp. Đó là dấu hiệu **rò rỉ dữ liệu (data leakage)**: với quá ít trạng thái tải, mô hình học thuộc được dòng điện "bình thường" là bao nhiêu.
- **Câu chuyện này rất đáng kể khi phỏng vấn.** Nó cho thấy bạn nghi ngờ một kết quả quá đẹp và đi tìm nguyên nhân.

**Nhiễu đo:** sai số 1% về độ lớn và 0,5° về góc pha (mô phỏng sai số biến dòng/biến áp đo lường).

**Mỗi thiết bị đo (đặc trưng cho ML):**
- Độ lớn dòng 3 pha `Ia, Ib, Ic` và điện áp 3 pha `Va, Vb, Vc`.
- **Đại lượng gia số (incremental / superimposed):** `dIa = |Ia(sự cố) − Ia(trước sự cố)|`, tính bằng số phức. Đây chính là phần dòng do sự cố "thêm vào". Recloser hiện đại lưu bản ghi sự kiện có cả vài chu kỳ trước sự cố, nên thiết bị tự tính được đại lượng này mà không cần đồng bộ thời gian.
- **Thành phần thứ tự:** `I0` (thứ tự không, gần với dòng chạm đất) và `I2` (thứ tự nghịch, phản ánh mất cân bằng).

**Câu hỏi có thể bị hỏi**
- *Vì sao phải khóa nấc bộ điều áp khi mô phỏng sự cố?* Đã giải thích ở trên: bảo vệ nhanh hơn bộ điều áp rất nhiều.
- *Sự cố trở kháng cao ngoài đời có giống mô phỏng không?* Không hoàn toàn. Ngoài đời có hồ quang chập chờn, phi tuyến. Mô phỏng dùng điện trở tuyến tính, nên kết quả ở 200–400 Ω là **giới hạn trên** của độ chính xác thực tế.

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
- *Mô hình sai ở đâu?* Xem `results/figures/confusion_ml.png` và phần phân tích lỗi đầy đủ trong `results/error_analysis/` (chạy `scripts/error_analysis.py`). Lỗi tập trung ở các vùng gần trạm (Sw1, Sw2, Sw4, L13). Ở đó dòng tải qua các thiết bị là 240–630 A, nên sai số đo 1% (2–6 A) xấp xỉ dòng sự cố 400 Ω (khoảng 6 A). Vùng ở cuối lưới có dòng tải nhỏ, nên sự cố trở kháng cao lại dễ nhận ra hơn.
- *Kết quả chính?* ML đúng 97,7% (FPI cổ điển 56,1%). Với sự cố chạm đất 100 Ω: ML đúng 98,4%, FPI chỉ 8,4%. Mất một cảm biến bất kỳ: ML vẫn đúng 83–96%. Quãng dây đội phải tuần tra trung bình giảm từ 39,0 kft xuống 5,1 kft.

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

## 8. Trang báo cáo (`shf/dashboard.py` → `docs/index.html`)

- **Mở trên mạng:** https://chau1912550.github.io/self-healing-feeder/?lang=vi (GitHub Pages, miễn phí, không cần cài gì, xem được trên điện thoại).
- **Hai ngôn ngữ:** nút **EN / VI** ở góc trên đổi toàn bộ chữ, nhãn biểu đồ và chú thích. Thêm `?lang=vi` hoặc `?lang=en` vào link để gửi đúng ngôn ngữ.
- **Tiện ích đọc hiểu:** ô *Tóm lại* đầu mỗi mục; từ gạch chân chấm chấm có định nghĩa khi rê chuột hoặc chạm; mục *Thuật ngữ* (19 từ); mục *Hỏi đáp* 15 câu có ô tìm kiếm (gõ không dấu vẫn được), lọc theo chủ đề, mở tất cả, sao chép link từng câu; thanh trên cùng nhảy tới từng mục; nút ◐ đổi giao diện tự động / sáng / tối; in ra giấy sẽ tự mở hết câu trả lời.
- **Nhân vật hướng dẫn (kiểu heyclicky):** nhấp vào bất kỳ thẻ, biểu đồ, bảng nào (hoặc nút **?** ở góc của nó). Nhân vật bay tới, vẽ khoanh quanh thành phần đó và mở khung giải thích 3 ý: *Đây là gì / Đọc thế nào / Vì sao quan trọng*. Nút Trước / Tiếp (hoặc phím ← →) đi qua cả 15 thành phần, Esc để đóng. Gửi link có `?explain=heat` (hoặc `tile-acc`, `chart-res`…) thì người nhận mở ra là thấy giải thích ngay phần đó.
- **Tour 30 giây** ở đầu trang: hình vẽ gọn một tuyến điện tự chạy 5 bước (sự cố → mất điện → mô hình chỉ ra zone → cô lập và cấp điện lại → đội sửa đi thẳng tới chỗ lỗi), số liệu lấy từ lần chạy mới nhất, cuối cùng gợi ý đọc tiếp theo thứ tự nào. Có nút Tạm dừng / Xem lại, hoặc nhấp vào từng bước.
- **Chế độ giải thích luôn bật** cho mọi người xem, không có nút tắt.
- **Nút Monitor** (màu cam, trên cùng trang) mở trang giám sát theo vai trò ở `docs/monitor/`: điều độ viên, đội hiện trường, kỹ sư, quản lý, mỗi vai trò có khung *How to handle* riêng.
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
