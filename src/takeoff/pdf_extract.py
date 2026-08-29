import fitz
from .models import SheetData

def extract_sheet(pdf_path: str, page_index: int = 0, dpi: int = 200) -> SheetData:
    doc = fitz.open(pdf_path)
    try:
        # Single chokepoint: pymupdf also opens markdown/xps/etc as documents;
        # only vector PDFs are takeoff input. is_pdf, not metadata['format'],
        # because the format value is version-stamped ("PDF 1.7").
        if not doc.is_pdf:
            raise ValueError(f"not a PDF: {pdf_path}")
        if doc.is_encrypted:                      # PyMuPDF does NOT auto-decrypt; check up front
            raise ValueError(f"pdf is password-protected: {pdf_path}")
        page = doc[page_index]
        pix = page.get_pixmap(dpi=dpi)
        return SheetData(
            page_w=page.rect.width, page_h=page.rect.height,
            paths=page.get_drawings(), words=page.get_text("words"),
            png_bytes=pix.tobytes("png"),
        )
    finally:
        doc.close()   # fitz Document holds a file handle; close in all paths

def page_text_upper(words: list) -> str:
    return " ".join(w[4] for w in words).upper()
