"""Issues tab — displays the structured diagnostics from a pipeline run.

Pulls together everything the executor surfaces about silent drops, rule
problems, schema-detection failures, and parse-failure rates into a single
QTreeWidget. The log panel shows a condensed version (first 5 entries per
group); this tab shows the full lists with each issue as its own row.

Data sources read from the execution summary dict:
  * summary['errors'] — fatal-ish errors collected during execution
  * summary['warnings'] — non-fatal warnings (per-wing prefix folded in)
  * summary['rule_diagnostics'] — pre-flight rule validation issues
  * summary['evidence_accounting'] — silent DB fallbacks, schema-detection
    errors, identity-grouping errors, timestamp parse-failure rates

The grouped-lines formatter `format_evidence_accounting_for_panel` in
`pipeline/rule_preflight.py` is the single source of truth for what each
finding looks like; this widget consumes its output.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush, QColor, QFont, QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


def _severity_for_group(group_name: str) -> str:
    """Return a severity keyword ('error' / 'warning' / 'info') for a
    top-level group. Used to pick the matching Qt standardIcon."""
    lower = group_name.lower()
    if "error" in lower:
        return "error"
    if any(tok in lower for tok in ("warning", "fallback", "failure", "diagnostic")):
        return "warning"
    return "info"


def _icon_for_severity(severity: str, widget: QWidget) -> QIcon:
    """Map a severity keyword to a Crow-Eye custom icon. The `widget`
    arg is kept for API compatibility but no longer used (the icon set
    is brand-themed, not style-derived)."""
    from .crow_eye_icons import CrowEyeIcons

    if severity == "error":
        return CrowEyeIcons.error()
    if severity == "warning":
        return CrowEyeIcons.warning()
    return CrowEyeIcons.info()

# The site look (ui/site_theme.py): the panel, tree and button come from the
# window sheet; severity colours are the site's meaning colours, so the tree
# matches status colours everywhere else in the engine.
from ui.site_theme import STATUS_COLORS, set_status, set_variant

_COLOR_ERROR = QColor(STATUS_COLORS["bad"])
_COLOR_WARNING = QColor(STATUS_COLORS["warn"])
_COLOR_INFO = QColor(STATUS_COLORS["neutral"])
_COLOR_HEADER = QColor("#E2E8F0")


class IssuesTab(QWidget):
    """Tree view of all issues collected during a pipeline run.

    `populate(summary)` is idempotent — it clears the tree and re-renders
    from scratch, so calling it on every wing-completion or final-summary
    event is safe."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._total_count = 0
        self._init_ui()

    @property
    def total_count(self) -> int:
        """Number of individual issue entries currently displayed.
        Used by the containing widget to set the tab-title badge."""
        return self._total_count

    def _init_ui(self):
        # Outer container styled as a Crow-Eye GroupBox so the panel
        # chrome (border, title, padding) matches other diagnostic
        # panels elsewhere in the app.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        container = QGroupBox("Pipeline Issues")
        outer.addWidget(container, 1)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(8)

        # Header row: summary label on the left, "Copy" button on the right.
        # Copy dumps the rendered tree as plain text so analysts can paste
        # into incident-report templates.
        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        self._summary_label = QLabel("No issues — pipeline ran cleanly.")
        set_status(self._summary_label, "neutral")
        header_row.addWidget(self._summary_label, 1)

        self._copy_button = QPushButton("Copy")
        self._copy_button.setToolTip("Copy all issues to clipboard as plain text")
        set_variant(self._copy_button, "ghost")
        self._copy_button.setMaximumWidth(120)
        self._copy_button.clicked.connect(self._copy_to_clipboard)
        # Disabled by default; populate() flips it on when there's anything
        # worth copying.
        self._copy_button.setEnabled(False)
        header_row.addWidget(self._copy_button)
        layout.addLayout(header_row)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Issue", "Detail"])
        self._tree.setColumnWidth(0, 280)
        self._tree.setAlternatingRowColors(True)
        # The tree takes the window's site sheet, like every other tree.
        layout.addWidget(self._tree, 1)

    def _copy_to_clipboard(self):
        """Render the current tree contents as plain text and copy to the
        system clipboard. Format: one section per group, indented children.
        Reads from the tree itself (not the source summary) so what the
        user sees is exactly what they get."""
        lines: List[str] = []
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            lines.append(top.text(0))
            for j in range(top.childCount()):
                child = top.child(j)
                lines.append(f" {child.text(0)}")
            lines.append("") # blank line between groups
        text = "\n".join(lines).rstrip()
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)

    def populate(self, summary: Dict[str, Any]) -> int:
        """Re-render the tree from a fresh summary dict. Returns the total
        number of issue entries displayed (so the caller can update the
        tab title badge)."""
        self._tree.clear()
        groups = self._build_groups(summary or {})

        total = 0
        for group_name, entries in groups:
            if not entries:
                continue
            total += len(entries)
            severity = _severity_for_group(group_name)
            color = _COLOR_ERROR if severity == "error" else _COLOR_WARNING
            top = QTreeWidgetItem(
                self._tree,
                [f"{group_name} ({len(entries)})", ""],
            )
            # Severity is conveyed by an icon on the row (theme-aware via
            # Qt's standardIcon set) plus the foreground color — no
            # emoji in the row text.
            top.setIcon(0, _icon_for_severity(severity, self))
            top.setForeground(0, QBrush(color))
            top_font = top.font(0)
            top_font.setBold(True)
            top.setFont(0, top_font)
            for entry in entries:
                child = QTreeWidgetItem(top, [entry, ""])
                child.setForeground(0, QBrush(_COLOR_HEADER))
            top.setExpanded(True)

        # Enable the Copy button only when there's something to copy.
        self._copy_button.setEnabled(total > 0)
        self._total_count = total
        if total == 0:
            self._summary_label.setText("No issues — pipeline ran cleanly.")
            set_status(self._summary_label, "neutral")
        else:
            self._summary_label.setText(
                f"{total} issue(s) across {sum(1 for _, e in groups if e)} category(ies). "
                "Expand each group for details."
            )
            set_status(self._summary_label, "warn")
        return total

    @staticmethod
    def _build_groups(summary: Dict[str, Any]) -> List[Tuple[str, List[str]]]:
        """Assemble (heading, entries) tuples preserving display order.

        Reuses the formatter from rule_preflight so the Issues tab and the
        execution log show the exact same finding text. Adds two
        Issues-tab-only groups (Errors, Warnings) that the log already
        displays inline; here they're surfaced in the structured tree."""
        from ..pipeline.rule_preflight import (
            format_evidence_accounting_for_panel,
            format_issues_for_log,
        )

        groups: List[Tuple[str, List[str]]] = []

        errors = summary.get('errors') or []
        if errors:
            groups.append(("Errors", [str(e) for e in errors]))

        warnings = summary.get('warnings') or []
        # The log already shows the [Evidence accounting] warning line; we
        # don't strip it here because the analyst may want to see exactly
        # what reached summary['warnings'].
        if warnings:
            groups.append(("Warnings", [str(w) for w in warnings]))

        rule_diags = summary.get('rule_diagnostics') or []
        if rule_diags:
            # rule_diagnostics is a list of dicts; format each as a line.
            lines = []
            for d in rule_diags:
                wing = d.get('wing', '?')
                rule_id = d.get('rule_id', '?')
                kind = d.get('kind', '?')
                detail = d.get('detail', '?')
                lines.append(f"[{wing} / {rule_id}] {kind}: {detail}")
            groups.append(("Rule pre-flight diagnostics", lines))

        ea_groups = format_evidence_accounting_for_panel(summary.get('evidence_accounting') or {})
        for heading, lines in ea_groups.items():
            groups.append((heading, lines))

        return groups
