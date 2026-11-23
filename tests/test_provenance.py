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
