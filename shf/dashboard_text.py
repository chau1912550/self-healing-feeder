"""English and Vietnamese text for the report page: questions & answers and the glossary.

Answers are templates. `{name}` fields are filled from the latest results by
shf/dashboard.py (see `numbers()`), so the page never quotes a stale number.
Entries with needs_ea=True use the error analysis and are skipped until
scripts/error_analysis.py has been run; entries with needs_h=True use the hourly
restoration study (scripts/hourly_restoration.py) and are skipped until it has run.
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
     "a": ("<p>No. Everything on this page is <b>simulation only</b> in OpenDSS (60 Hz phasors) on the IEEE 123-bus "
           "test feeder: {faults} faults across all four types (0.01–400 Ω nominal). Ground faults at 100 Ω or more "
           "use an <b>intermittent arcing HIF</b> equivalent 60 Hz resistance (Emanuel two-diode describing function + "
           "45% intermittent conduction probability + contact-path jitter, capped at 2,500 Ω); each event also draws "
           "<b>independent per-zone loading</b> (±30% 1σ), <b>pre-to-post load drift</b> (0.8% zone / 1.5% spot), and "
           "<b>CT/PT measurement errors</b> (systematic ratio/angle bias, 1% / 0.5° random noise, and a 0.5 A / "
           "0.001 pu additive floor).</p><p>Even with those upgrades, this is still a 60 Hz phasor simulation without "
           "EMTP transients, CT core saturation, or cycle-by-cycle arc harmonics (harmonics are examined in LTspice "
           "§2b and the Tier-1 / §2d Edge HIF Sensor). Real deployment would require validation on utility field event "
           "records.</p>",
           "<p>Không. Toàn bộ trang này là <b>mô phỏng 100%</b> trong OpenDSS (miền phasor 60 Hz) trên lưới thử nghiệm "
           "IEEE 123-bus: {faults} sự cố đủ 4 loại (điện trở danh định 0.01–400 Ω). Sự cố chạm đất từ 100 Ω trở lên "
           "dùng mô hình <b>hồ quang HIF chập chờn</b> quy đổi sang điện trở tương đương 60 Hz (hàm mô tả hai diode "
           "Emanuel + xác suất dẫn chập chờn 45% + dao động trở kháng tiếp xúc, trần 2,500 Ω); mỗi ca còn lấy mẫu "
           "<b>tải biến động độc lập theo từng zone</b> (±30% 1σ), <b>trôi tải giữa pre/post</b> (0.8% theo zone / "
           "1.5% theo điểm tải) và <b>nhiễu đo CT/PT thực tế</b> (sai số hệ thống tỉ số/góc pha, nhiễu ngẫu nhiên "
           "1% / 0.5° và sàn nhiễu cộng tính 0.5 A / 0.001 pu).</p><p>Dù sát thực tế hơn, đây vẫn là mô phỏng phasor "
           "60 Hz, chưa có quá độ điện từ EMTP, bão hòa lõi CT hay sóng hài từng chu kỳ (sóng hài được xét riêng ở "
           "LTspice mục 2b và Cảm biến HIF Tầng 1 / mục 2d). Muốn dùng ngoài lưới thật vẫn phải kiểm chứng bằng bản "
           "ghi sự kiện thực địa của công ty điện lực.</p>")},
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
           "ends of the feeder stay at or below {leaf_fnr} FNR. The full table is in <a href='#errors'>the error analysis</a>.</p>",
           "<p>Accuracy ({acc}) che mất việc sự cố <i>nào</i> bị bỏ sót và câu trả lời sai rơi vào đâu. Model luôn "
           "chọn 1 trong 10 zone, nên bỏ sót và báo nhầm được tính theo từng zone, một zone so với phần còn lại:</p>"
           "<ul><li><b>FNR</b>: tỉ lệ sự cố của zone đó bị đoán sang zone khác.</li>"
           "<li><b>FPR</b>: tỉ lệ sự cố ở zone khác bị đổ cho zone này.</li></ul>"
           "<p>FNR cao nhất là {fnr_zone} với {fnr_max}, FPR cao nhất là {fpr_zone} với {fpr_max}; các zone ở cuối "
           "tuyến có FNR không quá {leaf_fnr}. Bảng đầy đủ ở mục <a href='#errors'>Phân tích lỗi</a>.</p>")},
    {"id": "what-missed", "cat": "results", "needs_ea": True,
     "q": ("Which faults does the model miss most, and why?",
           "Model hay bỏ sót loại sự cố nào, và tại sao?"),
     "a": ("<p><b>Weak intermittent arcing ground faults.</b> {slg_hi} of the {errors} errors ({slg_hi_share}) are "
           "ground faults at 200 Ω nominal or more. At 400 Ω the error rate is {err400} (only {r400} correct); for "
           "three-phase faults it is {err3ph}.</p>"
           "<p>The reason is physics: even as a linear 400 Ω resistor at nominal load, a fault on a 2.4 kV phase draws "
           "only {s2l_i400_123} (OpenDSS), {s2l_sh400_123} of the {s2l_head123} at the feeder head. Under the "
           "<b>intermittent arcing model</b>, ignition voltage and partial-cycle extinction push effective 60 Hz "
           "resistance even higher (up to 2,500 Ω), shrinking the 60 Hz fault current below natural <b>pre/post load "
           "drift</b> (0.8% zone / 1.5% spot) and <b>CT/PT noise + 0.5 A floor</b>. Heavier load makes it worse: the "
           "error rate is {load_lo} in the lightest third of load scenarios and {load_hi} in the heaviest third.</p>",
           "<p><b>Sự cố chạm đất một pha có hồ quang yếu và chập chờn.</b> {slg_hi} trên {errors} lỗi ({slg_hi_share}) "
           "là sự cố chạm đất từ 200 Ω danh định trở lên. Ở 400 Ω tỉ lệ sai là {err400} (chỉ đúng {r400}); với sự cố "
           "ba pha là {err3ph}.</p>"
           "<p>Lý do là vật lý: ngay cả khi là điện trở tuyến tính 400 Ω ở tải định mức, sự cố trên pha 2.4 kV chỉ tạo "
           "{s2l_i400_123} (OpenDSS), bằng {s2l_sh400_123} dòng {s2l_head123} ở đầu tuyến. Với <b>mô hình hồ quang "
           "chập chờn</b>, điện áp mồi và chu kỳ tắt/mồi đẩy điện trở tương đương 60 Hz cao hơn nữa (lên tới 2,500 Ω), "
           "làm dòng sự cố 60 Hz chìm dưới <b>trôi tải pre/post</b> (0.8% theo zone / 1.5% theo điểm tải) và <b>nhiễu "
           "CT/PT + sàn 0.5 A</b>. Tải càng nặng càng khó: tỉ lệ sai là {load_lo} ở 1/3 kịch bản tải nhẹ nhất và "
           "{load_hi} ở 1/3 nặng nhất.</p>")},
    {"id": "where-wrong", "cat": "results", "needs_ea": True,
     "q": ("When the model is wrong, where does it point? Does that matter?",
           "Khi model sai, nó đoán sang đâu? Điều đó có quan trọng không?"),
     "a": ("<p>Most stay on the same feeder path, though weak arcing faults can spill to other busy trunk zones. "
           "{same_path} of errors stay on the same path from the substation ({off1} off by exactly one zone, "
           "{upstream} leaning toward the substation); the largest confusion pair is {top_pair} ({top_n} faults). "
           "When an intermittent arc draws only a few amps, load drift and CT noise on other heavy-load branches can "
           "look just as large.</p><p>It matters because a wrong zone means the faulted section is not the one "
           "switched out, so re-closing or tie restoration could re-energize the fault. Real schemes guard against "
           "this by checking for fault current after each switching step; this study does not yet simulate those "
           "consequences.</p>",
           "<p>Phần lớn vẫn nằm trên cùng đường đi từ trạm ra, nhưng sự cố hồ quang rất yếu có thể lệch sang nhánh "
           "trục chính đông tải khác. {same_path} số lỗi nằm trên cùng đường từ trạm ({off1} lệch đúng 1 zone, "
           "{upstream} lệch về phía trạm); cặp nhầm nhiều nhất là {top_pair} ({top_n} sự cố). Khi hồ quang chập chờn "
           "chỉ kéo vài ampe, trôi tải và nhiễu CT ở nhánh đông tải khác có biên độ tương đương.</p>"
           "<p>Điều này quan trọng vì đoán sai zone nghĩa là đoạn bị cắt ra không phải đoạn đang sự cố, nên khi đóng "
           "lại hoặc cấp điện qua tie có thể đóng điện vào đúng chỗ sự cố. Hệ thống thật chặn việc này bằng cách "
           "kiểm tra dòng sự cố sau mỗi bước đóng cắt; nghiên cứu này chưa mô phỏng các hậu quả đó.</p>")},
    {"id": "fpi-bad", "cat": "results",
     "q": ("Why does the conventional method do so badly?",
           "Sao phương pháp truyền thống lại kém như vậy?"),
     "a": ("<p>Fault passage indicators flag when current exceeds a fixed pickup (here 2× peak load for phase "
           "current, plus a residual-current threshold for ground), and the fault is placed after the deepest "
           "flagged device. That works for three-phase and line-to-line faults ({fpi_3ph} and {fpi_ll} correct) but "
           "not for ground faults ({fpi_slg}):</p><ul><li>High-resistance and intermittent arcing faults stay below "
           "pickup, so on {fpi_none} of all faults no device flags at all.</li><li>Per-phase CT ratio/angle bias "
           "creates spurious residual current (3·I₀), and a bolted ground fault collapses that phase's voltage so "
           "single-phase loads beyond it drop out and downstream devices raise false ground flags ({bolted_fpi} "
           "correct at 0.01 Ω).</li></ul><p>Real schemes add directional elements, so this baseline is on the "
           "pessimistic side.</p>",
           "<p>Bộ chỉ báo dòng sự cố (FPI) bật cờ khi dòng vượt ngưỡng cố định (ở đây là 2 lần dòng tải đỉnh cho "
           "dòng pha, cộng một ngưỡng dòng dư cho chạm đất), rồi sự cố được xác định nằm sau thiết bị bật cờ xa "
           "nhất. Cách này tốt với sự cố ba pha và hai pha (đúng {fpi_3ph} và {fpi_ll}) nhưng kém với chạm đất "
           "({fpi_slg}):</p><ul><li>Sự cố điện trở cao và hồ quang chập chờn không vượt ngưỡng, nên ở {fpi_none} "
           "tổng số sự cố không thiết bị nào bật cờ.</li><li>Sai số tỉ số/góc pha riêng từng CT tạo dòng dư giả "
           "(3·I₀), và sự cố chạm đất trực tiếp làm sụp áp pha đó khiến tải một pha phía sau rớt ra, làm thiết bị "
           "phía dưới bật cờ chạm đất giả (chỉ đúng {bolted_fpi} ở 0.01 Ω).</li></ul>"
           "<p>Hệ thống thật có thêm phần tử định hướng, nên baseline này hơi bi quan.</p>")},
    {"id": "memorizing", "cat": "model",
     "q": ("How do you know the model is not memorizing the test data?",
           "Làm sao biết model không “học thuộc” dữ liệu kiểm tra?"),
     "a": ("<p>Validation is grouped by fault bus (5-fold GroupKFold): every test fault sits on a bus the model "
           "never saw a fault at during training, so near-duplicate rows (same bus, different resistance) cannot "
           "leak into the test.</p><p>An early version scored almost perfectly with simple magnitude features (its "
           "result files were not kept), which was too good to be true: with only three fixed load levels the model "
           "had memorized “normal” current. Randomizing feeder-wide, independent per-zone (±30% 1σ), and per-spot "
           "demand, adding pre/post load drift, and re-sampling CT/PT bias per event removed those shortcuts and "
           "produced the realistic gap shown here ({acc_mag} with magnitudes only vs {acc} with full features).</p>",
           "<p>Kiểm định được chia nhóm theo bus sự cố (GroupKFold 5 phần): mọi sự cố dùng để kiểm tra nằm ở bus "
           "mà model chưa từng thấy sự cố khi huấn luyện, nên các dòng gần giống nhau (cùng bus, khác điện trở) "
           "không lọt sang tập kiểm tra.</p><p>Phiên bản đầu gần như đúng tuyệt đối chỉ với đặc trưng biên độ đơn "
           "giản (file kết quả lần đó không được giữ lại), tốt đến mức đáng ngờ: chỉ có 3 mức tải cố định nên model "
           "đã học thuộc dòng điện “bình thường”. Ngẫu nhiên hóa tải toàn tuyến, tải độc lập từng zone (±30% 1σ), "
           "tải từng điểm, thêm trôi tải pre/post và lấy mẫu lại sai số CT/PT cho mỗi sự cố đã bịt các đường tắt đó "
           "và cho ra khoảng cách thực tế trên trang ({acc_mag} chỉ biên độ so với {acc} đủ đặc trưng).</p>")},
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
           "of {conf_wrong}, right ones {conf_right}, so a 0.95 cutoff defers {deferred} of faults, raises "
           "accuracy on the rest to {acc_kept}, and cuts errors from {errors} to {errors_kept} (−{err_cut}).</p>",
           "<p>Model đưa ra xác suất cho từng zone. Khi xác suất cao nhất thấp hơn ngưỡng, hệ thống không hành động "
           "theo dự đoán đó và đội sửa chữa đi tuần như hiện nay. Câu trả lời sai có độ tự tin trung vị "
           "{conf_wrong}, câu đúng là {conf_right}, nên với ngưỡng 0.95 hệ thống chuyển {deferred} số sự cố sang "
           "tuần tra tay, accuracy phần còn lại lên {acc_kept}, và số lỗi giảm từ {errors} xuống {errors_kept} "
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
    {"id": "by-hour", "cat": "restoration", "needs_h": True,
     "q": ("Does the hour of the fault change how much load comes back?",
           "Giờ xảy ra sự cố có làm thay đổi lượng tải được cấp lại không?"),
     "a": ("<p>Yes. At night the feeder carries less load, so voltage drops less along the long tie paths and more of "
           "the dark load fits within limits. On a typical summer day the ties pick up {su_hi} of the healthy load left "
           "dark for a fault at {su_hi_t}, but only {su_lo} at {su_lo_t}; in winter it goes from {wi_hi} at {wi_hi_t} "
           "to {wi_lo} at {wi_lo_t}. Averaged over every hour of {h_year} it is {h_pct}, against {h_peak} when every "
           "fault is assumed to happen at peak load.</p><p>A tie closed at night must still be within limits when "
           "the morning load arrives, because the outage lasts until the repair ends ({h_hold} h). Planning for the "
           "highest load in that window lowers the yearly average to {h_held} and gives a smaller plan in {h_lower} "
           "of the hours.</p>",
           "<p>Có. Về đêm tuyến mang ít tải hơn, nên điện áp sụt ít hơn trên đường tie dài và nhiều phần tải bị mất "
           "điện hơn nằm được trong giới hạn. Vào một ngày hè điển hình, tie cấp lại được {su_hi} phần tải lành bị "
           "mất điện nếu sự cố lúc {su_hi_t}, nhưng chỉ {su_lo} nếu lúc {su_lo_t}; mùa đông từ {wi_hi} lúc {wi_hi_t} "
           "xuống {wi_lo} lúc {wi_lo_t}. Trung bình trên mọi giờ của năm {h_year} là {h_pct}, so với {h_peak} khi giả "
           "định mọi sự cố đều xảy ra lúc tải đỉnh.</p><p>Tie đóng lúc nửa đêm vẫn phải nằm trong giới hạn khi tải "
           "buổi sáng tăng lên, vì mất điện kéo dài tới khi sửa xong ({h_hold} giờ). Lập phương án cho mức tải cao "
           "nhất trong khoảng đó làm trung bình cả năm giảm còn {h_held}, và cho phương án nhỏ hơn ở {h_lower} số "
           "giờ.</p>")},
    {"id": "load-shape", "cat": "project", "needs_h": True,
     "q": ("Where does the hourly load come from, and what does it assume?",
           "Tải theo giờ lấy từ đâu, và giả định những gì?"),
     "a": ("<p>From PJM's hourly load for the AEP region (Kaggle dataset <i>Hourly Energy Consumption</i>, public "
           "domain). Each hour of {h_year} is divided by that year's peak, which gives a load level between "
           "{h_mult_min} and 1.00 (mean {h_mult_mean}); every spot load on the feeder is scaled by it.</p><p>It "
           "assumes that one regional shape stands in for every customer (a single feeder swings more than a whole "
           "utility region), that the IEEE nominal loads are the yearly peak, that the capacitors stay fixed as in "
           "the test case, and that the adjacent feeder behind the tie still has no load of its own. It is a "
           "simulation driven by a real load curve, not a measurement on a real feeder.</p>",
           "<p>Từ tải theo giờ của PJM cho vùng AEP (bộ dữ liệu Kaggle <i>Hourly Energy Consumption</i>, phạm vi công "
           "cộng). Mỗi giờ của năm {h_year} được chia cho đỉnh của năm đó, cho ra mức tải từ {h_mult_min} tới 1.00 "
           "(trung bình {h_mult_mean}); mọi phụ tải trên tuyến được nhân với mức này.</p><p>Giả định: một hình dạng "
           "tải của cả vùng đại diện cho mọi khách hàng (một tuyến riêng lẻ dao động mạnh hơn cả vùng), tải danh định "
           "IEEE là đỉnh năm, tụ bù giữ cố định như trong mạch mẫu, và tuyến bên cạnh sau dao liên lạc vẫn không có "
           "tải riêng. Đây là mô phỏng chạy theo đường tải thật, không phải số đo trên một tuyến thật.</p>")},
    {"id": "next-steps", "cat": "limits",
     "q": ("What are the limitations, and what would you do next?",
           "Giới hạn là gì, và bước tiếp theo là gì?"),
     "a": ("<ul><li><b>False alarms in the main sweep:</b> the core 123-bus dataset holds only faulted cases (no-fault "
           "disturbances are evaluated separately in the active-grid §2c and two-tier HIF-Fusion §2d studies).</li>"
           "<li><b>60 Hz phasor domain limits:</b> the main sweep now models intermittent arcing HIFs (SLG ≥ 100 Ω) as "
           "an equivalent 60 Hz resistance with per-zone load drift and CT/PT bias, but still omits EMTP transients, "
           "CT core saturation, and waveform harmonics (harmonics are studied in LTspice §2b and the 15.36 kHz Tier-1 "
           "Edge HIF Sensor §2d).</li><li><b>Consequences of a wrong zone:</b> simulate re-closing onto the fault and "
           "add a fault-current check after each switching step.</li><li><b>Fairer baseline:</b> compare against fault "
           "indicators with directional elements.</li><li><b>Field data:</b> validate on real utility event records "
           "(beyond offline Tier-1 tests on real 22 kV VeHIF recordings).</li></ul>",
           "<ul><li><b>Báo động giả ở bộ lõi:</b> bộ dữ liệu 123-bus chính chỉ chứa các ca sự cố (nhiễu không sự cố "
           "NO_FAULT được đánh giá riêng ở lưới chủ động mục 2c và HIF-Fusion mục 2d).</li>"
           "<li><b>Giới hạn miền phasor 60 Hz:</b> bộ lõi nay đã mô phỏng hồ quang HIF chập chờn (SLG ≥ 100 Ω) qua "
           "điện trở tương đương 60 Hz cùng trôi tải theo zone và sai số CT/PT, nhưng vẫn chưa có quá độ điện từ EMTP, "
           "bão hòa lõi CT hay sóng hài dạng sóng (sóng hài được xét riêng ở LTspice mục 2b và Cảm biến HIF Tầng 1 "
           "15.36 kHz mục 2d).</li><li><b>Hậu quả khi đoán sai zone:</b> mô phỏng việc đóng lại vào chỗ sự cố và thêm "
           "bước kiểm tra dòng sự cố sau mỗi lần đóng cắt.</li><li><b>Baseline công bằng hơn:</b> so với bộ chỉ báo sự "
           "cố có phần tử định hướng.</li><li><b>Dữ liệu thực địa:</b> kiểm chứng bằng bản ghi sự kiện thật của công "
           "ty điện (mở rộng từ kiểm chứng ngoại tuyến Tầng 1 trên bản ghi VeHIF 22 kV thật).</li></ul>")},
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
    "hif": ("High-impedance fault (HIF)", "A ground fault through a high-resistance contact (tree, dry soil, asphalt) "
            "that typically arcs intermittently and draws only a few amps, making it hard to detect at 60 Hz.",
            "Sự cố trở kháng cao (HIF)", "Sự cố chạm đất qua tiếp xúc điện trở lớn (cây, đất khô, nhựa đường), thường "
            "phát hồ quang chập chờn và chỉ kéo vài ampe nên rất khó phát hiện ở 60 Hz."),
    "arcing": ("Intermittent arcing model (R_eff)", "For simulated SLG ≥ 100 Ω, maps nominal resistance to an "
               "equivalent 60 Hz resistance using the Emanuel two-diode describing function k₁(γ), 45% intermittent "
               "conduction duty (0.35–0.85), and log-normal path jitter (capped at 2,500 Ω).",
               "Mô hình hồ quang chập chờn (R_eff)", "Với SLG ≥ 100 Ω mô phỏng, quy đổi điện trở danh định sang điện "
               "trở tương đương 60 Hz theo hàm mô tả hai diode Emanuel k₁(γ), xác suất dẫn chập chờn 45% (chu kỳ dẫn "
               "0.35–0.85) và dao động log-normal trở kháng tiếp xúc (trần 2,500 Ω)."),
    "loaddrift": ("Per-zone load & drift", "Each of the 10 zones draws its own load multiplier (1σ = 30%), and spot "
                  "loads drift slightly (0.8% zone / 1.5% spot) between pre- and post-fault snapshots while regulators "
                  "stay frozen.",
                  "Tải theo zone & trôi tải", "Mỗi zone trong 10 zone lấy hệ số tải riêng (1σ = 30%), và tải điểm trôi "
                  "nhẹ (0.8% theo zone / 1.5% theo điểm) giữa ảnh trước và sau sự cố khi nấc điều áp bị khóa."),
    "ctbias": ("CT/PT bias & noise floor", "Per-event systematic CT (1.5% / 0.8°) and PT (0.8% / 0.4°) calibration "
               "bias held fixed pre→post, plus 1% / 0.5° random error and a 0.5 A / 0.001 pu additive floor on "
               "energized phases.",
               "Sai số CT/PT & sàn nhiễu", "Sai số hệ thống riêng theo từng sự cố của CT (1.5% / 0.8°) và PT (0.8% / "
               "0.4°) giữ nguyên từ pre sang post, cộng nhiễu ngẫu nhiên 1% / 0.5° và sàn nhiễu 0.5 A / 0.001 pu trên "
               "pha có điện."),
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
    "loadmult": ("LoadMult (load level)", "One number that scales every load on the feeder: 1.00 is the IEEE nominal "
                 "load, taken here as the yearly peak; 0.50 is half of it.",
                 "LoadMult (mức tải)", "Một hệ số nhân cho mọi phụ tải trên tuyến: 1.00 là tải danh định IEEE, ở đây "
                 "coi là đỉnh năm; 0.50 là một nửa."),
    "dcoffset": ("DC offset", "When a fault starts, the current in an inductive circuit cannot jump, so the first "
                 "cycles are pushed to one side and decay to a normal sine. How much depends on the instant it starts.",
                 "DC lệch", "Khi sự cố bắt đầu, dòng trong mạch có điện cảm không thể nhảy ngay, nên vài chu kỳ đầu "
                 "bị lệch về một phía rồi tắt dần về sóng sin bình thường. Lệch nhiều hay ít tuỳ thời điểm bắt đầu."),
    "harmonic": ("Harmonic", "A part of a current at a multiple of 60 Hz (180 Hz is the 3rd). A clean sine has none; "
                 "an arc has many.",
                 "Sóng hài", "Phần của dòng điện ở bội số của 60 Hz (180 Hz là hài bậc 3). Sóng sin sạch không có; "
                 "hồ quang có nhiều."),
    "loadshape": ("Load shape", "Load hour by hour divided by its yearly peak: it says when load is high or low, not "
                  "how many MW. Here from PJM, AEP region.",
                  "Hình dạng tải", "Tải từng giờ chia cho đỉnh của năm: cho biết lúc nào tải cao hay thấp, không cho "
                  "biết bao nhiêu MW. Ở đây lấy từ PJM, vùng AEP."),
    "opendss": ("OpenDSS", "EPRI's open-source simulator for electric distribution systems.",
                "OpenDSS", "Phần mềm mô phỏng lưới phân phối điện mã nguồn mở của EPRI."),
    "edgehif": ("Edge HIF-Sensor (p_hif)", "A compact int8 detector (417 parameters, 504 bytes) running locally on "
                "15.36 kHz residual current behind a 4th-order Butterworth filter, outputting a persisted arc score "
                "p_hif ∈ [0, 1] per switch.",
                "Cảm biến hồ quang biên (p_hif)", "Bộ phát hiện int8 gọn nhẹ (417 tham số, 504 byte) chạy cục bộ trên "
                "dòng dư lấy mẫu 15.36 kHz qua mạch lọc Butterworth bậc 4, xuất ra điểm xác suất hồ quang p_hif ∈ [0, 1] "
                "tại mỗi dao."),
    "provenance": ("SHA-256 provenance", "A 64-character cryptographic fingerprint recorded for every result file when "
                   "its script runs, so any manual edit or missing file is caught automatically.",
                   "Chứng thực SHA-256", "Dấu vân tay mật mã 64 ký tự được ghi tự động cho từng file kết quả khi "
                   "script chạy xong, giúp phát hiện ngay mọi chỉnh sửa bằng tay hay file bị thiếu."),
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
        "what": ("Every fault simulated in OpenDSS: four fault types across the feeder's buses, nominal resistances "
                 "from 0.01 to 400 Ω with intermittent arcing HIFs from 100 Ω up, independent per-zone loading + "
                 "pre/post drift, and CT/PT bias + noise floor.",
                 "Toàn bộ sự cố mô phỏng trong OpenDSS: 4 loại sự cố trên các bus của tuyến, điện trở danh định từ "
                 "0.01 đến 400 Ω kèm hồ quang HIF chập chờn từ 100 Ω trở lên, tải biến động theo zone + trôi tải "
                 "pre/post, và sai số CT/PT + sàn nhiễu."),
        "read": ("{faults} simulated faults in total. Most are line-to-ground (SLG), the most common fault on real feeders.",
                 "Tổng cộng {faults} sự cố mô phỏng. Phần lớn là chạm đất một pha (SLG), loại sự cố hay gặp nhất ngoài thực tế."),
        "why": ("A large, varied, realistic simulation dataset allows honest unseen-bus testing across easy and hard regimes.",
                "Dữ liệu mô phỏng lớn, đa dạng và sát thực tế giúp kiểm tra trung thực trên bus chưa thấy ở cả ca dễ lẫn ca khó."),
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
                 "to 400 Ω nominal (with intermittent arcing equivalent 60 Hz resistance active from 100 Ω upward).",
                 "Mỗi phương pháp đoán đúng zone bao nhiêu với sự cố chạm đất một pha, từ chạm trực tiếp (0.01 Ω) tới "
                 "400 Ω danh định (có mô hình hồ quang chập chờn quy đổi 60 Hz từ 100 Ω trở lên)."),
        "read": ("One line per method; higher is better. At 100 Ω the model is at {r100} (FPI {r100_fpi}); at 400 Ω "
                 "under intermittent arcing + load drift it drops to {r400}. Hover a point for exact numbers.",
                 "Mỗi đường là một phương pháp; càng cao càng tốt. Ở 100 Ω model đạt {r100} (FPI {r100_fpi}); ở 400 Ω "
                 "dưới hồ quang chập chờn + trôi tải độ chính xác giảm còn {r400}. Rê chuột vào điểm để xem số."),
        "why": ("Intermittent weak ground faults expose the physical ceiling of 60 Hz phasors and motivate the edge "
                "harmonic sensor in §2d.",
                "Sự cố chạm đất hồ quang yếu cho thấy giới hạn vật lý của pha 60 Hz và là lý do cần cảm biến sóng hài "
                "biên ở mục 2d."),
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
        "why": ("Most mistakes cluster among the busy trunk zones ({same_path} on the same path, {off1} one zone off), "
                "while the weakest arcing HIFs can spill across branches.",
                "Phần lớn lỗi tập trung ở các zone trục chính đông tải ({same_path} cùng đường từ trạm, {off1} lệch "
                "đúng 1 zone), còn hồ quang yếu nhất có thể lệch sang nhánh khác."),
    },
    "chart-dir": {
        "needs_ea": True,
        "title": ("Where the wrong answers point", "Câu trả lời sai rơi vào đâu"),
        "what": ("Every wrong answer grouped by where the guess sits relative to the true zone in the feeder tree.",
                 "Mọi câu trả lời sai được nhóm theo vị trí của zone đoán so với zone thật trên cây lưới."),
        "read": ("{same_path} of errors stay on the same path ({off1} off by one zone, {upstream} toward the "
                 "substation); the rest fall on sibling or unrelated branches.",
                 "{same_path} số lỗi nằm trên cùng đường đi ({off1} lệch 1 zone, {upstream} về phía trạm); phần còn "
                 "lại rơi vào zone anh em hoặc nhánh khác."),
        "why": ("Knowing which way errors go tells an engineer what extra check to add before switching.",
                "Biết lỗi hay lệch về hướng nào giúp kỹ sư biết cần thêm bước kiểm tra gì trước khi đóng cắt."),
    },
    "table-defer": {
        "needs_ea": True,
        "title": ("Let the model say “not sure”", "Cho model nói “không chắc”"),
        "what": ("What happens if low-confidence answers go to a manual patrol instead of being acted on.",
                 "Điều gì xảy ra nếu các câu trả lời có độ tự tin thấp được chuyển sang tuần tra tay thay vì hành động "
                 "theo."),
        "read": ("Each row is a cutoff. At 0.95, {deferred} of faults are deferred, accuracy on the rest rises to "
                 "{acc_kept}, and errors drop to {errors_kept}.",
                 "Mỗi hàng là một ngưỡng. Ở 0.95, {deferred} số sự cố được chuyển sang tuần tra tay, accuracy phần "
                 "còn lại tăng lên {acc_kept}, và số lỗi giảm còn {errors_kept}."),
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
    "chart-dc": {
        "needs_sp": True,
        "title": ("Fault current in the first cycles", "Dòng sự cố trong vài chu kỳ đầu"),
        "what": ("LTspice waveform of a bolted fault at bus {sp_bus}, from a circuit whose resistance and inductance come "
                 "from the OpenDSS feeder model. The two lines are the same fault starting at two different instants.",
                 "Dạng sóng LTspice của sự cố trực tiếp tại bus {sp_bus}, từ mạch có điện trở và điện cảm lấy từ mô hình "
                 "OpenDSS. Hai đường là cùng một sự cố bắt đầu ở hai thời điểm khác nhau."),
        "read": ("The solid line starts at the worst instant: it is pushed to one side at first (the DC offset) and "
                 "settles around zero within a few cycles. The dashed line starts at the instant with no offset.",
                 "Đường liền bắt đầu ở thời điểm xấu nhất: lúc đầu bị đẩy lệch về một phía (DC lệch) rồi dần cân lại "
                 "quanh 0 sau vài chu kỳ. Đường đứt bắt đầu ở thời điểm không có lệch."),
        "why": ("The first peak, {sp_pk} A instead of {sp_pk0} A, is what CTs, breakers and the ADC must survive; the "
                "phasor study only sees the steady {sp_rms} A.",
                "Đỉnh đầu tiên, {sp_pk} A thay vì {sp_pk0} A, là mức CT, máy cắt và ADC phải chịu; nghiên cứu theo pha "
                "chỉ thấy dòng ổn định {sp_rms} A."),
    },
    "chart-arc": {
        "needs_sp": True,
        "title": ("Arcing fault vs linear resistance", "Sự cố có hồ quang so với điện trở tuyến tính"),
        "what": ("Two cycles of a ground-fault current at bus {sp_bus}: an arcing fault (two-diode Emanuel model) and "
                 "a reference linear {hif_hi_r} Ω resistor, matched to the same RMS current.",
                 "Hai chu kỳ dòng chạm đất tại bus {sp_bus}: sự cố có hồ quang (mô hình hai diode Emanuel) và điện trở "
                 "tuyến tính tham chiếu {hif_hi_r} Ω, chỉnh cho cùng dòng hiệu dụng."),
        "read": ("The arc stays at zero until the voltage passes the arc voltage, then jumps: flat gaps near each zero "
                 "crossing, steeper flanks. The linear resistor gives a clean sine.",
                 "Hồ quang đứng ở 0 cho tới khi điện áp vượt điện áp hồ quang rồi mới nhảy lên: có đoạn phẳng gần mỗi "
                 "lần qua 0 và sườn dốc hơn. Điện trở tuyến tính cho sóng sin sạch."),
        "why": ("The main 60 Hz sweep captures the fundamental-current drop and intermittency via R_eff, but these "
                "zero-crossing gaps create harmonics ({hif_h3} 3rd at {hif_hi_r} Ω) that only a time-domain sensor "
                "(§2d / Tier 1) sees.",
                "Mô phỏng 60 Hz chính đã phản ánh suy giảm thành phần cơ bản và tính chập chờn qua R_eff, nhưng các "
                "đoạn phẳng qua 0 này tạo sóng hài ({hif_h3} hài bậc 3 ở {hif_hi_r} Ω) mà chỉ cảm biến miền thời gian "
                "(mục 2d / Tầng 1) mới thấy."),
    },
    "table-arc": {
        "needs_sp": True,
        "title": ("What changes with an arc", "Hồ quang làm thay đổi gì"),
        "what": ("For each fault resistance, an arc and a fixed resistance with the same RMS current, compared.",
                 "Với mỗi điện trở sự cố, so sánh hồ quang và điện trở cố định có cùng dòng hiệu dụng."),
        "read": ("Percent rows are the arc's 60 Hz part and harmonics; the last two rows compare the fault current with "
                 "the {sp_ipre} A load at the feeder head and with one ADC count ({sp_apc} A).",
                 "Các hàng phần trăm là thành phần 60 Hz và sóng hài của hồ quang; hai hàng cuối so dòng sự cố với dòng "
                 "tải {sp_ipre} A ở đầu tuyến và với một mức ADC ({sp_apc} A)."),
        "why": ("At {hif_hi_r} Ω the fault is {hif_hi_share} of the load and spans {hif_hi_counts} ADC counts: small "
                "whatever its shape.",
                "Ở {hif_hi_r} Ω dòng sự cố bằng {hif_hi_share} dòng tải và chỉ chiếm {hif_hi_counts} mức ADC: nhỏ, dù "
                "dạng sóng thế nào."),
    },
    "chart-hour": {
        "needs_h": True,
        "title": ("Restored load by hour of day", "Tải được cấp lại theo giờ trong ngày"),
        "what": ("For a fault at each hour of a typical summer or winter day of {h_year}: the share of the healthy load "
                 "left dark that the ties pick up.",
                 "Với sự cố ở từng giờ của một ngày hè hoặc ngày đông điển hình năm {h_year}: phần trăm tải lành bị "
                 "mất điện mà tie cấp lại được."),
        "read": ("Solid lines check the limits at the fault hour. Dashed lines also require the plan to hold for the "
                 "next {h_hold} h, until the repair ends, so they never sit above the solid line. Hover an hour for the "
                 "exact values.",
                 "Đường liền kiểm tra giới hạn đúng giờ sự cố. Đường đứt còn đòi phương án giữ được thêm {h_hold} giờ "
                 "tới khi sửa xong, nên không bao giờ nằm trên đường liền. Rê chuột vào một giờ để xem số chính xác."),
        "why": ("Load is lower at night, so more can be restored then; but a plan made at 3 a.m. must survive the "
                "morning rise.",
                "Về đêm tải thấp hơn nên cấp lại được nhiều hơn; nhưng phương án lập lúc 3 giờ sáng phải chịu được lúc "
                "tải tăng vào buổi sáng."),
    },
    "heat-hour": {
        "needs_h": True,
        "title": ("Faulted zone × hour", "Zone sự cố × giờ"),
        "what": ("One row per faulted zone that leaves healthy load dark, one column per hour of the fault, for summer "
                 "and for winter.",
                 "Mỗi hàng là một zone sự cố làm mất điện phần tải lành phía sau, mỗi cột là một giờ xảy ra sự cố, cho "
                 "mùa hè và mùa đông."),
        "read": ("Darker cells mean a larger share of that zone's dark load comes back. A row that keeps one colour "
                 "all day is limited by the network, not by the load level.",
                 "Ô càng đậm thì phần tải bị mất điện của zone đó được cấp lại càng nhiều. Hàng giữ một màu cả ngày là "
                 "bị giới hạn bởi lưới, không phải bởi mức tải."),
        "why": ("It shows which faults gain from low load and which do not; {h_flips_en} sit right at the voltage "
                "limit.",
                "Cho thấy sự cố nào được lợi khi tải thấp và sự cố nào không; {h_flips_vi} nằm sát giới hạn điện áp."),
    },
    "table-reasons": {
        "needs_h": True,
        "title": ("Why options were rejected", "Vì sao phương án bị loại"),
        "what": ("The average number of rejected power-flow checks per fault hour, by the limit that failed, summed over "
                 "the 10 fault zones.",
                 "Số lần tính trào lưu bị loại trung bình ở mỗi giờ sự cố, theo giới hạn bị vi phạm, cộng cho 10 zone "
                 "sự cố."),
        "read": ("Compare the columns: the limit that fails most often is the one that stops more load from coming "
                 "back. One check can fail for more than one reason.",
                 "So các cột: giới hạn bị vi phạm nhiều nhất là thứ cản việc cấp lại thêm tải. Một lần kiểm tra có thể "
                 "bị loại vì nhiều lý do."),
        "why": ("It points to the upgrade that would help: voltage support, or stronger lines.",
                "Cho biết nên nâng cấp gì: hỗ trợ điện áp, hay đường dây lớn hơn."),
    },
    "oneline": {
        "title": ("One-line diagram", "Sơ đồ một sợi"),
        "what": ("The feeder as an engineering one-line diagram, drawn in AutoCAD from the same data as the study: every "
                 "line, switch, tie, regulator and capacitor, with the 10 zones in colour.",
                 "Tuyến vẽ thành sơ đồ một sợi kỹ thuật bằng AutoCAD, từ cùng dữ liệu với nghiên cứu: mọi đường dây, "
                 "dao, dao liên lạc, bộ điều áp và tụ bù, với 10 zone tô màu."),
        "read": ("Heavy lines are 3-phase, light lines 1-phase, dashed lines underground cable. Filled squares are "
                 "normally-closed switches, hollow squares normally-open ties, R is the feeder-head recloser.",
                 "Nét đậm là 3 pha, nét mảnh là 1 pha, nét đứt là cáp ngầm. Ô vuông đặc là dao thường đóng, ô vuông "
                 "rỗng là dao liên lạc thường mở, R là recloser đầu tuyến."),
        "why": ("It is the kind of drawing an engineer works from: where each zone's switches sit on the circuit.",
                "Đây là loại bản vẽ kỹ sư dùng để làm việc: dao của từng zone nằm ở đâu trên mạch."),
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
    "map3d": {
        "title": ("3D feeder model", "Mô hình lưới 3D"),
        "what": ("The whole IEEE 123-bus feeder built from the study's own data: lines colored by zone, poles, "
                 "switches, ties, regulators, capacitors, and one column per load.",
                 "Toàn bộ lưới IEEE 123-bus dựng từ chính dữ liệu của nghiên cứu: đường dây tô màu theo zone, cột "
                 "điện, dao đóng cắt, dao liên lạc, bộ điều áp, tụ bù, và mỗi phụ tải là một cột."),
        "read": ("Drag to rotate, scroll or pinch to zoom. Taller columns are bigger loads; thicker lines carry "
                 "more phases. Click a zone, switch or column to have it explained.",
                 "Kéo để xoay, cuộn chuột hoặc chụm hai ngón để phóng to. Cột càng cao là tải càng lớn; đường dây "
                 "càng dày là càng nhiều pha. Nhấp vào zone, dao hay cột tải để được giải thích."),
        "why": ("Every number on this page is counted per zone, so seeing where each zone sits makes the rest "
                "easier to read.",
                "Mọi con số trên trang đều tính theo zone, nên thấy được mỗi zone nằm ở đâu giúp đọc phần còn lại dễ "
                "hơn."),
    },
    "table-transfer": {
        "needs_tr": True,
        "title": ("Cross-feeder transfer & active-grid GNN", "Chuyển lưới & GNN trên lưới có DER / vòng kín"),
        "what": ("Fault-zone accuracy when models trained ONLY on IEEE 123-bus (4.16 kV, 10 switches) are tested on "
                 "IEEE 123-bus and transferred unchanged to unseen IEEE 34-bus (24.9 kV, 7 switches) and underground "
                 "delta IEEE 37-bus (4.8 kV, 10 switches), first on passive radial graphs and then on active grids "
                 "with 0–50% inverter DER, reconfiguration/loops, HIFs and non-fault switching transients.",
                 "Độ chính xác tìm zone khi các model CHỈ học trên IEEE 123-bus (4.16 kV, 10 dao) được kiểm tra trên "
                 "123-bus và thử thẳng sang IEEE 34-bus (24.9 kV, 7 dao) cùng lưới cáp ngầm delta IEEE 37-bus (4.8 kV, "
                 "10 dao) chưa từng thấy, từ lưới hình tia thụ động tới lưới hiện đại có 0–50% điện mặt trời DER, đổi "
                 "cấu trúc/vòng kín, sự cố trở kháng cao và quá độ đóng cắt không phải sự cố."),
        "read": ("On passive radial 34-bus, per-node GBDT ({tr_p3_gbdt}) and tree GNN ({tr_p3_gnn}) both transfer "
                 "zero-shot above FPI ({tr_p3_fpi}). On active grids with DER and loops, FPI drops to {ag_fpi123} "
                 "(123-bus) and {ag_fpi34} (34-bus), while bidirectional ActiveGridGATv2 leads on 123-bus ({ag_gat123} "
                 "vs {ag_gbdt123}, cutting false trips in half to {ag_gat123_fpr}) and at 20% few-shot on 34-bus "
                 "({ag_gat34_fs20} vs {ag_gbdt34_fs20}).{tr37_explain_en}",
                 "Trên lưới hình tia thụ động 34-bus, cả GBDT theo nút ({tr_p3_gbdt}) và GNN cây ({tr_p3_gnn}) đều "
                 "chuyển lưới zero-shot vượt xa FPI ({tr_p3_fpi}). Trên lưới có DER và vòng kín, FPI sụp xuống "
                 "{ag_fpi123} (123-bus) và {ag_fpi34} (34-bus), còn ActiveGridGATv2 hai chiều dẫn đầu trên 123-bus "
                 "({ag_gat123} so với {ag_gbdt123}, giảm một nửa báo động giả còn {ag_gat123_fpr}) và ở chế độ tinh "
                 "chỉnh 20% trên 34-bus ({ag_gat34_fs20} so với {ag_gbdt34_fs20}).{tr37_explain_vi}"),
        "why": ("Testing across three different feeders (including ungrounded delta cables) shows both where relative "
                "graph features generalize and where grounding physics sets a hard boundary.",
                "Kiểm tra trên cả ba lưới khác nhau (gồm cả cáp ngầm delta không nối đất) cho thấy rõ nơi đặc trưng "
                "đồ thị tương đối tổng quát hóa được và nơi vật lý nối đất tạo ra giới hạn cứng."),
    },
    "table-bus-stage": {
        "needs_tr": True,
        "title": ("Stage 2: from zone down to bus", "Stage 2: từ zone xuống tới từng bus"),
        "what": ("Inside the predicted zone, ranking individual buses by 3-phase Takagi reactance (using OpenDSS 3×3 "
                 "line impedances, zero training) versus a bus-graph GNN and random selection.",
                 "Bên trong zone dự đoán, xếp hạng từng bus bằng phương pháp điện kháng Takagi 3 pha (dùng ma trận "
                 "đường dây 3×3 của OpenDSS, không cần học) so với mạng GNN đồ thị bus và chọn ngẫu nhiên."),
        "read": ("Physics beats ML on grounded overhead feeders: Takagi reactance reaches {tr_b123_top1} top-1 / "
                 "{tr_b123_top3} top-3 on 123-bus (vs {tr_b123_rand3} random top-3) and {tr_b34_top1} / {tr_b34_top3} "
                 "on 34-bus (vs {tr_b34_rand3}). Confused buses sit at the same electrical distance (ΔX₁ ≈ 0 Ω).{b37_explain_en}",
                 "Ở lưới trên không nối đất, vật lý thắng ML: điện kháng Takagi đạt {tr_b123_top1} top-1 / "
                 "{tr_b123_top3} top-3 trên 123-bus (ngẫu nhiên top-3 là {tr_b123_rand3}) và {tr_b34_top1} / "
                 "{tr_b34_top3} trên 34-bus (ngẫu nhiên {tr_b34_rand3}). Các bus bị nhầm có cùng khoảng cách điện "
                 "(ΔX₁ ≈ 0 Ω).{b37_explain_vi}"),
        "why": ("Naming the top-3 candidate buses cuts crew search inside a multi-lateral zone while honestly showing "
                "the physical observability limit of boundary-only sensors.",
                "Chỉ ra top-3 bus khả nghi giúp thu hẹp phạm vi tìm kiếm trong zone nhiều nhánh, đồng thời chỉ rõ "
                "giới hạn quan sát vật lý khi chỉ đặt cảm biến ở đầu zone."),
    },
    "table-conformal": {
        "needs_tr": True,
        "title": ("Split Conformal Prediction: pre-registered vs post-hoc", "Split Conformal Prediction: đăng ký trước so với kiểm tra sau"),
        "what": ("A conformal set lists every zone (or NO_FAULT) the model cannot rule out, sized so that it holds the "
                 "true answer for 95% of events. A one-label set is the only case where switching could be automatic; "
                 "anything larger goes to an operator. Rows compare the pre-registered score with a randomized APS "
                 "score tried afterwards on the same probabilities.",
                 "Tập conformal liệt kê mọi zone (hoặc NO_FAULT) mà model chưa loại được, chọn cỡ sao cho chứa đáp án "
                 "đúng ở 95% số ca. Chỉ khi tập có 1 nhãn mới có thể tự đóng cắt; tập lớn hơn thì chuyển cho điều độ "
                 "viên. Các hàng so cách tính đã đăng ký trước với APS ngẫu nhiên thử sau trên cùng xác suất."),
        "read": ("Pre-registered APS: {ag_conf123_cov} coverage but {ag_pd_size} labels per set, so only "
                 "{ag_pd_single} of events get one label. Randomized APS: {ag_pr_cov} coverage with {ag_pr_size} labels "
                 "per set on 123-bus, but only {ag_pr_zs34} on the unseen 34-bus feeder with the 123-bus threshold.{conf37_explain_en}",
                 "APS đăng ký trước: phủ {ag_conf123_cov} nhưng mỗi tập có {ag_pd_size} nhãn, nên chỉ {ag_pd_single} "
                 "số ca có tập 1 nhãn. APS ngẫu nhiên: phủ {ag_pr_cov} với {ag_pr_size} nhãn mỗi tập trên 123-bus, "
                 "nhưng chỉ phủ {ag_pr_zs34} trên lưới 34-bus chưa thấy khi dùng ngưỡng của 123-bus.{conf37_explain_vi}"),
        "why": ("It shows how far the coverage target holds: on the feeder it was calibrated on, not on a new one.",
                "Cho thấy mục tiêu độ phủ giữ được tới đâu: đúng trên lưới đã hiệu chỉnh, không đúng trên lưới mới."),
    },
    "table-hif-fusion": {
        "title": ("Two-tier Edge HIF-Sensor → Graph FLISR", "Kiến trúc 2 tầng Edge HIF-Sensor → Graph FLISR"),
        "what": ("Paired ablation on identical OpenDSS events comparing 60 Hz phasor features alone against adding "
                 "two scalar outputs (p_hif, hif_alarm) from a frozen 504-byte int8 Edge HIF-Sensor at each switch, "
                 "across passive (PerNodeGBDT, ZoneTreeGNN) and active DER/looped grids (ActivePerNodeGBDT, ActiveGridGATv2).",
                 "So sánh đối chứng trên cùng tập sự cố OpenDSS giữa đặc trưng pha 60 Hz thuần với khi ghép thêm "
                 "2 đại lượng vô hướng (p_hif, hif_alarm) từ cảm biến hồ quang biên int8 504 byte đóng băng tại mỗi dao, "
                 "trên cả lưới thụ động (PerNodeGBDT, ZoneTreeGNN) và lưới chủ động có DER/vòng kín (ActivePerNodeGBDT, ActiveGridGATv2)."),
        "read": ("{hif_read_en}", "{hif_read_vi}"),
        "why": ("At 400 Ω on 4.16 kV, the 60 Hz fault current ({s2l_i400_123}) is buried in 1% CT noise. Detecting "
                "arc harmonics locally at 15.36 kHz and passing compact scores into the graph targets that ceiling directly.",
                "Ở 400 Ω trên lưới 4.16 kV, dòng sự cố 60 Hz ({s2l_i400_123}) chìm trong nhiễu CT 1%. Phát hiện sóng hài "
                "hồ quang cục bộ ở 15.36 kHz rồi đưa điểm số gọn vào đồ thị nhắm thẳng vào giới hạn vật lý đó."),
    },
    "table-hif-surfaces": {
        "title": ("Breakdown across 5 Emanuel arc surfaces", "Phân rã theo 5 bề mặt hồ quang Emanuel"),
        "what": ("Zone localization accuracy on arcing high-impedance ground faults split by the 5 simulated contact "
                 "surfaces (wet grass, wet sand, concrete, dry grass, dry asphalt) from the two-diode Emanuel arc model.",
                 "Độ chính xác định vị zone trên các sự cố chạm đất trở kháng cao có hồ quang, tách theo 5 bề mặt tiếp "
                 "xúc mô phỏng (cỏ ướt, cát ướt, bê tông, cỏ khô, nhựa đường khô) của mô hình hồ quang hai diode Emanuel."),
        "read": ("{hif_surf_read_en}", "{hif_surf_read_vi}"),
        "why": ("Higher ignition voltage and resistance (dry grass, dry asphalt) produce sparser, weaker arcs and test "
                "whether the two-tier detector holds beyond easy wet-ground cases. All 5 surfaces are simulated.",
                "Điện áp đánh lửa và điện trở cao hơn (cỏ khô, nhựa đường khô) tạo hồ quang thưa và yếu hơn, kiểm tra xem "
                "hệ 2 tầng có giữ vững ngoài các ca đất ướt dễ hay không. Cả 5 bề mặt đều là mô phỏng."),
    },
    "table-hif-disturbances": {
        "title": ("False-alarm rate on 7 background disturbances", "Tỉ lệ báo động giả trên 7 nhiễu nền"),
        "what": ("Share of active-grid NO_FAULT events wrongly flagged as a fault, broken down across 7 simulated "
                 "time-domain disturbances including hard negatives (arc welder, transformer inrush, nonlinear loads).",
                 "Tỉ lệ các sự kiện không sự cố (NO_FAULT) trên lưới chủ động bị báo nhầm là sự cố, tách theo 7 dạng nhiễu "
                 "nền miền thời gian mô phỏng gồm cả âm tính khó (máy hàn hồ quang, dòng xung kích MBA, tải phi tuyến)."),
        "read": ("{hif_dist_read_en}", "{hif_dist_read_vi}"),
        "why": ("Adding an edge arc score is only useful if harmonic-rich normal loads (welders, inrush, inverters) "
                "do not flood Graph FLISR with nuisance trips.",
                "Thêm điểm hồ quang từ cảm biến biên chỉ có ích khi các tải bình thường giàu sóng hài (máy hàn, dòng xung "
                "kích, nghịch lưu) không làm Graph FLISR cắt nhầm hàng loạt."),
    },
    "evidence": {
        "title": ("Verification, provenance & scientific honesty", "Chứng thực, kiểm chứng & độ tin cậy khoa học"),
        "what": ("A reviewer-ready audit panel read directly from all {prov_manifests} SHA-256 manifests in "
                 "results/provenance/ ({prov_files} result files), pairing cryptographic hashes with honest failures, "
                 "simulation limits, and static-page security commitments.",
                 "Khối kiểm toán dành cho giảng viên và phản biện, đọc trực tiếp từ toàn bộ {prov_manifests} manifest "
                 "SHA-256 trong results/provenance/ ({prov_files} file kết quả), đặt mã băm mật mã ngay cạnh các ca "
                 "thất bại trung thực, giới hạn mô phỏng và cam kết bảo mật trang tĩnh."),
        "read": ("Green ✓ means 100% hash match ({prov_changed} changed, {prov_missing} missing, {prov_unrec} unrecorded). "
                 "Red ✕ and amber ! chips highlight honest failures and physical limits right beside passing evidence.",
                 "Nhãn ✓ xanh nghĩa là khớp băm 100% ({prov_changed} sửa đổi, {prov_missing} thiếu, {prov_unrec} chưa ghi). "
                 "Nhãn ✕ đỏ và ! vàng nêu rõ các ca thất bại trung thực và giới hạn vật lý ngay cạnh bằng chứng đạt."),
        "why": ("Any lecturer or reviewer can verify every figure locally in two commands without trusting screenshots.",
                "Mọi giảng viên hay phản biện đều có thể tự kiểm chứng toàn bộ số liệu trên máy bằng 2 lệnh mà không cần tin vào ảnh chụp."),
    },
    "table-provenance": {
        "title": ("SHA-256 Provenance Ledger", "Sổ cái chứng thực SHA-256"),
        "what": ("All {prov_manifests} manifests in results/provenance/*.json with producer ID, Local/Kaggle run source, "
                 "event count, shortened SHA-256 with one-click copy, and live verification status.",
                 "Toàn bộ {prov_manifests} manifest trong results/provenance/*.json gồm mã thí nghiệm, nguồn chạy Local/Kaggle, "
                 "số sự kiện, SHA-256 rút gọn kèm nút sao chép và trạng thái khớp trực tiếp."),
        "read": ("Click Copy to copy the full 64-character SHA-256, or expand the full {prov_files}-file manifest below "
                 "to download and verify any JSON or CSV directly.",
                 "Bấm Sao chép để lấy đủ 64 ký tự SHA-256, hoặc mở danh sách đủ {prov_files} file bên dưới để tải và "
                 "đối chiếu trực tiếp từng file JSON/CSV."),
        "why": ("Proves every result file matches the script run that produced it and was never edited by hand.",
                "Chứng minh mọi file kết quả đều khớp với lần chạy sinh ra nó và không bị chỉnh sửa thủ công."),
    },
    "table-honesty": {
        "title": ("Passed evidence vs. honest failures & limits", "Bằng chứng đạt vs. ca thất bại trung thực & giới hạn"),
        "what": ("Side-by-side summary of passing criteria (Main FLISR, 10/11 unseen multi-feeder, H1–H4 HIF-Fusion) "
                 "next to honest failures (IEEE 37-bus ungrounded delta SLG P1-Fail, BusGraphGNN vs Takagi, cross-feeder "
                 "conformal coverage) and the VeHIF real-arc domain gap.",
                 "Bảng đối chiếu song song giữa bằng chứng đạt tiêu chí (FLISR chính, 10/11 đa lưới, H1–H4 HIF-Fusion) "
                 "với các ca thất bại trung thực (P1-Fail SLG lưới cáp ngầm delta IEEE 37-bus, BusGraphGNN thua Takagi, "
                 "conformal liên lưới) và khoảng cách miền hồ quang thật VeHIF."),
        "read": ("Every project metric comes directly from results/ (simulation only); the VeHIF domain-gap check is "
                 "cited explicitly from research/hif-fusion/PLAN.md.",
                 "Mọi chỉ số của dự án đều đọc trực tiếp từ results/ (hoàn toàn là mô phỏng); đối chiếu khoảng cách miền "
                 "VeHIF được trích nguồn rõ từ research/hif-fusion/PLAN.md."),
        "why": ("Reporting where a model breaks under real physics builds scientific trust far more than hiding failures.",
                "Báo cáo trung thực nơi mô hình gãy vì giới hạn vật lý tạo độ tin cậy khoa học hơn nhiều so với việc giấu lỗi."),
    },
}

# What the guide says about the parts of the 3D feeder model. Filled per object by
# shf/dashboard.py (model_texts); {name} fields come from the results and the geometry.
MODEL = {
    "zone": {
        "title": ("Zone {zone}", "Zone {zone}"),
        "what": ("{kw} kW across {loads} loads and {kft} kft of line, fed through {device}. Upstream: {parent}.",
                 "{kw} kW gồm {loads} điểm tải và {kft} kft đường dây, được cấp qua {device_vi}. Phía trên: "
                 "{parent_vi}."),
        "read": ("The model finds faults in this zone {recall} of the time and wrongly blames it for {fpr} of "
                 "faults elsewhere.",
                 "Model tìm đúng sự cố ở zone này {recall} số lần, và đổ nhầm cho zone này {fpr} số sự cố ở nơi "
                 "khác."),
        "why": ("If a fault hits here: {restore}", "Nếu sự cố xảy ra ở đây: {restore_vi}"),
    },
    "recloser": {
        "title": ("{name} · feeder-head recloser", "{name} · recloser đầu tuyến"),
        "what": ("The breaker at the start of the feeder. It trips on a fault, recloses a few times, and locks out if "
                 "the fault is still there.",
                 "Máy cắt ở đầu tuyến. Nó cắt khi có sự cố, tự đóng lại vài lần, và mở hẳn (lockout) nếu sự cố vẫn "
                 "còn."),
        "read": ("Every fault in this study starts with {name} locking out the whole feeder.",
                 "Mọi sự cố trong nghiên cứu đều bắt đầu bằng việc {name} cắt hẳn toàn tuyến."),
        "why": ("That lockout is what starts fault location, isolation and restoration.",
                "Lần cắt hẳn đó chính là thứ khởi động việc định vị, cô lập và khôi phục."),
    },
    "ieee": {
        "title": ("{name} · sectionalizing switch", "{name} · dao phân đoạn"),
        "what": ("A switch from the IEEE test case that splits the feeder; it feeds zone {zone}.",
                 "Dao có sẵn trong lưới thử nghiệm IEEE, chia tuyến thành nhiều đoạn; nó cấp điện cho zone {zone}."),
        "read": ("Its current and voltage readings are part of what the fault-location model sees.",
                 "Số đo dòng và áp của nó là một phần dữ liệu mà model định vị sự cố nhìn vào."),
        "why": ("Opening it cuts zone {zone} off from everything upstream.",
                "Mở dao này là tách zone {zone} khỏi toàn bộ phần phía trên."),
    },
    "added": {
        "title": ("{name} · automated switch (added)", "{name} · dao tự động (thêm vào)"),
        "what": ("An automated switch added in this study on an existing line, so the feeder splits into smaller "
                 "zones. It feeds zone {zone}.",
                 "Dao tự động được thêm vào trong nghiên cứu này trên một đoạn dây có sẵn, để chia tuyến thành các zone "
                 "nhỏ hơn. Nó cấp điện cho zone {zone}."),
        "read": ("It reports current and voltage just like the IEEE switches.",
                 "Nó gửi số đo dòng và áp giống như các dao của IEEE."),
        "why": ("Smaller zones mean fewer customers out and a shorter patrol after a fault.",
                "Zone càng nhỏ thì sau sự cố càng ít khách hàng mất điện và quãng tuần tra càng ngắn."),
    },
    "tie": {
        "title": ("{name} · tie switch (normally open)", "{name} · dao liên lạc (thường mở)"),
        "what": ("{what}", "{what_vi}"),
        "read": ("{read}", "{read_vi}"),
        "why": ("Ties are how healthy zones beyond a fault get power back before the repair.",
                "Dao liên lạc là cách để các zone lành phía sau chỗ sự cố có điện lại trước khi sửa xong."),
    },
    "reg": {
        "title": ("{name} · voltage regulator", "{name} · bộ điều áp"),
        "what": ("Raises or lowers voltage in small steps to keep customers within limits. It sits at bus {bus}; the "
                 "substation has Reg 1.",
                 "Tăng hoặc giảm điện áp theo từng nấc nhỏ để giữ điện áp khách hàng trong giới hạn. Nó đặt ở bus "
                 "{bus}; trạm nguồn có Reg 1."),
        "read": ("During a fault study its taps are frozen, so the measurements reflect the fault, not the regulator.",
                 "Khi mô phỏng sự cố, nấc điều áp được giữ cố định, nên số đo phản ánh sự cố chứ không phải bộ điều áp."),
        "why": ("Long feeders lose voltage along the way; regulators keep it within 0.95–1.05 pu.",
                "Tuyến dài bị sụt áp dọc đường; bộ điều áp giữ điện áp trong khoảng 0.95–1.05 pu."),
    },
    "cap": {
        "title": ("{name} · capacitor bank", "{name} · tụ bù"),
        "what": ("{kvar} kvar of reactive power at bus {bus}.", "{kvar} kvar công suất phản kháng ở bus {bus}."),
        "read": ("It supplies reactive power locally, so less current has to flow from the substation.",
                 "Tụ cấp công suất phản kháng tại chỗ, nên dòng điện từ trạm phải tải ít hơn."),
        "why": ("That props up voltage and cuts losses, most of all at the end of long branches.",
                "Nhờ vậy điện áp được nâng lên và tổn thất giảm, nhất là ở cuối các nhánh dài."),
    },
    "source": {
        "title": ("Substation · bus {bus}", "Trạm nguồn · bus {bus}"),
        "what": ("The 4.16 kV source that feeds the whole test feeder, with voltage regulator Reg 1.",
                 "Nguồn 4.16 kV cấp điện cho toàn bộ lưới thử nghiệm, kèm bộ điều áp Reg 1."),
        "read": ("Power flows outward from here through recloser Sw1.",
                 "Điện đi từ đây ra ngoài qua recloser Sw1."),
        "why": ("“Upstream” on this page always means closer to the substation.",
                "“Phía trên” trên trang này luôn có nghĩa là gần trạm nguồn hơn."),
    },
    "load": {
        "title": ("Bus {bus} · load", "Bus {bus} · phụ tải"),
        "what": ("{kw} kW of customer load at bus {bus}, in zone {zone}.",
                 "{kw} kW phụ tải khách hàng ở bus {bus}, thuộc zone {zone}."),
        "read": ("Column height is load size: the tallest columns are the biggest customers.",
                 "Chiều cao cột là độ lớn phụ tải: cột cao nhất là khách hàng lớn nhất."),
        "why": ("Loads are what restoration is trying to bring back; every kW restored early counts.",
                "Phụ tải là thứ mà việc khôi phục muốn cấp điện lại; mỗi kW có điện sớm đều có giá trị."),
    },
}

TIE_TEXT = {  # what / read for each tie, (English, Vietnamese)
    "Sw7": (("A normally open link between two branches of this feeder (bus 151 to bus 300).",
             "Mối nối thường mở giữa hai nhánh của chính tuyến này (bus 151 tới bus 300)."),
            ("Restoration closes it only after a power flow confirms voltage, current and radial limits.",
             "Việc khôi phục chỉ đóng nó sau khi tính trào lưu xác nhận điện áp, dòng điện và hình tia đều đạt.")),
    "Sw8": (("A single-phase tie from the IEEE test case (bus 54 to bus 94).",
             "Dao liên lạc một pha có sẵn trong lưới IEEE (bus 54 tới bus 94)."),
            ("It stays open in every case: one phase cannot pick up three-phase load.",
             "Nó luôn mở trong mọi trường hợp: một pha không thể nhận tải ba pha.")),
    "Sw9": (("A normally open link from bus 450 to an adjacent feeder, modeled as a 4.16 kV source.",
             "Mối nối thường mở từ bus 450 sang tuyến kế bên, mô phỏng như một nguồn 4.16 kV."),
            ("Restoration closes it only after a power flow confirms voltage, current and radial limits.",
             "Việc khôi phục chỉ đóng nó sau khi tính trào lưu xác nhận điện áp, dòng điện và hình tia đều đạt.")),
}
