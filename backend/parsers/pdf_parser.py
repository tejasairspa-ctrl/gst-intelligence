"""
GST PDF Parser — Base engine.
Extracts raw text and tables from uploaded PDFs using pdfplumber.
Only returns data explicitly present in the document. Never infers or assumes.
"""

import pdfplumber
import re
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def extract_raw_text(filepath: str) -> str:
    """Extract all raw text from a PDF file."""
    try:
        with pdfplumber.open(filepath) as pdf:
            pages = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
            return "\n".join(pages)
    except Exception as e:
        logger.error(f"Text extraction failed: {e}")
        raise ValueError(f"Could not extract text from PDF: {e}")


def extract_tables(filepath: str) -> list[list]:
    """Extract all tables from a PDF file."""
    try:
        all_tables = []
        with pdfplumber.open(filepath) as pdf:
            for page_num, page in enumerate(pdf.pages):
                tables = page.extract_tables()
                for table in tables:
                    if table:
                        all_tables.append({
                            "page": page_num + 1,
                            "data": table
                        })
        return all_tables
    except Exception as e:
        logger.error(f"Table extraction failed: {e}")
        return []


def detect_document_type(text: str) -> str:
    """
    Detect GSTR type from document text.
    Returns: 'GSTR-1', 'GSTR-3B', 'GSTR-9', 'GSTR-9C', or 'UNKNOWN'
    """
    text_upper = text.upper()

    if "GSTR-9C" in text_upper or "GSTR9C" in text_upper or "RECONCILIATION STATEMENT" in text_upper:
        return "GSTR-9C"
    elif "GSTR-9" in text_upper or "GSTR9" in text_upper or "ANNUAL RETURN" in text_upper:
        return "GSTR-9"
    elif "GSTR-3B" in text_upper or "GSTR3B" in text_upper or "MONTHLY RETURN" in text_upper:
        return "GSTR-3B"
    elif "GSTR-1" in text_upper or "GSTR1" in text_upper or "OUTWARD SUPPLIES" in text_upper:
        return "GSTR-1"
    else:
        return "UNKNOWN"


def clean_number(value: str) -> Optional[float]:
    """
    Safely parse a numeric string from PDF text.
    Returns None if value is missing, blank, or non-numeric.
    Never estimates or defaults to 0 for missing values.
    """
    if not value or str(value).strip() in ["", "-", "N/A", "NA", "NIL", "Nil", "--"]:
        return None
    # Remove commas, currency symbols, whitespace
    cleaned = re.sub(r"[₹,\s]", "", str(value).strip())
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_gstin(text: str) -> Optional[str]:
    """Extract GSTIN from document text."""
    pattern = r'\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}\b'
    match = re.search(pattern, text)
    return match.group(0) if match else None


def extract_period(text: str) -> Optional[str]:
    """Extract filing period from document text."""
    # Try "April 2023", "Apr-23", "FY 2023-24", "Q1 2023"
    patterns = [
        r'(?:Financial Year|FY)[:\s]+(\d{4}[-–]\d{2,4})',
        r'(?:Period|Month|Quarter)[:\s]+([A-Za-z]+[-\s]\d{4})',
        r'\b((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})\b',
        r'\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[-\s]\d{2,4})\b',
        r'\b(\d{4}[-–]\d{2,4})\b',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None
