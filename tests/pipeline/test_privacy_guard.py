"""Tests for pipeline/privacy_guard.py (Req 1.11, 1.12, 26.7, 31.4, 31.5).

Uses only the reserved fictional numbers from tests/conftest.py, written to tmp files.
The guard scans api/ and data/processed/ only, never tests/.
"""
import pytest

from pipeline import privacy_guard as pg
from pipeline.common import PipelineError
from pipeline.run import STEPS, Ctx, main as run_main
from tests.conftest import FICTIONAL_NUMBERS


def fmt(n: str, style: int) -> str:
    """'+16175550123' in a few common formats."""
    a, b, c = n[2:5], n[5:8], n[8:]
    return [n, f"+1 {a} {b} {c}", f"({a}) {b}-{c}", f"{a}.{b}.{c}", f"1-{a}-{b}-{c}", f"{a}{b}{c}"][style]


def write(tmp_path, name, text):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.mark.parametrize("style", range(6))
def test_fictional_numbers_detected_and_never_printed(tmp_path, capsys, style):
    num = fmt(FICTIONAL_NUMBERS[23], style)
    write(tmp_path, "llm_cache/abc.json", '{\n  "tz": "America/New_York",\n  "body": "call ' + num + '"\n}\n')
    assert pg.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert out.strip().endswith("abc.json:3: phone_number")
    assert num not in out and FICTIONAL_NUMBERS[23][5:] not in out


def test_address_detected(tmp_path, capsys):
    write(tmp_path, "notes.md", "ok line\nMeet at 12 Main Street today\n")
    assert pg.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert out.strip().endswith("notes.md:2: street_address") and "Main" not in out


@pytest.mark.parametrize("text", [
    "+1 *** *** 0123",                       # masked (Req 26.4)
    "Call 911 for emergencies, 2-1-1 for help, 311 for the city.",
    '{"lon": -70.123456, "lat": 41.6175550123, "pct": 0.6175550123}',  # decimals
    "Simulated household #3, Falmouth COA driver (Simulated)",
    "Dark 40 hours, 82% without power",
])
def test_clean_text_not_flagged(tmp_path, capsys, text):
    write(tmp_path, "x.txt", text + "\n")
    assert pg.main([str(tmp_path)]) == 0
    assert capsys.readouterr().out == ""


def test_skips_binary_pycache_and_missing_roots(tmp_path):
    num = FICTIONAL_NUMBERS[0]
    (tmp_path / "blob.bin").write_bytes(b"\0\x01" + num.encode())
    write(tmp_path, "__pycache__/m.txt", num)
    assert pg.scan([tmp_path, tmp_path / "does_not_exist"]) == []
    assert pg.main([str(tmp_path / "does_not_exist")]) == 0


def test_findings_sorted_by_path_and_line(tmp_path):
    write(tmp_path, "b.json", f"{FICTIONAL_NUMBERS[1]}\n")
    write(tmp_path, "a.py", f"x = 1\n# 7 Ocean Avenue\n'{FICTIONAL_NUMBERS[2]}'\n")
    got = [(f.path.name, f.line, f.kind) for f in pg.scan([tmp_path])]
    assert got == [("a.py", 2, "street_address"), ("a.py", 3, "phone_number"), ("b.json", 1, "phone_number")]


def test_pipeline_step_registered_after_export_and_fails_on_finding(tmp_path, monkeypatch, capsys):
    names = [n for n, _ in STEPS]
    assert names[-2:] == ["export", "privacy_guard"]
    write(tmp_path, "processed/llm_cache/k.json", f'"{FICTIONAL_NUMBERS[5]}"\n')
    monkeypatch.setattr(pg, "PROCESSED", tmp_path / "processed")
    monkeypatch.setattr(pg, "ROOT", tmp_path)  # api/ is absent under tmp_path
    assert run_main(["--no-llm"], steps=[("privacy_guard", pg.step)]) == 1
    cap = capsys.readouterr()
    assert "k.json:1: phone_number" in cap.out and "pipeline error: privacy_guard:" in cap.err
    assert FICTIONAL_NUMBERS[5] not in cap.out + cap.err
    assert (tmp_path / "processed/llm_cache/k.json").exists()  # flagged files stay in place


def test_pipeline_step_clean(tmp_path, monkeypatch):
    write(tmp_path, "processed/content.json", '{"tz": "America/New_York"}\n')
    monkeypatch.setattr(pg, "PROCESSED", tmp_path / "processed")
    monkeypatch.setattr(pg, "ROOT", tmp_path)
    ctx = Ctx(scoring=None, languages=None)
    pg.step(ctx)
    assert ctx["privacy_findings"] == []
    with pytest.raises(PipelineError):
        write(tmp_path, "api/x.py", "ADDR = '5 Shore Road'\n")
        pg.step(ctx)
