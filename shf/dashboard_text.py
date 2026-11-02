"""English and Vietnamese text for the report page: questions & answers and the glossary.

Answers are templates. `{name}` fields are filled from the latest results by
shf/dashboard.py (see `numbers()`), so the page never quotes a stale number.
Entries with needs_ea=True use the error analysis and are skipped until
scripts/error_analysis.py has been run.
"""

CATEGORIES = [  # (key, English, Vietnamese)
    ("project", "Project", "Dự án"),
    ("results", "Results", "Kết quả"),
    ("model", "Model", "Mô hình"),
    ("restoration", "Restoration", "Khôi phục"),
    ("limits", "Limits & next steps", "Giới hạn & bước tiếp"),
]

FAQ = [
    {"id": "problem", "cat": "project",
     "q": ("What problem does this project solve?",
           "Dự án này giải quyết vấn đề gì?"),
     "a": ("<p>When a fault trips the feeder-head recloser to lockout, the whole feeder goes dark and a crew has to "
           "patrol the line to find the fault. This study (1) tells the operator <b>which of the 10 switching zones</b> "
           "holds the fault, using only measurements that reclosers and automated switches already record, and "
           "(2) <b>isolates that zone and restores the healthy ones</b> through tie switches, closing a tie only when a "
           "power flow shows every limit is met. Utilities call this FLISR.</p>",
           "<p>Khi sự cố làm recloser đầu tuyến cắt hẳn (lockout), cả tuyến mất điện và đội sửa chữa phải đi dọc "
           "đường dây để tìm chỗ hỏng. Nghiên cứu này (1) chỉ ra <b>sự cố nằm ở zone nào trong 10 zone</b>, chỉ dùng "
           "số đo mà recloser và dao tự động vốn đã ghi lại, và (2) <b>cô lập zone đó rồi cấp điện lại cho các zone "
           "còn lành</b> qua dao liên lạc (tie), chỉ đóng tie khi tính trào lưu công suất cho thấy mọi giới hạn đều "
           "đạt. Các công ty điện gọi hệ thống này là FLISR.</p>")},
    {"id": "real-data", "cat": "project",
     "q": ("Is this real utility data?",
           "Đây có phải dữ liệu thật của công ty điện không?"),
     "a": ("<p>No. Everything is simulated in OpenDSS on the IEEE 123-bus test feeder: {faults} faults of every "
           "type, fault resistances from 0.01 to 400 Ω, random load levels and 1% sensor noise. Simulation gives exact "
           "labels and lets every bus be faulted. Real high-impedance faults arc and change over time, so the "
           "high-resistance results here are an upper bound, and a real deployment would have to be validated on "
           "field event records.</p>",
           "<p>Không. Toàn bộ là mô phỏng trong OpenDSS trên lưới thử nghiệm IEEE 123-bus: {faults} sự cố đủ các "
           "loại, điện trở sự cố từ 0.01 đến 400 Ω, mức tải ngẫu nhiên và nhiễu cảm biến 1%. Mô phỏng cho nhãn "
           "chính xác và cho phép tạo sự cố ở mọi bus. Sự cố trở kháng cao ngoài thực tế có hồ quang và thay đổi "
           "theo thời gian, nên kết quả ở điện trở cao chỉ là giới hạn trên; muốn dùng thật thì phải kiểm chứng bằng "
           "bản ghi sự kiện ngoài hiện trường.</p>")},
    {"id": "run-it", "cat": "project",
     "q": ("How can I run it myself?",
           "Tôi tự chạy thử thế nào?"),
     "a": ("<p>Clone the repository, create a Python environment and install <code>requirements.txt</code>. Then "
           "<code>python run.py</code> runs the full study (6–8 minutes) and "
           "<code>python scripts/error_analysis.py</code> adds the error breakdown (about a minute). Both rebuild this "
           "page at the end. To run without installing anything, use the Kaggle notebook in "
           "<code>notebooks/</code>.</p>",
           "<p>Clone repo, tạo môi trường Python và cài <code>requirements.txt</code>. Sau đó "
           "<code>python run.py</code> chạy toàn bộ nghiên cứu (6–8 phút) và "
           "<code>python scripts/error_analysis.py</code> thêm phần phân tích lỗi (khoảng 1 phút). Cả hai đều tự "
           "dựng lại trang này khi chạy xong. Muốn chạy mà không cài gì thì dùng notebook Kaggle trong "
           "<code>notebooks/</code>.</p>")},
    {"id": "ai", "cat": "project",
     "q": ("Was AI used to build this?",
           "Dự án có dùng AI hỗ trợ không?"),
     "a": ("<p>Yes. It was built with AI-assisted development (Claude Code), as the README states. Every assumption "
           "is marked in <code>shf/config.py</code> and every number on this page comes from code that anyone can "
           "rerun and check.</p>",
           "<p>Có. Dự án được làm với sự hỗ trợ của AI (Claude Code), như README đã ghi. Mọi giả định đều được đánh "
           "dấu trong <code>shf/config.py</code> và mọi con số trên trang đều đến từ code mà ai cũng có thể chạy "
           "lại và kiểm tra.</p>")},
    {"id": "why-not-accuracy", "cat": "results", "needs_ea": True,
     "q": ("Why not just report accuracy? What do FNR and FPR mean here?",
           "Sao không chỉ báo accuracy? FNR và FPR ở đây nghĩa là gì?"),
     "a": ("<p>Accuracy ({acc}) hides <i>which</i> faults are missed and where the wrong answers go. The model "
           "always names one of 10 zones, so misses and false blames are counted per zone, one zone against the "
           "rest:</p><ul><li><b>FNR</b>: share of a zone's faults that were placed somewhere else.</li>"
           "<li><b>FPR</b>: share of other zones' faults that were blamed on this zone.</li></ul>"
           "<p>The worst FNR is {fnr_zone} at {fnr_max} and the worst FPR is {fpr_zone} at {fpr_max}; zones at the "
           "ends of the feeder stay at or below {leaf_fnr} FNR. The full table is in section 2.</p>",
           "<p>Accuracy ({acc}) che mất việc sự cố <i>nào</i> bị bỏ sót và câu trả lời sai rơi vào đâu. Model luôn "
           "chọn 1 trong 10 zone, nên bỏ sót và báo nhầm được tính theo từng zone, một zone so với phần còn lại:</p>"
           "<ul><li><b>FNR</b>: tỉ lệ sự cố của zone đó bị đoán sang zone khác.</li>"
           "<li><b>FPR</b>: tỉ lệ sự cố ở zone khác bị đổ cho zone này.</li></ul>"
           "<p>FNR cao nhất là {fnr_zone} với {fnr_max}, FPR cao nhất là {fpr_zone} với {fpr_max}; các zone ở cuối "
           "tuyến có FNR không quá {leaf_fnr}. Bảng đầy đủ ở mục 2.</p>")},
    {"id": "what-missed", "cat": "results", "needs_ea": True,
     "q": ("Which faults does the model miss most, and why?",
           "Model hay bỏ sót loại sự cố nào, và tại sao?"),
     "a": ("<p><b>Weak line-to-ground faults.</b> {slg_hi} of the {errors} errors ({slg_hi_share}) are ground "
           "faults at 200 Ω or more. At 400 Ω the error rate is {err400}; for three-phase faults it is {err3ph}.</p>"
           "<p>The reason is physics: a 400 Ω fault on a 2.4 kV phase draws about 6 A, while devices on the main "
           "trunk carry hundreds of amps of load, so the fault is about 1% of the signal, the same size as sensor "
           "noise. Heavier load makes it worse: the error rate is {load_lo} in the lightest third of load scenarios "
           "and {load_hi} in the heaviest third.</p>",
           "<p><b>Sự cố chạm đất một pha có dòng nhỏ.</b> {slg_hi} trên {errors} lỗi ({slg_hi_share}) là sự cố "
           "chạm đất từ 200 Ω trở lên. Ở 400 Ω tỉ lệ sai là {err400}; với sự cố ba pha là {err3ph}.</p>"
           "<p>Lý do là vật lý: sự cố 400 Ω trên pha 2.4 kV chỉ tạo khoảng 6 A, trong khi thiết bị trên trục chính "
           "mang dòng tải hàng trăm ampe, nên dòng sự cố chỉ cỡ 1% tín hiệu, ngang nhiễu cảm biến. Tải càng nặng "
           "càng khó: tỉ lệ sai là {load_lo} ở 1/3 kịch bản tải nhẹ nhất và {load_hi} ở 1/3 nặng nhất.</p>")},
    {"id": "where-wrong", "cat": "results", "needs_ea": True,
     "q": ("When the model is wrong, where does it point? Does that matter?",
           "Khi model sai, nó đoán sang đâu? Điều đó có quan trọng không?"),
     "a": ("<p>Usually next door. {off1} of errors are off by exactly one zone and {same_path} stay on the same "
           "path from the substation; the largest pair is {top_pair} ({top_n} faults). The model leans toward the "
           "substation ({upstream} of errors): when a fault is tiny, only the feeder-head device still sees a "
           "change.</p><p>It matters because a wrong zone means the faulted section is not the one switched out, so "
           "re-closing or tie restoration could re-energize the fault. Real schemes guard against this by checking "
           "for fault current after each switching step; this study does not yet simulate those consequences.</p>",
           "<p>Thường là zone ngay bên cạnh. {off1} số lỗi lệch đúng 1 zone và {same_path} nằm trên cùng một đường "
           "đi từ trạm ra; cặp nhầm nhiều nhất là {top_pair} ({top_n} sự cố). Model có xu hướng đoán về phía trạm "
           "({upstream} số lỗi): khi sự cố quá nhỏ thì chỉ thiết bị đầu tuyến còn thấy thay đổi.</p>"
           "<p>Điều này quan trọng vì đoán sai zone nghĩa là đoạn bị cắt ra không phải đoạn đang sự cố, nên khi đóng "
           "lại hoặc cấp điện qua tie có thể đóng điện vào đúng chỗ sự cố. Hệ thống thật chặn việc này bằng cách "
           "kiểm tra dòng sự cố sau mỗi bước đóng cắt; nghiên cứu này chưa mô phỏng các hậu quả đó.</p>")},
    {"id": "fpi-bad", "cat": "results",
     "q": ("Why does the conventional method do so badly?",
           "Sao phương pháp truyền thống lại kém như vậy?"),
     "a": ("<p>Fault passage indicators flag when current exceeds a fixed pickup (here 2× peak load for phase "
           "current, plus a residual-current threshold for ground), and the fault is placed after the deepest "
           "flagged device. That works for three-phase and line-to-line faults ({fpi_3ph} and {fpi_ll} correct) but "
           "not for ground faults ({fpi_slg}):</p><ul><li>High-resistance faults stay below pickup, so on "
           "{fpi_none} of all faults no device flags at all.</li><li>A bolted ground fault collapses that phase's "
           "voltage, single-phase loads beyond it drop out, and downstream devices raise false ground flags "
           "({bolted_fpi} correct at 0.01 Ω).</li></ul><p>Real schemes add directional elements, so this baseline "
           "is on the pessimistic side.</p>",
           "<p>Bộ chỉ báo dòng sự cố (FPI) bật cờ khi dòng vượt ngưỡng cố định (ở đây là 2 lần dòng tải đỉnh cho "
           "dòng pha, cộng một ngưỡng dòng dư cho chạm đất), rồi sự cố được xác định nằm sau thiết bị bật cờ xa "
           "nhất. Cách này tốt với sự cố ba pha và hai pha (đúng {fpi_3ph} và {fpi_ll}) nhưng kém với chạm đất "
           "({fpi_slg}):</p><ul><li>Sự cố điện trở cao không vượt ngưỡng, nên ở {fpi_none} tổng số sự cố không "
           "thiết bị nào bật cờ.</li><li>Sự cố chạm đất trực tiếp làm sụp điện áp pha đó, các tải một pha phía sau "
           "rớt ra, và thiết bị phía dưới bật cờ chạm đất giả (chỉ đúng {bolted_fpi} ở 0.01 Ω).</li></ul>"
           "<p>Hệ thống thật có thêm phần tử định hướng, nên baseline này hơi bi quan.</p>")},
    {"id": "memorizing", "cat": "model",
     "q": ("How do you know the model is not memorizing the test data?",
           "Làm sao biết model không “học thuộc” dữ liệu kiểm tra?"),
     "a": ("<p>Validation is grouped by fault bus (5-fold GroupKFold): every test fault sits on a bus the model "
           "never saw a fault at during training, so near-duplicate rows (same bus, different resistance) cannot "
           "leak into the test.</p><p>An early version still scored 99.9% with simple magnitude features, which was "
           "too good to be true: with only three fixed load levels the model had memorized “normal” current. "
           "Randomizing feeder-wide and per-load demand removed the leak and produced the realistic gap shown here "
           "({acc_mag} with magnitudes only vs {acc} with full features).</p>",
           "<p>Kiểm định được chia nhóm theo bus sự cố (GroupKFold 5 phần): mọi sự cố dùng để kiểm tra nằm ở bus "
           "mà model chưa từng thấy sự cố khi huấn luyện, nên các dòng gần giống nhau (cùng bus, khác điện trở) "
           "không lọt sang tập kiểm tra.</p><p>Phiên bản đầu vẫn đạt 99.9% chỉ với đặc trưng biên độ đơn giản, tốt "
           "đến mức đáng ngờ: chỉ có 3 mức tải cố định nên model đã học thuộc dòng điện “bình thường”. Ngẫu nhiên "
           "hóa phụ tải toàn tuyến và từng tải đã bịt chỗ rò rỉ đó và cho ra khoảng cách thực tế như trên trang "
           "({acc_mag} khi chỉ dùng biên độ so với {acc} khi đủ đặc trưng).</p>")},
    {"id": "features", "cat": "model",
     "q": ("What does the model actually look at?",
           "Model thực sự nhìn vào những gì?"),
     "a": ("<p>For each of the 10 devices: phase currents, residual (zero-sequence) current, phase voltages, and how "
           "much each changed from just before the fault to during it, plus the change in negative-sequence "
           "current. A recloser's event record holds all of these.</p><p>Instantaneous magnitudes alone (what a "
           "basic SCADA poll returns) give {acc_mag}. Adding the before/after change gives {acc}, and for 100 Ω "
           "ground faults lifts accuracy from {r100_mag} to {r100}. The classifier is gradient-boosted trees "
           "(scikit-learn HistGradientBoosting).</p>",
           "<p>Với mỗi thiết bị trong 10 thiết bị: dòng các pha, dòng dư (thứ tự không), điện áp các pha, và mức "
           "thay đổi của từng đại lượng từ ngay trước sự cố sang lúc sự cố, cộng thêm thay đổi dòng thứ tự nghịch. "
           "Bản ghi sự kiện của recloser có đủ các số này.</p><p>Chỉ dùng biên độ tức thời (thứ mà một lần hỏi vòng "
           "SCADA cơ bản trả về) đạt {acc_mag}. Thêm phần thay đổi trước/sau đạt {acc}, và với sự cố chạm đất "
           "100 Ω thì tăng từ {r100_mag} lên {r100}. Bộ phân loại là cây tăng cường gradient (HistGradientBoosting "
           "của scikit-learn).</p>")},
    {"id": "sensor-offline", "cat": "model",
     "q": ("What happens if a sensor stops reporting?",
           "Nếu một cảm biến ngừng gửi số liệu thì sao?"),
     "a": ("<p>During training one random device is blanked on {dropout} of the rows, so the model learns to cope. "
           "With any single device offline it still places {miss_lo}–{miss_hi} of faults correctly; the worst case "
           "is {miss_dev} offline ({miss_lo}).</p>",
           "<p>Khi huấn luyện, {dropout} số dòng bị xóa ngẫu nhiên số liệu của một thiết bị, nên model học cách "
           "xoay xở. Khi bất kỳ một thiết bị nào mất tín hiệu, model vẫn đoán đúng {miss_lo}–{miss_hi} số sự cố; "
           "trường hợp tệ nhất là mất {miss_dev} ({miss_lo}).</p>")},
    {"id": "not-sure", "cat": "model", "needs_ea": True,
     "q": ("What does “let the model say not sure” mean in practice?",
           "“Cho model nói không chắc” nghĩa là gì trong thực tế?"),
     "a": ("<p>The model gives a probability for each zone. When the top probability is below a cutoff, the system "
           "does not act on the guess and the crew patrols as it does today. Wrong answers have a median confidence "
           "of {conf_wrong}, right ones {conf_right}, so a 0.95 cutoff defers only {deferred} of faults, raises "
           "accuracy on the rest to {acc_kept}, and cuts errors from {errors} to {errors_kept} (−{err_cut}).</p>",
           "<p>Model đưa ra xác suất cho từng zone. Khi xác suất cao nhất thấp hơn ngưỡng, hệ thống không hành động "
           "theo dự đoán đó và đội sửa chữa đi tuần như hiện nay. Câu trả lời sai có độ tự tin trung vị "
           "{conf_wrong}, câu đúng là {conf_right}, nên với ngưỡng 0.95 chỉ {deferred} số sự cố bị chuyển sang tuần "
           "tra tay, accuracy phần còn lại lên {acc_kept}, và số lỗi giảm từ {errors} xuống {errors_kept} "
           "(−{err_cut}).</p>")},
    {"id": "not-all-restored", "cat": "restoration",
     "q": ("Why is not all healthy load restored?",
           "Sao không cấp điện lại được hết phần phụ tải còn lành?"),
     "a": ("<p>A tie can only carry what the other source and the long path can support. Every pickup is tested "
           "with a power flow and rejected if any node leaves {vmin}–{vmax} pu, a line exceeds its emergency "
           "rating, or the feeder stops being radial. On this 4.16 kV feeder voltage is the limit that binds, not "
           "current. Across the 10 cases the ties restored {kw_back} of the {kw_dark} kW left dark ({kw_share}); the "
           "rest waits for the repair.</p>",
           "<p>Một dao liên lạc chỉ mang được phần tải mà nguồn bên kia và đường dây dài chịu được. Mỗi lần nhận "
           "thêm tải đều được kiểm tra bằng tính trào lưu công suất và bị loại nếu có nút nào ra ngoài "
           "{vmin}–{vmax} pu, có đường dây vượt định mức khẩn cấp, hoặc lưới không còn hình tia. Trên tuyến 4.16 kV "
           "này, giới hạn quyết định là điện áp chứ không phải dòng điện. Qua 10 trường hợp, các tie cấp lại được "
           "{kw_back} trên {kw_dark} kW bị mất điện ({kw_share}); phần còn lại chờ sửa xong.</p>")},
    {"id": "outage-number", "cat": "restoration",
     "q": ("Where does the {kwmin}% outage reduction come from, and how far can I trust it?",
           "Con số giảm {kwmin}% mức mất điện từ đâu ra, tin được đến đâu?"),
     "a": ("<p>Customer outage is counted in kW·min: kW interrupted × minutes interrupted. The automated case "
           "assumes {t_auto} min to isolate and restore by tie, the manual case {t_man} min, and repair {t_rep} min. "
           "Zones are weighted by line length (faults per mile assumed equal). The saving ranges from {kwmin_lo} "
           "(fault in {kwmin_lo_zone}) to {kwmin_hi} (fault in {kwmin_hi_zone}).</p><p>The number moves directly "
           "with those time assumptions, so read it as an illustration, not a forecast.</p>",
           "<p>Mức mất điện của khách hàng được tính bằng kW·phút: kW bị mất × số phút mất. Trường hợp tự động giả "
           "định {t_auto} phút để cô lập và cấp lại qua tie, thủ công {t_man} phút, sửa chữa {t_rep} phút. Các zone "
           "được tính trọng số theo chiều dài đường dây (giả định số sự cố trên mỗi dặm như nhau). Mức tiết kiệm dao "
           "động từ {kwmin_lo} (sự cố ở {kwmin_lo_zone}) đến {kwmin_hi} (sự cố ở {kwmin_hi_zone}).</p><p>Con số "
           "thay đổi trực tiếp theo các giả định thời gian này, nên chỉ xem là minh họa, không phải dự báo.</p>")},
    {"id": "next-steps", "cat": "limits",
     "q": ("What are the limitations, and what would you do next?",
           "Giới hạn là gì, và bước tiếp theo là gì?"),
     "a": ("<ul><li><b>False alarms:</b> add healthy, no-fault cases; today the dataset holds only faults, so false "
           "alarms on a normal feeder are not measured.</li><li><b>Realistic weak faults:</b> model arcing, "
           "time-varying high-impedance faults instead of fixed resistances.</li><li><b>Consequences of a wrong "
           "zone:</b> simulate re-closing onto the fault and add a fault-current check after each switching "
           "step.</li><li><b>Fairer baseline:</b> compare against fault indicators with directional "
           "elements.</li><li><b>Field data:</b> validate on real event records from a utility.</li></ul>",
           "<ul><li><b>Báo động giả:</b> thêm các ca lưới bình thường, không sự cố; hiện dataset chỉ có ca sự cố nên "
           "chưa đo được báo động giả.</li><li><b>Sự cố yếu thực tế hơn:</b> mô hình hóa sự cố trở kháng cao có hồ "
           "quang, thay đổi theo thời gian thay vì điện trở cố định.</li><li><b>Hậu quả khi đoán sai zone:</b> mô "
           "phỏng việc đóng lại vào chỗ sự cố và thêm bước kiểm tra dòng sự cố sau mỗi lần đóng cắt.</li>"
           "<li><b>Baseline công bằng hơn:</b> so với bộ chỉ báo sự cố có phần tử định hướng.</li>"
           "<li><b>Dữ liệu thực địa:</b> kiểm chứng bằng bản ghi sự kiện thật của một công ty điện.</li></ul>")},
]

# key: (English term, English definition, Vietnamese term, Vietnamese definition)
GLOSSARY = {
    "flisr": ("FLISR", "Fault Location, Isolation and Service Restoration: find the faulted section, switch it out, "
              "and bring power back to everyone else.",
              "FLISR", "Định vị sự cố, cô lập và khôi phục cấp điện: tìm đoạn hỏng, cắt nó ra, rồi cấp điện lại cho "
              "phần còn lại."),
    "recloser": ("Recloser / lockout", "A line breaker that trips on a fault and recloses a few times; if the fault "
                 "is still there it stays open (lockout).",
                 "Recloser / lockout", "Máy cắt trên đường dây, cắt khi có sự cố rồi tự đóng lại vài lần; nếu sự cố "
                 "vẫn còn thì mở hẳn (lockout)."),
    "zone": ("Zone", "The section of feeder between switching devices: the smallest piece that can be switched out.",
             "Zone (vùng)", "Đoạn lưới nằm giữa các thiết bị đóng cắt: phần nhỏ nhất có thể cắt ra riêng."),
    "tie": ("Tie switch", "A normally-open switch that connects this feeder to another source to pick up load.",
            "Dao liên lạc (tie)", "Dao thường mở, khi đóng sẽ nối tuyến này với nguồn khác để nhận tải."),
    "fpi": ("FPI", "Fault passage indicator: flags when a current above a fixed pickup flows through it.",
            "FPI", "Bộ chỉ báo dòng sự cố đi qua: bật cờ khi có dòng vượt ngưỡng cố định chạy qua."),
    "types": ("SLG / LL / LLG / 3PH", "Fault types: single line-to-ground, line-to-line, double line-to-ground, "
              "three-phase.",
              "SLG / LL / LLG / 3PH", "Loại sự cố: một pha chạm đất, hai pha chạm nhau, hai pha chạm đất, ba pha."),
    "hif": ("High-impedance fault", "A fault through a large resistance (a tree, dry ground), so the fault current is "
            "small and hard to detect.",
            "Sự cố trở kháng cao", "Sự cố qua điện trở lớn (cây, đất khô), dòng sự cố nhỏ nên khó phát hiện."),
    "pu": ("pu (per unit)", "A value divided by its nominal value: 1.00 pu voltage is exactly nominal.",
           "pu (đơn vị tương đối)", "Giá trị chia cho giá trị định mức: điện áp 1.00 pu là đúng định mức."),
    "c841": ("ANSI C84.1 Range A", "The US service-voltage band: 114–126 V on a 120 V base (0.95–1.05 pu).",
             "ANSI C84.1 Range A", "Dải điện áp cung cấp chuẩn của Mỹ: 114–126 V trên nền 120 V (0.95–1.05 pu)."),
    "radial": ("Radial", "Tree-shaped feeder with one path from the source to every load and no loops; feeder "
               "protection relies on it.",
               "Hình tia (radial)", "Lưới dạng cây, mỗi phụ tải chỉ có một đường từ nguồn và không có vòng kín; hệ "
               "thống bảo vệ dựa vào điều này."),
    "kwmin": ("kW·min", "Size of an outage: kW interrupted × minutes interrupted.",
              "kW·phút", "Mức mất điện: số kW bị mất × số phút mất."),
    "kft": ("kft", "Thousand feet of line (1 kft ≈ 305 m).",
            "kft", "Nghìn feet đường dây (1 kft ≈ 305 m)."),
    "fnr": ("FNR", "False negative rate of a zone: the share of its faults that were placed in another zone.",
            "FNR", "Tỉ lệ bỏ sót của một zone: phần sự cố của zone đó bị đoán sang zone khác."),
    "fpr": ("FPR", "False positive rate of a zone: the share of other zones' faults that were blamed on it.",
            "FPR", "Tỉ lệ báo nhầm của một zone: phần sự cố ở zone khác bị đổ cho zone này."),
    "precision": ("Precision", "When the model names this zone, how often it is right.",
                  "Precision", "Khi model chọn zone này, tỉ lệ chọn đúng là bao nhiêu."),
    "confusion": ("Confusion matrix", "Table of true zone (rows) against predicted zone (columns); cells off the "
                  "diagonal are mistakes.",
                  "Ma trận nhầm lẫn", "Bảng zone thật (hàng) so với zone dự đoán (cột); các ô ngoài đường chéo là "
                  "lỗi."),
    "grouped": ("Grouped cross-validation", "Testing only on buses the model never saw in training, so the score "
                "reflects new locations.",
                "Kiểm định chéo theo nhóm", "Chỉ kiểm tra trên các bus model chưa thấy khi huấn luyện, nên điểm số "
                "phản ánh vị trí mới."),
    "confidence": ("Confidence", "The probability the model gives to the zone it picks (0 to 1).",
                   "Độ tự tin", "Xác suất model gán cho zone nó chọn (từ 0 đến 1)."),
    "opendss": ("OpenDSS", "EPRI's open-source simulator for electric distribution systems.",
                "OpenDSS", "Phần mềm mô phỏng lưới phân phối điện mã nguồn mở của EPRI."),
}

# What the guide buddy says when a reader clicks a card, chart or table. The key is the
# element's data-x attribute; each field is (English, Vietnamese) and may use {name} fields.
EXPLAIN = {
    "tile-acc": {
        "title": ("Fault zone found", "Tìm đúng zone sự cố"),
        "what": ("The share of simulated faults where the model named the right one of the 10 zones, tested on buses "
                 "it never saw in training.",
                 "Tỉ lệ sự cố mô phỏng mà model chọn đúng 1 trong 10 zone, kiểm tra trên các bus model chưa từng thấy "
                 "khi huấn luyện."),
        "read": ("{acc} for the model against {acc_fpi} for conventional fault indicators. Higher is better; a blind "
                 "guess would get about 10%.",
                 "Model đạt {acc}, bộ chỉ báo sự cố truyền thống đạt {acc_fpi}. Càng cao càng tốt; đoán mò chỉ được "
                 "khoảng 10%."),
        "why": ("A correct zone sends the crew to one section instead of the whole feeder, so power comes back sooner.",
                "Đoán đúng zone thì đội sửa chữa chỉ cần tới một đoạn thay vì cả tuyến, nên có điện lại sớm hơn."),
    },
    "tile-patrol": {
        "title": ("Average crew patrol", "Quãng đường tuần tra trung bình"),
        "what": ("How much line a crew has to check, on average, to find the fault. A wrong zone is charged a "
                 "full-feeder patrol.",
                 "Trung bình đội sửa chữa phải kiểm tra bao nhiêu đường dây để tìm chỗ hỏng. Đoán sai zone bị tính như "
                 "đi cả tuyến."),
        "read": ("{patrol_ml} kft with the model vs {patrol_none} kft with no fault location (1 kft ≈ 305 m). Lower "
                 "is better.",
                 "{patrol_ml} kft khi có model so với {patrol_none} kft khi không định vị (1 kft ≈ 305 m). Càng thấp "
                 "càng tốt."),
        "why": ("Patrolling is a large part of every outage, especially at night or in a storm.",
                "Đi tuần chiếm phần lớn thời gian mỗi lần mất điện, nhất là ban đêm hoặc khi có bão."),
    },
    "tile-restore": {
        "title": ("Healthy load restored by ties", "Phụ tải lành được cấp lại qua tie"),
        "what": ("Load in healthy zones that goes dark only because it sits beyond the fault, then gets power back "
                 "through a tie switch from another source.",
                 "Phụ tải ở các zone lành bị mất điện chỉ vì nằm phía sau chỗ sự cố, rồi được cấp điện lại qua dao "
                 "liên lạc từ nguồn khác."),
        "read": ("{kw_back} of {kw_dark} kW, summed over the 10 fault cases ({kw_share}). The rest waits for the "
                 "repair.",
                 "{kw_back} trên {kw_dark} kW, cộng qua 10 trường hợp sự cố ({kw_share}). Phần còn lại chờ sửa xong."),
        "why": ("Every kW picked up early is customers back in minutes instead of hours.",
                "Mỗi kW được cấp lại sớm là khách hàng có điện sau vài phút thay vì vài giờ."),
    },
    "tile-kwmin": {
        "title": ("Customer outage (kW·min)", "Mức mất điện khách hàng (kW·phút)"),
        "what": ("Outage size, kW interrupted × minutes interrupted, compared between automated and manual "
                 "switching.",
                 "Mức mất điện, tính bằng kW bị mất × số phút mất, so sánh giữa đóng cắt tự động và thủ công."),
        "read": ("−{kwmin}% means automation removes about half of the outage, assuming {t_auto} min automated, "
                 "{t_man} min manual and {t_rep} min repair.",
                 "−{kwmin}% nghĩa là tự động hóa giảm khoảng một nửa mức mất điện, với giả định tự động {t_auto} phút, "
                 "thủ công {t_man} phút, sửa chữa {t_rep} phút."),
        "why": ("It is the number a utility cares about, but it moves with the time assumptions, so read it as an "
                "illustration.",
                "Đây là con số công ty điện quan tâm, nhưng nó thay đổi theo giả định thời gian, nên chỉ xem là minh "
                "họa."),
    },
    "tile-faults": {
        "title": ("Faults simulated", "Số sự cố mô phỏng"),
        "what": ("Every fault simulated in OpenDSS: four fault types across the feeder's buses, fault resistances from "
                 "0.01 to 400 Ω, random load and sensor noise.",
                 "Toàn bộ sự cố đã mô phỏng trong OpenDSS: 4 loại sự cố trên các bus của tuyến, điện trở sự cố từ 0.01 "
                 "đến 400 Ω, tải ngẫu nhiên và nhiễu cảm biến."),
        "read": ("{faults} faults in total. Most are line-to-ground (SLG), the most common fault on real feeders.",
                 "Tổng cộng {faults} sự cố. Phần lớn là chạm đất một pha (SLG), loại sự cố hay gặp nhất ngoài thực tế."),
        "why": ("A large, varied dataset is what allows testing on buses the model never saw.",
                "Dữ liệu lớn và đa dạng mới cho phép kiểm tra model trên các bus nó chưa từng thấy."),
    },
    "health": {
        "title": ("Run checks", "Kiểm tra lần chạy"),
        "what": ("An automatic checklist built from the results every time the study runs.",
                 "Danh sách kiểm tra tự động, tạo từ kết quả mỗi lần chạy nghiên cứu."),
        "read": ("Pass = meets its limit, Watch = a known weak spot, Fail = fix before trusting the numbers.",
                 "Đạt = nằm trong giới hạn, Lưu ý = điểm yếu đã biết, Lỗi = phải sửa trước khi tin vào số liệu."),
        "why": ("Read it first: it tells you whether the rest of the page can be trusted.",
                "Nên đọc phần này trước: nó cho biết có nên tin phần còn lại của trang hay không."),
    },
    "chart-res": {
        "title": ("Accuracy vs fault resistance", "Độ chính xác theo điện trở sự cố"),
        "what": ("How often each method finds the right zone for line-to-ground faults, from a bolted fault (0.01 Ω) "
                 "to a very weak one (400 Ω).",
                 "Mỗi phương pháp đoán đúng zone bao nhiêu với sự cố chạm đất một pha, từ chạm trực tiếp (0.01 Ω) tới "
                 "rất yếu (400 Ω)."),
        "read": ("One line per method; higher is better. Look where a line drops: at 100 Ω the model is at {r100}, "
                 "fault indicators at {r100_fpi}. Hover a point for exact numbers.",
                 "Mỗi đường là một phương pháp; càng cao càng tốt. Chú ý chỗ đường bắt đầu rơi: ở 100 Ω model đạt "
                 "{r100}, bộ chỉ báo sự cố chỉ {r100_fpi}. Rê chuột vào điểm để xem số."),
        "why": ("Weak ground faults are the hard case in the field; this chart shows which method still works there.",
                "Sự cố chạm đất yếu là trường hợp khó ngoài thực tế; biểu đồ cho thấy phương pháp nào vẫn dùng được."),
    },
    "table-type": {
        "title": ("Accuracy by fault type", "Độ chính xác theo loại sự cố"),
        "what": ("Accuracy split by fault type: three-phase, line-to-line, double line-to-ground and single "
                 "line-to-ground.",
                 "Độ chính xác chia theo loại sự cố: ba pha, hai pha, hai pha chạm đất và một pha chạm đất."),
        "read": ("Compare down each column. Fault indicators do well on 3PH and LL ({fpi_3ph}, {fpi_ll}) but poorly "
                 "on SLG ({fpi_slg}).",
                 "So sánh theo từng cột. Bộ chỉ báo sự cố tốt với 3PH và LL ({fpi_3ph}, {fpi_ll}) nhưng kém với SLG "
                 "({fpi_slg})."),
        "why": ("Ground faults are the most common, so weakness on SLG is weakness where it matters most.",
                "Chạm đất là loại hay gặp nhất, nên yếu ở SLG là yếu đúng chỗ quan trọng nhất."),
    },
    "chart-sensor": {
        "title": ("One sensor offline", "Mất một cảm biến"),
        "what": ("Accuracy when one of the 10 measuring devices stops reporting, one device at a time.",
                 "Độ chính xác khi một trong 10 thiết bị đo ngừng gửi số liệu, lần lượt từng thiết bị."),
        "read": ("Longer bar is better. The dashed line is accuracy with every sensor online ({acc}). The worst case "
                 "is {miss_dev} offline at {miss_lo}.",
                 "Thanh càng dài càng tốt. Đường nét đứt là độ chính xác khi đủ cảm biến ({acc}). Tệ nhất là mất "
                 "{miss_dev}, còn {miss_lo}."),
        "why": ("Field sensors fail or lose communication; a useful model has to degrade gracefully.",
                "Cảm biến ngoài hiện trường có lúc hỏng hoặc mất liên lạc; model dùng được phải giảm chất lượng từ "
                "từ chứ không sập."),
    },
    "table-zone": {
        "needs_ea": True,
        "title": ("Misses and false blames per zone", "Bỏ sót và báo nhầm theo zone"),
        "what": ("For each zone: how many of its faults were missed (FNR) and how often other zones' faults were "
                 "blamed on it (FPR).",
                 "Với mỗi zone: bao nhiêu sự cố của nó bị bỏ sót (FNR) và bao nhiêu lần sự cố ở zone khác bị đổ cho nó "
                 "(FPR)."),
        "read": ("Lower FNR and FPR are better. The worst FNR is {fnr_zone} at {fnr_max}; zones at the ends of the "
                 "feeder stay at or below {leaf_fnr}.",
                 "FNR và FPR càng thấp càng tốt. FNR cao nhất là {fnr_zone} với {fnr_max}; các zone ở cuối tuyến không "
                 "quá {leaf_fnr}."),
        "why": ("Accuracy alone hides where the model fails; this table shows it is the busy zones near the "
                "substation.",
                "Accuracy một mình che mất chỗ model sai; bảng này cho thấy đó là các zone đông tải gần trạm."),
    },
    "heat": {
        "needs_ea": True,
        "title": ("Confusion matrix", "Ma trận nhầm lẫn"),
        "what": ("Every fault counted by its true zone (row) and the zone the model picked (column).",
                 "Mọi sự cố được đếm theo zone thật (hàng) và zone model chọn (cột)."),
        "read": ("The gray diagonal is correct answers. Blue cells are mistakes, darker means more; the biggest is "
                 "{top_pair} ({top_n} faults).",
                 "Đường chéo xám là câu trả lời đúng. Ô xanh là lỗi, càng đậm càng nhiều; lớn nhất là {top_pair} "
                 "({top_n} sự cố)."),
        "why": ("It shows the mistakes land next to the right zone, not across the feeder.",
                "Nó cho thấy lỗi rơi vào zone ngay bên cạnh chứ không văng sang đầu kia của tuyến."),
    },
    "chart-dir": {
        "needs_ea": True,
        "title": ("Where the wrong answers point", "Câu trả lời sai rơi vào đâu"),
        "what": ("Every wrong answer grouped by where the guess sits relative to the true zone in the feeder tree.",
                 "Mọi câu trả lời sai được nhóm theo vị trí của zone đoán so với zone thật trên cây lưới."),
        "read": ("{off1} of errors are exactly one zone off (parent or child), and {upstream} lean toward the "
                 "substation.",
                 "{off1} số lỗi lệch đúng 1 zone (zone cha hoặc con), và {upstream} lệch về phía trạm."),
        "why": ("Knowing which way errors go tells an engineer what extra check to add before switching.",
                "Biết lỗi hay lệch về hướng nào giúp kỹ sư biết cần thêm bước kiểm tra gì trước khi đóng cắt."),
    },
    "table-defer": {
        "needs_ea": True,
        "title": ("Let the model say “not sure”", "Cho model nói “không chắc”"),
        "what": ("What happens if low-confidence answers go to a manual patrol instead of being acted on.",
                 "Điều gì xảy ra nếu các câu trả lời có độ tự tin thấp được chuyển sang tuần tra tay thay vì hành động "
                 "theo."),
        "read": ("Each row is a cutoff. At 0.95 only {deferred} of faults are deferred, accuracy on the rest is "
                 "{acc_kept}, and errors drop to {errors_kept}.",
                 "Mỗi hàng là một ngưỡng. Ở 0.95 chỉ {deferred} số sự cố bị chuyển, accuracy phần còn lại là "
                 "{acc_kept}, và số lỗi giảm còn {errors_kept}."),
        "why": ("A model that knows when it is unsure is safer to put in front of a real operator.",
                "Model biết lúc nào mình không chắc thì an toàn hơn khi đưa cho điều độ viên thật dùng."),
    },
    "table-rest": {
        "title": ("Isolation and restoration", "Cô lập và khôi phục"),
        "what": ("One row per faulted zone: what was switched, how much healthy load came back, and whether every "
                 "limit held.",
                 "Mỗi hàng là một zone bị sự cố: đã đóng cắt gì, cấp lại được bao nhiêu tải lành, và mọi giới hạn có "
                 "được giữ không."),
        "read": ("Status should be ✓ on every row. Voltage must stay within {vmin}–{vmax} pu; “Still dark” is load "
                 "that could not be picked up within limits.",
                 "Mọi hàng nên có ✓. Điện áp phải nằm trong {vmin}–{vmax} pu; “Vẫn mất điện” là phần tải không thể "
                 "cấp lại mà vẫn giữ giới hạn."),
        "why": ("Restoring power is only useful if it does not overload a line or push voltage out of range.",
                "Cấp điện lại chỉ có ích khi không làm quá tải đường dây hay đẩy điện áp ra ngoài giới hạn."),
    },
    "table-zones": {
        "title": ("Feeder zones", "Các zone của tuyến"),
        "what": ("The 10 sections the feeder is split into by its switching devices.",
                 "10 đoạn mà tuyến được chia ra bởi các thiết bị đóng cắt."),
        "read": ("Each row gives the device that feeds the zone, the zone above it, its load and its line length.",
                 "Mỗi hàng cho biết thiết bị cấp điện cho zone, zone phía trên, phụ tải và chiều dài đường dây."),
        "why": ("Everything on this page is counted per zone, so this is the map for reading the rest.",
                "Mọi số liệu trên trang đều tính theo zone, nên đây là bản đồ để đọc các phần còn lại."),
    },
}
