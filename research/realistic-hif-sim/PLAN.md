# Kế hoạch nghiên cứu & khóa giả định: Mô phỏng sự cố sát thực tế hơn (Hồ quang HIF chập chờn, tải theo zone và nhiễu đo CT/PT)

Trạng thái: **Đã khóa thiết kế & giả định trước khi chạy (T-42 — chưa chạy mô phỏng, chờ triển khai T-43 và chạy pipeline T-44)**.  
Phạm vi: Nâng cấp lõi mô phỏng sự cố chính trên lưới **IEEE 123-bus (4.16 kV)** trong OpenDSS (`shf/config.py`, `shf/feeder.py`, `shf/faults.py`, `run.py`, `scripts/error_analysis.py`, `scripts/export_control_room.py`).  
**Tuyên bố phạm vi:** Toàn bộ thí nghiệm trong kế hoạch này là **mô phỏng 100%** trong miền phasor 60 Hz của OpenDSS — không có dữ liệu hiện trường, không có thử nghiệm phần cứng mang điện, không có kết nối SCADA vận hành thực tế.

Tài liệu liên quan:
- Luật trung thực và quy tắc vận hành: `AGENTS.md`, `CLAUDE.local.md`
- Kiểm chứng miền thời gian LTspice (mạch hồ quang Emanuel 2-diode & CT/ADC): `shf/spice.py`, `results/spice/summary.json`
- Nghiên cứu chuyển giao lưới & lưới chủ động / hợp nhất cảm biến HIF hai tầng: `research/gnn-transfer/PLAN.md`, `research/active-grid-gnn/PLAN.md`, `research/hif-fusion/PLAN.md`

---

## 1. Động lực kỹ thuật & lỗ hổng của mô phỏng hiện tại

Mô phỏng lõi hiện tại (`shf/faults.py`, kết quả trong `results/metrics.json` và `results/error_analysis/error_analysis.json`) đạt độ chính xác tổng `97.7%` cho `ml_full` (`98.4%` ở SLG `100 Ω`, `93.7%` ở SLG `200 Ω`, `76.5%` ở SLG `400 Ω`), nhưng tồn tại **3 đơn giản hóa lớn** thường bị hội đồng kỹ thuật điện chất vấn:

1. **Sự cố chạm đất trở kháng cao (SLG `100–400 Ω`) đang được mô phỏng như điện trở tuyến tính cố định:** Trong thực tế, chạm đất trở kháng cao (HIF) qua đất ẩm, cỏ, cây, bê tông hay nhựa đường luôn xuất hiện **hồ quang phi tuyến và chập chờn**. Ngay trong mạch LTspice đã chạy của chính dự án (`results/spice/summary.json`, bus `60`, mô hình 2-diode Emanuel et al. 1990 với $V_p = 0.30\,V_{\text{pk}}$, $V_n = 0.33\,V_{\text{pk}}$), hồ quang tạo tổng méo sóng hài `THD = 20.98%` (`h3 = 18.85%`, `h5 = 8.30%`), lấy đi một phần năng lượng khỏi thành phần cơ bản 60 Hz mà rơ-le phasor đo được; ngoài ra hồ quang còn tắt/mồi chập chờn giữa các chu kỳ và có trở kháng tiếp xúc biến thiên liên tục.
2. **Tải giữa các vùng đóng cắt chưa biến động độc lập và hoàn toàn đứng yên giữa hai ảnh `pre-fault` / `post-fault`:** Hiện tại `shf/faults.py` chỉ nhân một hệ số chung `LOAD_MULT_RANGE = (0.3, 1.1)` cho toàn tuyến và nhiễu i.i.d. `LOAD_SPREAD = 0.20` cho từng phụ tải điểm. Do mỗi zone có `3–17` phụ tải điểm (`results/zones.csv`), tổng tải từng zone bị trung bình hóa và vẫn đồng biến chặt với đầu tuyến. Quan trọng hơn, ảnh `pre` và ảnh `post` giải trên **cùng một vector tải cố định 100%**, khiến mọi thay đổi $\Delta I = I_{\text{post}} - I_{\text{pre}}$ vượt nhiễu `1%` đều là tín hiệu sự cố thuần túy — giúp `ml_full` đạt tới `97.7%` so với `87.5%` của `ml_magnitude_only`. Ngoài đời, ảnh nền trước sự cố luôn có **trôi tải tự nhiên** (tải sinh hoạt/điều hòa/bơm đóng cắt liên tục).
3. **Mô hình nhiễu đo quá sạch ở dòng nhỏ và bỏ qua sai số hệ thống CT/PT:** `faults._perturb()` hiện chỉ nhân nhiễu ngẫu nhiên độc lập `NOISE_MAG = 1%`, `NOISE_ANG_DEG = 0.5°`. Mô hình này bỏ qua hai hiệu ứng đo lường thực tế:
   - **Sai số hệ thống (calibration/ratio/phase bias) của từng kênh CT/PT** giữ nguyên giữa `pre` và `post` (tạo dòng thứ tự không giả $3I_0$ tỷ lệ theo tải khi 3 CT pha lệch tỷ số/góc pha nhẹ).
   - **Sàn nhiễu cộng tính ở dòng nhỏ** (nhiễu nhiệt mạch analog + độ phân giải ADC/IED): với nhiễu nhân thuần túy, nhánh tải nhẹ `15 A` chỉ có nhiễu `0.15 A` và pha không tải có nhiễu `0.0 A`, làm phóng đại tỷ số tín hiệu/nhiễu (SNR) của HIF ở cuối tuyến.

Mục tiêu của nhánh phát triển này (T-41 → T-47) là nâng cấp lõi mô phỏng `shf/faults.py` để phản ánh trung thực 3 hiệu ứng vật lý trên **trong giới hạn của miền phasor 60 Hz OpenDSS**, sau đó chạy lại toàn bộ pipeline lõi (`run.py`, `error_analysis.py`, `export_control_room.py`, `dashboard`) và **báo cáo trung thực đúng số liệu mới — kể cả khi độ chính xác giảm mạnh**.

---

## 2. Thiết kế vật lý & công thức toán học (khóa trước khi lập trình)

Toàn bộ các hằng số mới đều là giả định mô phỏng, phải khai báo tập trung trong `shf/config.py` kèm chú thích `ASSUMPTION`.

### 2.1 Mô hình hồ quang chập chờn cho SLG trở kháng cao trong miền phasor 60 Hz OpenDSS

**Điều kiện áp dụng (`ASSUMPTION`):**
Áp dụng cho mọi sự cố thỏa đồng thời:
$$\text{ftype} = \text{"SLG"} \quad \text{và} \quad R_{\text{nom}} \ge R_{\text{arc,min}} = 100.0\ \Omega \quad (\texttt{HIF\_ARC\_MIN\_R})$$

*Cơ sở vật lý của ngưỡng `100.0 Ω` (từ `results/transfer/signal_to_load.json` và `shf/config.py`):* Trên tuyến IEEE 123-bus `4.16 kV` ($V_{\text{ph}} \approx 2,402\text{ V}$, dòng đầu tuyến định mức `631.5 A`), chạm đất `100 Ω` kéo trung vị `24.55 A` (`3.89%` dòng đầu tuyến), `200 Ω` khoảng `~12.3 A`, và `400 Ω` kéo trung vị `6.16 A` (`0.97%` dòng đầu tuyến) — đúng dải dòng HIF điển hình (`< 50 A`) và khớp với tập `HIF_R_CASES = (100, 400)` của LTspice (`shf/config.py`) cũng như ngưỡng `R >= 100 Ω` trong `research/hif-fusion/PLAN.md`. Các sự cố `3PH`, `LL`, `LLG` và `SLG` trở kháng thấp/trung bình (`0.01–50 Ω`) giữ điện trở tiếp xúc tuyến tính $R_{\text{eff}} = R_{\text{nom}}$ (nhưng vẫn chịu tải biến động theo zone, trôi tải pre/post và nhiễu đo thực tế).

Với mỗi sự cố SLG thỏa $R_{\text{nom}} \ge 100\ \Omega$, mô hình quy đổi hồ quang miền thời gian sang **điện trở tương đương thành phần cơ bản 60 Hz** $R_{\text{eff}}$ qua 3 thành phần nhân:

#### (a) Suy giảm thành phần cơ bản 60 Hz theo mô hình Emanuel 2-diode (Describing Function)

Xét mô hình hồ quang 2-diode Emanuel et al. (1990) dưới điện áp pha hình sin $v(\theta) = V_{\text{pk}} \sin\theta$ với $V_{\text{pk}} = \sqrt{2} V_{\text{ph}}$ và bỏ qua tổng trở nguồn nhỏ ($|Z_s| \approx 0.63\ \Omega \ll R_{\text{nom}} \ge 100\ \Omega$ tại bus `60`, `results/spice/summary.json`):
$$
i_{\text{arc}}(\theta) =
\begin{cases}
\dfrac{V_{\text{pk}}\sin\theta - V_p}{R_{\text{path}}}, & \text{khi } \sin\theta > \gamma_p \quad (\theta \in (\alpha_p, \pi - \alpha_p)) \\[6pt]
\dfrac{V_{\text{pk}}\sin\theta + V_n}{R_{\text{path}}}, & \text{khi } \sin\theta < -\gamma_n \quad (\theta \in (\pi + \alpha_n, 2\pi - \alpha_n)) \\[6pt]
0, & \text{ngược lại (vùng chết quanh điểm 0 dòng)}
\end{cases}
$$
trong đó $\gamma_p = V_p / V_{\text{pk}} \in (0, 1)$, $\gamma_n = V_n / V_{\text{pk}} \in (0, 1)$ là tỷ số điện áp mồi hồ quang nửa chu kỳ dương/âm, và góc mồi $\alpha_p = \arcsin\gamma_p$, $\alpha_n = \arcsin\gamma_n$.

Do dạng sóng đối xứng quanh $\theta = \pi/2$ trên bán chu kỳ dương và quanh $\theta = 3\pi/2$ trên bán chu kỳ âm, thành phần lệch pha $90^\circ$ ($\cos\theta$) bằng $0$ tuyệt đối, nên thành phần cơ bản 60 Hz hoàn toàn đồng pha với điện áp pha (tương đương thuần trở trong miền phasor). Tích phân hệ số Fourier bậc 1 trên mỗi bán chu kỳ cho **hệ số dẫn thành phần cơ bản** chính xác:
$$
k_1(\gamma) = \frac{2}{\pi} \int_{\arcsin\gamma}^{\pi - \arcsin\gamma} \left(\sin^2\theta - \gamma\sin\theta\right) d\theta
= 1 - \frac{2}{\pi}\left(\arcsin\gamma + \gamma\sqrt{1 - \gamma^2}\right)
$$
Hệ số suy giảm thành phần cơ bản 60 Hz trung bình hai bán chu kỳ là:
$$
\kappa_{\text{arc}}(\gamma_p, \gamma_n) = \frac{k_1(\gamma_p) + k_1(\gamma_n)}{2} \in (0, 1)
$$

*Kiểm chứng chéo với LTspice (`results/spice/summary.json`, bus `60`, `400 Ω`):* Với `Vp_frac = 0.30`, `Vn_frac = 0.33`, công thức giải tích cho $k_1(0.30) = 0.6238$, $k_1(0.33) = 0.5876$, suy ra $\kappa_{\text{arc}} = 0.6057$. Trong `results/spice/summary.json`, tỷ số $R_{\text{arc}} / R_{\text{fault}} \times (I_{1,\text{arc}} / I_{1,\text{lin}}) = (247.5427 / 400.0) \times 0.97830 = 0.6054$, khớp đến 3–4 chữ số có nghĩa (sai khác nhỏ ~0.05% là do $R_s, X_s$ hữu hạn trong LTspice).

**Phân bố lấy mẫu theo từng sự cố (`ASSUMPTION`):**
- $\gamma_p \sim \text{Uniform}(0.15,\ 0.45)$ (`HIF_VP_FRAC_RANGE = (0.15, 0.45)`, tâm `0.30` khớp `HIF_VP_FRAC` hiện có; đại diện cho bề mặt từ đất/cỏ ẩm có điện áp mồi thấp đến bê tông/nhựa đường khô có điện áp mồi cao).
- Tỷ số bất đối xứng nửa chu kỳ âm/dương: $u_{\text{asym}} \sim \text{Uniform}(1.00,\ 1.20)$ (`HIF_ASYM_RANGE = (1.00, 1.20)`, tâm `1.10` khớp `HIF_VN_FRAC / HIF_VP_FRAC = 0.33 / 0.30`).
- $\gamma_n = \text{clip}(\gamma_p \cdot u_{\text{asym}},\ 0.15,\ 0.55)$ (`HIF_VN_FRAC_MAX = 0.55`).

#### (b) Chu kỳ dẫn/tắt chập chờn ($d_{\text{cond}}$) trong cửa sổ ước lượng phasor

Trong thực tế, hồ quang HIF thường xuất hiện hiện tượng mồi–tắt chập chờn (intermittent restrike / extinction) trong cửa sổ ước lượng phasor 1–4 chu kỳ của rơ-le hoặc bản ghi SCADA: một số chu kỳ không mồi lại được hoặc chỉ dẫn một phần, làm biên độ phasor 60 Hz ước lượng suy giảm tỷ lệ với tỷ lệ thời gian dẫn $d_{\text{cond}}$.

**Phân bố lấy mẫu (`ASSUMPTION`):**
$$
d_{\text{cond}} =
\begin{cases}
u_d \sim \text{Uniform}(0.35,\ 0.85), & \text{với xác suất } p_{\text{int}} = 0.45 \quad (\texttt{HIF\_INTERMITTENT\_PROB},\ \texttt{HIF\_DUTY\_RANGE}) \\
1.0, & \text{với xác suất } 1 - p_{\text{int}} = 0.55 \quad (\text{hồ quang dẫn liên tục suốt cửa sổ})
\end{cases}
$$
*Ghi chú phạm vi:* Mô hình không cho $d_{\text{cond}} = 0$ (tắt hoàn toàn trong suốt cửa sổ đo) vì bài toán định vị lõi mặc định rơ-le/bộ ghi đã kích hoạt chụp ảnh sự cố; trạng thái không có tín hiệu hoặc nhiễu vận hành không phải sự cố (`NO_FAULT`) thuộc phạm vi của `research/active-grid-gnn/PLAN.md` và `research/hif-fusion/PLAN.md`.

#### (c) Biến thiên trở kháng tiếp xúc ($m_R$) và trở kháng hiệu dụng $R_{\text{eff}}$ đưa vào OpenDSS

Do độ ẩm bề mặt bốc hơi, cành cây đung đưa hoặc chiều dài khe hồ quang thay đổi ngẫu nhiên, điện trở đường dẫn đất dao động quanh giá trị danh định theo phân bố log-normal (`ASSUMPTION`):
$$
m_R = \text{clip}\!\left(\exp(\eta),\ 0.60,\ 1.80\right), \qquad \eta \sim \mathcal{N}(0,\ \sigma_{\ln R}^2),\ \sigma_{\ln R} = 0.25
$$
(`HIF_R_JITTER_LOGSTD = 0.25`, `HIF_R_JITTER_CLIP = (0.60, 1.80)`).

Trở kháng hiệu dụng 60 Hz đưa vào lệnh OpenDSS `Edit Fault.F ... r={R_eff}` là:
$$
R_{\text{eff}} = \text{clip}\!\left(\frac{R_{\text{nom}} \cdot m_R}{\kappa_{\text{arc}} \cdot d_{\text{cond}}},\ 0.5 \cdot R_{\text{nom}},\ R_{\text{eff,max}}\right), \qquad R_{\text{eff,max}} = 2500.0\ \Omega \quad (\texttt{HIF\_R\_EFF\_MAX})
$$

*Ý nghĩa định lượng của $R_{\text{eff}}$:*
- Ở trạng thái hồ quang liên tục trung bình ($\gamma_p = 0.30, \gamma_n = 0.33 \Rightarrow \kappa_{\text{arc}} = 0.606$, $d_{\text{cond}} = 1.0$, $m_R = 1.0$): $R_{\text{eff}} \approx 1.65\, R_{\text{nom}}$ (nghĩa là SLG danh định `100 Ω` cho dòng 60 Hz tương đương `~165 Ω`, `200 Ω` tương đương `~330 Ω`, `400 Ω` tương đương `~660 Ω`).
- Ở trạng thái chập chờn ($d_{\text{cond}} = 0.50$, $\kappa_{\text{arc}} = 0.606$, $m_R = 1.0$): $R_{\text{eff}} \approx 3.30\, R_{\text{nom}}$ (SLG danh định `400 Ω` lên tới `~1,320 Ω`, dòng 60 Hz chỉ còn `~1.8 A`, nằm sâu dưới nền nhiễu đo).
- Trong bộ dữ liệu `data/generated/dataset.csv.gz`, cột `r` **giữ nguyên giá trị danh định** (`0.01, ..., 100, 200, 400`) để bảo toàn cấu trúc phân tích theo dải điện trở trong `results/metrics.json` và `harness/facts.toml`, đồng thời ghi thêm 4 cột chẩn đoán: `r_eff`, `is_arcing`, `arc_kappa`, `arc_duty`.

---

### 2.2 Tải biến động độc lập theo từng switching zone & trôi tải pre-fault / post-fault

Thay vì chỉ kéo tải đồng bộ toàn tuyến + nhiễu điểm độc lập, trạng thái tải được mô phỏng theo cấu trúc phân cấp 3 tầng (`ASSUMPTION`):

1. **Hệ số tải chung toàn tuyến (giữ nguyên phạm vi cũ):**
   $$m_{\text{feeder}} \sim \text{Uniform}(0.3,\ 1.1) \qquad (\texttt{LOAD\_MULT\_RANGE})$$
2. **Hệ số tải độc lập theo từng switching zone $z \in \{1, \dots, 10\}$ (`ZONE_LOAD_SPREAD`):**
   $$m_{\text{zone}}(z) = \text{clip}\!\left(\mathcal{N}(1.0,\ \sigma_{\text{zone}}^2),\ 0.45,\ 1.65\right), \qquad \sigma_{\text{zone}} = 0.30$$
   (`ZONE_LOAD_SPREAD = 0.30`, `ZONE_LOAD_CLIP = (0.45, 1.65)`). Điều này phản ánh sự khác biệt cơ cấu phụ tải (dân cư, thương mại, xưởng nhỏ, mây che cục bộ) giữa 10 vùng đóng cắt; một zone có thể mang tải cao trong khi zone nhánh song song đang non tải.
3. **Biến động từng phụ tải điểm $\ell$ trong zone $z(\ell)$ (giữ nguyên `LOAD_SPREAD = 0.20`):**
   $$m_{\text{spot}}(\ell) = \text{clip}\!\left(\mathcal{N}(1.0,\ \sigma_{\text{spot}}^2),\ 0.30,\ 1.70\right), \qquad \sigma_{\text{spot}} = 0.20$$
   Hệ số nhân trước sự cố cho phụ tải điểm $\ell$:
   $$f_{\text{pre}}(\ell) = \text{clip}\!\left(m_{\text{zone}}(z(\ell)) \cdot m_{\text{spot}}(\ell),\ 0.25,\ 2.00\right) \qquad (\texttt{SPOT\_FACTOR\_CLIP})$$
   Áp dụng bằng `feeder.scale_loads(base, f_pre)` cùng `feeder.set_load_level(m_feeder)`, giải trào lưu công suất với `controls=True` (bộ điều áp tự chỉnh nấc về trạng thái nền), sau đó chụp ảnh `pre`.
4. **Trôi tải nhẹ giữa ảnh `pre-fault` và ảnh `post-fault` (khóa nấc điều áp `controls=False`):**
   Giữa thời điểm ảnh tham chiếu `pre` (thường cách sự cố vài giây đến vài chục giây trong bộ đệm SCADA/recloser) và thời điểm đóng cắt sự cố `post`, các tải điểm và tổng tải từng zone có dao động tự nhiên nhỏ trong khi bộ điều áp (trễ `15–30 s`) chưa kịp nhảy nấc:
   $$f_{\text{post}}(\ell) = f_{\text{pre}}(\ell) \cdot \text{clip}\!\left(1 + \delta_{\text{zone}}(z(\ell)) + \delta_{\text{spot}}(\ell),\ 0.90,\ 1.10\right)$$
   trong đó (`ASSUMPTION`):
   - $\delta_{\text{zone}}(z) \sim \mathcal{N}(0,\ \sigma_{\text{drift,zone}}^2)$ với $\sigma_{\text{drift,zone}} = 0.008$ (`0.8%`, `LOAD_DRIFT_ZONE`),
   - $\delta_{\text{spot}}(\ell) \sim \mathcal{N}(0,\ \sigma_{\text{drift,spot}}^2)$ với $\sigma_{\text{drift,spot}} = 0.015$ (`1.5%`, `LOAD_DRIFT_SPOT`).

*Đánh giá quy mô vật lý của trôi tải:* Tại các nhánh phụ tải `100–350 A` (`Sw2..L77`), mức trôi `~0.8%` theo zone + `1.5%` theo điểm gây độ lệch dòng nền $\Delta I \approx 1\text{–}3\text{ A}$ trên cả những nhánh lành — tương đương hoặc lớn hơn một phần dòng chạm đất hồ quang ở `200–400 Ω`, nhưng không đáng kể so với sự cố trở kháng thấp (`50–6,000 A`). Nhờ vậy, đặc trưng biến thiên $\Delta I, \Delta I_0, \Delta V$ không còn "sạch tuyệt đối" ở vùng HIF.

---

### 2.3 Nhiễu đo thực tế (sai số hệ thống CT/PT + nhiễu ngẫu nhiên + sàn nhiễu dòng nhỏ)

Với mỗi thiết bị $d \in \mathcal{D}$ (`10` thiết bị đóng cắt) và mỗi pha $k \in \{a, b, c\}$, phasor đo được tại thời điểm $t \in \{\text{pre}, \text{post}\}$ gồm 3 lớp sai số (`ASSUMPTION`, tham chiếu sai số cấp chính xác IEEE C57.13 Class 1.2 CT / Class 0.6–1.2 PT và độ phân giải mạch đo IED):

$$
\tilde{I}_{d,k}^{(t)} = I_{d,k}^{(t)} \cdot (1 + b_{I,d,k})\, e^{j\theta_{I,d,k}} \cdot \left(1 + \epsilon_{I,d,k}^{(t)}\right)\, e^{j\phi_{I,d,k}^{(t)}} + n_{I,d,k}^{(t)}
$$
$$
\tilde{V}_{d,k}^{(t)} = V_{d,k}^{(t)} \cdot (1 + b_{V,d,k})\, e^{j\theta_{V,d,k}} \cdot \left(1 + \epsilon_{V,d,k}^{(t)}\right)\, e^{j\phi_{V,d,k}^{(t)}} + n_{V,d,k}^{(t)}
$$

Trong đó:
1. **Sai số hệ thống CT/PT (giữ cố định giữa `pre` và `post` trong cùng một sự cố, lấy mẫu mới giữa các sự cố để mô hình ML không học thuộc 10 hằng số hiệu chuẩn cố định):**
   - Tỷ số dòng CT: $b_{I,d,k} = \text{clip}(\mathcal{N}(0,\ \sigma_{bI}^2),\ -0.045,\ 0.045)$, $\sigma_{bI} = 0.015$ (`1.5%`, `CT_BIAS_MAG`).
   - Góc pha CT: $\theta_{I,d,k} = \text{clip}(\mathcal{N}(0,\ \sigma_{\theta I}^2),\ -2.5^\circ,\ 2.5^\circ)$, $\sigma_{\theta I} = 0.8^\circ$ (`CT_BIAS_ANG_DEG`).
   - Tỷ số áp PT: $b_{V,d,k} = \text{clip}(\mathcal{N}(0,\ \sigma_{bV}^2),\ -0.025,\ 0.025)$, $\sigma_{bV} = 0.008$ (`0.8%`, `PT_BIAS_MAG`).
   - Góc pha PT: $\theta_{V,d,k} = \text{clip}(\mathcal{N}(0,\ \sigma_{\theta V}^2),\ -1.5^\circ,\ 1.5^\circ)$, $\sigma_{\theta V} = 0.4^\circ$ (`PT_BIAS_ANG_DEG`).
2. **Nhiễu ngẫu nhiên độc lập giữa hai ảnh `pre` và `post` (giữ nguyên tên hằng số cũ):**
   - $\epsilon_{I,d,k}^{(t)},\ \epsilon_{V,d,k}^{(t)} \sim \mathcal{N}(0,\ \texttt{NOISE\_MAG}^2)$ với `NOISE_MAG = 0.01` (`1.0%`).
   - $\phi_{I,d,k}^{(t)},\ \phi_{V,d,k}^{(t)} \sim \mathcal{N}(0,\ \texttt{NOISE\_ANG\_DEG}^2)$ với `NOISE_ANG_DEG = 0.5°`.
3. **Sàn nhiễu cộng tính cho tín hiệu nhỏ (độc lập giữa `pre` và `post`, chỉ áp dụng trên các pha có điện $|V_{\text{clean},d,k}| > 0.05\text{ pu}$ hoặc $|I_{\text{clean},d,k}| > 10^{-6}\text{ A}$ để không tạo điện áp/dòng ảo trên pha không tồn tại):**
   - Sàn nhiễu dòng (Gaussian phức đối xứng tròn):
     $$n_{I,d,k}^{(t)} \sim \mathcal{N}\!\left(0,\ \frac{\sigma_{I,\text{floor}}^2}{2}\right) + j\,\mathcal{N}\!\left(0,\ \frac{\sigma_{I,\text{floor}}^2}{2}\right), \qquad \sigma_{I,\text{floor}} = 0.5\text{ A} \quad (\texttt{NOISE\_I\_FLOOR\_A})$$
     (đại diện cho mạch đo IED hai dải bảo vệ/đo lường có nền nhiễu ~0.1–0.2% dòng định mức CT 300–600 A; ghi nhận rõ là sạch hơn bộ ADC 12-bit một dải trong `shf/spice.py` vốn có bước lượng tử `5.76 A/count` khi dải đo mở rộng cho ngắn mạch trực tiếp).
   - Sàn nhiễu điện áp:
     $$n_{V,d,k}^{(t)} \sim \mathcal{N}\!\left(0,\ \frac{\sigma_{V,\text{floor}}^2}{2}\right) + j\,\mathcal{N}\!\left(0,\ \frac{\sigma_{V,\text{floor}}^2}{2}\right), \qquad \sigma_{V,\text{floor}} = 0.001\text{ pu} \quad (\texttt{NOISE\_V\_FLOOR\_PU})$$
4. **Tính lại thành phần thứ tự sau nhiễu (như mã hiện hành):**
   $$\tilde{I}_{0,d}^{(t)} = \frac{\tilde{I}_{d,a}^{(t)} + \tilde{I}_{d,b}^{(t)} + \tilde{I}_{d,c}^{(t)}}{3}, \qquad \tilde{I}_{2,d}^{(t)} = \frac{\tilde{I}_{d,a}^{(t)} + a^2\tilde{I}_{d,b}^{(t)} + a\tilde{I}_{d,c}^{(t)}}{3}, \quad a = e^{j2\pi/3}$$
   Do $b_{I,d,k}$ và $\theta_{I,d,k}$ độc lập theo pha, sai số hệ thống CT tự nhiên sinh ra **dòng thứ tự không giả** trong cả `pre` và `post`, gây thách thức thực tế cho cả rơ-le `FPI` (`3*I0 > ground_pu`) lẫn `ml_magnitude_only`.

---

## 3. Bảng tổng hợp tham số `ASSUMPTION` dự kiến đưa vào `shf/config.py`

| Nhóm | Hằng số `shf/config.py` | Giá trị khóa | Đơn vị | Vai trò & ghi chú |
|---|---|---:|---|---|
| Hồ quang HIF | `HIF_ARC_MIN_R` | `100.0` | `Ω` | Ngưỡng trở kháng danh định kích hoạt hồ quang cho sự cố `SLG` |
| Hồ quang HIF | `HIF_VP_FRAC_RANGE` | `(0.15, 0.45)` | tỷ số $V_{\text{pk}}$ | Dải lấy mẫu $\gamma_p = V_p/V_{\text{pk}}$ (tâm `0.30` khớp `HIF_VP_FRAC`) |
| Hồ quang HIF | `HIF_ASYM_RANGE` | `(1.00, 1.20)` | tỷ số | Tỷ số bất đối xứng $\gamma_n/\gamma_p$ (tâm `1.10` khớp `0.33/0.30`) |
| Hồ quang HIF | `HIF_VN_FRAC_MAX` | `0.55` | tỷ số $V_{\text{pk}}$ | Trần kẹp $\gamma_n$ để đảm bảo $k_1(\gamma_n) > 0$ |
| Hồ quang HIF | `HIF_INTERMITTENT_PROB` | `0.45` | xác suất | Xác suất cửa sổ chụp ảnh rơi vào chu kỳ hồ quang chập chờn |
| Hồ quang HIF | `HIF_DUTY_RANGE` | `(0.35, 0.85)` | tỷ lệ chu kỳ | Hệ số dẫn hiệu dụng $d_{\text{cond}}$ khi hồ quang chập chờn |
| Hồ quang HIF | `HIF_R_JITTER_LOGSTD` | `0.25` | log-std | Độ lệch chuẩn log-normal của biến thiên trở kháng tiếp xúc $m_R$ |
| Hồ quang HIF | `HIF_R_JITTER_CLIP` | `(0.60, 1.80)` | hệ số | Giới hạn kẹp cho $m_R$ |
| Hồ quang HIF | `HIF_R_EFF_MAX` | `2500.0` | `Ω` | Trần $R_{\text{eff}}$ đưa vào OpenDSS nhằm đảm bảo hội tụ số |
| Tải theo zone | `ZONE_LOAD_SPREAD` | `0.30` | `1σ` | Độ lệch chuẩn hệ số tải độc lập giữa 10 switching zones |
| Tải theo zone | `ZONE_LOAD_CLIP` | `(0.45, 1.65)` | hệ số | Giới hạn kẹp cho $m_{\text{zone}}(z)$ |
| Tải theo zone | `SPOT_FACTOR_CLIP` | `(0.25, 2.00)` | hệ số | Giới hạn kẹp cho tích $f_{\text{pre}}(\ell) = m_{\text{zone}} \cdot m_{\text{spot}}$ |
| Trôi tải pre/post | `LOAD_DRIFT_ZONE` | `0.008` | `1σ` (`0.8%`) | Trôi tải tương quan cấp zone giữa ảnh `pre` và `post` |
| Trôi tải pre/post | `LOAD_DRIFT_SPOT` | `0.015` | `1σ` (`1.5%`) | Trôi tải độc lập cấp phụ tải điểm giữa ảnh `pre` và `post` |
| Trôi tải pre/post | `LOAD_DRIFT_CLIP` | `(0.90, 1.10)` | hệ số | Giới hạn kẹp cho hệ số trôi tải tổng $1 + \delta_{\text{zone}} + \delta_{\text{spot}}$ |
| Nhiễu đo CT/PT | `CT_BIAS_MAG` | `0.015` | `1σ` (`1.5%`) | Sai số hệ thống biên độ CT (kẹp `±0.045`), cố định giữa `pre`/`post` |
| Nhiễu đo CT/PT | `CT_BIAS_ANG_DEG` | `0.8` | `1σ` (`°`) | Sai số hệ thống góc pha CT (kẹp `±2.5°`), cố định giữa `pre`/`post` |
| Nhiễu đo CT/PT | `PT_BIAS_MAG` | `0.008` | `1σ` (`0.8%`) | Sai số hệ thống biên độ PT (kẹp `±0.025`), cố định giữa `pre`/`post` |
| Nhiễu đo CT/PT | `PT_BIAS_ANG_DEG` | `0.4` | `1σ` (`°`) | Sai số hệ thống góc pha PT (kẹp `±1.5°`), cố định giữa `pre`/`post` |
| Nhiễu đo CT/PT | `NOISE_I_FLOOR_A` | `0.5` | `A RMS` | Sàn nhiễu cộng tính dòng pha (Gaussian phức, độc lập `pre`/`post`) |
| Nhiễu đo CT/PT | `NOISE_V_FLOOR_PU` | `0.001` | `pu` | Sàn nhiễu cộng tính điện áp pha (chỉ trên pha có điện) |

*Giữ nguyên không đổi:* `LOAD_MULT_RANGE = (0.3, 1.1)`, `LOAD_SPREAD = 0.20`, `SCENARIOS_PER_CASE = 3`, `SLG_RESISTANCES = [0.01, 1, 5, 10, 25, 50, 100, 200, 400]`, `PHASE_RESISTANCES = [0.01, 0.5, 2]`, `NOISE_MAG = 0.01`, `NOISE_ANG_DEG = 0.5`.

---

## 4. Hợp đồng tương thích ngược (ràng buộc cho T-43)

Để nâng cấp lõi mô phỏng mà **không làm gãy** các nghiên cứu đã công bố (`shf/transfer.py`, `shf/active_grid.py`, `shf/bus_locator.py`, `shf/hif_fusion.py`, `scripts/multi_feeder_eval.py`) và bộ 144 unit test hiện tại:

1. **`shf/feeder.py`:** Giữ nguyên chữ ký và kiểu trả về của `base_loads() -> list[tuple[str, float, float]]` và `scale_loads(base, factors)`. Bổ sung hàm phụ trợ mới (ví dụ `load_buses(base) -> list[str]`) để ánh xạ tên phụ tải sang bus/zone một lần duy nhất trước vòng lặp sự cố.
2. **`shf/faults.py`:**
   - Giữ nguyên hành vi mặc định khi gọi 2 tham số `faults._perturb(clean, rng)` (đang được gọi bởi `transfer.py`, `active_grid.py`, `bus_locator.py`, `hif_fusion.py`, `multi_feeder_eval.py`, `test_hif_fusion.py`). Mở rộng bằng tham số từ khóa tùy chọn `*, bias=None, floor_i=0.0, floor_v=0.0`.
   - Bổ sung các hàm thuần toán học dễ kiểm thử đơn vị: `emanuel_fundamental_factor(gamma)`, `sample_arc_resistance(r_nom, ftype, rng)`, `sample_ct_pt_bias(devices, rng)`.
   - Chữ ký `faults.generate(zones, noise=True, seed=0, verbose=True, realistic=None)`: khi `realistic is None`, tự động lấy `realistic = noise`.
     - Khi `noise=False` (dùng cho test vật lý sạch như `test_fpi_baseline_finds_bolted_three_phase_fault`): **tắt** toàn bộ hồ quang chập chờn, trôi tải pre/post, sai số hệ thống CT/PT và nhiễu đo (chỉ giữ bài toán tuyến tính sạch).
     - Khi `noise=True` (mặc định của `run.py`): **bật** đầy đủ cả 3 cơ chế thực tế, hoàn toàn **deterministic theo `seed`**.
   - Xuất đủ toàn bộ cột cũ trong `DataFrame` + 4 cột chẩn đoán `r_eff`, `is_arcing`, `arc_kappa`, `arc_duty`.
   - Khôi phục mạch OpenDSS về trạng thái sạch (`Edit Fault.F enabled=no`, tải hệ số `1.0`, `LoadMult=1.0`, `solve(controls=True)`) sau khi kết thúc `generate()`.
3. **`run.py` và `results/metrics.json`:** Giữ nguyên toàn bộ schema khóa cũ để `scripts/error_analysis.py`, `scripts/export_control_room.py`, `shf/dashboard.py`, và `harness/facts.toml` đọc trực tiếp không lỗi; có thể bổ sung khối metadata mô tả chế độ mô phỏng trong `metrics.json["simulation_model"]` nếu cần.

---

## 5. Bảng tiêu chí đánh giá Trước / Sau (số liệu Trước đọc từ `results/`, Sau khóa trống chờ T-44)

Mọi con số ở cột **Trước (Baseline cũ)** dưới đây được đọc trực tiếp từ `results/metrics.json` và `results/error_analysis/error_analysis.json` (mô phỏng tuyến tính 60 Hz cũ, `11,448` sự cố, `SCENARIOS_PER_CASE = 3`, `GroupKFold` 5-fold theo bus). Cột **Sau (Mô phỏng thực tế mới)** chưa chạy nên ghi rõ trạng thái theo đúng quy tắc 1 của `CLAUDE.local.md`.

| Nhóm chỉ số | Chỉ số đánh giá | Trước (Baseline cũ, `results/`) | Sau (Mô phỏng thực tế mới — T-44) | Ghi chú đọc kết quả |
|---|---|---:|---|---|
| Dữ liệu & hội tụ | Tổng số sự cố mô phỏng | `11,448` (`SLG 7,155`, `LL 1,845`, `LLG 1,845`, `3PH 603`) | *chưa chạy (chờ T-44)* | Giữ đúng 10 zones, `SCENARIOS_PER_CASE = 3` |
| Dữ liệu & hội tụ | Tỷ lệ hội tụ OpenDSS (`converged_share`) | `100.0%` (`1.0`) | *chưa chạy (chờ T-44)* | Yêu cầu nghiệm thu `≥ 99.5%` |
| Accuracy tổng | Conventional FPI (`fpi_baseline`) | `56.1%` (`0.5609`) | *chưa chạy (chờ T-44)* | Báo cáo trung thực mức tăng/giảm |
| Accuracy tổng | FPI không phát hiện (`no_device_flagged`) | `25.8%` (`0.2582`) | *chưa chạy (chờ T-44)* | Dự kiến tăng do hồ quang suy giảm dòng 60 Hz |
| Accuracy tổng | ML chỉ biên độ (`ml_magnitude_only`) | `87.5%` (`0.8751`) | *chưa chạy (chờ T-44)* | Chịu tác động trực tiếp của `ZONE_LOAD_SPREAD` & bias CT/PT |
| Accuracy tổng | ML đầy đủ (`ml_full`, biên độ + `pre/post`) | `97.7%` (`0.9774`) | *chưa chạy (chờ T-44)* | Dự kiến giảm do HIF hồ quang + trôi tải + sàn nhiễu |
| Theo loại sự cố (`ml_full`) | `3PH` / `LL` / `LLG` / `SLG` | `100.0%` / `99.8%` / `99.9%` / `96.5%` | *chưa chạy (chờ T-44)* | Kiểm tra pha ngắn mạch nặng vẫn giữ vững |
| SLG `100 Ω` | FPI / ML mag / ML full | `8.4%` / `70.8%` / `98.4%` | *chưa chạy (chờ T-44)* | Điểm bắt đầu kích hoạt hồ quang (`R >= 100 Ω`) |
| SLG `200 Ω` | FPI / ML mag / ML full | `2.3%` / `38.0%` / `93.7%` | *chưa chạy (chờ T-44)* | Dự kiến giảm rõ do $R_{\text{eff}}$ và trôi tải |
| SLG `400 Ω` | FPI / ML mag / ML full | `1.0%` / `22.4%` / `76.5%` | *chưa chạy (chờ T-44)* | Vùng khó nhất: dòng 60 Hz chìm trong sàn nhiễu & trôi tải |
| Mất 1 cảm biến (`ml_full`) | `missing_sensor_accuracy` (min–max / mean) | `83.2%–95.5%` (mean `89.0%`) | *chưa chạy (chờ T-44)* | Đánh giá độ bền khi 1 thiết bị mất liên lạc |
| Quãng đường tuần tra | `patrol_kft`: không định vị / FPI / ML full | `39.0` / `19.5` / `5.1 kft` | *chưa chạy (chờ T-44)* | Đo tác động vận hành thực tế của sai số mới |
| Phân tích lỗi (`error_analysis`) | Tổng số lỗi ML & tỷ trọng từ SLG `≥ 200 Ω` | `259` lỗi (`2.3%`), `237` (`91.5%`) ở `≥ 200 Ω` | *chưa chạy (chờ T-44)* | Theo dõi dịch chuyển phân bố lỗi xuống `100 Ω` và tải nặng |
| Phân tích lỗi (`error_analysis`) | Lỗi theo nhóm tải nhẹ / vừa / nặng | `0.9%` / `1.8%` / `4.1%` | *chưa chạy (chờ T-44)* | Kiểm tra ảnh hưởng của tải nặng lên SNR |
| Phân tích lỗi (`error_analysis`) | Trì hoãn dưới ngưỡng tin cậy `0.95` | Giữ `97.2%` (`2.8%` chuyển người), đúng `99.1%` (`97` lỗi) | *chưa chạy (chờ T-44)* | Kiểm tra độ hiệu chuẩn xác suất khi bài toán khó hơn |

---

## 6. Tiêu chí nghiệm thu (khóa trước khi chạy)

Nhánh phát triển này **KHÔNG** đặt mục tiêu "độ chính xác phải cao hơn bản cũ" — ngược lại, vì bài toán trở nên sát thực tế và khó hơn, độ chính xác `SLG 100–400 Ω` và tổng thể được kỳ vọng sẽ **giảm**. Các tiêu chí nghiệm thu (`R1`–`R5`) kiểm tra **chất lượng kỹ thuật, tính đúng đắn vật lý và tính trung thực**:

1. **`R1` — Đúng vật lý, deterministic & hội tụ ổn định (T-43):**
   - Toàn bộ unit test mới trong `tests/test_shf.py` kiểm chứng: (i) công thức $k_1(\gamma)$ khớp giá trị giải tích (`k_1(0)=1`, `k_1(0.30)≈0.6238`, `k_1(0.33)≈0.5876`) và khớp LTspice; (ii) $R_{\text{eff}} \ge 0.5 R_{\text{nom}}$ và phân bố có $R_{\text{eff}} > R_{\text{nom}}$ cho SLG `≥ 100 Ω`, còn `3PH/LL/LLG` và `SLG < 100 Ω` giữ $R_{\text{eff}} = R_{\text{nom}}$; (iii) tải theo zone biến động độc lập và có trôi tải nhẹ giữa `pre`/`post`; (iv) sai số hệ thống CT/PT giữ nguyên giữa `pre`/`post` trong cùng 1 sự cố, sàn nhiễu dòng hoạt động trên pha có điện và không bơm nhiễu vào pha vắng mặt; (v) `faults.generate(..., seed=k)` tái lập giống hệt nhau giữa 2 lần chạy; (vi) chế độ `noise=False` giữ sạch hoàn toàn.
   - Chạy `run.py` đầy đủ đạt `converged_share ≥ 99.5%`.
2. **`R2` — Không tinh chỉnh ngược tham số để "làm đẹp" kết quả (T-43 & T-44):**
   - Giữ nguyên hoàn toàn các hằng số đã khóa ở Mục 3, cấu trúc `GroupKFold` 5-fold theo bus, và siêu tham số `HistGradientBoostingClassifier` (`max_iter=300, lr=0.1, max_leaf_nodes=31`, `DROPOUT_RATE=0.15`) trong `shf/model.py`.
   - Tuyệt đối không nới nhẹ `ZONE_LOAD_SPREAD`, `LOAD_DRIFT_*`, `HIF_DUTY_RANGE` hay `NOISE_I_FLOOR_A` sau khi thấy độ chính xác giảm. Nếu phát hiện lỗi kỹ thuật thật sự (ví dụ OpenDSS không hội tụ diện rộng dưới `99.5%`), phải ghi rõ mục **Phụ lục điều chỉnh (Addendum)** trong `PLAN.md` kèm nguyên nhân trước khi chạy lại.
3. **`R3` — Chẩn đoán tương đối FPI vs ML & ý nghĩa kỹ thuật điện (T-44):**
   - Kiểm tra và báo cáo trung thực: (a) sự cố trở kháng thấp (`3PH`, `LL`, `LLG`, `SLG 0.01–25 Ω`) vẫn giữ độ chính xác cao; (b) so sánh `ml_full` với `fpi_baseline` và `ml_magnitude_only` ở cả tổng thể lẫn dải `SLG 100/200/400 Ω` và `patrol_kft`; (c) chỉ ra rõ giới hạn vật lý của cảm biến 60 Hz đơn thuần khi đối diện hồ quang HIF chập chờn + trôi tải, qua đó liên kết mạch lạc với nghiên cứu hợp nhất cảm biến biên 15.36 kHz (`research/hif-fusion/PLAN.md`).
4. **`R4` — Cách ly phạm vi & không làm hỏng các phân hệ khác (T-43 → T-47):**
   - Không làm gãy `shf/transfer.py`, `shf/active_grid.py`, `shf/hif_fusion.py`, `shf/hourly.py`, `shf/spice.py`, và phân hệ Tier-1 `hif_sensor/`.
   - Toàn bộ pytest Tier-2 (`144+` tests) và Tier-1 (`10` tests trong `hif_sensor/tests/test_hif.py`) pass `0 failed`.
5. **`R5` — Truy xuất nguồn gốc & đồng bộ báo cáo EN/VI (T-44 → T-47):**
   - Mọi file trong `results/` được sinh từ script (`run.py`, `scripts/error_analysis.py`, `scripts/export_control_room.py`, `scripts/export_oneline_dxf.py`), không chỉnh tay.
   - `.venv\Scripts\python -m shf.provenance` pass (`0` changed, `0` missing).
   - `.venv\Scripts\python harness\check.py --tests` kết thúc với **0 failed, 0 warnings** sau khi đồng bộ `shf/dashboard.py`, `shf/dashboard_text.py`, `docs/index.html`, `docs/monitor/data.json`, `README.md`, `docs/vi/study-guide.md`, `docs/vi/module-guide.md`, `docs/monitor/README.md`, và `harness/facts.toml`.
   - Bên trong `hif_sensor/`: provenance (`23` files) và pytest (`10 passed`) đều xanh.

---

## 7. Cam kết trung thực & giới hạn vật lý không thể vượt qua

Theo đúng quy định bắt buộc tại `CLAUDE.local.md` và `AGENTS.md`:

1. **Báo cáo trung thực kể cả khi độ chính xác giảm:** Nếu độ chính xác `ml_full` giảm từ `97.7%` xuống thấp hơn đáng kể (hoặc `SLG 400 Ω` giảm mạnh xuống dưới `50%`), đó là **phát hiện khoa học trung thực** phản ánh giới hạn vật lý thực sự của định vị 60 Hz trước hồ quang chập chờn và trôi tải — phải được trình bày thẳng thắn trên trang báo cáo (EN/VI), `README.md`, và `PLAN.md` (Mục 8 sau khi chạy T-44), tuyệt đối không giấu số liệu cũ hay ngụy tạo giải thích.
2. **Mọi con số chỉ lấy từ `results/`:** Không có bất kỳ con số ước đoán hay điền tạm nào cho cột "Sau" trước khi T-44 hoàn tất và qua kiểm tra SHA-256 `shf.provenance`.
3. **Vẫn là mô phỏng 100%:** Ngay cả sau nâng cấp này, nghiên cứu vẫn là **mô phỏng miền phasor 60 Hz trong OpenDSS** — **không phải** đo đạc hiện trường trên lưới vận hành, **không phải** thử nghiệm thiết bị đóng cắt mang điện, và **không phải** kiểm chứng SCADA ngoài lưới thực.
4. **Giới hạn vật lý còn lại (phải ghi rõ trong `Assumptions and limitations` ở T-46):**
   - Quy đổi hồ quang Emanuel + chu kỳ chập chờn sang điện trở hiệu dụng 60 Hz ($R_{\text{eff}}$) nắm bắt được suy giảm thành phần cơ bản và sự phân tán biên độ dòng sự cố, nhưng **không** mô phỏng quá độ điện từ (EMTP), sóng lan truyền, bão hòa lõi CT khi dòng ngắn mạch lớn có thành phần DC lệch trục, hay dạng sóng thời gian thực (các đặc trưng sóng hài bậc cao `h2, h3, h5`, `DC`, bất đối xứng bán chu kỳ chỉ được khai thác ở phân hệ cảm biến biên 15.36 kHz `hif_sensor/` và `research/hif-fusion/PLAN.md`).
   - Khoảng cách miền giữa hồ quang Emanuel mô phỏng và hồ quang thực tế vẫn tồn tại (như đã ghi nhận ở phân hệ `hif_sensor/` khi áp dụng mô hình Phase-0 lên bản ghi thực 22 kV VeHIF).
   - Chưa mô phỏng đóng cắt tụ bù hoặc bước nhảy phụ tải lớn như sự kiện không phải sự cố (`NO_FAULT`) trong bộ lõi này — bài toán phân biệt `NO_FAULT` đã được tách riêng trong `research/active-grid-gnn/PLAN.md` và `research/hif-fusion/PLAN.md`.

---

## 8. Kết quả thực nghiệm (chưa chạy — chờ T-43 & T-44)

*Chưa chạy. Mục này sẽ được điền sau khi T-43 hoàn tất nâng cấp lõi mô phỏng và T-44 chạy lại đầy đủ `run.py`, `scripts/error_analysis.py`, `scripts/export_control_room.py` với xác thực `shf.provenance`.*
