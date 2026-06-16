"""
In-memory application state store — upgraded for multi-file + reconciliation.
Single-user, single-process — suitable for local demo use.
"""
from datetime import datetime
from typing import Dict, List, Optional, Any


class AppStore:
    """Central singleton store for all runtime state."""

    def __init__(self):
        self.files: Dict[str, Dict] = {}
        self.extracted_data: Dict[str, Dict] = {}
        self.analytics: Dict[str, Dict] = {}
        self.reconciliations: Dict[str, Dict] = {}   # keyed by "period"
        self.chat_history: List[Dict] = []
        self.active_file_id: Optional[str] = None

    # ── File management ────────────────────────────────────────────────────────

    def add_file(self, file_id: str, filename: str, gst_type: str, period: str = ""):
        self.files[file_id] = {
            "id": file_id,
            "filename": filename,
            "gst_type": gst_type,
            "period": period,
            "uploaded_at": datetime.now().isoformat(),
            "status": "processing",
        }

    def mark_file_ready(self, file_id: str):
        if file_id in self.files:
            self.files[file_id]["status"] = "ready"

    def mark_file_error(self, file_id: str, error: str):
        if file_id in self.files:
            self.files[file_id]["status"] = "error"
            self.files[file_id]["error"] = error

    def list_files(self) -> List[Dict]:
        return list(self.files.values())

    def get_files_by_period(self) -> Dict[str, Dict]:
        """
        Group files by period.
        Returns: { "March 2022": { "GSTR-1": file_info, "GSTR-3B": file_info, ... } }
        """
        groups: Dict[str, Dict] = {}
        for file_id, file_info in self.files.items():
            period   = file_info.get("period") or "Unknown Period"
            gst_type = file_info.get("gst_type") or "UNKNOWN"
            if period not in groups:
                groups[period] = {}
            # If there's a duplicate type for the same period, keep the latest
            groups[period][gst_type] = {**file_info, "id": file_id}
        return groups

    def get_period_for_file(self, file_id: str) -> Optional[str]:
        return self.files.get(file_id, {}).get("period")

    def find_counterpart(self, file_id: str) -> Optional[str]:
        """
        Given a GSTR-1 file_id, find the GSTR-3B for the same period, or vice versa.
        Returns counterpart file_id or None.
        """
        this_file = self.files.get(file_id)
        if not this_file:
            return None

        this_period   = this_file.get("period")
        this_gst_type = this_file.get("gst_type")

        if this_gst_type == "GSTR-1":
            counterpart_type = "GSTR-3B"
        elif this_gst_type == "GSTR-3B":
            counterpart_type = "GSTR-1"
        else:
            return None

        for fid, finfo in self.files.items():
            if fid == file_id:
                continue
            if finfo.get("period") == this_period and finfo.get("gst_type") == counterpart_type:
                return fid

        return None

    # ── Data management ────────────────────────────────────────────────────────

    def set_extracted_data(self, file_id: str, data: Dict):
        self.extracted_data[file_id] = data
        self.active_file_id = file_id

    def get_extracted_data(self, file_id: str) -> Optional[Dict]:
        return self.extracted_data.get(file_id)

    def set_analytics(self, file_id: str, analytics: Dict):
        self.analytics[file_id] = analytics

    def get_analytics(self, file_id: str) -> Optional[Dict]:
        return self.analytics.get(file_id)

    # ── Reconciliation ─────────────────────────────────────────────────────────

    def set_reconciliation(self, period: str, recon: Dict):
        self.reconciliations[period] = recon

    def get_reconciliation(self, period: str) -> Optional[Dict]:
        return self.reconciliations.get(period)

    def get_all_reconciliations(self) -> Dict[str, Dict]:
        return dict(self.reconciliations)

    # ── Chat management ────────────────────────────────────────────────────────

    def add_message(self, role: str, content: str, sources: Optional[List] = None):
        self.chat_history.append({
            "id":        len(self.chat_history) + 1,
            "role":      role,
            "content":   content,
            "sources":   sources or [],
            "timestamp": datetime.now().isoformat(),
        })

    def get_chat_history(self) -> List[Dict]:
        return self.chat_history

    def clear_chat(self):
        self.chat_history = []

    # ── Active context ─────────────────────────────────────────────────────────

    def get_active_context(self) -> Optional[Dict[str, Any]]:
        fid = self.active_file_id
        if not fid:
            return None
        file_info = self.files.get(fid)
        period = file_info.get("period") if file_info else None
        return {
            "file_info":      file_info,
            "extracted_data": self.extracted_data.get(fid),
            "analytics":      self.analytics.get(fid),
            "reconciliation": self.reconciliations.get(period) if period else None,
        }

    def get_full_context(self) -> Dict[str, Any]:
        """
        Return context for ALL uploaded files grouped by period.
        Used for comprehensive chat answers.
        """
        by_period = self.get_files_by_period()
        context = {
            "files_by_period": {},
            "all_analytics":   {},
        }
        for period, type_map in by_period.items():
            context["files_by_period"][period] = {}
            for gst_type, file_info in type_map.items():
                fid = file_info["id"]
                context["files_by_period"][period][gst_type] = {
                    "file_info":      file_info,
                    "extracted_data": self.extracted_data.get(fid),
                    "analytics":      self.analytics.get(fid),
                }
            context["files_by_period"][period]["reconciliation"] = \
                self.reconciliations.get(period)

        return context

    def set_active_file(self, file_id: str):
        if file_id in self.files:
            self.active_file_id = file_id

    def clear_all(self):
        """Reset the entire store — wipes all files, analytics, reconciliations and chat."""
        self.files.clear()
        self.extracted_data.clear()
        self.analytics.clear()
        self.reconciliations.clear()
        self.chat_history.clear()
        self.active_file_id = None

    def has_data(self) -> bool:
        return self.active_file_id is not None and self.active_file_id in self.extracted_data

    def get_gstr1_for_period(self, period: str) -> Optional[Dict]:
        """Return extracted data for GSTR-1 of given period."""
        for file_id, file_info in self.files.items():
            if file_info.get("period") == period and file_info.get("gst_type") == "GSTR-1":
                return self.extracted_data.get(file_id)
        return None

    def get_gstr3b_for_period(self, period: str) -> Optional[Dict]:
        """Return extracted data for GSTR-3B of given period."""
        for file_id, file_info in self.files.items():
            if file_info.get("period") == period and file_info.get("gst_type") == "GSTR-3B":
                return self.extracted_data.get(file_id)
        return None


# Singleton
store = AppStore()
