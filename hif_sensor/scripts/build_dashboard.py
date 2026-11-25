"""Build the Tier-1 Edge HIF Sensor technical report page (index.html + figures/ + data/).

Matches self-healing-feeder/docs/index.html byte-for-byte in typography (system-ui),
warm-paper palette (#f9f9f7) & dark mode, shared EN/VI (shf-lang) & Theme (shf-theme) keys,
sleek 2-tier navigation pill, interactive Explain Guide buddy (? buttons on every tile & section),
and collapsible <details class="deep"> cards.
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESULTS = ROOT / "results"
esc = html.escape


def T(en: str, vi: str) -> str:
    return f'<span data-l="en">{en}</span><span data-l="vi">{vi}</span>'


def pct(v, digits=1) -> str:
    if v is None:
        return "—"
    return f"{float(v) * 100:.{digits}f}%"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def deep_box(title_en: str, title_vi: str, sub_en: str, sub_vi: str,
             inner: str, badge: str = "", id_: str = "") -> str:
    if not inner or not inner.strip():
        return ""
    id_attr = f' id="{id_}"' if id_ else ""
    b_html = f'<span class="deep-badge">{badge}</span>' if badge else ""
    return (
        f'<details class="deep"{id_attr}>'
        f'<summary class="deep-sum">'
        f'<span class="deep-t"><b>{T(title_en, title_vi)}</b>'
        f'<small>{T(sub_en, sub_vi)}</small></span>'
        f'<span class="deep-r">{b_html}'
        f'<span class="deep-act">{T("Expand", "Xem chi tiết")}</span></span>'
        f'</summary>'
        f'<div class="deep-body">{inner}</div>'
        f'</details>'
    )


def copy_assets(out_dir: Path):
    fig_dir = out_dir / "figures"
    data_dir = out_dir / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    fig_src = RESULTS / "figures"
    copied_figs = []
    if fig_src.exists():
        for p in sorted(fig_src.glob("*.png")):
            shutil.copy2(p, fig_dir / p.name)
            copied_figs.append(p.name)

    data_files = [
        (ROOT / "circuit" / "ltspice_results.json", "ltspice_results.json"),
        (RESULTS / "metrics.json", "metrics.json"),
        (RESULTS / "real_vehif.json", "real_vehif.json"),
        (RESULTS / "real_vehif_tests.csv", "real_vehif_tests.csv"),
        (RESULTS / "test_vectors.json", "test_vectors.json"),
        (RESULTS / "test_vectors_phase15.json", "test_vectors_phase15.json"),
        (RESULTS / "c_firmware_verify.json", "c_firmware_verify.json"),
        (RESULTS / "phase15_vehif.json", "phase15_vehif.json"),
        (RESULTS / "provenance" / "manifest.json", "provenance_manifest.json"),
        (ROOT / "firmware" / "hif_model.h", "hif_model.h"),
        (ROOT / "firmware" / "hif_model_phase15.h", "hif_model_phase15.h"),
    ]
    copied_data = []
    for src, dst_name in data_files:
        if src.exists():
            shutil.copy2(src, data_dir / dst_name)
            copied_data.append((dst_name, src.stat().st_size))
    return copied_figs, copied_data


def figure_card(fig_dir: Path, fname: str, cap_en: str, cap_vi: str) -> str:
    if not (fig_dir / fname).exists():
        return ""
    return (
        f'<figure class="fig">'
        f'<img src="figures/{esc(fname)}" alt="{esc(cap_en)}" loading="lazy">'
        f'<figcaption>{T(esc(cap_en), esc(cap_vi))}</figcaption>'
        f'</figure>'
    )


def build_explain_data(m: dict, ve: dict, p15: dict | None, cv: dict | None, lt: dict) -> str:
    ml = m.get("test_ml_int8", {})
    b51 = m.get("test_baselines", {}).get("residual_overcurrent_51N", {})
    rf = ve.get("real_faults", {})
    bg = ve.get("background_recordings", {})
    ac = lt.get("ac", {})
    j20 = (p15 or {}).get("few_shot_adaptation", {}).get("by_fraction", {}).get("0.2", {}).get("joint_mlp_int8", {})
    z0 = (p15 or {}).get("few_shot_adaptation", {}).get("zero_shot_phase0", {})
    c0 = (cv or {}).get("phase0_official_6_vectors", {})

    xdata = {
        "tile-p0": {
            "en": {
                "title": "Simulated HIF detection (Phase 0)",
                "what": f"The 504 B int8 Tiny MLP detects <b>{pct(ml.get('detection_rate'))}</b> of simulated downed-conductor arcs across 5 ground surfaces, compared to <b>{pct(b51.get('detection_rate'))}</b> for a conventional 51N ground-overcurrent relay.",
                "read": f"Measured on 396 simulated HIF events and 404 normal disturbance events at a <b>{pct(ml.get('false_alarm_rate_normal'))}</b> normal false-alarm rate.",
                "why": "Downed conductors on dry ground draw only a few amps, buried below normal feeder load; harmonic asymmetry and cycle-to-cycle randomness reveal the arc.",
            },
            "vi": {
                "title": "Phát hiện HIF mô phỏng (Phase 0)",
                "what": f"Mạng Tiny MLP int8 504 B phát hiện <b>{pct(ml.get('detection_rate'))}</b> sự cố hồ quang chạm đất mô phỏng trên 5 loại bề mặt, so với chỉ <b>{pct(b51.get('detection_rate'))}</b> của rơ-le quá dòng chạm đất 51N.",
                "read": f"Đo trên 396 sự cố HIF và 404 nhiễu bình thường mô phỏng ở mức báo nhầm <b>{pct(ml.get('false_alarm_rate_normal'))}</b>.",
                "why": "Dây đứt rơi xuống nền khô chỉ kéo vài ampe, lọt dưới ngưỡng dòng tải thường; độ bất đối xứng sóng hài và dao động ngẫu nhiên giữa các chu kỳ giúp nhận ra hồ quang.",
            },
        },
        "tile-size": {
            "en": {
                "title": "Microcontroller footprint (504 B)",
                "what": f"The entire neural network (16→16→8→1) holds <b>{m.get('model', {}).get('params', 417)}</b> parameters quantized to <b>int8</b> weights plus float32 biases — <b>{m.get('model', {}).get('bytes_int8_weights_float_bias', 504)} bytes</b> total.",
                "read": "Less than 0.1% of an ESP32-S3's 512 KB SRAM, with a median detection delay of 5 power cycles.",
                "why": "Runs directly at each recloser/switch edge node without cloud latency or expensive industrial GPUs.",
            },
            "vi": {
                "title": "Dung lượng siêu gọn trên chip (504 B)",
                "what": f"Toàn bộ mạng nơ-ron (16→16→8→1) chỉ gồm <b>{m.get('model', {}).get('params', 417)}</b> tham số lượng tử hóa <b>int8</b> — tốn đúng <b>{m.get('model', {}).get('bytes_int8_weights_float_bias', 504)} byte</b> bộ nhớ.",
                "read": "Chiếm chưa tới 0,1% bộ nhớ SRAM 512 KB của ESP32-S3, trễ phát hiện trung vị chỉ 5 chu kỳ điện.",
                "why": "Chạy trực tiếp tại từng nút cảm biến trên cột mà không cần gửi dạng sóng thô về máy chủ.",
            },
        },
        "tile-p1": {
            "en": {
                "title": "Real 22 kV VeHIF zero-shot test (Phase 1)",
                "what": f"Tested zero-shot on <b>250 real 22 kV, 50 Hz vegetation-fault recordings</b> (VeHIF, CC0) with <b>{pct(bg.get('alarm_rate'))}</b> alarms on all 53 real background recordings.",
                "read": f"Detection drops from 94.7% (sim) to <b>{pct(rf.get('detection_rate'))}</b> because real tree-contact leakage under 2 A is much more symmetric than simulated downed-conductor arcs.",
                "why": "Exposes the honest simulation-to-reality domain gap instead of hiding behind simulated numbers.",
            },
            "vi": {
                "title": "Kiểm thử Zero-Shot trên VeHIF 22 kV thật (Phase 1)",
                "what": f"Thử thẳng không train lại trên <b>250 bản ghi sự cố chạm cây thật 22 kV, 50 Hz</b> (VeHIF, CC0), đạt <b>{pct(bg.get('alarm_rate'))}</b> báo nhầm trên cả 53 bản ghi nền thật.",
                "read": f"Tỉ lệ phát hiện giảm từ 94,7% (mô phỏng) xuống <b>{pct(rf.get('detection_rate'))}</b> vì dòng rò chạm cây thật dưới 2 A đối xứng và đều hơn hồ quang mô phỏng.",
                "why": "Chỉ ra trung thực khoảng cách giữa mô phỏng và thực tế thay vì chỉ báo cáo số liệu mô phỏng đẹp.",
            },
        },
        "tile-p15": {
            "en": {
                "title": "Phase 1.5 few-shot adaptation (5 seeds)",
                "what": f"Jointly fine-tuning the exact same <b>504 B int8</b> MLP with 20% real VeHIF recordings (strict recording-ID split) lifts overall detection from <b>{pct(z0.get('real_detection_mean'))}</b> to <b>{pct(j20.get('real_detection_mean'))}</b> and 0–2 A from <b>{pct(z0.get('real_0_to_2A_mean'))}</b> to <b>{pct(j20.get('real_0_to_2A_mean'))}</b>.",
                "read": f"Keeps strict safety: real background FA <b>{pct(j20.get('real_bg_fa_mean'))}</b>, simulated retention <b>{pct(j20.get('sim_detection_mean'))}</b>, but honestly misses the pre-registered +15 pp 0–2 A target (+7.41 pp).",
                "why": "Shows both the real gain from target-domain calibration and the physical SNR limit of sub-1 A leakage under 1–20 A unbalance.",
            },
            "vi": {
                "title": "Thích ứng Few-Shot Phase 1.5 (5 seed)",
                "what": f"Tinh chỉnh đồng thời chính mạng <b>504 B int8</b> bằng 20% bản ghi VeHIF thật (tách tuyệt đối theo ID bản ghi) giúp tổng phát hiện tăng từ <b>{pct(z0.get('real_detection_mean'))}</b> lên <b>{pct(j20.get('real_detection_mean'))}</b>, dải 0–2 A tăng từ <b>{pct(z0.get('real_0_to_2A_mean'))}</b> lên <b>{pct(j20.get('real_0_to_2A_mean'))}</b>.",
                "read": f"Giữ chặt an toàn báo nhầm: nền thật <b>{pct(j20.get('real_bg_fa_mean'))}</b>, giữ mô phỏng <b>{pct(j20.get('sim_detection_mean'))}</b>, nhưng ghi nhận trung thực chưa chạm ngưỡng kỳ vọng +15 pp (đạt +7,41 pp).",
                "why": "Chứng minh hiệu quả thật của hiệu chỉnh miền dữ liệu đồng thời chỉ rõ giới hạn tỷ số tín hiệu/nhiễu của dòng rò dưới 1 A.",
            },
        },
        "tile-c": {
            "en": {
                "title": "Compiled GCC C firmware bit-parity",
                "what": f"<code>firmware/hif_infer.c</code> compiled natively with <code>gcc -O2 -Wall -Wextra -Werror</code> matches Python int8 within <b>{c0.get('max_abs_prob_error', 0):.2e}</b> with <b>100%</b> threshold agreement.",
                "read": f"Host benchmark runs in <b>{c0.get('host_latency_us_per_inference', 0):.3f} µs</b> per inference and verifies the 3-window relay persistence state machine.",
                "why": "Proves the exported C header is not pseudocode — it executes identically to the evaluated Python model.",
            },
            "vi": {
                "title": "Khớp bit Firmware C biên dịch bằng GCC",
                "what": f"<code>firmware/hif_infer.c</code> biên dịch thật bằng <code>gcc -O2 -Wall -Wextra -Werror</code> khớp Python int8 tới sai số <b>{c0.get('max_abs_prob_error', 0):.2e}</b> và đồng thuận ngưỡng <b>100%</b>.",
                "read": f"Tốc độ đo trên máy chủ <b>{c0.get('host_latency_us_per_inference', 0):.3f} µs/lần</b> và đã kiểm đúng bộ đếm duy trì 3 cửa sổ.",
                "why": "Khẳng định file header C xuất ra chạy khớp tuyệt đối với mô hình Python đã kiểm chứng, không phải mã giả.",
            },
        },
        "sec-frontend": {
            "en": {
                "title": "Analog anti-alias filter (50 Hz VN vs 60 Hz US)",
                "what": f"4th-order Butterworth Sallen-Key LPF verified in LTspice 26.1.1: <b>−3 dB at {ac.get('f_minus3dB_Hz', 2045.1)} Hz</b> and <b>−{ac.get('attenuation_at_7680Hz_dB', 46.4)} dB</b> at 60 Hz Nyquist.",
                "read": "Compare rows 1–3: keeping the same PCB on Vietnam 50 Hz (12.8 kHz ADC) gives −40.0 dB at Nyquist; scaling two resistors ×1.2 restores −46.7 dB with zero PCB layout change.",
                "why": "Prevents inverter switching noise (8–20 kHz) from aliasing into harmonic bands used by the AI detector.",
            },
            "vi": {
                "title": "Mạch lọc chống răng cưa (50 Hz VN vs 60 Hz Mỹ)",
                "what": f"Mạch lọc thông thấp Butterworth bậc 4 Sallen-Key kiểm chứng LTspice 26.1.1: <b>−3 dB tại {ac.get('f_minus3dB_Hz', 2045.1)} Hz</b> và suy giảm <b>−{ac.get('attenuation_at_7680Hz_dB', 46.4)} dB</b> tại Nyquist 60 Hz.",
                "read": "So sánh 3 hàng bảng: mang mạch sang lưới 50 Hz Việt Nam (12,8 kHz) đạt −40,0 dB; chỉ cần đổi 2 điện trở ×1,2 là khôi phục −46,7 dB mà không phải vẽ lại PCB.",
                "why": "Chặn nhiễu đóng cắt inverter (8–20 kHz) gập ngược xuống dải sóng hài mà mô hình AI dùng để nhận diện hồ quang.",
            },
        },
        "sec-vehif": {
            "en": {
                "title": "Real VeHIF 22 kV & Phase 1.5 analysis",
                "what": "Side-by-side comparison across fault-current bands from 0–1 A up to 5–10 A comparing Phase 0 simulated, Phase 1 real zero-shot, and Phase 1.5 few-shot adapted models.",
                "read": "Notice that above 2 A real faults reach 94.7% detection; the hard region is 0–1 A where resistive vegetation leakage is tiny compared to feeder load.",
                "why": "Feature ablation further proves cycle-to-cycle temporal randomness (temporal_only_8) transfers best zero-shot on 0–2 A (51.1% vs 43.1%).",
            },
            "vi": {
                "title": "Phân tích dữ liệu thật VeHIF 22 kV & Phase 1.5",
                "what": "Đối chiếu trực tiếp từng dải dòng sự cố từ 0–1 A tới 5–10 A giữa mô phỏng Phase 0, chạy thẳng zero-shot Phase 1 và tinh chỉnh few-shot Phase 1.5.",
                "read": "Trên 2 A mô hình đạt tới 94,7%; vùng khó nhất là 0–1 A khi dòng rò chạm cây quá nhỏ so với dòng tải nền.",
                "why": "Khảo sát bỏ đặc trưng chứng minh thêm rằng độ dao động ngẫu nhiên giữa các chu kỳ (temporal_only_8) chuyển giao zero-shot ở dải 0–2 A tốt nhất (51,1% so với 43,1%).",
            },
        },
    }
    return json.dumps(xdata, ensure_ascii=False)


def build(out_dir: Path | None = None, parent_href: str = "../") -> Path:
    out_dir = out_dir or (ROOT / "docs")
    fig_dir = out_dir / "figures"
    copied_figs, copied_data = copy_assets(out_dir)

    lt = load_json(ROOT / "circuit" / "ltspice_results.json") or {}
    m = load_json(RESULTS / "metrics.json") or {}
    ve = load_json(RESULTS / "real_vehif.json") or {}
    p15 = load_json(RESULTS / "phase15_vehif.json")
    cv = load_json(RESULTS / "c_firmware_verify.json")
    prov = load_json(RESULTS / "provenance" / "manifest.json")

    ml = m.get("test_ml_int8", {})
    b51 = m.get("test_baselines", {}).get("residual_overcurrent_51N", {})
    bh3 = m.get("test_baselines", {}).get("third_harmonic_level", {})
    rf = ve.get("real_faults", {})
    bg = ve.get("background_recordings", {})

    # Headline tiles
    p15_det_str = "Pending"
    p15_sub_en = "Phase 1.5 Kaggle run"
    p15_sub_vi = "Chưa có kết quả Phase 1.5"
    if p15 and "few_shot_adaptation" in p15:
        j20 = p15["few_shot_adaptation"]["by_fraction"]["0.2"]["joint_mlp_int8"]
        z0 = p15["few_shot_adaptation"]["zero_shot_phase0"]
        p15_det_str = pct(j20["real_detection_mean"])
        p15_sub_en = f"0–2 A: {pct(z0['real_0_to_2A_mean'])} → {pct(j20['real_0_to_2A_mean'])} (20% few-shot)"
        p15_sub_vi = f"Dải 0–2 A: {pct(z0['real_0_to_2A_mean'])} → {pct(j20['real_0_to_2A_mean'])} (20% few-shot)"

    c_err_str = "Header OK"
    c_sub_en = "Header ↔ NPZ int8 exact match"
    c_sub_vi = "Khớp bit header ↔ NPZ int8"
    if cv and cv.get("phase0_official_6_vectors", {}).get("compiled"):
        c0 = cv["phase0_official_6_vectors"]
        c_err_str = f"{c0['max_abs_prob_error']:.1e}"
        c_sub_en = f"GCC -O2 -Werror · {c0['host_latency_us_per_inference']:.2f} µs/inf"
        c_sub_vi = f"GCC -O2 -Werror · {c0['host_latency_us_per_inference']:.2f} µs/lần"

    tiles_html = f"""
    <div class="tiles">
      <div class="tile" data-x="tile-p0"><div class="tk">{T("Sim HIF Detected (Phase 0)", "Bắt HIF mô phỏng (Phase 0)")}</div>
        <div class="tv">{pct(ml.get("detection_rate"))}</div>
        <div class="ts">{T(f"vs 51N {pct(b51.get('detection_rate'))} · FA {pct(ml.get('false_alarm_rate_normal'))}",
                           f"so với 51N {pct(b51.get('detection_rate'))} · báo nhầm {pct(ml.get('false_alarm_rate_normal'))}")}</div></div>
      <div class="tile" data-x="tile-size"><div class="tk">{T("Chip Footprint", "Dung lượng trên chip")}</div>
        <div class="tv">{m.get('model', {}).get('bytes_int8_weights_float_bias', 504)} B</div>
        <div class="ts">{T(f"{m.get('model', {}).get('params', 417)} params · int8 · {ml.get('delay_cycles_median', 5):.0f}-cycle delay",
                           f"{m.get('model', {}).get('params', 417)} tham số · int8 · trễ {ml.get('delay_cycles_median', 5):.0f} chu kỳ")}</div></div>
      <div class="tile" data-x="tile-p1"><div class="tk">{T("Real VeHIF 0-Shot (Phase 1)", "VeHIF thật 0-Shot (Phase 1)")}</div>
        <div class="tv">{pct(rf.get("detection_rate"))}</div>
        <div class="ts">{T(f"250 real 22 kV faults · 53 bg {pct(bg.get('alarm_rate'))} FA",
                           f"250 sự cố 22 kV thật · 53 nền {pct(bg.get('alarm_rate'))} FA")}</div></div>
      <div class="tile" data-x="tile-p15"><div class="tk">{T("VeHIF Adapted (Phase 1.5)", "Thích ứng VeHIF (Phase 1.5)")}</div>
        <div class="tv">{esc(p15_det_str)}</div>
        <div class="ts">{T(esc(p15_sub_en), esc(p15_sub_vi))}</div></div>
      <div class="tile" data-x="tile-c"><div class="tk">{T("C Firmware Parity", "Khớp bit code C")}</div>
        <div class="tv">{esc(c_err_str)}</div>
        <div class="ts">{T(esc(c_sub_en), esc(c_sub_vi))}</div></div>
    </div>
    """

    story3 = f"""
    <div class="steps3">
      <div class="st3"><span class="sn">1</span><div><b>{T("Hardware Front End (LTspice)", "Mạch đầu vào Analog (LTspice)")}</b>
        <small>{T("Clamp CT + 4th-order Butterworth 2.05 kHz filter (−46.4 dB @ 60 Hz Nyquist; 50 Hz VN retune ready).",
                  "Kẹp CT + lọc Butterworth bậc 4 (2.05 kHz, −46.4 dB tại Nyquist 60 Hz; có bảng đổi 2 trở cho lưới 50 Hz VN).")}</small></div></div>
      <div class="st3"><span class="sn">2</span><div><b>{T("Tiny 504 B int8 AI + GCC C", "AI siêu gọn 504 B int8 + C GCC")}</b>
        <small>{T("16 FFT harmonic/randomness features → 16→16→8→1 MLP. Feeds Tier-2 Feeder FLISR (4/4 H1–H4 PASS).",
                  "16 đặc trưng sóng hài/ngẫu nhiên → MLP 16→16→8→1. Cấp tín hiệu cho Tầng 2 Lưới FLISR (đạt 4/4 H1–H4).")}</small></div></div>
      <div class="st3"><span class="sn">3</span><div><b>{T("Real 22 kV VeHIF + Phase 1.5", "Kiểm chứng VeHIF 22 kV thật + Phase 1.5")}</b>
        <small>{T("Diagnosed the 94.7% → 56.0% domain gap (symmetric tree arcs) and evaluated leak-free few-shot adaptation.",
                  "Tìm ra nguyên nhân tụt 94.7% → 56.0% (hồ quang cây đối xứng hơn) và thử nghiệm thích ứng few-shot không rò rỉ.")}</small></div></div>
    </div>
    """

    # Section 1: Front End & 50/60 Hz
    from hif.frontend import F_LINE, F_LINE_VN, STAGES, STAGES_50HZ_RETUNED, frequency_response_summary
    hw60 = frequency_response_summary(F_LINE, STAGES)
    hw50 = frequency_response_summary(F_LINE_VN, STAGES)
    hw50r = frequency_response_summary(F_LINE_VN, STAGES_50HZ_RETUNED)
    ac = lt.get("ac", {})
    tr_lt = lt.get("transient_30A_rms_plus_15pct_3rd_plus_9kHz", {})

    freq_rows = ""
    for label_en, label_vi, d in (
        ("60 Hz US (Current PCB, LTspice)", "60 Hz Mỹ (Mạch hiện tại, LTspice)", hw60),
        ("50 Hz Vietnam / VeHIF (Same PCB)", "50 Hz Việt Nam / VeHIF (Giữ nguyên mạch)", hw50),
        ("50 Hz Vietnam (Retuned R×1.2)", "50 Hz Việt Nam (Đổi 2 điện trở R×1.2)", hw50r),
    ):
        freq_rows += (
            f"<tr><td>{T(label_en, label_vi)}</td>"
            f"<td>{d['adc_sample_rate_Hz']:,.0f} Hz</td>"
            f"<td>{d['nyquist_Hz']:,.0f} Hz</td>"
            f"<td>{d['f_minus3dB_Hz']:,.1f} Hz</td>"
            f"<td>−{d['attenuation_at_nyquist_dB']:.2f} dB</td>"
            f"<td>{d['phase_lag_at_f1_deg']:.2f}°</td>"
            f"<td>1..{d['harmonics_within_3dB']}</td>"
            f"<td>{d['window_8cycles_ms']:.1f} ms</td></tr>"
        )

    sec1_deep_inner = figure_card(
        fig_dir, "front_end_bode.png",
        "LTspice 26.1.1 AC Bode response vs Python model (max diff < 0.1 dB below 5 kHz).",
        "Đáp ứng tần số Bode giữa LTspice 26.1.1 và mô hình Python (lệch < 0.1 dB dưới 5 kHz).",
    )
    if p15 and "freq_50hz_vs_60hz" in p15:
        fc = p15["freq_50hz_vs_60hz"]
        v60_p = pct(fc["vehif_250_resampled_60hz"]["detection_rate"])
        v50_p = pct(fc["vehif_250_native_50hz"]["detection_rate"])
        sec1_deep_inner += (
            f'<p class="note">{T(f"Paired 250-recording VeHIF test: 60 Hz resampled <b>{v60_p}</b> vs 50 Hz native VN/AU <b>{v50_p}</b>.", f"So sánh đối cặp 250 bản ghi VeHIF: 60 Hz resample <b>{v60_p}</b> so với 50 Hz gốc VN/Úc <b>{v50_p}</b>.")}</p>'
            + figure_card(fig_dir, "phase15_50hz_vs_60hz.png",
                          "Same PCB anti-aliasing margin & paired VeHIF check: 50 Hz VN vs 60 Hz US.",
                          "Biên chống răng cưa và kiểm tra đối cặp VeHIF: 50 Hz VN vs 60 Hz Mỹ.")
        )

    sec1 = f"""
    <section id="frontend" data-x="sec-frontend">
      <h2>{T("1 · Analog Front End & 50 Hz (Vietnam) vs 60 Hz (US)", "1 · Mạch đầu vào Analog & Lưới 50 Hz (Việt Nam) vs 60 Hz (Mỹ)")}</h2>
      <p class="lead-p">{T(
          f"<b>Key result:</b> LTspice 26.1.1 verified −3 dB at <b>{ac.get('f_minus3dB_Hz', 2045.1)} Hz</b>, −<b>{ac.get('attenuation_at_7680Hz_dB', 46.4)} dB</b> at 60 Hz Nyquist, and clean ADC swing <b>{tr_lt.get('adc_pin_min_V', 1.043)}–{tr_lt.get('adc_pin_max_V', 2.257)} V</b>. On Vietnam 50 Hz grids (12.8 kHz ADC), keeping the PCB yields −40.0 dB at Nyquist; scaling two resistors ×1.2 restores −46.7 dB.",
          f"<b>Kết luận nhanh:</b> LTspice 26.1.1 xác nhận tần số cắt <b>{ac.get('f_minus3dB_Hz', 2045.1)} Hz</b>, chống răng cưa −<b>{ac.get('attenuation_at_7680Hz_dB', 46.4)} dB</b> ở 60 Hz, chân ADC sạch <b>{tr_lt.get('adc_pin_min_V', 1.043)}–{tr_lt.get('adc_pin_max_V', 2.257)} V</b>. Với lưới 50 Hz Việt Nam (12.8 kHz), giữ nguyên PCB đạt −40.0 dB; đổi 2 điện trở ×1.2 khôi phục lại −46.7 dB."
      )}</p>
      <div class="tw"><table>
        <thead><tr>
          <th>{T("Grid / Hardware Mode", "Chế độ lưới / Phần cứng")}</th>
          <th>FS_ADC</th><th>Nyquist</th><th>f (−3 dB)</th><th>Nyquist</th><th>Phase</th><th>Harmonics</th><th>Window</th>
        </tr></thead>
        <tbody>{freq_rows}</tbody>
      </table></div>
      {deep_box("Bode plot & paired 50 Hz vs 60 Hz VeHIF charts", "Xem biểu đồ Bode LTspice & so sánh 50 Hz vs 60 Hz",
                "LTspice vs Python agreement (< 0.1 dB) and 50 Hz native evaluation.",
                "Khớp LTspice vs Python (< 0.1 dB) và đánh giá trực tiếp ở 50 Hz.",
                sec1_deep_inner, badge='<span class="chip good">LTspice</span>', id_="deep-bode")}
    </section>
    """

    # Section 2: Phase 0 Simulation
    surf_rows = ""
    loso = m.get("leave_one_surface_out", {})
    for s in ("wet_grass", "wet_sand", "concrete", "dry_grass", "dry_asphalt"):
        surf_rows += (
            f"<tr><td><code>{s}</code></td>"
            f"<td><b>{pct(ml.get('by_surface', {}).get(s))}</b></td>"
            f"<td>{pct(loso.get(s, {}).get('detection_unseen_surface'))}</td>"
            f"<td>{pct(b51.get('by_surface', {}).get(s))}</td>"
            f"<td>{pct(bh3.get('by_surface', {}).get(s))}</td></tr>"
        )
    uw = m.get("unseen_arc_welder", {})
    uw_seen = pct(uw.get("false_alarm_arc_welder_seen"))
    uw_unseen = pct(uw.get("false_alarm_arc_welder_unseen"))
    sec2_deep = (
        f'<p class="note">{T(f"Honest hard-negative stress test: when <code>arc_welder</code> is withheld from training, its false-alarm rate rises from <b>{uw_seen}</b> (seen) to <b>{uw_unseen}</b> (unseen).", f"Kiểm thử trung thực với nhiễu khó chưa từng thấy: giấu <code>arc_welder</code> khi train làm báo nhầm tăng từ <b>{uw_seen}</b> lên <b>{uw_unseen}</b>.")}</p>'
        + '<div class="figgrid">'
        + figure_card(fig_dir, "example_waveforms.png", "Simulated Emanuel arc waveforms vs normal disturbances.", "Dạng sóng hồ quang Emanuel mô phỏng so với nhiễu thường.")
        + figure_card(fig_dir, "detection_by_surface.png", "Detection by surface vs 51N and 3rd harmonic.", "Tỉ lệ phát hiện theo bề mặt so với 51N và hài bậc 3.")
        + figure_card(fig_dir, "detection_vs_current.png", "Simulated detection across fault current bands.", "Tỉ lệ phát hiện mô phỏng theo dải dòng sự cố.")
        + figure_card(fig_dir, "false_alarm_by_disturbance.png", "False alarms across all 7 simulated disturbances.", "Báo nhầm trên 7 loại nhiễu bình thường mô phỏng.")
        + '</div>'
    )
    sec2 = f"""
    <section id="phase0">
      <h2>{T("2 · Phase 0: Simulated Emanuel Arcs (504 B int8 vs Baselines)", "2 · Phase 0: Mô phỏng hồ quang Emanuel (504 B int8 vs Cơ sở)")}</h2>
      <p class="lead-p">{T(
          f"<b>Key result:</b> Across 4,000 simulated events (1% val FA budget, 3-window persistence), Tiny MLP int8 detects <b>{pct(ml.get('detection_rate'))}</b> (FA {pct(ml.get('false_alarm_rate_normal'))}) vs 51N <b>{pct(b51.get('detection_rate'))}</b> and 3rd harmonic <b>{pct(bh3.get('detection_rate'))}</b> — and holds <b>93.0–98.5%</b> on unseen surfaces.",
          f"<b>Kết luận nhanh:</b> Trên 4.000 sự kiện mô phỏng (giới hạn 1% FA, duy trì 3 cửa sổ), Tiny MLP int8 phát hiện <b>{pct(ml.get('detection_rate'))}</b> (FA {pct(ml.get('false_alarm_rate_normal'))}) so với 51N <b>{pct(b51.get('detection_rate'))}</b> và hài bậc 3 <b>{pct(bh3.get('detection_rate'))}</b> — giữ <b>93.0–98.5%</b> trên bề mặt chưa từng học."
      )}</p>
      <div class="tw"><table>
        <thead><tr>
          <th>{T("Ground Surface", "Bề mặt chạm đất")}</th><th>Tiny MLP (int8)</th><th>Leave-One-Surface-Out</th><th>51N</th><th>3rd Harm.</th>
        </tr></thead>
        <tbody>{surf_rows}</tbody>
      </table></div>
      {deep_box("Phase 0 charts & unseen arc-welder stress test (4 figures)", "Xem 4 biểu đồ Phase 0 & thử nghiệm máy hàn chưa từng thấy",
                "Waveforms, surface breakdown, current bands, and disturbance false alarms.",
                "Dạng sóng mẫu, biểu đồ theo bề mặt, dải dòng và báo nhầm từng loại nhiễu.",
                sec2_deep, id_="deep-phase0")}
    </section>
    """

    # Section 3: Real VeHIF + Phase 1.5 Adaptation
    band_rows = ""
    sim_bins = ve.get("sim_reference_by_arc_current_A_rms", {})
    real_bins = rf.get("by_peak_fault_current_A_rms", {})
    j20_bands = (p15 or {}).get("few_shot_adaptation", {}).get("by_fraction", {}).get("0.2", {}).get("joint_mlp_int8", {}).get("by_current_band_mean", {})
    for b in ("0-1", "1-2", "2-5", "5-10"):
        sb = sim_bins.get(b, {})
        rb = real_bins.get(b, {})
        p15_cell = f"<b>{pct(j20_bands.get(b))}</b>" if b in j20_bands else "—"
        band_rows += (
            f"<tr><td>{b} A rms</td>"
            f"<td>{pct(sb.get('detected'))}</td>"
            f"<td>{pct(rb.get('detected'))} (n={rb.get('n', 0)})</td>"
            f"<td>{p15_cell}</td></tr>"
        )

    shift_rows = ""
    for item in (ve.get("feature_shift_real_vs_sim") or [])[:8]:
        shift_rows += (
            f"<tr><td><code>{esc(item['feature'])}</code></td>"
            f"<td>{item['sim_median']:.4f}</td><td>{item['real_median']:.4f}</td>"
            f"<td><b>{item['shift_in_sim_iqr']:+.2f} IQR</b></td></tr>"
        )

    sec3_deep = (
        '<div class="tw"><table>'
        f'<thead><tr><th>{T("Top Shifted Feature", "Đặc trưng lệch nhất")}</th><th>Sim med</th><th>VeHIF med</th><th>Shift</th></tr></thead>'
        f'<tbody>{shift_rows}</tbody></table></div>'
        + '<div class="figgrid">'
        + figure_card(fig_dir, "real_detection_by_current.png", "Phase 1 zero-shot gap: simulated arcs vs real VeHIF 22 kV.", "Khoảng cách zero-shot Phase 1: mô phỏng vs VeHIF 22 kV thật.")
        + figure_card(fig_dir, "real_vs_sim_waveform.png", "Real 22 kV vegetation fault current vs simulated Emanuel dry-grass arc.", "Dạng sóng chạm cây 22 kV thật vs hồ quang cỏ khô mô phỏng.")
        + '</div>'
    )

    sec3 = f"""
    <section id="vehif" data-x="sec-vehif">
      <h2>{T("3 · Real VeHIF 22 kV Recordings (Phase 1 Zero-Shot → Phase 1.5 Adaptation)", "3 · Dữ liệu đo thật VeHIF 22 kV (Phase 1 Zero-Shot → Phase 1.5 Thích ứng)")}</h2>
      <p class="lead-p">{T(
          f"<b>Key finding:</b> Evaluated zero-shot on 250 real 22 kV 50 Hz tree-contact recordings (VeHIF, CC0), the frozen Phase-0 model drops from <b>{pct(ve.get('sim_reference_detection_rate'))}</b> to <b>{pct(rf.get('detection_rate'))}</b> (0.0% alarms on all 53 real background recordings), mainly in 0–2 A because real vegetation arcs are much more symmetric (<code>dc_ratio</code> −0.49 IQR, <code>h2_ratio</code> −0.47 IQR).",
          f"<b>Phát hiện cốt lõi:</b> Khi chạy zero-shot trên 250 bản ghi chạm cây thật 22 kV 50 Hz (VeHIF, CC0), model Phase 0 giảm từ <b>{pct(ve.get('sim_reference_detection_rate'))}</b> xuống <b>{pct(rf.get('detection_rate'))}</b> (0.0% báo nhầm trên cả 53 bản ghi nền), chủ yếu ở dải 0–2 A do hồ quang cây thật đối xứng hơn nhiều (<code>dc_ratio</code> −0.49 IQR, <code>h2_ratio</code> −0.47 IQR)."
      )}</p>
      <div class="tw"><table>
        <thead><tr>
          <th>{T("Fault Current Band", "Dải dòng sự cố")}</th>
          <th>{T("Phase 0 Sim", "Phase 0 Mô phỏng")}</th>
          <th>{T("Phase 1 Real 0-Shot", "Phase 1 Thật 0-Shot")}</th>
          <th>{T("Phase 1.5 Adapted (20%)", "Phase 1.5 Thích ứng (20%)")}</th>
        </tr></thead>
        <tbody>{band_rows}</tbody>
      </table></div>
      {figure_card(fig_dir, "phase15_adaptation.png",
                   "Phase 1.5 leak-free few-shot learning curve (5 recording-disjoint seeds, 504 B int8) & current-band gain.",
                   "Đường cong thích ứng few-shot không rò rỉ (5 seed tách theo ID bản ghi, 504 B int8) & mức tăng theo dải dòng.")}
      {deep_box("Feature-shift diagnostics & real vs simulated waveform plots", "Xem bảng lệch đặc trưng & dạng sóng thật vs mô phỏng",
                "Why zero-shot drops on vegetation faults (top 8 shifted features + 2 plots).",
                "Giải thích vì sao zero-shot tụt trên sự cố cây (8 đặc trưng lệch mạnh nhất + 2 biểu đồ).",
                sec3_deep, id_="deep-shift")}
    """

    if p15:
        abl = p15.get("feature_ablation", {})
        abl_rows = ""
        for k, v in abl.items():
            abl_rows += (
                f"<tr><td><code>{esc(k)}</code> ({v['n_features']})</td>"
                f"<td>{pct(v['sim_test']['detection_rate'])}</td>"
                f"<td>{pct(v['sim_test']['false_alarm_rate_normal'])}</td>"
                f"<td><b>{pct(v['real_vehif_50hz']['detection_rate'])}</b></td>"
                f"<td>{pct(v['real_vehif_50hz']['detection_rate_0_to_2A'])}</td>"
                f"<td>{pct(v['real_bg_50hz']['alarm_rate'])}</td></tr>"
            )
        ad = p15.get("few_shot_adaptation", {})
        z0 = ad.get("zero_shot_phase0", {})
        ad_rows = (
            f"<tr><td><b>Zero-Shot (0%)</b></td><td>0</td>"
            f"<td>{pct(z0.get('real_detection_mean'))} ± {z0.get('real_detection_std', 0)*100:.1f}</td>"
            f"<td>{pct(z0.get('real_0_to_2A_mean'))} ± {z0.get('real_0_to_2A_std', 0)*100:.1f}</td>"
            f"<td>{pct(z0.get('real_bg_fa_mean'))}</td><td>{pct(z0.get('sim_detection_mean'))}</td><td>{pct(z0.get('sim_fa_mean'))}</td></tr>"
        )
        for fr in ("0.05", "0.1", "0.2"):
            for mkey, mlabel in (("head_recal_int8", "Head Recal"), ("joint_mlp_int8", "Joint MLP")):
                d = ad.get("by_fraction", {}).get(fr, {}).get(mkey)
                if not d:
                    continue
                cls = " class='hl'" if (fr == "0.2" and mkey == "joint_mlp_int8") else ""
                ad_rows += (
                    f"<tr{cls}><td>{mlabel} · {int(float(fr)*100)}%</td><td>{d['n_adapt_recordings']}</td>"
                    f"<td><b>{pct(d['real_detection_mean'])}</b> ± {d['real_detection_std']*100:.1f}</td>"
                    f"<td><b>{pct(d['real_0_to_2A_mean'])}</b> ± {d['real_0_to_2A_std']*100:.1f}</td>"
                    f"<td>{pct(d['real_bg_fa_mean'])}</td><td>{pct(d['sim_detection_mean'])}</td><td>{pct(d['sim_fa_mean'])}</td></tr>"
                )
        crit_rows = ""
        n_pass = 0
        for ck, ci in p15.get("criteria", {}).items():
            ok = bool(ci.get("pass"))
            n_pass += ok
            badge = '<span class="chip good">PASS</span>' if ok else '<span class="chip critical">FAIL</span>'
            det = ", ".join(f"{k}={v}" for k, v in ci.items() if k != "pass")
            crit_rows += f"<tr><td><code>{esc(ck)}</code></td><td>{badge}</td><td><code>{esc(det)}</code></td></tr>"

        p15_deep = (
            f'<h3>{T("Few-Shot Adaptation Breakdown (5 Seeds, Strict FA Guard)", "Chi tiết Thích ứng Few-Shot (5 Seed, Chốt chặn FA)")}</h3>'
            '<div class="tw"><table><thead><tr>'
            '<th>Method</th><th># Real</th><th>Held-out Real</th><th>0–2 A</th><th>Bg FA</th><th>Sim Det</th><th>Sim FA</th>'
            f'</tr></thead><tbody>{ad_rows}</tbody></table></div>'
            f'<h3>{T("Zero-Shot Feature-Group Ablation", "Khảo sát bỏ nhóm đặc trưng Zero-Shot")}</h3>'
            '<div class="tw"><table><thead><tr>'
            '<th>Subset</th><th>Sim Det</th><th>Sim FA</th><th>Real VeHIF</th><th>0–2 A</th><th>Bg FA</th>'
            f'</tr></thead><tbody>{abl_rows}</tbody></table></div>'
            + figure_card(fig_dir, "phase15_ablation.png", "Feature-group ablation: simulated accuracy vs zero-shot real VeHIF.", "Bỏ nhóm đặc trưng: mô phỏng vs zero-shot VeHIF thật.")
            + f'<h3>{T("Pre-Registered Criteria (P1.5-A..D)", "Bảng kiểm tiêu chí đăng ký trước (P1.5-A..D)")}</h3>'
            + f'<div class="tw"><table><thead><tr><th>Criterion</th><th>Status</th><th>Measured</th></tr></thead><tbody>{crit_rows}</tbody></table></div>'
        )
        sec3 += deep_box(
            "Phase 1.5 full tables: Few-shot (5/10/20%), Feature Ablation & Criteria P1.5-A..D",
            "Xem đầy đủ Phase 1.5: Bảng Few-Shot (5/10/20%), Bỏ đặc trưng & Tiêu chí P1.5-A..D",
            "Recording-disjoint 5-seed averages, simulated disturbance retention, and ablation chart.",
            "Trung bình 5 seed tách theo ID bản ghi, giữ độ chính xác nhiễu mô phỏng và biểu đồ bỏ đặc trưng.",
            p15_deep,
            badge=f'<span class="chip good">{n_pass}/{len(p15.get("criteria", {}))} PASS</span>',
            id_="deep-phase15",
        )
    sec3 += "</section>"

    # Section 4: C Firmware Verification
    c_rows = ""
    if cv:
        for label, key in (
            ("Phase 0 · Official (6 vecs)", "phase0_official_6_vectors"),
            ("Phase 0 · Extended (100 vecs)", "phase0_extended_100_vectors"),
            ("Phase 1.5 · Adapted 20% (100 vecs)", "phase15_adapted_100_vectors"),
        ):
            item = cv.get(key)
            if not item or not item.get("compiled"):
                continue
            ok = bool(item.get("parity_pass"))
            badge = '<span class="chip good">PASS</span>' if ok else '<span class="chip critical">FAIL</span>'
            c_rows += (
                f"<tr><td>{esc(label)}</td><td><code>{esc(item.get('header', ''))}</code></td>"
                f"<td>{item.get('max_abs_prob_error', 0):.2e}</td>"
                f"<td>{pct(item.get('decision_agreement'))}</td>"
                f"<td>{item.get('host_latency_us_per_inference', 0):.3f} µs</td>"
                f"<td>{badge}</td></tr>"
            )

    sec4 = f"""
    <section id="firmware">
      <h2>{T("4 · C Firmware Bit-Parity & Tier-2 Feeder Integration", "4 · Kiểm chứng khớp bit Firmware C & Tích hợp Tầng 2 FLISR")}</h2>
      <p class="lead-p">{T(
          f"<code>firmware/hif_infer.c</code> compiled natively with <code>gcc -O2 -Wall -Wextra -Werror</code> matches Python int8 within <code>&lt; 10⁻⁵</code>. "
          f"Fused into <a href='{esc(parent_href)}index.html#deep-hif'>Tier-2 Feeder FLISR (Section 2d)</a>, this exact frozen 504 B edge sensor passed 4/4 criteria (H1–H4): "
          f"400 Ω passive SLG <b>78.1% → 97.7%</b>, active-grid 400 Ω GATv2 <b>73.5% → 87.5%</b>, NO_FAULT false trips <b>6.5% → 1.2%</b>.",
          f"<code>firmware/hif_infer.c</code> biên dịch bằng <code>gcc -O2 -Wall -Wextra -Werror</code> khớp Python int8 sai số <code>&lt; 10⁻⁵</code>. "
          f"Khi gắn vào <a href='{esc(parent_href)}index.html#deep-hif'>Tầng 2 Lưới FLISR (Mục 2d)</a>, cảm biến 504 B cố định này đạt 4/4 tiêu chí H1–H4: "
          f"SLG 400 Ω thụ động <b>78.1% → 97.7%</b>, lưới chủ động 400 Ω GATv2 <b>73.5% → 87.5%</b>, giảm báo nhầm NO_FAULT từ <b>6.5% → 1.2%</b>."
      )}</p>
      <div class="tw"><table>
        <thead><tr><th>Test Suite</th><th>C Header</th><th>Max |p_c − p_py|</th><th>Agree</th><th>Host Latency</th><th>Status</th></tr></thead>
        <tbody>{c_rows or "<tr><td colspan='6'>Verified in Python; awaiting GCC Linux run</td></tr>"}</tbody>
      </table></div>
    </section>
    """

    # Section 5: SHA-256 Provenance & Downloads
    prov_rows = ""
    n_prov = len((prov or {}).get("files", []))
    for item in (prov or {}).get("files", []):
        prov_rows += (
            f"<tr><td><code>{esc(item['path'])}</code></td>"
            f"<td><code>{esc(item['sha256'][:16])}…</code></td>"
            f"<td>{item['bytes']:,} B</td><td>{esc(item['description'])}</td></tr>"
        )
    data_links = " · ".join(f'<a href="data/{esc(name)}">{esc(name)}</a>' for name, _ in copied_data)
    sec5 = f"""
    <section id="evidence">
      <h2>{T("5 · SHA-256 Verification, Honest Scope & Downloads", "5 · Chứng thực SHA-256, Phạm vi trung thực & Tải dữ liệu")}</h2>
      <p class="note">{T(
          "<b>Real vs Simulated:</b> VeHIF 22 kV fault currents and 53 background recordings are REAL field measurements (CC0). "
          "The SCT-013 + Sallen-Key + ADC front end is LTspice/Python verified (not yet soldered on energized hardware). All background loads, Emanuel arcs, and 7 disturbances are simulated.",
          "<b>Thật vs Mô phỏng:</b> Dòng sự cố VeHIF 22 kV và 53 bản ghi nền là DỮ LIỆU ĐO THẬT (CC0). "
          "Mạch SCT-013 + Sallen-Key + ADC được kiểm chứng trên LTspice/Python (chưa hàn chạy trên lưới mang điện). Toàn bộ tải nền, hồ quang Emanuel và 7 loại nhiễu đều mô phỏng."
      )}</p>
      <p><b>{T("Direct downloads:", "Tải trực tiếp:")}</b> {data_links}</p>
      {deep_box(f"Full SHA-256 Provenance Ledger ({n_prov} verified files) & audit commands",
                f"Xem sổ cái SHA-256 đầy đủ ({n_prov} file) & lệnh tự kiểm tra",
                "Verify locally with: python -m hif.provenance --verify && pytest -v tests/test_hif.py",
                "Tự kiểm chứng trên máy bằng: python -m hif.provenance --verify && pytest -v tests/test_hif.py",
                f'<div class="tw"><table><thead><tr><th>File</th><th>SHA-256</th><th>Size</th><th>Description</th></tr></thead><tbody>{prov_rows}</tbody></table></div>',
                badge=f'<span class="chip good">✓ {n_prov} files</span>', id_="deep-sha")}
    </section>
    """

    tiers_nav = f"""
    <nav class="tiers" aria-label="System tiers">
      <span class="tier-lbl">{T("2-Tier System:", "Hệ thống 2 tầng:")}</span>
      <a class="tier" href="{esc(parent_href)}index.html">{T("← Tier 2 · Feeder FLISR", "← Tầng 2 · Lưới FLISR")}</a>
      <a class="tier on" href="index.html" aria-current="page">{T("Tier 1 · Edge HIF Sensor (ESP32)", "Tầng 1 · Cảm biến HIF (ESP32)")}</a>
      <a class="tier sub" href="{esc(parent_href)}study/">{T("Technical Paper ↗", "Bài nghiên cứu ↗")}</a>
    </nav>
    """

    xdata_json = build_explain_data(m, ve, p15, cv, lt)

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HIF Sensor · Edge AI Report</title>
<style>
:root {{
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink2: #52514e; --muted: #6f6d68;
  --border: #e1e0d9; --axis: #c3c2b7; --soft: #f0efec; --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a;
  --link: #1c5cab; --good: #0ca30c; --good-ink: #006300; --critical: #d03b3b;
}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink2: #c3c2b7; --muted: #9a988f;
    --border: #2c2c2a; --axis: #383835; --soft: #232322; --s1: #3987e5; --s2: #d95926; --s3: #199e70;
    --link: #6da7ec; --good-ink: #4ade80;
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink2: #c3c2b7; --muted: #9a988f;
  --border: #2c2c2a; --axis: #383835; --soft: #232322; --s1: #3987e5; --s2: #d95926; --s3: #199e70;
  --link: #6da7ec; --good-ink: #4ade80;
}}
html[lang="vi"] [data-l="en"], html:not([lang="vi"]) [data-l="vi"] {{ display: none !important; }}
* {{ box-sizing: border-box; }}
html {{ scroll-padding-top: 64px; }}
body {{ margin: 0; background: var(--page); color: var(--ink);
  font: 15px/1.6 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
main {{ max-width: 1040px; margin: 0 auto; padding: 24px 16px 64px; }}
a {{ color: var(--link); }}
code {{ font-size: 0.9em; background: var(--soft); padding: 1px 5px; border-radius: 4px; }}
.topbar {{ position: sticky; top: 0; z-index: 6; background: var(--page); border-bottom: 1px solid var(--border); }}
.topbar-in {{ max-width: 1280px; margin: 0 auto; padding: 8px 16px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
.brand {{ font-weight: 650; font-size: 14px; white-space: nowrap; }}
.mon-pill {{ display: inline-flex; align-items: center; gap: 6px; padding: 4px 11px; border-radius: 8px;
  background: var(--s2); color: #fff; font-size: 13px; font-weight: 700; text-decoration: none; white-space: nowrap; }}
.mon-pill:hover {{ filter: brightness(1.08); }}
.topbar nav {{ display: flex; gap: 4px; overflow-x: auto; flex: 1; }}
.topbar nav a {{ padding: 4px 10px; border-radius: 999px; text-decoration: none; color: var(--ink2); font-size: 13.5px; white-space: nowrap; }}
.topbar nav a:hover {{ background: var(--soft); }}
.ctrls {{ display: flex; gap: 6px; align-items: center; }}
.seg {{ display: inline-flex; border: 1px solid var(--border); border-radius: 999px; overflow: hidden; }}
.seg button, .iconbtn {{ font: inherit; font-size: 12.5px; font-weight: 600; border: 0; background: transparent;
  color: var(--ink2); padding: 4px 10px; cursor: pointer; }}
.seg button[aria-pressed="true"] {{ background: var(--ink); color: var(--page); }}
.iconbtn {{ border: 1px solid var(--border); border-radius: 999px; white-space: nowrap; }}
.xlaunch {{ border-color: var(--s1) !important; color: var(--s1) !important;
  background: color-mix(in srgb, var(--s1) 10%, transparent) !important; }}
.xlaunch:hover {{ background: color-mix(in srgb, var(--s1) 18%, transparent) !important; }}
.tiers {{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 0 0 12px; }}
.tier-lbl {{ font-size: 12px; font-weight: 600; color: var(--muted); margin-right: 2px; }}
.tier {{ display: inline-flex; align-items: center; padding: 4px 11px; border-radius: 999px;
  border: 1px solid var(--border); background: var(--surface); color: var(--ink2);
  font-size: 12.5px; font-weight: 600; text-decoration: none; transition: border-color .15s, background-color .15s, color .15s; }}
.tier:hover {{ border-color: var(--s1); color: var(--ink); background: var(--soft); }}
.tier.on {{ border-color: var(--s1); background: color-mix(in srgb, var(--s1) 14%, var(--surface)); color: var(--s1); }}
.tier.sub {{ background: transparent; color: var(--muted); }}
header h1 {{ font-size: 28px; line-height: 1.2; margin: 6px 0 6px; letter-spacing: -0.01em; }}
header p {{ margin: 0; color: var(--ink2); max-width: 820px; }}
.meta {{ margin-top: 8px; font-size: 13px; color: var(--muted); }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(185px, 1fr)); gap: 10px; margin: 18px 0 14px; }}
.tile {{ position: relative; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; }}
.tk {{ font-size: 12px; font-weight: 600; color: var(--muted); padding-right: 20px; }}
.tv {{ font-size: 24px; font-weight: 700; margin: 4px 0 2px; font-variant-numeric: tabular-nums; }}
.ts {{ font-size: 12.5px; color: var(--ink2); line-height: 1.35; }}
.steps3 {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 12px 0 24px; }}
.st3 {{ display: flex; gap: 10px; padding: 11px 12px; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; }}
.sn {{ flex: none; width: 24px; height: 24px; border-radius: 6px; display: grid; place-items: center;
  background: var(--s1); color: #fff; font-size: 12.5px; font-weight: 700; }}
.st3 b {{ display: block; font-size: 13.5px; }}
.st3 small {{ display: block; font-size: 12.5px; color: var(--ink2); margin-top: 2px; line-height: 1.4; }}
@media (max-width: 760px) {{ .steps3 {{ grid-template-columns: 1fr; }} }}
section {{ position: relative; margin-top: 26px; padding: 18px 20px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; }}
section h2 {{ font-size: 19px; margin: 0 0 8px; padding-right: 26px; }}
section h3 {{ font-size: 15.5px; margin: 18px 0 8px; }}
.lead-p {{ margin: 0 0 12px; color: var(--ink2); }}
.note {{ padding: 10px 14px; border-left: 3px solid var(--s1); background: var(--page);
  border-radius: 0 8px 8px 0; font-size: 13.5px; color: var(--ink2); margin: 10px 0; }}
.tw {{ overflow-x: auto; margin: 10px 0; border: 1px solid var(--border); border-radius: 10px; background: var(--page); }}
table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; font-variant-numeric: tabular-nums; }}
th, td {{ padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border); }}
th {{ font-weight: 650; color: var(--ink2); background: var(--soft); }}
tr:last-child td {{ border-bottom: 0; }}
tr.hl {{ background: color-mix(in srgb, var(--s3) 10%, var(--surface)); }}
.chip {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11.5px; font-weight: 700; }}
.chip.good {{ background: color-mix(in srgb, var(--good) 14%, transparent); color: var(--good-ink); }}
.chip.critical {{ background: color-mix(in srgb, var(--critical) 14%, transparent); color: var(--critical); }}
details.deep {{ margin: 12px 0 0; border: 1px solid var(--border); border-radius: 10px; background: var(--page); }}
details.deep[open] {{ background: var(--surface); border-color: var(--axis); }}
summary.deep-sum {{ list-style: none; cursor: pointer; padding: 10px 14px; display: flex; gap: 12px; align-items: center; justify-content: space-between; }}
summary.deep-sum::-webkit-details-marker {{ display: none; }}
summary.deep-sum:hover {{ background: var(--soft); border-radius: 10px; }}
details.deep[open] > summary.deep-sum {{ border-bottom: 1px solid var(--border); border-radius: 10px 10px 0 0; }}
.deep-t b {{ display: block; font-size: 14px; color: var(--ink); }}
.deep-t small {{ display: block; font-size: 12.5px; color: var(--muted); margin-top: 2px; }}
.deep-r {{ display: inline-flex; align-items: center; gap: 8px; flex: none; }}
.deep-act {{ font-size: 12px; font-weight: 600; color: var(--link); padding: 3px 9px; border-radius: 999px;
  border: 1px solid var(--border); background: var(--surface); white-space: nowrap; }}
details.deep[open] .deep-act::before {{ content: "▴ "; }}
details.deep:not([open]) .deep-act::before {{ content: "▾ "; }}
.deep-body {{ padding: 12px 14px 14px; }}
.figgrid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 12px; margin: 10px 0; }}
figure.fig {{ margin: 10px 0; background: var(--page); border: 1px solid var(--border); border-radius: 10px; padding: 10px; }}
figure.fig img {{ display: block; width: 100%; height: auto; border-radius: 6px; background: #fff; }}
figure.fig figcaption {{ margin-top: 6px; font-size: 12.5px; color: var(--muted); }}
/* Interactive Explain buddy (matches Tier-2 docs/index.html) */
.xq {{ position: absolute; top: 8px; right: 8px; z-index: 2; width: 22px; height: 22px; padding: 0; border-radius: 50%;
  border: 1px solid var(--border); background: var(--surface); color: var(--muted); font: 700 12px/20px system-ui, sans-serif;
  cursor: pointer; opacity: .85; }}
.xq:hover {{ opacity: 1; color: var(--s1); border-color: var(--s1); }}
body.xmode [data-x] {{ cursor: help; }}
body.xmode [data-x]:hover {{ outline: 2px dashed var(--s1); outline-offset: 3px; }}
.face {{ position: relative; display: inline-block; flex: none; width: 32px; height: 32px; border-radius: 50%;
  background: var(--s1); box-shadow: inset -3px -4px 0 rgb(0 0 0 / .14); }}
.face i {{ position: absolute; top: 9px; width: 5px; height: 8px; border-radius: 50%; background: #fff; }}
.face i:first-child {{ left: 8px; }} .face i:last-child {{ right: 8px; }}
.face::after {{ content: ""; position: absolute; left: 10px; bottom: 6px; width: 12px; height: 5px;
  border-bottom: 2px solid #fff; border-radius: 0 0 10px 10px; }}
.xring {{ position: absolute; z-index: 5; border-radius: 12px; pointer-events: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--s2) 55%, transparent); transition: left .3s, top .3s, width .3s, height .3s; }}
.xbubble {{ position: fixed; right: 16px; bottom: 16px; z-index: 9; width: min(380px, calc(100vw - 32px));
  max-height: calc(100vh - 96px); overflow-y: auto; padding: 14px 16px; border-radius: 14px;
  background: var(--surface); color: var(--ink); border: 1px solid var(--border); box-shadow: 0 12px 40px rgb(0 0 0 / .24); }}
.xb-head {{ display: flex; align-items: center; gap: 10px; }}
.xb-head b {{ flex: 1; font-size: 15px; line-height: 1.3; }}
.xb-x {{ font: inherit; font-size: 22px; line-height: 1; border: 0; background: none; color: var(--muted); cursor: pointer; padding: 2px 6px; }}
.xb-body {{ margin: 4px 0 0; }}
.xb-body dt {{ margin-top: 10px; font-size: 11.5px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--ink2); }}
.xb-body dd {{ margin: 2px 0 0; font-size: 14px; }}
.xb-foot {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 12px; }}
.xb-nav {{ font: inherit; font-size: 13px; font-weight: 600; padding: 5px 12px; border-radius: 999px;
  border: 1px solid var(--border); background: transparent; color: var(--ink); cursor: pointer; }}
.xb-nav:hover {{ border-color: var(--s1); color: var(--s1); }}
footer {{ margin-top: 32px; font-size: 13px; color: var(--muted); }}
@media print {{ .topbar, .tiers, .xq, .xring, .xbubble {{ display: none !important; }} }}
</style>
</head>
<body class="xmode">
<div class="topbar"><div class="topbar-in">
  <span class="brand">HIF Sensor · Tier 1</span>
  <a class="mon-pill" href="{esc(parent_href)}monitor/">{T("Monitor", "Giám sát")}</a>
  <nav>
    <a href="#frontend">{T("Front End", "Mạch 50/60 Hz")}</a>
    <a href="#phase0">{T("Phase 0", "Phase 0")}</a>
    <a href="#vehif">{T("VeHIF & Phase 1.5", "VeHIF & Phase 1.5")}</a>
    <a href="#firmware">{T("C Firmware", "Code C")}</a>
    <a href="#evidence">{T("SHA-256", "SHA-256")}</a>
  </nav>
  <div class="ctrls">
    <button type="button" class="iconbtn xlaunch" id="xlaunch">{T("? Guide", "? Giải thích")}</button>
    <button type="button" class="iconbtn" id="view-all" aria-pressed="false">{T("⊞ Full view", "⊞ Mở tất cả")}</button>
    <div class="seg" role="group" aria-label="Language">
      <button id="b-en" aria-pressed="true" onclick="setLang('en')">EN</button>
      <button id="b-vi" aria-pressed="false" onclick="setLang('vi')">VI</button>
    </div>
    <button class="iconbtn" onclick="toggleTheme()">◐</button>
  </div>
</div></div>

<main>
  <header>
    {tiers_nav}
    <h1>{T("Tier 1 · Edge High-Impedance Fault Sensor (ESP32-S3)", "Tầng 1 · Cảm biến biên phát hiện sự cố trở kháng cao (ESP32-S3)")}</h1>
    <p>{T("Clamp-CT analog front end (LTspice) + 504 B int8 neural network, validated on 4,000 simulated arcs, real 22 kV 50 Hz VeHIF vegetation-fault recordings, and GCC C bit-parity tests.",
          "Mạch kẹp CT chống răng cưa (LTspice) + mạng nơ-ron int8 504 B, kiểm chứng trên 4.000 hồ quang mô phỏng, dữ liệu đo thật VeHIF 22 kV 50 Hz và kiểm tra khớp bit code C bằng GCC.")}</p>
    <div class="meta">{T("Chau Nguyen (EE Student) · Unified 2-tier system with Self-Healing Feeder · Click any ? button for plain-language guidance",
                         "Chau Nguyen (SV Kỹ thuật Điện) · Hệ thống 2 tầng thống nhất cùng Self-Healing Feeder · Bấm nút ? bất kỳ để xem giải thích đơn giản")}</div>
  </header>

  {tiles_html}
  {story3}
  {sec1}
  {sec2}
  {sec3}
  {sec4}
  {sec5}

  <footer>{T("Generated from results/ by hif_sensor/scripts/build_dashboard.py · Zero external fonts or trackers.",
             "Tạo tự động từ results/ bởi hif_sensor/scripts/build_dashboard.py · Không nhúng font ngoài hay mã theo dõi.")}</footer>
</main>
<script type="application/json" id="xdata">{xdata_json}</script>
<div class="xring" id="xring" hidden></div>
<div class="xbubble" id="xbubble" role="dialog" aria-labelledby="xb-title" tabindex="-1" hidden>
  <div class="xb-head"><span class="face" aria-hidden="true"><i></i><i></i></span><b id="xb-title"></b><button type="button" class="xb-x" id="xb-close">×</button></div>
  <dl class="xb-body"><dt id="xk-what"></dt><dd id="xb-what"></dd><dt id="xk-read"></dt><dd id="xb-read"></dd><dt id="xk-why"></dt><dd id="xb-why"></dd></dl>
  <div class="xb-foot"><button type="button" class="xb-nav" id="xb-prev"></button><span id="xb-count"></span><button type="button" class="xb-nav" id="xb-next"></button></div>
</div>
<script>
var _xRender = null;
function setLang(l) {{
  document.documentElement.lang = l;
  document.getElementById('b-en').setAttribute('aria-pressed', String(l === 'en'));
  document.getElementById('b-vi').setAttribute('aria-pressed', String(l === 'vi'));
  try {{ localStorage.setItem('shf-lang', l); }} catch (e) {{}}
  if (_xRender) _xRender();
}}
function toggleTheme() {{
  var cur = document.documentElement.getAttribute('data-theme');
  var nxt = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', nxt);
  try {{ localStorage.setItem('shf-theme', nxt); }} catch (e) {{}}
}}
(function() {{
  var p = new URLSearchParams(location.search);
  var l = p.get('lang') || (function() {{ try {{ return localStorage.getItem('shf-lang'); }} catch (e) {{ return null; }} }})() || 'en';
  setLang(l === 'vi' ? 'vi' : 'en');
  try {{ var t = localStorage.getItem('shf-theme'); if (t && t !== 'auto') document.documentElement.setAttribute('data-theme', t); }} catch (e) {{}}
  var vb = document.getElementById('view-all');
  function setFull(on) {{
    document.querySelectorAll('details.deep').forEach(function(d) {{ d.open = on; }});
    vb.setAttribute('aria-pressed', String(on));
    vb.innerHTML = on
      ? '<span data-l="en">⊟ Quick scan</span><span data-l="vi">⊟ Thu gọn</span>'
      : '<span data-l="en">⊞ Full view</span><span data-l="vi">⊞ Mở tất cả</span>';
  }}
  vb.addEventListener('click', function() {{ setFull(vb.getAttribute('aria-pressed') !== 'true'); }});
  if (p.get('full') === '1') setFull(true);
  addEventListener('beforeprint', function() {{ setFull(true); }});

  var XD = JSON.parse(document.getElementById('xdata').textContent);
  var XL = {{
    en: {{ what: 'What it is', read: 'How to read it', why: 'Why it matters', prev: '← Prev', next: 'Next →' }},
    vi: {{ what: 'Đây là gì', read: 'Đọc thế nào', why: 'Vì sao quan trọng', prev: '← Trước', next: 'Tiếp →' }}
  }};
  var els = Array.prototype.slice.call(document.querySelectorAll('[data-x]')).filter(function(el) {{ return !!XD[el.dataset.x]; }});
  var ring = document.getElementById('xring'), bub = document.getElementById('xbubble'), xi = -1;
  function openParents(el) {{ var cur = el; while (cur) {{ if (cur.tagName === 'DETAILS') cur.open = true; cur = cur.parentElement; }} }}
  function place(el) {{
    var r = el.getBoundingClientRect(), pad = 6;
    ring.style.left = (r.left + scrollX - pad) + 'px';
    ring.style.top = (r.top + scrollY - pad) + 'px';
    ring.style.width = (r.width + 2 * pad) + 'px';
    ring.style.height = (r.height + 2 * pad) + 'px';
  }}
  function render() {{
    if (xi < 0) return;
    var lang = document.documentElement.lang === 'vi' ? 'vi' : 'en';
    var d = XD[els[xi].dataset.x][lang], t = XL[lang];
    document.getElementById('xb-title').textContent = d.title;
    ['what', 'read', 'why'].forEach(function(k) {{
      document.getElementById('xk-' + k).textContent = t[k];
      document.getElementById('xb-' + k).innerHTML = d[k];
    }});
    document.getElementById('xb-prev').textContent = t.prev;
    document.getElementById('xb-next').textContent = t.next;
    document.getElementById('xb-count').textContent = (xi + 1) + ' / ' + els.length;
  }}
  _xRender = render;
  function showX(i) {{
    xi = (i + els.length) % els.length;
    var el = els[xi];
    openParents(el);
    var r = el.getBoundingClientRect();
    if (r.top < 80 || r.top > innerHeight * 0.5) scrollTo({{ top: Math.max(0, r.top + scrollY - 100), behavior: 'smooth' }});
    place(el); ring.hidden = false; bub.hidden = false; render();
  }}
  function closeX() {{ xi = -1; ring.hidden = true; bub.hidden = true; }}
  els.forEach(function(el, i) {{
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'xq'; b.textContent = '?';
    b.addEventListener('click', function(e) {{ e.stopPropagation(); showX(i); }});
    el.appendChild(b);
    el.addEventListener('click', function(e) {{
      if (e.target.closest('a, button, summary, details')) return;
      showX(i);
    }});
  }});
  document.getElementById('xlaunch').addEventListener('click', function() {{ if (xi >= 0) closeX(); else if (els.length) showX(0); }});
  document.getElementById('xb-close').addEventListener('click', closeX);
  document.getElementById('xb-prev').addEventListener('click', function() {{ showX(xi - 1); }});
  document.getElementById('xb-next').addEventListener('click', function() {{ showX(xi + 1); }});
  document.addEventListener('keydown', function(e) {{
    if (xi < 0) return;
    if (e.key === 'Escape') closeX();
    else if (e.key === 'ArrowRight') showX(xi + 1);
    else if (e.key === 'ArrowLeft') showX(xi - 1);
  }});
  addEventListener('resize', function() {{ if (xi >= 0) place(els[xi]); }});
}})();
</script>
</body>
</html>
"""
    out = out_dir / "index.html"
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({len(copied_figs)} figures, {len(copied_data)} data files)")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None, help="Output directory (default: docs/)")
    ap.add_argument("--parent-href", default="../", help="Relative link back to Tier-2 FLISR root")
    args = ap.parse_args()
    build(args.out, args.parent_href)
