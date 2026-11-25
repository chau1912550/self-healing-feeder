"""Run provenance: a result file edited by hand after its run must be caught."""
import json

from shf import config, provenance


def test_hand_edited_result_is_caught(tmp_path, monkeypatch):
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "RESULTS", results)
    monkeypatch.setattr(provenance, "DIR", results / "provenance")

    m = results / "metrics.json"
    m.write_text(json.dumps({"accuracy": 0.977}), encoding="utf-8")
    provenance.record("run", [m])
    assert provenance.verify() == {"changed": [], "missing": [], "unrecorded": []}

    m.write_text(json.dumps({"accuracy": 0.995}), encoding="utf-8")        # a number typed in by hand
    assert provenance.verify()["changed"] == ["results/metrics.json"]

    (results / "extra.csv").write_text("a,b\n1,2\n", encoding="utf-8")     # a file no run wrote
    assert provenance.verify()["unrecorded"] == ["results/extra.csv"]


def test_line_endings_do_not_count_as_edits(tmp_path, monkeypatch):
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "RESULTS", results)
    monkeypatch.setattr(provenance, "DIR", results / "provenance")
    f = results / "zones.csv"
    f.write_bytes(b"zone,kW\nSw1,400\n")
    provenance.record("run", [f])
    f.write_bytes(b"zone,kW\r\nSw1,400\r\n")                               # a Windows checkout
    assert provenance.verify()["changed"] == []


def test_record_refuses_a_file_the_run_did_not_write(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(provenance, "DIR", tmp_path / "prov")
    try:
        provenance.record("run", [tmp_path / "missing.json"])
    except FileNotFoundError:
        return
    raise AssertionError("record() accepted a file that does not exist")


def test_sanitize_command_strips_local_user_paths():
    cmd = r"multi_feeder_eval.py --merge C:\Users\alice\scratch\g1,C:\Users\alice\scratch\g2"
    clean = provenance._sanitize_command(cmd)
    assert "alice" not in clean
    assert "<local>/scratch/g1" in clean and "<local>/scratch/g2" in clean
    kaggle_cmd = "hif_fusion_run.py --model-npz /kaggle/input/notebooks/user/nb/model_int8.npz"
    assert provenance._sanitize_command(kaggle_cmd) == kaggle_cmd


def test_ledger_and_cli_verify_clean(tmp_path, monkeypatch, capsys):
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "RESULTS", results)
    monkeypatch.setattr(provenance, "DIR", results / "provenance")
    f = results / "summary.json"
    f.write_text('{"ok": true}\n', encoding="utf-8")
    provenance.record("unit", [f])
    rows = provenance.ledger()
    assert len(rows) == 1 and rows[0]["verified"] is True and rows[0]["file_count"] == 1
    assert provenance.main([]) == 0
    out = capsys.readouterr().out
    assert "PASS:" in out and "changed: 0, missing: 0, unrecorded: 0" in out


def test_dashboard_evidence_provenance_honesty_and_security():
    """docs/index.html exposes the live 23-manifest SHA-256 ledger, honest failures table, and static security block."""
    html = (config.ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    # Preserve AGENTS.md layout order: health -> evidence -> model
    i_health = html.index('id="health"')
    i_ev = html.index('id="evidence"')
    i_model = html.index('id="model"')
    assert i_health < i_ev < i_model
    # Every manifest in results/provenance/*.json appears with a full 64-char copyable SHA-256
    rows = provenance.ledger()
    assert len(rows) >= 23
    for r in rows:
        assert f'<code>{r["producer"]}</code>' in html
        for f in r["files"]:
            assert f'data-copy-text="{f["sha256"]}"' in html
    # Explain guide keys + honest failures (P1-Fail, VeHIF) + H1-H4 + static-page security commitment (EN & VI)
    for xid in ("evidence", "table-provenance", "table-honesty"):
        assert f'data-x="{xid}"' in html
        assert f'"{xid}":' in html
    for needle in ("P1-Fail", "VeHIF", "H1–H4", "3ba5bd23685d7964a6cea0c94064c1e65a8bf3129d83ac129215d110218397c1",
                   "Pure static GitHub Pages", "GitHub Pages thuần tĩnh", "python -m shf.provenance",
                   "python harness/check.py --tests", 'id="data-files"'):
        assert needle in html, f"Missing expected marker in docs/index.html: {needle}"
