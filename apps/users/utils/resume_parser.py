"""
Resume Parser Utility
=====================
Extracts and cleans text from PDF and DOCX resume files.

Supported formats:
    - PDF  → extracted via pdfplumber (handles tables, columns, etc.)
    - DOCX → extracted via python-docx (paragraph-by-paragraph)

The cleaned output is a normalized plain-text representation of
the resume content, suitable for downstream NLP / keyword matching.
"""

import io
import re
import logging

import pdfplumber
from docx import Document

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def extract_text_from_pdf(file) -> str:
    """
    Extract all text from a PDF file object using pdfplumber.

    Args:
        file: A file-like object (e.g. InMemoryUploadedFile) or path string.

    Returns:
        Raw concatenated text from every page.
    """
    text_parts = []
    try:
        # pdfplumber can accept a file path or file-like object
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
    except Exception as exc:
        logger.error("PDF extraction failed: %s", exc)
        raise ValueError(f"Could not extract text from PDF: {exc}") from exc

    return "\n\n".join(text_parts)


def extract_text_from_docx(file) -> str:
    """
    Extract all text from a DOCX file object using python-docx.

    Args:
        file: A file-like object (e.g. InMemoryUploadedFile).

    Returns:
        Raw concatenated text from every paragraph.
    """
    text_parts = []
    try:
        doc = Document(file)
        for paragraph in doc.paragraphs:
            stripped = paragraph.text.strip()
            if stripped:
                text_parts.append(stripped)
    except Exception as exc:
        logger.error("DOCX extraction failed: %s", exc)
        raise ValueError(f"Could not extract text from DOCX: {exc}") from exc

    return "\n".join(text_parts)


# ---------------------------------------------------------------------------
# Cleaning & normalisation
# ---------------------------------------------------------------------------

def clean_and_normalize_text(raw_text: str) -> str:
    """
    Apply noise removal and formatting cleanup to raw resume text.

    Steps:
        1. Strip non-printable / control characters (except newlines).
        2. Normalise unicode whitespace to regular spaces.
        3. Collapse multiple blank lines into a maximum of two newlines.
        4. Collapse multiple spaces into a single space per line.
        5. Strip leading/trailing whitespace from each line.
        6. Strip leading/trailing whitespace from the final result.

    Args:
        raw_text: The raw extracted text from a resume.

    Returns:
        Cleaned, normalised text.
    """
    if not raw_text:
        return ""

    # 1. Remove non-printable characters (keep \n and \r)
    text = re.sub(r'[^\S\n\r]+', ' ', raw_text)       # normalise whitespace chars to space
    text = re.sub(r'[^\x20-\x7E\n\r\u00A0-\uFFFF]', '', text)  # remove control chars

    # 2. Normalise line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # 3. Collapse 3+ consecutive newlines → 2
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 4. Clean up each line
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        line = re.sub(r' {2,}', ' ', line)  # collapse multiple spaces
        cleaned_lines.append(line.strip())

    text = '\n'.join(cleaned_lines)

    return text.strip()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.doc'}

def process_resume(file, filename: str) -> dict:
    """
    Determine the file type, extract text, clean it, and return
    a structured result dict.

    Args:
        file: A file-like object.
        filename: Original filename (used to detect extension).

    Returns:
        dict with keys:
            - file_type: 'pdf' | 'docx'
            - raw_text: the unprocessed extracted text
            - cleaned_text: the normalised text
            - character_count: length of cleaned text
            - line_count: number of non-empty lines
    """
    ext = _get_extension(filename)

    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file format '{ext}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # Route to the correct extractor
    if ext == '.pdf':
        raw_text = extract_text_from_pdf(file)
        file_type = 'pdf'
    else:  # .docx / .doc
        raw_text = extract_text_from_docx(file)
        file_type = 'docx'

    cleaned_text = clean_and_normalize_text(raw_text)

    non_empty_lines = [l for l in cleaned_text.split('\n') if l.strip()]

    return {
        'file_type': file_type,
        'raw_text': raw_text,
        'cleaned_text': cleaned_text,
        'character_count': len(cleaned_text),
        'line_count': len(non_empty_lines),
    }


def _get_extension(filename: str) -> str:
    """Return the lowercased file extension including the dot."""
    if '.' not in filename:
        return ''
    return '.' + filename.rsplit('.', 1)[-1].lower()
