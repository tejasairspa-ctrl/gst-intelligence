"""
Pydantic schemas for request/response validation.
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


# ── Upload ──────────────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    file_id: str
    filename: str
    gst_type: str
    period: str
    extracted_data: Dict[str, Any]
    analytics: Dict[str, Any]
    message: str


# ── Chat ─────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    query: str
    file_id: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    sources: List[str] = []
    query: str


# ── Analytics ────────────────────────────────────────────────────────────────

class KPICard(BaseModel):
    label: str
    value: Optional[float]
    unit: str = "₹"
    available: bool = True
    note: str = ""


class RatioItem(BaseModel):
    name: str
    value: Optional[float]
    unit: str = "%"
    available: bool = True
    benchmark: Optional[str] = None
    interpretation: str = ""


class ChartPoint(BaseModel):
    label: str
    value: Optional[float]


class AnalyticsResponse(BaseModel):
    file_id: str
    gst_type: str
    period: str
    kpis: List[KPICard]
    ratios: List[RatioItem]
    tax_distribution: List[ChartPoint]
    itc_breakdown: List[ChartPoint]
    sales_breakdown: List[ChartPoint]
    insights: List[str]
    raw: Dict[str, Any]


# ── Export ───────────────────────────────────────────────────────────────────

class ExportRequest(BaseModel):
    file_id: str
    format: str = "excel"  # "excel" | "pdf"
