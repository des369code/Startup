from takeoff.pdf_extract import extract_sheet, page_text_upper
from tests.fixtures import make_synthetic_drawing

def test_extract_reads_geometry_and_text(tmp_path):
    pdf, _ = make_synthetic_drawing(tmp_path)
    sheet = extract_sheet(pdf)
    assert sheet.page_w > 0 and sheet.page_h > 0
    assert len(sheet.paths) >= 4                 # 2 rects + 2 runs + title lines
    assert len(sheet.words) > 5
    assert "SCALE" in page_text_upper(sheet.words)
    assert sheet.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

def test_extract_twice_equal(tmp_path):
    pdf, _ = make_synthetic_drawing(tmp_path)
    a = extract_sheet(pdf); b = extract_sheet(pdf)
    assert len(a.words) == len(b.words) and len(a.png_bytes) == len(b.png_bytes)
