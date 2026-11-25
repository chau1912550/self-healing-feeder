"""Build a self-contained Kaggle notebook (Phase 0 + Phase 1 + Phase 1.5) from the source files."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text}


def code(text):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": text}


cells = [md(
    "# HIF sensor (Phase 0 + Phase 1 + Phase 1.5): simulate HIF, test VeHIF 22 kV, adapt & verify C firmware\n\n"
    "Bấm **Run All** trên Kaggle (CPU là đủ, không cần Internet). Để chạy Phase 1 & Phase 1.5, gắn dataset "
    "`dougpsg/highimpedance-vegetation-fault-data-set` (106 GB sẵn trên Kaggle, không tải về máy).\n\n"
    "All simulated arcs use the Emanuel model; VeHIF currents are real 22 kV 50 Hz vegetation-fault recordings "
    "passed through a simulated sensor and load."),
    code("!mkdir -p hif results/figures firmware build")]
for name in (
    "hif/__init__.py", "hif/frontend.py", "hif/waveforms.py", "hif/features.py",
    "hif/provenance.py", "train_kaggle.py", "real_data_test.py", "phase15_vehif_adaptation.py",
    "firmware/hif_infer.h", "firmware/hif_infer.c", "firmware/test_infer.c",
):
    cells.append(code(f"%%writefile {name}\n" + (ROOT / name).read_text(encoding="utf-8")))
cells += [
    code("import importlib, train_kaggle\nimportlib.reload(train_kaggle)\ntrain_kaggle.main()"),
    code("import json; print(json.dumps(json.load(open('results/metrics.json')), indent=1)[:6000])"),
    md("## Phase 1: Zero-shot evaluation on REAL VeHIF 22 kV recordings"),
    code("import importlib, real_data_test\nimportlib.reload(real_data_test)\nreal_data_test.main()"),
    md("## Phase 1.5: GCC C firmware parity + 50 Hz VN vs 60 Hz US + feature ablation + few-shot VeHIF adaptation"),
    code("import importlib, phase15_vehif_adaptation\nimportlib.reload(phase15_vehif_adaptation)\nphase15_vehif_adaptation.main()"),
]
nb = {"cells": cells, "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3",
                                                  "language": "python"}},
      "nbformat": 4, "nbformat_minor": 5}
out = ROOT / "kaggle" / "hif_phase0.ipynb"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print("wrote", out)
