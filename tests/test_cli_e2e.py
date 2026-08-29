"""CLI end-to-end: the product's only human entry point, exercised through
main() with a real fixture sheet — extraction to annotated PDF and Excel."""

import fitz
from pathlib import Path

from takeoff.cli import main
from tests.fixtures import make_synthetic_drawing


def test_cli_full_run(tmp_path, capsys):
    pdf, truth = make_synthetic_drawing(tmp_path)
    out = tmp_path / "o"
    rc = main(["run", pdf, "--prompt", "", "--scale", "100", "--out", str(out), "--mock"])
    assert rc == 0
    assert (out / f"{Path(pdf).stem}-takeoff.xlsx").exists()   # matches CLI output contract
    assert "Asphalt" in capsys.readouterr().out


def test_cli_corrupt_pdf_exits_1(tmp_path, capsys):
    bad = tmp_path / "garbage.pdf"
    bad.write_bytes(b"not a pdf at all")
    rc = main(["run", str(bad), "--out", str(tmp_path / "o"), "--mock"])
    assert rc == 1
    assert "cannot read PDF" in capsys.readouterr().err


def test_cli_annotated_pdf_has_overlay(tmp_path):
    # the annotated PDF is the QA surface — assert it was written AND the quantity
    # label text is actually drawn on it (search page text for "50.00")
    pdf, _ = make_synthetic_drawing(tmp_path)
    out = tmp_path / "o"; main(["run", pdf, "--scale", "100", "--out", str(out), "--mock"])
    ann = fitz.open(out / f"{Path(pdf).stem}-annotated.pdf")
    assert any("50.00" in page.get_text() for page in ann)


def test_cli_dry_run_no_files(tmp_path, capsys):
    # cost estimate only: geometry extraction, no semantics, no output files
    pdf, _ = make_synthetic_drawing(tmp_path)
    out = tmp_path / "dryout"
    rc = main(["run", pdf, "--dry-run", "--out", str(out)])
    assert rc == 0
    assert not out.exists()
    text = capsys.readouterr().out
    assert "dry run" in text or "estimate" in text


def test_cli_mock_banner(tmp_path, capsys):
    # the banner is the demo-misuse guard — grep-able on stdout
    pdf, _ = make_synthetic_drawing(tmp_path)
    rc = main(["run", pdf, "--out", str(tmp_path / "o"), "--mock"])
    assert rc == 0
    assert "MOCK SEMANTICS" in capsys.readouterr().out
