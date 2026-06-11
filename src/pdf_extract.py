from pathlib import Path
import fitz


def extract_pdf_text(pdf_path: str | Path, progress=None) -> list[dict]:
    """Extract text page by page from a PDF using PyMuPDF.

    progress, when provided, receives (current_page, total_pages). This keeps
    the UI progress tied to real PDF iteration instead of a fake timer.
    """
    pdf_path = Path(pdf_path)
    pages: list[dict] = []
    with fitz.open(pdf_path) as doc:
        total = len(doc) or 1
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            pages.append({"page": i, "text": text})
            if progress:
                progress(i, total)
    return pages


def save_extracted_markdown(pages: list[dict], output_path: str | Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    parts = []
    for page in pages:
        parts.append(f"\n\n<!-- page:{page['page']} -->\n\n{page['text'].strip()}\n")
    output_path.write_text("\n".join(parts), encoding="utf-8")
