"""
Extracts plain text from an uploaded course document, regardless of
format, so it can feed into the same chunking/embedding pipeline that
already exists for admin-typed raw_text.
"""
import docx
import pdfplumber


class UnsupportedFileType(Exception):
    pass


def extract_text_from_file(uploaded_file) -> str:
    """
    uploaded_file is a Django UploadedFile (from request.FILES).
    Dispatches based on the file extension.
    """
    filename = uploaded_file.name.lower()

    if filename.endswith(".pdf"):
        return _extract_pdf(uploaded_file)
    elif filename.endswith(".docx"):
        return _extract_docx(uploaded_file)
    elif filename.endswith((".txt", ".md")):
        return _extract_plain_text(uploaded_file)
    else:
        raise UnsupportedFileType(
            f"Unsupported file type: {filename}. "
            "Supported formats: PDF, DOCX, TXT, MD."
        )


def _extract_pdf(uploaded_file) -> str:
    text_parts = []
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n\n".join(text_parts)


def _extract_docx(uploaded_file) -> str:
    document = docx.Document(uploaded_file)
    paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def _extract_plain_text(uploaded_file) -> str:
    # Read and decode bytes directly — uploaded_file is a file-like
    # object positioned at the start, since nothing has read it yet.
    content = uploaded_file.read()
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="ignore")
    return content