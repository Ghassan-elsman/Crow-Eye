"""
Case Summary Dialog for EYE AI Forensic Assistant

This module provides a dialog for displaying the investigation timeline from the
investigation log. It shows a chronological list of queries, findings, and suggestions
with filtering capabilities.

Enhanced with tabbed interface for Investigation Timeline, Report Findings, and Charts.

"""

import logging
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from collections import Counter

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QGroupBox, QAbstractItemView, QMessageBox, QSizePolicy,
    QTabWidget, QWidget, QTextBrowser, QFileDialog, QSplitter,
    QDateEdit, QMenu, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal, QDate
from PyQt5.QtGui import QPalette, QColor, QFont
import csv

from eye.models.report_blocks import ReportBlock, TextBlock, TableBlock, ImageBlock, ChartBlock

# Use the application-wide style system so the Case Summary matches the rest of
# Crow-Eye (unified tables, tab bar, buttons, palette) instead of a bespoke look.
from styles import CrowEyeStyles, Colors

# Crow-Eye design tokens — sourced from the shared Colors palette (styles.py) so
# this dialog stays in lock-step with the rest of the app.
CROW_EYE_FONT_FAMILY = "'Segoe UI', 'Inter', system-ui, sans-serif"
CROW_EYE_BG = Colors.BG_PRIMARY          # outer window  (#0F172A)
CROW_EYE_PANEL = Colors.BG_TABLES        # deep surfaces (#0B1220)
CROW_EYE_PANEL_RAISED = Colors.BG_PANELS # cards / group boxes (#1E293B)
CROW_EYE_BORDER = Colors.BORDER_SUBTLE   # (#334155)
CROW_EYE_TEXT = Colors.TEXT_PRIMARY      # (#E2E8F0)
CROW_EYE_TEXT_DIM = Colors.TEXT_SECONDARY # (#94A3B8)
CROW_EYE_ACCENT = Colors.ACCENT_CYAN     # (#00FFFF)

# Shared combo-box style (styles.py has no dedicated QComboBox constant) — built
# from the Colors palette so the filter dropdowns match the app's inputs.
CROW_EYE_COMBO_STYLE = f"""
    QComboBox {{
        background: {CROW_EYE_PANEL_RAISED};
        border: 1px solid {CROW_EYE_BORDER};
        padding: 6px 12px;
        color: {CROW_EYE_TEXT};
        font-size: 10pt;
        border-radius: 4px;
        font-family: {CROW_EYE_FONT_FAMILY};
    }}
    QComboBox:hover {{ border: 1px solid {CROW_EYE_ACCENT}; }}
    QComboBox::drop-down {{ border: none; padding-right: 8px; }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 5px solid {CROW_EYE_TEXT};
        margin-right: 5px;
    }}
    QComboBox QAbstractItemView {{
        background: {CROW_EYE_PANEL_RAISED};
        border: 1px solid {CROW_EYE_BORDER};
        color: {CROW_EYE_TEXT};
        selection-background-color: {CROW_EYE_BORDER};
        selection-color: {CROW_EYE_ACCENT};
    }}
"""


logger = logging.getLogger(__name__)


class CaseSummaryDialog(QDialog):
    """
    Dialog for displaying investigation timeline from investigation log.
    
    Shows a chronological list of all queries, findings, and suggestions from the
    investigation log with filtering capabilities by evidence_found status.
    
    Enhanced with tabbed interface for Investigation Timeline, Report Findings, and Charts.
    
    The dialog follows the UI pattern from CaseSetupDialog and CaseContextEditDialog
    with dark theme styling and user-friendly layout.
    
    """
    
    def __init__(
        self,
        timeline_entries: List[Dict[str, Any]],
        report_blocks: Optional[List[ReportBlock]] = None,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        case_context: Optional[Dict[str, Any]] = None,
        parent=None
    ):
        """
        Initialize the case summary dialog.

        Args:
            timeline_entries: AI-curated investigation log entries from get_investigation_timeline()
            report_blocks: Imported / generated report blocks
            conversation_history: Full chat history (role/content/metadata) — powers the Queries tab
            case_context: Dict of case-level fields (case_name, investigation_reason, etc.) — drives the overview band
            parent: Parent widget (typically the main Eye window)
        """
        super().__init__(parent)

        self.setWindowFlags(self.windowFlags() | Qt.Window)

        self.timeline_entries = timeline_entries or []
        self.filtered_entries = self.timeline_entries.copy()
        self.report_blocks = report_blocks or []
        self.filtered_blocks = self.report_blocks.copy()
        self.conversation_history = conversation_history or []
        self.case_context = case_context or {}
        # User queries only — the Queries tab does not show assistant or system messages.
        self.user_queries = [m for m in self.conversation_history if m.get("role") == "user"]
        self.filtered_queries = self.user_queries.copy()

        # UI components
        self.tab_widget = None
        self.filter_combo = None
        self.timeline_table = None
        self.entry_count_label = None
        self.timeline_detail = None
        self.timeline_from = None
        self.timeline_to = None
        self.findings_filter = None
        self.findings_table = None
        self.detail_pane = None
        self.queries_table = None
        self.queries_search = None
        self.queries_count_label = None
        self.queries_detail = None
        self.queries_from = None
        self.queries_to = None

        self._init_ui()
        self._apply_styling()
    
    def _init_ui(self):
        """
        Initialize the user interface components with tabbed interface.
        
        """
        self.setWindowTitle("Case Summary")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(24, 24, 24, 16)
        
        # Title
        title = QLabel("Case Summary")
        title.setStyleSheet(
            f"font-size: 16pt; font-weight: bold; color: {CROW_EYE_ACCENT};"
            f" background: transparent; font-family: {CROW_EYE_FONT_FAMILY};"
            f" letter-spacing: 1.5px;"
        )
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)

        # Subtitle
        subtitle = QLabel(
            "Investigation timeline, queries run, and report findings."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            f"font-size: 10pt; color: {CROW_EYE_TEXT_DIM}; background: transparent;"
            f" font-family: {CROW_EYE_FONT_FAMILY};"
        )
        subtitle.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(subtitle)

        main_layout.addSpacing(6)

        # Case Overview band — case identification + key counts at a glance.
        main_layout.addWidget(self._build_overview_band())
        main_layout.addSpacing(6)

        # Conclusion / Key Findings — the latest answer narrative at a glance.
        main_layout.addWidget(self._build_conclusion_panel())
        main_layout.addSpacing(8)

        # Create tab widget — wider tabs that fill the bar (setExpanding) so they
        # read as primary navigation, matching the Crow-Eye toolbar style.
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)
        # Unified app-wide tab styling (UNIFIED_TAB_STYLE + expanding tab bar).
        CrowEyeStyles.apply_tab_styles(self.tab_widget)

        # Add tabs (Charts tab removed per case-summary scope; chart blocks still
        # appear in the exported HTML report).
        self.tab_widget.addTab(self._init_timeline_tab(), "Investigation Timeline")
        self.tab_widget.addTab(self._init_queries_tab(), "Queries Run")
        self.tab_widget.addTab(self._init_report_findings_tab(), "Report Findings")
        
        main_layout.addWidget(self.tab_widget, 1)
        
        # Button layout
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        button_layout.setContentsMargins(0, 12, 0, 0)
        
        button_layout.addStretch()
        
        # Export Summary button — shared primary button style.
        export_button = QPushButton("Export Summary")
        export_button.setFixedHeight(40)
        export_button.setMinimumWidth(160)
        export_button.setStyleSheet(
            CrowEyeStyles.BUTTON_STYLE + " QPushButton { font-size: 12px; padding: 8px 16px; }"
        )
        export_button.clicked.connect(self._on_export_summary_clicked)
        button_layout.addWidget(export_button)

        # Close button — shared neutral/clear button style.
        close_button = QPushButton("Close")
        close_button.setFixedHeight(40)
        close_button.setMinimumWidth(140)
        close_button.setStyleSheet(
            CrowEyeStyles.CLEAR_BUTTON_STYLE + " QPushButton { font-size: 12px; padding: 8px 16px; }"
        )
        close_button.clicked.connect(self.accept)
        button_layout.addWidget(close_button)
        
        main_layout.addLayout(button_layout)
    
    def _build_overview_band(self) -> QWidget:
        """Top-of-dialog case identification + headline counts."""
        band = QFrame()
        band.setStyleSheet(f"""
            QFrame {{
                background: {CROW_EYE_PANEL_RAISED};
                border: 1px solid {CROW_EYE_BORDER};
                border-radius: 8px;
            }}
        """)
        outer = QVBoxLayout(band)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(8)

        ctx = self.case_context or {}
        case_name = ctx.get("case_name") or "(Unnamed Case)"
        case_id = ctx.get("case_id") or ctx.get("id") or ""
        investigator = ctx.get("investigator") or ctx.get("analyst_name") or ""
        reason = (ctx.get("investigation_reason") or "").strip()

        identity_row = QHBoxLayout()
        identity_row.setSpacing(20)
        name_label = QLabel(f"<b>{case_name}</b>")
        name_label.setStyleSheet(
            f"font-size: 13pt; color: {CROW_EYE_ACCENT}; font-family: {CROW_EYE_FONT_FAMILY}; background: transparent;"
        )
        identity_row.addWidget(name_label)

        if case_id:
            id_label = QLabel(f"ID: <code>{case_id}</code>")
            id_label.setStyleSheet(
                f"font-size: 10pt; color: {CROW_EYE_TEXT_DIM}; font-family: {CROW_EYE_FONT_FAMILY}; background: transparent;"
            )
            identity_row.addWidget(id_label)
        if investigator:
            inv_label = QLabel(f"Investigator: <b>{investigator}</b>")
            inv_label.setStyleSheet(
                f"font-size: 10pt; color: {CROW_EYE_TEXT}; font-family: {CROW_EYE_FONT_FAMILY}; background: transparent;"
            )
            identity_row.addWidget(inv_label)
        identity_row.addStretch()
        outer.addLayout(identity_row)

        if reason:
            reason_label = QLabel(f"<i>{reason[:240]}{'…' if len(reason) > 240 else ''}</i>")
            reason_label.setWordWrap(True)
            reason_label.setStyleSheet(
                f"font-size: 10pt; color: {CROW_EYE_TEXT_DIM}; font-family: {CROW_EYE_FONT_FAMILY}; background: transparent;"
            )
            outer.addWidget(reason_label)

        first_ts, last_ts = self._activity_time_range()
        total_queries = len(self.user_queries)
        total_findings = len(self.timeline_entries)
        evidence_hits = sum(1 for e in self.timeline_entries if e.get("evidence_found"))
        evidence_rate = (evidence_hits / total_findings * 100.0) if total_findings else 0.0
        total_blocks = len(self.report_blocks)

        time_label = "Activity:  "
        if first_ts and last_ts:
            time_label += f"{self._format_timestamp(first_ts)}  →  {self._format_timestamp(last_ts)}"
        elif first_ts:
            time_label += f"since {self._format_timestamp(first_ts)}"
        else:
            time_label += "—"

        time_row = QLabel(time_label)
        time_row.setStyleSheet(
            f"font-size: 10pt; color: {CROW_EYE_TEXT_DIM}; font-family: {CROW_EYE_FONT_FAMILY};"
            f" background: transparent;"
        )
        outer.addWidget(time_row)

        # Inline pill metrics — Queries | AI Steps | Evidence Hits / Rate | Report Blocks
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(10)
        metrics_row.addWidget(self._build_metric_pill("Queries", str(total_queries)))
        metrics_row.addWidget(self._build_metric_pill("AI Steps", str(total_findings)))
        evidence_pill_value = (
            f"{evidence_hits} / {total_findings} ({evidence_rate:.0f}%)"
            if total_findings else "0"
        )
        metrics_row.addWidget(self._build_metric_pill("Evidence Hits", evidence_pill_value))
        metrics_row.addWidget(self._build_metric_pill("Report Blocks", str(total_blocks)))
        metrics_row.addStretch()
        outer.addLayout(metrics_row)

        return band

    def _latest_findings_text(self) -> str:
        """Best-effort 'conclusion' text: the most recent AI-authored report
        narrative, else the latest assistant chat message, else the latest
        investigation-timeline summary. Empty string if nothing yet."""
        # 1. Most recent AI-authored TextBlock (the findings narrative).
        for block in reversed(self.report_blocks):
            if getattr(block, "block_type", "") != "text":
                continue
            author = ((block.metadata or {}).get("author") or "").strip().lower()
            content = getattr(block, "markdown_content", "") or ""
            if content.strip() and author in ("ai", ""):
                return content.strip()
        # 2. Latest assistant chat message.
        for msg in reversed(self.conversation_history):
            if msg.get("role") == "assistant":
                c = (msg.get("content") or "").strip()
                if c:
                    return c
        # 3. Latest timeline response summary.
        if self.timeline_entries:
            latest = sorted(self.timeline_entries, key=lambda e: e.get("timestamp", ""))[-1]
            return (latest.get("response_summary") or "").strip()
        return ""

    def _build_conclusion_panel(self) -> QWidget:
        """Compact card surfacing the latest findings/conclusion at a glance."""
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background: {CROW_EYE_PANEL};
                border: 1px solid {CROW_EYE_BORDER};
                border-left: 3px solid {CROW_EYE_ACCENT};
                border-radius: 8px;
            }}
        """)
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 10, 16, 12)
        v.setSpacing(4)

        heading = QLabel("CONCLUSION · KEY FINDINGS")
        heading.setStyleSheet(
            f"color: {CROW_EYE_ACCENT}; font-size: 9pt; font-weight: 700;"
            f" letter-spacing: 0.8px; background: transparent; font-family: {CROW_EYE_FONT_FAMILY};"
        )
        v.addWidget(heading)

        text = self._latest_findings_text()
        if text:
            # Strip the heaviest markdown so the card reads cleanly; keep it short.
            clean = text.replace("**", "").replace("##", "").replace("`", "").strip()
            shown = clean[:600] + ("…" if len(clean) > 600 else "")
            body = QLabel(shown)
            body.setWordWrap(True)
            body.setStyleSheet(
                f"color: {CROW_EYE_TEXT}; font-size: 10.5pt; background: transparent;"
                f" font-family: {CROW_EYE_FONT_FAMILY};"
            )
            v.addWidget(body)
            if len(clean) > 600:
                hint = QLabel("Full text in the Report Findings tab below.")
                hint.setStyleSheet(
                    f"color: {CROW_EYE_TEXT_DIM}; font-size: 9pt; background: transparent;"
                    f" font-family: {CROW_EYE_FONT_FAMILY};"
                )
                v.addWidget(hint)
        else:
            empty = QLabel("No findings yet — the Eye documents its conclusions here as it investigates.")
            empty.setWordWrap(True)
            empty.setStyleSheet(
                f"color: {CROW_EYE_TEXT_DIM}; font-size: 10pt; font-style: italic;"
                f" background: transparent; font-family: {CROW_EYE_FONT_FAMILY};"
            )
            v.addWidget(empty)

        return card

    def _build_metric_pill(self, label: str, value: str) -> QWidget:
        pill = QFrame()
        pill.setStyleSheet(f"""
            QFrame {{
                background: {CROW_EYE_PANEL};
                border: 1px solid {CROW_EYE_BORDER};
                border-radius: 14px;
            }}
        """)
        h = QHBoxLayout(pill)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(8)
        v = QLabel(f"<b>{value}</b>")
        v.setStyleSheet(
            f"color: {CROW_EYE_ACCENT}; font-size: 11pt; font-family: {CROW_EYE_FONT_FAMILY}; background: transparent;"
        )
        l = QLabel(label)
        l.setStyleSheet(
            f"color: {CROW_EYE_TEXT_DIM}; font-size: 9pt; font-family: {CROW_EYE_FONT_FAMILY};"
            f" background: transparent; text-transform: uppercase; letter-spacing: 0.6px;"
        )
        h.addWidget(v)
        h.addWidget(l)
        return pill

    def _activity_time_range(self):
        """Return (first_iso, last_iso) timestamps across timeline + chat history.
        Either may be empty string if no data."""
        stamps = []
        for e in self.timeline_entries:
            ts = e.get("timestamp")
            if ts:
                stamps.append(ts)
        for m in self.conversation_history:
            # HistoryManager stamps timestamp at the TOP LEVEL of the message
            # dict (see history_manager.add_message); the metadata fallback
            # covers older payloads only.
            ts = m.get("timestamp") or (m.get("metadata") or {}).get("timestamp")
            if ts:
                stamps.append(ts)
        if not stamps:
            return "", ""
        stamps.sort()
        return stamps[0], stamps[-1]

    def _parse_iso(self, ts: str):
        """Best-effort ISO 8601 → datetime. Returns None on failure."""
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None

    def _init_timeline_tab(self) -> QWidget:
        """
        Initialize the Investigation Timeline tab.
        
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Filter controls
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(12)
        
        filter_label = QLabel("Filter by Evidence:")
        filter_label.setStyleSheet(
            "font-size: 11pt; font-weight: bold; color: #E5E7EB; background: transparent;"
        )
        filter_layout.addWidget(filter_label)
        
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "Evidence Found", "No Evidence"])
        self.filter_combo.setMinimumWidth(200)
        self.filter_combo.setStyleSheet(CROW_EYE_COMBO_STYLE)
        self.filter_combo.currentTextChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.filter_combo)

        # Date range filter
        self.timeline_from, self.timeline_to = self._make_date_range_controls()
        self.timeline_from.dateChanged.connect(lambda *_: self._on_filter_changed(self.filter_combo.currentText()))
        self.timeline_to.dateChanged.connect(lambda *_: self._on_filter_changed(self.filter_combo.currentText()))
        filter_layout.addSpacing(12)
        filter_layout.addWidget(QLabel("From:"))
        filter_layout.addWidget(self.timeline_from)
        filter_layout.addWidget(QLabel("To:"))
        filter_layout.addWidget(self.timeline_to)

        filter_layout.addStretch()

        # Entry count label
        self.entry_count_label = QLabel()
        self.entry_count_label.setStyleSheet(
            f"font-size: 10pt; color: {CROW_EYE_TEXT_DIM}; background: transparent;"
            f" font-family: {CROW_EYE_FONT_FAMILY};"
        )
        filter_layout.addWidget(self.entry_count_label)

        # Per-tab export
        filter_layout.addWidget(self._make_export_button(lambda fmt: self._export_timeline(fmt)))

        layout.addLayout(filter_layout)
        
        # Timeline table
        self.timeline_table = QTableWidget()
        self.timeline_table.setColumnCount(6)
        self.timeline_table.setHorizontalHeaderLabels([
            "Timestamp", "Action/Query", "Forensic Summary", "Evidence", "Artifacts", "Next Steps"
        ])
        
        # Unified app-wide table styling.
        CrowEyeStyles.apply_table_styles(self.timeline_table)

        # Table behavior
        self.timeline_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.timeline_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.timeline_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.timeline_table.setAlternatingRowColors(True)
        self.timeline_table.verticalHeader().setVisible(False)
        self.timeline_table.setSortingEnabled(True)
        self.timeline_table.itemSelectionChanged.connect(self._on_timeline_row_selected)

        # Column sizing - optimized for uncollapsed view
        header = self.timeline_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Timestamp
        header.setSectionResizeMode(1, QHeaderView.Interactive)       # Query
        header.setSectionResizeMode(2, QHeaderView.Stretch)           # Forensic Summary
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Evidence
        header.setSectionResizeMode(4, QHeaderView.Interactive)       # Artifacts
        header.setSectionResizeMode(5, QHeaderView.Interactive)       # Next Steps
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)

        # Set specific widths to prevent 'collapsed' look
        self.timeline_table.setColumnWidth(0, 160)  # Timestamp
        self.timeline_table.setColumnWidth(1, 250)  # Query
        self.timeline_table.setColumnWidth(3, 80)   # Evidence
        self.timeline_table.setColumnWidth(4, 150)  # Artifacts
        self.timeline_table.setColumnWidth(5, 200)  # Next Steps

        # Splitter: table on top, detail pane on the bottom — click a row to drill in.
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.timeline_table)
        self.timeline_detail = self._make_detail_pane("Select a row to view the full forensic summary, response, and queried artifacts.")
        splitter.addWidget(self.timeline_detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([500, 280])
        layout.addWidget(splitter, 1)

        # Populate timeline
        self._populate_timeline()

        return tab
    
    def _init_report_findings_tab(self) -> QWidget:
        """
        Initialize the Report Findings tab.
        
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Statistics panel — shared group-box style.
        stats_group = QGroupBox("Report Statistics")
        stats_group.setStyleSheet(CrowEyeStyles.GROUP_BOX)
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(20)
        
        # Count blocks by type
        text_count = len([b for b in self.report_blocks if b.block_type == "text"])
        table_count = len([b for b in self.report_blocks if b.block_type == "table"])
        image_count = len([b for b in self.report_blocks if b.block_type == "image"])
        chart_count = len([b for b in self.report_blocks if b.block_type == "chart"])
        
        stats_layout.addWidget(self._create_stat_label("Total", len(self.report_blocks)))
        stats_layout.addWidget(self._create_stat_label("Text", text_count))
        stats_layout.addWidget(self._create_stat_label("Tables", table_count))
        stats_layout.addWidget(self._create_stat_label("Images", image_count))
        stats_layout.addWidget(self._create_stat_label("Charts", chart_count))
        stats_layout.addStretch()
        
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        # Filter dropdown
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(12)
        
        filter_label = QLabel("Filter by Type:")
        filter_label.setStyleSheet(
            "font-size: 11pt; font-weight: bold; color: #E5E7EB; background: transparent;"
        )
        filter_layout.addWidget(filter_label)
        
        self.findings_filter = QComboBox()
        self.findings_filter.addItems(["All", "Text", "Table", "Image", "Chart"])
        self.findings_filter.setMinimumWidth(200)
        self.findings_filter.setStyleSheet(CROW_EYE_COMBO_STYLE)
        self.findings_filter.currentTextChanged.connect(self._on_findings_filter_changed)
        filter_layout.addWidget(self.findings_filter)
        filter_layout.addStretch()

        # Per-tab export
        filter_layout.addWidget(self._make_export_button(lambda fmt: self._export_findings(fmt)))

        layout.addLayout(filter_layout)
        
        # Findings table
        self.findings_table = QTableWidget()
        self.findings_table.setColumnCount(4)
        self.findings_table.setHorizontalHeaderLabels([
            "Type", "Title/Caption", "Timestamp", "Source Report"
        ])
        
        # Unified app-wide table styling.
        CrowEyeStyles.apply_table_styles(self.findings_table)

        # Table behavior
        self.findings_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.findings_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.findings_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.findings_table.verticalHeader().setVisible(False)
        self.findings_table.setAlternatingRowColors(True)
        self.findings_table.setSortingEnabled(True)
        self.findings_table.horizontalHeader().setSectionsClickable(True)
        self.findings_table.horizontalHeader().setSortIndicatorShown(True)
        
        # Column sizing
        header = self.findings_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Type
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Title/Caption
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Timestamp
        header.setSectionResizeMode(3, QHeaderView.Stretch)  # Source Report
        
        self.findings_table.itemSelectionChanged.connect(self._on_finding_selected)
        layout.addWidget(self.findings_table, 1)
        
        # Detail pane
        detail_label = QLabel("Detail View:")
        detail_label.setStyleSheet(
            "font-size: 11pt; font-weight: bold; color: #E5E7EB; background: transparent; margin-top: 10px;"
        )
        layout.addWidget(detail_label)
        
        self.detail_pane = QTextBrowser()
        self.detail_pane.setMinimumHeight(200)
        self.detail_pane.setMaximumHeight(300)
        self.detail_pane.setStyleSheet("""
            QTextBrowser {
                background: #0F172A;
                border: 2px solid #334155;
                border-radius: 6px;
                color: #E5E7EB;
                padding: 10px;
                font-size: 10pt;
            }
            QScrollBar:vertical {
                background: #1E293B;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #334155;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #475569;
            }
        """)
        layout.addWidget(self.detail_pane)
        
        # Populate findings table
        self._populate_findings_table()
        
        return tab
    
    def _init_queries_tab(self) -> QWidget:
        """
        Initialize the Queries Run tab — every user query asked in this chat
        session, including ones the investigation log did not retain. Useful
        for auditing what was explored vs. what produced evidence.
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        layout.setContentsMargins(10, 10, 10, 10)

        # Search bar + count row
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(12)

        search_label = QLabel("Search queries:")
        search_label.setStyleSheet(
            f"font-size: 11pt; font-weight: bold; color: {CROW_EYE_TEXT};"
            f" background: transparent; font-family: {CROW_EYE_FONT_FAMILY};"
        )
        controls_layout.addWidget(search_label)

        from PyQt5.QtWidgets import QLineEdit
        self.queries_search = QLineEdit()
        self.queries_search.setPlaceholderText("Filter by keyword…")
        self.queries_search.setMinimumWidth(280)
        self.queries_search.setStyleSheet(CrowEyeStyles.INPUT_FIELD)
        self.queries_search.textChanged.connect(self._on_queries_search_changed)
        controls_layout.addWidget(self.queries_search)

        # Date range filter (applies on top of the keyword search)
        self.queries_from, self.queries_to = self._make_date_range_controls()
        self.queries_from.dateChanged.connect(lambda *_: self._on_queries_search_changed(self.queries_search.text()))
        self.queries_to.dateChanged.connect(lambda *_: self._on_queries_search_changed(self.queries_search.text()))
        controls_layout.addSpacing(12)
        controls_layout.addWidget(QLabel("From:"))
        controls_layout.addWidget(self.queries_from)
        controls_layout.addWidget(QLabel("To:"))
        controls_layout.addWidget(self.queries_to)

        controls_layout.addStretch()

        self.queries_count_label = QLabel()
        self.queries_count_label.setStyleSheet(
            f"font-size: 10pt; color: {CROW_EYE_TEXT_DIM}; background: transparent;"
            f" font-family: {CROW_EYE_FONT_FAMILY};"
        )
        controls_layout.addWidget(self.queries_count_label)

        # Per-tab export
        controls_layout.addWidget(self._make_export_button(lambda fmt: self._export_queries(fmt)))

        layout.addLayout(controls_layout)

        # Queries table
        self.queries_table = QTableWidget()
        self.queries_table.setColumnCount(3)
        self.queries_table.setHorizontalHeaderLabels(["#", "Timestamp", "Query"])

        # Unified app-wide table styling.
        CrowEyeStyles.apply_table_styles(self.queries_table)

        self.queries_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.queries_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.queries_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.queries_table.verticalHeader().setVisible(False)
        self.queries_table.setWordWrap(True)
        self.queries_table.setAlternatingRowColors(True)
        self.queries_table.setSortingEnabled(True)
        self.queries_table.itemSelectionChanged.connect(self._on_query_row_selected)

        header = self.queries_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # #
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Timestamp
        header.setSectionResizeMode(2, QHeaderView.Stretch)           # Query
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)

        # Splitter: queries table + detail pane showing the full assistant reply.
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.queries_table)
        self.queries_detail = self._make_detail_pane("Select a query to view its full text and the assistant response.")
        splitter.addWidget(self.queries_detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([500, 280])
        layout.addWidget(splitter, 1)

        self._populate_queries_table()
        return tab

    def _populate_queries_table(self):
        """Render the user-query list (newest first) into the Queries Run table."""
        was_sorting = self.queries_table.isSortingEnabled()
        self.queries_table.setSortingEnabled(False)
        self.queries_table.setRowCount(0)
        if not self.filtered_queries:
            self._update_queries_count()
            # Empty-state row
            self.queries_table.insertRow(0)
            empty = QTableWidgetItem(
                "No queries yet — anything you ask in the Eye chat will appear here."
            )
            empty.setForeground(QColor(CROW_EYE_TEXT_DIM))
            empty.setTextAlignment(Qt.AlignCenter)
            self.queries_table.setItem(0, 0, empty)
            self.queries_table.setSpan(0, 0, 1, 3)
            self.queries_table.setSortingEnabled(was_sorting)
            return

        # Newest-first so the latest query is visible without scrolling.
        # HistoryManager.add_message stores `timestamp` at the top level of the
        # message dict, NOT inside metadata, so the top-level field is preferred.
        sorted_queries = sorted(
            self.filtered_queries,
            key=lambda m: m.get("timestamp") or (m.get("metadata") or {}).get("timestamp", ""),
            reverse=True
        )

        for idx, msg in enumerate(sorted_queries, start=1):
            row = self.queries_table.rowCount()
            self.queries_table.insertRow(row)

            # Sequence number — stash the full msg for the detail pane.
            num_item = QTableWidgetItem(str(idx))
            num_item.setTextAlignment(Qt.AlignCenter)
            num_item.setForeground(QColor(CROW_EYE_TEXT_DIM))
            num_item.setFont(QFont("Consolas", 9))
            num_item.setData(Qt.UserRole, msg)
            self.queries_table.setItem(row, 0, num_item)

            # Timestamp — HistoryManager stamps it at the top level of the
            # message dict; older payloads sometimes carried it inside metadata,
            # so we fall through both for compatibility.
            ts_raw = msg.get("timestamp") or (msg.get("metadata") or {}).get("timestamp", "")
            ts_item = QTableWidgetItem(self._format_timestamp(ts_raw) if ts_raw else "—")
            ts_item.setFont(QFont("Consolas", 9))
            ts_item.setForeground(QColor(CROW_EYE_TEXT_DIM))
            self.queries_table.setItem(row, 1, ts_item)

            # Query content
            content = (msg.get("content") or "").strip()
            query_item = QTableWidgetItem(content or "(empty query)")
            query_item.setToolTip(content)
            self.queries_table.setItem(row, 2, query_item)

            self.queries_table.setRowHeight(row, 44)

        self._update_queries_count()
        self.queries_table.setSortingEnabled(was_sorting)
        logger.info(f"Populated queries table with {len(sorted_queries)} user queries")

    def _on_queries_search_changed(self, text: str):
        needle = text.strip().lower()
        if needle:
            base = [m for m in self.user_queries if needle in (m.get("content") or "").lower()]
        else:
            base = self.user_queries.copy()

        # Apply date-range filter on top of the keyword filter.
        self.filtered_queries = [
            m for m in base
            if self._ts_in_range(
                (m.get("metadata") or {}).get("timestamp") or m.get("timestamp", ""),
                self.queries_from,
                self.queries_to,
            )
        ]
        self._populate_queries_table()

    def _update_queries_count(self):
        total = len(self.user_queries)
        shown = len(self.filtered_queries)
        if total == shown:
            self.queries_count_label.setText(f"{total} {'query' if total == 1 else 'queries'} asked")
        else:
            self.queries_count_label.setText(f"Showing {shown} of {total} queries")
    
    def _apply_styling(self):
        """Apply Crow-Eye palette + Segoe UI font globally to the dialog."""
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(CROW_EYE_BG))
        palette.setColor(QPalette.WindowText, QColor(CROW_EYE_TEXT))
        palette.setColor(QPalette.Base, QColor(CROW_EYE_PANEL_RAISED))
        palette.setColor(QPalette.Text, QColor("#F8FAFC"))
        self.setPalette(palette)

        # Set a base QFont so any widget that doesn't have an explicit font in its
        # stylesheet still picks up Segoe UI / Inter.
        base_font = QFont("Segoe UI", 10)
        base_font.setStyleHint(QFont.SansSerif)
        self.setFont(base_font)

        dialog_style = f"""
            QDialog {{
                background-color: {CROW_EYE_BG};
                color: {CROW_EYE_TEXT};
                font-size: 10pt;
                font-family: {CROW_EYE_FONT_FAMILY};
            }}
            QWidget {{
                background-color: {CROW_EYE_BG};
                color: {CROW_EYE_TEXT};
                font-family: {CROW_EYE_FONT_FAMILY};
            }}
            QLabel {{
                color: {CROW_EYE_TEXT};
                font-size: 10pt;
                background: transparent;
                font-family: {CROW_EYE_FONT_FAMILY};
            }}
        """
        # Append the shared themed scrollbar so non-table scroll areas match the app.
        self.setStyleSheet(dialog_style + CrowEyeStyles.SCROLLBAR_STYLE)
    
    def _populate_timeline(self):
        """
        Populate the timeline table with investigation log entries.

        Displays entries in chronological order with all relevant information.
        The full entry dict is stashed on column 0's UserRole so the click-to-
        drill detail pane can read it without re-matching by string.
        """
        # Sorting must be disabled while inserting rows or Qt will shuffle them
        # mid-populate and break the column-0 → entry-dict mapping.
        was_sorting = self.timeline_table.isSortingEnabled()
        self.timeline_table.setSortingEnabled(False)
        self.timeline_table.setRowCount(0)

        if not self.filtered_entries:
            logger.info("No timeline entries to display")
            self._update_entry_count()
            self.timeline_table.setSortingEnabled(was_sorting)
            return

        # Sort entries by timestamp (chronological order)
        sorted_entries = sorted(
            self.filtered_entries,
            key=lambda x: x.get("timestamp", ""),
            reverse=False  # Oldest first
        )

        # Populate table
        for entry in sorted_entries:
            row_position = self.timeline_table.rowCount()
            self.timeline_table.insertRow(row_position)

            # Timestamp
            timestamp_str = entry.get("timestamp", "")
            formatted_timestamp = self._format_timestamp(timestamp_str)
            timestamp_item = QTableWidgetItem(formatted_timestamp)
            timestamp_item.setFont(QFont("Consolas", 9))
            timestamp_item.setData(Qt.UserRole, entry)  # detail pane lookup
            self.timeline_table.setItem(row_position, 0, timestamp_item)
            
            # Query
            query = entry.get("query", "")
            query_item = QTableWidgetItem(query)
            query_item.setToolTip(query)
            self.timeline_table.setItem(row_position, 1, query_item)
            
            # Response Summary
            response_summary = entry.get("response_summary", "")
            response_item = QTableWidgetItem(response_summary)
            response_item.setToolTip(response_summary)
            self.timeline_table.setItem(row_position, 2, response_item)
            
            # Evidence Found
            evidence_found = entry.get("evidence_found", False)
            if evidence_found:
                evidence_item = QTableWidgetItem("FOUND")
                evidence_item.setForeground(QColor("#00FFFF")) # Cyan
                evidence_item.setFont(QFont("", 9, QFont.Bold))
            else:
                evidence_item = QTableWidgetItem("-")
                evidence_item.setForeground(QColor("#6B7280"))
            evidence_item.setTextAlignment(Qt.AlignCenter)
            self.timeline_table.setItem(row_position, 3, evidence_item)
            
            # Artifacts Queried (New Column)
            artifacts = entry.get("artifacts_queried", [])
            art_text = ", ".join(artifacts) if artifacts else "—"
            art_item = QTableWidgetItem(art_text)
            art_item.setFont(QFont("Consolas", 8))
            art_item.setToolTip(art_text)
            self.timeline_table.setItem(row_position, 4, art_item)
            
            # Suggested Next Steps
            suggested_next_steps = entry.get("suggested_next_steps", "")
            steps_item = QTableWidgetItem(suggested_next_steps or "—")
            steps_item.setToolTip(suggested_next_steps)
            self.timeline_table.setItem(row_position, 5, steps_item)
            
            # Set row height
            self.timeline_table.setRowHeight(row_position, 50)
        
        logger.info(f"Populated timeline table with {len(sorted_entries)} entries")
        self._update_entry_count()
        self.timeline_table.setSortingEnabled(was_sorting)
    
    def _format_timestamp(self, timestamp_str: str) -> str:
        """
        Format ISO 8601 timestamp for display.
        
        Args:
            timestamp_str: ISO 8601 timestamp string
            
        Returns:
            Formatted timestamp string (YYYY-MM-DD HH:MM:SS)
        """
        if not timestamp_str:
            return "Unknown"
        
        try:
            # Parse ISO 8601 timestamp
            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            # Format for display
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            logger.warning(f"Error formatting timestamp '{timestamp_str}': {e}")
            return timestamp_str
    
    def _on_filter_changed(self, filter_text: str):
        """
        Handle filter selection change.
        
        Filters timeline entries based on evidence_found status.
        
        Args:
            filter_text: Selected filter text ("All", "Evidence Found", "No Evidence")
            
        """
        logger.info(f"Filter changed to: {filter_text}")
        
        if filter_text == "Evidence Found":
            base = [e for e in self.timeline_entries if e.get("evidence_found")]
        elif filter_text == "No Evidence":
            base = [e for e in self.timeline_entries if not e.get("evidence_found")]
        else:
            base = self.timeline_entries.copy()

        # Apply date-range filter on top of the evidence filter.
        self.filtered_entries = [
            e for e in base
            if self._ts_in_range(e.get("timestamp", ""), self.timeline_from, self.timeline_to)
        ]

        # Repopulate table with filtered entries
        self._populate_timeline()
    
    def _update_entry_count(self):
        """Update the entry count label."""
        total = len(self.timeline_entries)
        filtered = len(self.filtered_entries)
        
        if total == filtered:
            self.entry_count_label.setText(f"Showing {total} entries")
        else:
            self.entry_count_label.setText(f"Showing {filtered} of {total} entries")
    
    def _create_stat_label(self, label: str, count: int) -> QLabel:
        """
        Create a statistics label for the Report Findings tab.
        
        Args:
            label: Label text
            count: Count value
            
        Returns:
            Styled QLabel widget
        """
        stat_label = QLabel(f"{label}: {count}")
        stat_label.setStyleSheet(
            "font-size: 11pt; color: #F8FAFC; background: transparent; font-weight: bold;"
        )
        return stat_label
    
    def _populate_findings_table(self):
        """
        Populate the findings table with report blocks.

        """
        was_sorting = self.findings_table.isSortingEnabled()
        self.findings_table.setSortingEnabled(False)
        self.findings_table.setRowCount(0)

        if not self.filtered_blocks:
            logger.info("No report blocks to display")
            # Explicit empty-state row (mirrors the Queries tab) so the tab never
            # looks broken when the report has no findings yet.
            self.findings_table.insertRow(0)
            empty = QTableWidgetItem(
                "No report findings yet — the Eye documents findings here as it investigates."
            )
            empty.setForeground(QColor(CROW_EYE_TEXT_DIM))
            empty.setTextAlignment(Qt.AlignCenter)
            self.findings_table.setItem(0, 0, empty)
            self.findings_table.setSpan(0, 0, 1, 4)
            if self.detail_pane:
                self.detail_pane.setHtml(
                    f"<div style='color:{CROW_EYE_TEXT_DIM};font-family:{CROW_EYE_FONT_FAMILY};"
                    f"padding:14px;font-size:10pt;'>Report findings will appear here once the Eye "
                    f"investigates and documents results.</div>"
                )
            self.findings_table.setSortingEnabled(was_sorting)
            return

        # Sort blocks by timestamp
        sorted_blocks = sorted(
            self.filtered_blocks,
            key=lambda x: x.metadata.get("timestamp", ""),
            reverse=False
        )
        
        # Populate table
        for block in sorted_blocks:
            row_position = self.findings_table.rowCount()
            self.findings_table.insertRow(row_position)
            
            # Type
            type_item = QTableWidgetItem(block.block_type.capitalize())
            type_item.setFont(QFont("", 10, QFont.Bold))
            self.findings_table.setItem(row_position, 0, type_item)
            
            # Title/Caption
            title_caption = ""
            if hasattr(block, 'title') and block.title:
                title_caption = block.title
            elif hasattr(block, 'caption') and block.caption:
                title_caption = block.caption
            else:
                title_caption = f"{block.block_type.capitalize()} Block"
            
            title_item = QTableWidgetItem(title_caption)
            title_item.setToolTip(title_caption)
            self.findings_table.setItem(row_position, 1, title_item)
            
            # Timestamp
            timestamp_str = block.metadata.get("timestamp", "")
            formatted_timestamp = self._format_timestamp(timestamp_str)
            timestamp_item = QTableWidgetItem(formatted_timestamp)
            timestamp_item.setFont(QFont("Consolas", 9))
            self.findings_table.setItem(row_position, 2, timestamp_item)
            
            # Source Report — try the explicit-source metadata fields first
            # (set by importers), then derive a source from the author the
            # report_engine recorded ("ai" / "user"), so AI-generated blocks
            # like the Triage report no longer surface as "Source not found".
            source_text, source_is_strong = self._resolve_block_source(block)
            source_item = QTableWidgetItem(source_text)
            source_item.setForeground(QColor(CROW_EYE_TEXT if source_is_strong else CROW_EYE_TEXT_DIM))
            source_item.setToolTip(source_text)
            self.findings_table.setItem(row_position, 3, source_item)
            
            # Set row height
            self.findings_table.setRowHeight(row_position, 50)
            
            # Store block reference in row
            self.findings_table.item(row_position, 0).setData(Qt.UserRole, block)
        
        logger.info(f"Populated findings table with {len(sorted_blocks)} blocks")
        self.findings_table.setSortingEnabled(was_sorting)

        # Auto-select the first finding so its content shows in the detail pane
        # immediately (the tab is no longer a blank table on open).
        if self.findings_table.rowCount() > 0:
            self.findings_table.selectRow(0)

    def _resolve_block_source(self, block: ReportBlock):
        """Return (display_text, is_strong_source) for the Source Report column.

        Resolution order:
          1. Explicit source/origin metadata fields (set by importers).
          2. Author = 'ai' → 'Eye AI', enriched with block.category if present
             (e.g. triage blocks tagged 'Automated Triage' show as
             'Eye AI — Automated Triage').
          3. Author = 'user' → 'Investigator'.
          4. Fallback 'Generated in this case (live session)' in dimmed text.

        is_strong_source distinguishes a known origin (rendered in normal text)
        from the generic live-session fallback (rendered dim).
        """
        meta = block.metadata or {}
        explicit = (
            meta.get("source")
            or meta.get("source_report")
            or meta.get("source_file")
            or meta.get("origin")
            or meta.get("imported_from")
        )
        if explicit:
            return explicit, True

        author = (meta.get("author") or "").strip().lower()
        category = (getattr(block, "category", "") or "").strip()
        if author == "ai":
            return (f"Eye AI — {category}" if category else "Eye AI"), True
        if author == "user":
            return "Investigator", True

        return "Generated in this case (live session)", False

    def _make_date_range_controls(self):
        """Create From/To QDateEdit widgets initialized to span the case's
        actual activity. Returns (from_edit, to_edit).

        When the case has no activity yet (or no parseable timestamps), the
        defaults are deliberately wide-open (year 2000 → year 2100) so the
        date filter does NOT silently hide rows the user just imported but
        whose dates fall outside an arbitrary 'last month' window."""
        first_iso, last_iso = self._activity_time_range()
        first_dt = self._parse_iso(first_iso)
        last_dt = self._parse_iso(last_iso)
        default_from = QDate(first_dt.year, first_dt.month, first_dt.day) if first_dt else QDate(2000, 1, 1)
        default_to = QDate(last_dt.year, last_dt.month, last_dt.day) if last_dt else QDate(2100, 12, 31)

        from_edit = QDateEdit(default_from)
        to_edit = QDateEdit(default_to)
        for w in (from_edit, to_edit):
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd")
            # Shared date/time + calendar styling (QDateEdit derives from
            # QDateTimeEdit so DATETIME_STYLE applies).
            w.setStyleSheet(CrowEyeStyles.DATETIME_STYLE)
            try:
                w.calendarWidget().setStyleSheet(CrowEyeStyles.CALENDAR_STYLE)
            except Exception:
                pass
        return from_edit, to_edit

    def _ts_in_range(self, ts_iso: str, from_edit, to_edit) -> bool:
        """True if ts_iso falls within the inclusive [from, to] range of the
        provided date edits. Missing timestamps pass (don't filter out blindly)."""
        if not ts_iso:
            return True
        dt = self._parse_iso(ts_iso)
        if dt is None:
            return True
        d = QDate(dt.year, dt.month, dt.day)
        if from_edit and d < from_edit.date():
            return False
        if to_edit and d > to_edit.date():
            return False
        return True

    def _make_export_button(self, on_export) -> QPushButton:
        """Build a small 'Export ▾' button with a CSV / Markdown menu.
        on_export(format_str) is invoked with 'csv' or 'markdown'."""
        btn = QPushButton("Export ▾")
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {CROW_EYE_PANEL_RAISED};
                color: {CROW_EYE_TEXT};
                border: 1px solid {CROW_EYE_BORDER};
                border-radius: 4px;
                padding: 6px 14px;
                font-family: {CROW_EYE_FONT_FAMILY};
                font-size: 10pt;
                font-weight: 600;
            }}
            QPushButton:hover {{ border-color: {CROW_EYE_ACCENT}; color: {CROW_EYE_ACCENT}; }}
            QPushButton::menu-indicator {{ width: 0; }}
        """)
        menu = QMenu(btn)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {CROW_EYE_PANEL_RAISED};
                border: 1px solid {CROW_EYE_BORDER};
                color: {CROW_EYE_TEXT};
                font-family: {CROW_EYE_FONT_FAMILY};
            }}
            QMenu::item:selected {{ background: {CROW_EYE_BORDER}; color: {CROW_EYE_ACCENT}; }}
        """)
        menu.addAction("CSV (.csv)", lambda: on_export("csv"))
        menu.addAction("Markdown (.md)", lambda: on_export("markdown"))
        btn.setMenu(menu)
        return btn

    def _make_detail_pane(self, placeholder: str) -> QTextBrowser:
        pane = QTextBrowser()
        pane.setMinimumHeight(160)
        pane.setOpenExternalLinks(False)
        pane.setHtml(
            f"<div style='color:{CROW_EYE_TEXT_DIM};font-family:{CROW_EYE_FONT_FAMILY};"
            f"padding:14px;font-size:10pt;'>{placeholder}</div>"
        )
        pane.setStyleSheet(f"""
            QTextBrowser {{
                background: {CROW_EYE_PANEL};
                border: 1px solid {CROW_EYE_BORDER};
                border-radius: 6px;
                color: {CROW_EYE_TEXT};
                padding: 6px;
                font-family: {CROW_EYE_FONT_FAMILY};
                font-size: 10pt;
            }}
            QScrollBar:vertical {{ background: {CROW_EYE_PANEL_RAISED}; width: 12px; border-radius: 6px; }}
            QScrollBar::handle:vertical {{ background: {CROW_EYE_BORDER}; border-radius: 6px; min-height: 20px; }}
        """)
        return pane

    def _on_timeline_row_selected(self):
        """Render full timeline entry detail when a row is selected."""
        if not self.timeline_table:
            return
        items = self.timeline_table.selectedItems()
        if not items:
            return
        row = items[0].row()
        entry_item = self.timeline_table.item(row, 0)
        entry = entry_item.data(Qt.UserRole) if entry_item else None
        if not isinstance(entry, dict):
            return

        query = entry.get("query", "—")
        response_summary = entry.get("response_summary", "")
        artifacts = entry.get("artifacts_queried", []) or []
        next_steps = entry.get("suggested_next_steps", "")
        ts = self._format_timestamp(entry.get("timestamp", ""))
        evidence = "Found" if entry.get("evidence_found") else "Not detected"
        evidence_color = CROW_EYE_ACCENT if entry.get("evidence_found") else CROW_EYE_TEXT_DIM
        query_type = entry.get("query_type", "")

        # Best-effort match to a full assistant response from chat history by
        # locating the user message with this query and taking the next assistant.
        full_response = self._find_assistant_response_for(query)

        html_parts = [
            f"<style>"
            f"body{{font-family:{CROW_EYE_FONT_FAMILY};color:{CROW_EYE_TEXT};font-size:10pt;}}"
            f"h3{{color:{CROW_EYE_ACCENT};margin:0 0 8px 0;font-size:12pt;}}"
            f"h4{{color:{CROW_EYE_TEXT};margin:14px 0 4px 0;font-size:10pt;letter-spacing:0.4px;}}"
            f".meta{{color:{CROW_EYE_TEXT_DIM};font-size:9pt;margin-bottom:6px;}}"
            f".chip{{display:inline-block;padding:2px 8px;border:1px solid {CROW_EYE_BORDER};"
            f"border-radius:10px;margin:2px 4px 2px 0;font-size:9pt;color:{CROW_EYE_TEXT};}}"
            f"pre{{background:{CROW_EYE_PANEL_RAISED};border:1px solid {CROW_EYE_BORDER};"
            f"padding:8px;border-radius:4px;white-space:pre-wrap;font-family:Consolas,monospace;}}"
            f"</style>",
            f"<h3>{self._html_escape(query)}</h3>",
            f"<div class='meta'>{ts}  ·  Evidence: "
            f"<span style='color:{evidence_color}'>{evidence}</span>"
            f"{('  ·  Type: ' + query_type) if query_type else ''}</div>",
        ]
        if response_summary:
            html_parts.append("<h4>Forensic Summary</h4>")
            html_parts.append(f"<div>{self._html_escape(response_summary)}</div>")
        if full_response and full_response.strip() != response_summary.strip():
            html_parts.append("<h4>Full Assistant Response</h4>")
            html_parts.append(f"<pre>{self._html_escape(full_response[:4000])}"
                              f"{'…' if len(full_response) > 4000 else ''}</pre>")
        if artifacts:
            html_parts.append("<h4>Artifacts Queried</h4>")
            html_parts.append("<div>" + "".join(f"<span class='chip'>{self._html_escape(a)}</span>" for a in artifacts) + "</div>")
        if next_steps:
            html_parts.append("<h4>Suggested Next Steps</h4>")
            html_parts.append(f"<div>{self._html_escape(next_steps)}</div>")
        self.timeline_detail.setHtml("".join(html_parts))

    def _on_query_row_selected(self):
        """Render full query + assistant response when a Queries Run row is selected."""
        if not self.queries_table:
            return
        items = self.queries_table.selectedItems()
        if not items:
            return
        row = items[0].row()
        meta_item = self.queries_table.item(row, 0)
        msg = meta_item.data(Qt.UserRole) if meta_item else None
        if not isinstance(msg, dict):
            return

        ts = (msg.get("metadata") or {}).get("timestamp") or msg.get("timestamp") or ""
        content = msg.get("content") or ""
        response = self._find_assistant_response_for(content, exact_msg=msg)
        html = [
            f"<style>"
            f"body{{font-family:{CROW_EYE_FONT_FAMILY};color:{CROW_EYE_TEXT};font-size:10pt;}}"
            f"h3{{color:{CROW_EYE_ACCENT};margin:0 0 6px 0;font-size:12pt;}}"
            f"h4{{color:{CROW_EYE_TEXT};margin:14px 0 4px 0;font-size:10pt;}}"
            f".meta{{color:{CROW_EYE_TEXT_DIM};font-size:9pt;margin-bottom:8px;}}"
            f"pre{{background:{CROW_EYE_PANEL_RAISED};border:1px solid {CROW_EYE_BORDER};"
            f"padding:8px;border-radius:4px;white-space:pre-wrap;font-family:Consolas,monospace;}}"
            f"</style>",
            f"<h3>Investigator Query</h3>",
            f"<div class='meta'>{self._format_timestamp(ts) if ts else '—'}</div>",
            f"<pre>{self._html_escape(content)}</pre>",
        ]
        if response:
            html.append("<h4>Assistant Response</h4>")
            html.append(f"<pre>{self._html_escape(response[:6000])}"
                        f"{'…' if len(response) > 6000 else ''}</pre>")
        else:
            html.append(f"<div class='meta' style='margin-top:10px;'>No assistant reply linked to this query in the loaded history.</div>")
        self.queries_detail.setHtml("".join(html))

    def _find_assistant_response_for(self, query_text: str, exact_msg: Optional[Dict[str, Any]] = None) -> str:
        """Walk conversation_history, locate the user message matching query_text
        (or the exact dict if provided), and return the immediately following
        assistant message content. Returns '' if not found.

        When `exact_msg` is supplied we use identity-only matching — without
        this, a duplicate query string earlier in history would silently win
        over the actual row the user clicked, and the detail pane would show
        the wrong assistant response."""
        if not self.conversation_history:
            return ""
        target_query = (query_text or "").strip()
        for i, m in enumerate(self.conversation_history):
            if exact_msg is not None:
                if m is not exact_msg:
                    continue
            else:
                if m.get("role") != "user" or (m.get("content") or "").strip() != target_query:
                    continue
            # Found the user message — return the next assistant reply before
            # the next user message starts a new turn.
            for j in range(i + 1, len(self.conversation_history)):
                nxt = self.conversation_history[j]
                if nxt.get("role") == "assistant":
                    return nxt.get("content") or ""
                if nxt.get("role") == "user":
                    break
            return ""
        return ""

    def _html_escape(self, s: str) -> str:
        if not s:
            return ""
        return (
            s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace("\"", "&quot;")
        )

    # ── Per-tab export helpers ───────────────────────────────────

    def _export_timeline(self, fmt: str):
        if not self.filtered_entries:
            QMessageBox.information(self, "Export Timeline", "No entries to export with the current filters.")
            return
        path = self._ask_save_path("timeline", fmt)
        if not path:
            return
        try:
            rows = [
                {
                    "Timestamp": e.get("timestamp", ""),
                    "Query": e.get("query", ""),
                    "Forensic Summary": e.get("response_summary", ""),
                    "Evidence Found": "Yes" if e.get("evidence_found") else "No",
                    "Artifacts Queried": ", ".join(e.get("artifacts_queried", []) or []),
                    "Next Steps": e.get("suggested_next_steps", ""),
                }
                for e in self.filtered_entries
            ]
            self._write_rows(path, rows, fmt)
            QMessageBox.information(self, "Export Timeline", f"Wrote {len(rows)} rows to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Timeline", f"Failed: {e}")

    def _export_queries(self, fmt: str):
        if not self.filtered_queries:
            QMessageBox.information(self, "Export Queries", "No queries to export with the current filters.")
            return
        path = self._ask_save_path("queries", fmt)
        if not path:
            return
        try:
            rows = []
            for m in self.filtered_queries:
                ts = (m.get("metadata") or {}).get("timestamp") or m.get("timestamp") or ""
                rows.append({
                    "Timestamp": ts,
                    "Query": (m.get("content") or "").strip(),
                    "Response": self._find_assistant_response_for(m.get("content") or "", exact_msg=m),
                })
            self._write_rows(path, rows, fmt)
            QMessageBox.information(self, "Export Queries", f"Wrote {len(rows)} rows to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Queries", f"Failed: {e}")

    def _export_findings(self, fmt: str):
        if not self.filtered_blocks:
            QMessageBox.information(self, "Export Findings", "No findings to export with the current filters.")
            return
        path = self._ask_save_path("findings", fmt)
        if not path:
            return
        try:
            rows = []
            for b in self.filtered_blocks:
                title = getattr(b, "title", "") or getattr(b, "caption", "") or f"{b.block_type.capitalize()} Block"
                ts = (b.metadata or {}).get("timestamp", "")
                source, _ = self._resolve_block_source(b)
                rows.append({
                    "Type": b.block_type.capitalize(),
                    "Title/Caption": title,
                    "Timestamp": ts,
                    "Source": source,
                })
            self._write_rows(path, rows, fmt)
            QMessageBox.information(self, "Export Findings", f"Wrote {len(rows)} rows to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Findings", f"Failed: {e}")

    def _ask_save_path(self, prefix: str, fmt: str) -> str:
        ext = ".csv" if fmt == "csv" else ".md"
        filt = "CSV (*.csv)" if fmt == "csv" else "Markdown (*.md)"
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export {prefix.title()}",
            f"{prefix}_export{ext}",
            filt,
        )
        if path and not path.lower().endswith(ext):
            path += ext
        return path

    def _write_rows(self, path: str, rows: List[Dict[str, Any]], fmt: str):
        if not rows:
            return
        cols = list(rows[0].keys())
        if fmt == "csv":
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=cols)
                writer.writeheader()
                for r in rows:
                    writer.writerow({k: (v if v is not None else "") for k, v in r.items()})
        else:  # markdown
            lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
            for r in rows:
                safe = [str(r.get(c, "")).replace("|", "\\|").replace("\n", "<br>") for c in cols]
                lines.append("| " + " | ".join(safe) + " |")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

    def _on_findings_filter_changed(self, filter_text: str):
        """
        Handle findings filter selection change.
        
        Args:
            filter_text: Selected filter text
            
        """
        logger.info(f"Findings filter changed to: {filter_text}")
        
        if filter_text == "All":
            self.filtered_blocks = self.report_blocks.copy()
        else:
            # Filter by block type (lowercase for comparison)
            filter_type = filter_text.lower()
            self.filtered_blocks = [
                block for block in self.report_blocks
                if block.block_type == filter_type
            ]
        
        # Repopulate table with filtered blocks
        self._populate_findings_table()
    
    def _on_finding_selected(self):
        """
        Handle finding selection in the findings table.
        
        Displays the selected block content in the detail pane.
        
        """
        selected_items = self.findings_table.selectedItems()
        if not selected_items:
            self.detail_pane.clear()
            return
        
        # Get the block from the first column item
        row = selected_items[0].row()
        type_item = self.findings_table.item(row, 0)
        block = type_item.data(Qt.UserRole)
        
        if not block:
            self.detail_pane.clear()
            return
        
        # Render block content based on type
        self._render_block_detail(block)
    
    def _render_block_detail(self, block: ReportBlock):
        """
        Render block content in the detail pane.
        
        Args:
            block: ReportBlock to render
            
        """
        if isinstance(block, TextBlock):
            # Render markdown content as HTML
            html = f"""
            <html>
            <head>
                <style>
                    body {{ background: #0F172A; color: #E5E7EB; font-family: sans-serif; padding: 10px; }}
                    h1, h2, h3 {{ color: #00FFFF; }}
                    p {{ line-height: 1.6; }}
                </style>
            </head>
            <body>
                <h2>{block.title}</h2>
                <div>{block.markdown_content}</div>
            </body>
            </html>
            """
            self.detail_pane.setHtml(html)
        
        elif isinstance(block, TableBlock):
            # Render table with styling
            rows_html = ""
            for row in block.rows[:10]:  # Limit to first 10 rows for detail pane
                row_html = "<tr>"
                for col in block.columns:
                    value = row.get(col, "")
                    row_html += f"<td>{value}</td>"
                row_html += "</tr>"
                rows_html += row_html
            
            html = f"""
            <html>
            <head>
                <style>
                    body {{ background: #0F172A; color: #E5E7EB; font-family: sans-serif; padding: 10px; }}
                    h3 {{ color: #00FFFF; margin-bottom: 10px; }}
                    table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
                    th, td {{ border: 1px solid #334155; padding: 8px; text-align: left; }}
                    th {{ background: #1E293B; color: #00FFFF; font-weight: bold; }}
                    tr:nth-child(even) {{ background: #1E293B; }}
                    .caption {{ color: #9CA3AF; font-style: italic; margin-bottom: 10px; }}
                </style>
            </head>
            <body>
                <h3>Table: {block.caption}</h3>
                <div class="caption">Showing first 10 rows of {len(block.rows)} total</div>
                <table>
                    <thead>
                        <tr>{''.join(f'<th>{col}</th>' for col in block.columns)}</tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </body>
            </html>
            """
            self.detail_pane.setHtml(html)
        
        elif isinstance(block, ImageBlock):
            # Display image with caption
            html = f"""
            <html>
            <head>
                <style>
                    body {{ background: #0F172A; color: #E5E7EB; font-family: sans-serif; padding: 10px; text-align: center; }}
                    img {{ max-width: 100%; height: auto; border: 2px solid #334155; border-radius: 6px; }}
                    .caption {{ color: #9CA3AF; font-style: italic; margin-top: 10px; }}
                </style>
            </head>
            <body>
                <img src="file:///{block.image_path}" alt="{block.caption}">
                <div class="caption">{block.caption}</div>
            </body>
            </html>
            """
            self.detail_pane.setHtml(html)
        
        else:
            # Generic block display
            html = f"""
            <html>
            <head>
                <style>
                    body {{ background: #0F172A; color: #E5E7EB; font-family: sans-serif; padding: 10px; }}
                    h3 {{ color: #00FFFF; }}
                </style>
            </head>
            <body>
                <h3>{block.block_type.capitalize()} Block</h3>
                <p>Block ID: {block.block_id}</p>
                <p>Timestamp: {block.metadata.get('timestamp', 'Unknown')}</p>
            </body>
            </html>
            """
            self.detail_pane.setHtml(html)
    
    def get_chart_data(self, chart_type: str) -> Dict[str, Any]:
        """
        Get data for a specific chart type.
        
        Args:
            chart_type: One of "activity", "evidence_ratio", "artifact_types"
            
        Returns:
            Chart data dictionary with Chart.js format
            
        Raises:
            ValueError: If chart_type is invalid
            
        """
        if chart_type == "activity":
            # Group entries by date
            date_counts = {}
            for entry in self.timeline_entries:
                timestamp = entry.get("timestamp", "")
                if timestamp:
                    try:
                        date = timestamp.split("T")[0]
                    except:
                        date = "Unknown"
                else:
                    date = "Unknown"
                date_counts[date] = date_counts.get(date, 0) + 1
            
            sorted_dates = sorted([d for d in date_counts.keys() if d != "Unknown"])
            if "Unknown" in date_counts:
                sorted_dates.append("Unknown")
            counts = [date_counts[d] for d in sorted_dates]
            
            return {
                "chart_type": "bar",
                "title": "Investigation Activity Over Time",
                "labels": sorted_dates,
                "datasets": [{
                    "label": "Timeline Entries",
                    "data": counts,
                    "backgroundColor": "#f97316"
                }]
            }
        
        elif chart_type == "evidence_ratio":
            evidence_found = sum(1 for entry in self.timeline_entries if entry.get("evidence_found"))
            no_evidence = len(self.timeline_entries) - evidence_found
            
            return {
                "chart_type": "pie",
                "title": "Evidence Found Ratio",
                "labels": ["Evidence Found", "No Evidence"],
                "datasets": [{
                    "label": "Queries",
                    "data": [evidence_found, no_evidence],
                    "backgroundColor": ["#10b981", "#6b7280"]
                }]
            }
        
        elif chart_type == "artifact_types":
            # Extract artifact types from queries
            artifact_keywords = [
                "prefetch", "mft", "registry", "usn", "browser", 
                "amcache", "shellbags", "lnk", "jumplists", "timeline"
            ]
            
            artifact_counts = Counter()
            for entry in self.timeline_entries:
                query = entry.get("query", "").lower()
                for keyword in artifact_keywords:
                    if keyword in query:
                        artifact_counts[keyword] += 1
            
            # Get top 5
            top_artifacts = artifact_counts.most_common(5)
            if not top_artifacts:
                labels = ["No Data"]
                counts = [0]
            else:
                labels = [artifact.capitalize() for artifact, _ in top_artifacts]
                counts = [count for _, count in top_artifacts]
            
            return {
                "chart_type": "bar",
                "title": "Top 5 Queried Artifact Types",
                "labels": labels,
                "datasets": [{
                    "label": "Query Count",
                    "data": counts,
                    "backgroundColor": "#06b6d4"
                }]
            }
        
        else:
            raise ValueError(f"Invalid chart_type: {chart_type}. Must be one of: activity, evidence_ratio, artifact_types")
    
    def _on_export_summary_clicked(self):
        """
        Handle export summary button click.
        
        Opens file dialog and exports case summary to HTML or PDF format.
        
        """
        try:
            file_path, selected_filter = QFileDialog.getSaveFileName(
                self,
                "Export Case Summary",
                "",
                "HTML Report (*.html);;PDF Report (*.pdf)"
            )
            
            # Handle user cancellation
            if not file_path:
                return
            
            # Export based on selected format
            if selected_filter == "HTML Report (*.html)":
                if not file_path.endswith('.html'):
                    file_path += '.html'
                self._export_html(file_path)
            elif selected_filter == "PDF Report (*.pdf)":
                if not file_path.endswith('.pdf'):
                    file_path += '.pdf'
                self._export_pdf(file_path)
            
            # Show success message
            QMessageBox.information(
                self,
                "Export Successful",
                f"Case summary exported to:\n{file_path}"
            )
            
        except PermissionError:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Permission denied writing to:\n{file_path}\n\n"
                "Please check file permissions or choose a different location."
            )
        except ImportError as e:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Missing required library:\n{str(e)}\n\n"
                "For PDF export, install weasyprint:\n"
                "pip install weasyprint"
            )
        except Exception as e:
            logger.error(f"Export error: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Error exporting summary:\n{str(e)}\n\n"
                "Check the logs for more details."
            )
    
    def _generate_summary_html(self) -> str:
        """
        Generate HTML content for case summary export.
        
        Includes timeline entries, report findings, and charts in a styled format.
        
        Returns:
            Complete HTML document as string
            
        """
        # Generate timeline table HTML
        timeline_rows = ""
        for entry in self.timeline_entries:
            timestamp = self._format_timestamp(entry.get("timestamp", ""))
            query = entry.get("query", "")
            response = entry.get("response_summary", "")
            evidence = "✓ Yes" if entry.get("evidence_found") else "✗ No"
            evidence_color = "#10B981" if entry.get("evidence_found") else "#6B7280"
            next_steps = entry.get("suggested_next_steps", "—")
            
            timeline_rows += f"""
            <tr>
                <td>{timestamp}</td>
                <td>{query}</td>
                <td>{response}</td>
                <td style="color: {evidence_color}; font-weight: bold; text-align: center;">{evidence}</td>
                <td>{next_steps}</td>
            </tr>
            """
        
        # Generate report findings table HTML
        findings_rows = ""
        for block in self.report_blocks:
            block_type = block.block_type.capitalize()
            title_caption = ""
            if hasattr(block, 'title') and block.title:
                title_caption = block.title
            elif hasattr(block, 'caption') and block.caption:
                title_caption = block.caption
            else:
                title_caption = f"{block_type} Block"
            
            timestamp = self._format_timestamp(block.metadata.get("timestamp", ""))
            source, _ = self._resolve_block_source(block)

            findings_rows += f"""
            <tr>
                <td>{block_type}</td>
                <td>{title_caption}</td>
                <td>{timestamp}</td>
                <td>{source}</td>
            </tr>
            """
        
        # Get chart data
        activity_data = self.get_chart_data("activity") if len(self.timeline_entries) >= 3 else None
        evidence_data = self.get_chart_data("evidence_ratio") if len(self.timeline_entries) >= 3 else None
        artifact_data = self.get_chart_data("artifact_types") if len(self.timeline_entries) >= 3 else None
        
        # Generate charts HTML
        charts_html = ""
        if activity_data:
            charts_html += f"""
            <div class="chart-container">
                <canvas id="activityChart"></canvas>
            </div>
            <script>
                new Chart(document.getElementById('activityChart'), {{
                    type: '{activity_data['chart_type']}',
                    data: {{
                        labels: {json.dumps(activity_data['labels'])},
                        datasets: {json.dumps(activity_data['datasets'])}
                    }},
                    options: {{
                        responsive: true,
                        plugins: {{
                            title: {{
                                display: true,
                                text: '{activity_data['title']}',
                                color: '#f97316',
                                font: {{ size: 16 }}
                            }},
                            legend: {{ labels: {{ color: '#e8edf5' }} }}
                        }},
                        scales: {{
                            y: {{ ticks: {{ color: '#8899aa' }}, grid: {{ color: '#1e2a3a' }} }},
                            x: {{ ticks: {{ color: '#8899aa' }}, grid: {{ color: '#1e2a3a' }} }}
                        }}
                    }}
                }});
            </script>
            """
        
        if evidence_data:
            charts_html += f"""
            <div class="chart-container">
                <canvas id="evidenceChart"></canvas>
            </div>
            <script>
                new Chart(document.getElementById('evidenceChart'), {{
                    type: '{evidence_data['chart_type']}',
                    data: {{
                        labels: {json.dumps(evidence_data['labels'])},
                        datasets: {json.dumps(evidence_data['datasets'])}
                    }},
                    options: {{
                        responsive: true,
                        plugins: {{
                            title: {{
                                display: true,
                                text: '{evidence_data['title']}',
                                color: '#f97316',
                                font: {{ size: 16 }}
                            }},
                            legend: {{ labels: {{ color: '#e8edf5' }}, position: 'right' }}
                        }}
                    }}
                }});
            </script>
            """
        
        if artifact_data:
            charts_html += f"""
            <div class="chart-container">
                <canvas id="artifactChart"></canvas>
            </div>
            <script>
                new Chart(document.getElementById('artifactChart'), {{
                    type: '{artifact_data['chart_type']}',
                    data: {{
                        labels: {json.dumps(artifact_data['labels'])},
                        datasets: {json.dumps(artifact_data['datasets'])}
                    }},
                    options: {{
                        responsive: true,
                        plugins: {{
                            title: {{
                                display: true,
                                text: '{artifact_data['title']}',
                                color: '#f97316',
                                font: {{ size: 16 }}
                            }},
                            legend: {{ labels: {{ color: '#e8edf5' }} }}
                        }},
                        scales: {{
                            y: {{ ticks: {{ color: '#8899aa' }}, grid: {{ color: '#1e2a3a' }} }},
                            x: {{ ticks: {{ color: '#8899aa' }}, grid: {{ color: '#1e2a3a' }} }}
                        }}
                    }}
                }});
            </script>
            """
        
        # Generate complete HTML document
        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Case Summary Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            background: #0B1220;
            color: #E5E7EB;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            padding: 40px;
            line-height: 1.6;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        
        h1 {{
            color: #00FFFF;
            font-size: 32pt;
            margin-bottom: 10px;
            text-align: center;
        }}
        
        .subtitle {{
            color: #9CA3AF;
            font-size: 14pt;
            text-align: center;
            margin-bottom: 40px;
        }}
        
        .toc {{
            background: #1E293B;
            border: 2px solid #334155;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 40px;
        }}
        
        .toc h2 {{
            color: #00FFFF;
            font-size: 18pt;
            margin-bottom: 15px;
        }}
        
        .toc ul {{
            list-style: none;
            padding-left: 0;
        }}
        
        .toc li {{
            margin: 8px 0;
        }}
        
        .toc a {{
            color: #06b6d4;
            text-decoration: none;
            font-size: 12pt;
        }}
        
        .toc a:hover {{
            color: #00FFFF;
            text-decoration: underline;
        }}
        
        .section {{
            margin-bottom: 50px;
            page-break-inside: avoid;
        }}
        
        .section h2 {{
            color: #00FFFF;
            font-size: 24pt;
            margin-bottom: 20px;
            border-bottom: 2px solid #334155;
            padding-bottom: 10px;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            background: #1E293B;
            border-radius: 8px;
            overflow: hidden;
            margin-bottom: 20px;
        }}
        
        th {{
            background: #334155;
            color: #00FFFF;
            padding: 12px;
            text-align: left;
            font-weight: bold;
            font-size: 11pt;
        }}
        
        td {{
            padding: 12px;
            border-bottom: 1px solid #334155;
            font-size: 10pt;
        }}
        
        tr:last-child td {{
            border-bottom: none;
        }}
        
        tr:nth-child(even) {{
            background: #0F172A;
        }}
        
        .chart-container {{
            background: #1E293B;
            border: 2px solid #334155;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 30px;
            height: 400px;
        }}
        
        .stats {{
            display: flex;
            justify-content: space-around;
            background: #1E293B;
            border: 2px solid #334155;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
        }}
        
        .stat-item {{
            text-align: center;
        }}
        
        .stat-label {{
            color: #9CA3AF;
            font-size: 10pt;
            margin-bottom: 5px;
        }}
        
        .stat-value {{
            color: #00FFFF;
            font-size: 24pt;
            font-weight: bold;
        }}
        
        .footer {{
            text-align: center;
            color: #6B7280;
            font-size: 9pt;
            margin-top: 50px;
            padding-top: 20px;
            border-top: 1px solid #334155;
        }}
        
        @media print {{
            body {{
                background: white;
                color: black;
            }}
            
            .section {{
                page-break-inside: avoid;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Case Summary Report</h1>
        <div class="subtitle">
            Generated on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        </div>
        
        <!-- Table of Contents -->
        <div class="toc">
            <h2>Table of Contents</h2>
            <ul>
                <li><a href="#timeline">Investigation Timeline</a></li>
                <li><a href="#findings">Report Findings</a></li>
                <li><a href="#charts">Analysis Charts</a></li>
            </ul>
        </div>
        
        <!-- Investigation Timeline Section -->
        <div class="section" id="timeline">
            <h2>Investigation Timeline</h2>
            <p style="color: #9CA3AF; margin-bottom: 15px;">
                Total entries: {len(self.timeline_entries)}
            </p>
            <table>
                <thead>
                    <tr>
                        <th>Timestamp</th>
                        <th>Query</th>
                        <th>Response Summary</th>
                        <th>Evidence</th>
                        <th>Next Steps</th>
                    </tr>
                </thead>
                <tbody>
                    {timeline_rows}
                </tbody>
            </table>
        </div>
        
        <!-- Report Findings Section -->
        <div class="section" id="findings">
            <h2>Report Findings</h2>
            
            <div class="stats">
                <div class="stat-item">
                    <div class="stat-label">Total Blocks</div>
                    <div class="stat-value">{len(self.report_blocks)}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Text Blocks</div>
                    <div class="stat-value">{len([b for b in self.report_blocks if b.block_type == "text"])}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Table Blocks</div>
                    <div class="stat-value">{len([b for b in self.report_blocks if b.block_type == "table"])}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Image Blocks</div>
                    <div class="stat-value">{len([b for b in self.report_blocks if b.block_type == "image"])}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Chart Blocks</div>
                    <div class="stat-value">{len([b for b in self.report_blocks if b.block_type == "chart"])}</div>
                </div>
            </div>
            
            <table>
                <thead>
                    <tr>
                        <th>Type</th>
                        <th>Title/Caption</th>
                        <th>Timestamp</th>
                        <th>Source Report</th>
                    </tr>
                </thead>
                <tbody>
                    {findings_rows}
                </tbody>
            </table>
        </div>
        
        <!-- Charts Section -->
        <div class="section" id="charts">
            <h2>Analysis Charts</h2>
            {charts_html if charts_html else '<p style="color: #9CA3AF;">Insufficient data for visualization (minimum 3 entries required)</p>'}
        </div>
        
        <div class="footer">
            EYE AI Forensic Assistant - Case Summary Report
        </div>
    </div>
</body>
</html>
        """
        
        return html
    
    def _export_html(self, file_path: str):
        """
        Export case summary as HTML file.
        
        Args:
            file_path: Output file path
            
        Raises:
            IOError: If file cannot be written
            PermissionError: If file permissions are insufficient
            
        """
        try:
            html_content = self._generate_summary_html()
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            logger.info(f"Exported case summary to HTML: {file_path}")
        except PermissionError:
            logger.error(f"Permission denied writing to: {file_path}")
            raise
        except IOError as e:
            logger.error(f"IO error writing to {file_path}: {e}")
            raise
    
    def _export_pdf(self, file_path: str):
        """
        Export case summary as PDF file using weasyprint.
        
        Args:
            file_path: Output file path
            
        Raises:
            ImportError: If weasyprint is not installed
            IOError: If file cannot be written
            PermissionError: If file permissions are insufficient
            
        """
        try:
            from weasyprint import HTML
        except ImportError:
            logger.error("weasyprint not installed")
            raise ImportError(
                "weasyprint is required for PDF export. "
                "Install with: pip install weasyprint"
            )
        
        try:
            html_content = self._generate_summary_html()
            HTML(string=html_content).write_pdf(file_path)
            logger.info(f"Exported case summary to PDF: {file_path}")
        except PermissionError:
            logger.error(f"Permission denied writing to: {file_path}")
            raise
        except IOError as e:
            logger.error(f"IO error writing to {file_path}: {e}")
            raise
