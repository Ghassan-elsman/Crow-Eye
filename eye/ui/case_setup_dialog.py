"""
Case context dialogs for the Eye, the Crow-Eye forensic assistant

This module provides dialogs for case context management:
- CaseSetupDialog: First-time case context initialization
- CaseContextEditDialog: Edit existing case context

The dialogs prompt investigators to enter case-specific information including:
- Investigation Reason (required)
- Primary Suspects (optional)
- Investigation Objectives (optional)
- Expected Evidence Types (optional)

Both share one layout (_CaseContextForm): a header with the Eye's mark, numbered
field cards in two columns that size on their own (no scrolling), Required /
Optional chips, artifact quick-pick pills for the evidence types, and a footer
whose main button waits for the one required field.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QMessageBox, QWidget, QGridLayout, QFrame
)
from PyQt5.QtCore import Qt, QSize, pyqtSignal


class _CaseContextForm:
    """The layout and field behaviour both case context dialogs share."""

    # Quick picks for "Expected evidence types": the artifact families Crow-Eye
    # parses, with the same icons as the main window's buttons and tabs.
    EVIDENCE_PICKS = (
        ("Prefetch", "prefetch"), ("Registry", "registry"), ("Event Logs", "event_logs"),
        ("Browser History", "browser"), ("LNK & Jump Lists", "lnk_jumplists"), ("MFT & USN", "mftusn"),
        ("Amcache", "amcache"), ("ShimCache", "shimcache"), ("SRUM", "srum"),
        ("Recycle Bin", "recycle_bin"), ("USB Devices", "disks"), ("Accounts", "accounts"),
    )

    def _build_form(self, window_title, title_text, subtitle_text, primary_text, on_primary,
                    ready_text, extra_cards=()):
        """Header, the four field cards (plus any ``extra_cards`` under the right
        column) and the footer. Returns the primary button."""
        from ui.app_theme import set_role, set_variant, keep_style
        self.setWindowTitle(window_title)
        self.setMinimumSize(960, 680)
        self.resize(1040, 760 if extra_cards else 720)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(18)
        main_layout.setContentsMargins(32, 28, 32, 24)

        # Header: the Eye's mark beside the title
        header = QHBoxLayout()
        header.setSpacing(16)
        mark = QLabel()
        mark.setFixedSize(56, 56)
        mark.setAlignment(Qt.AlignCenter)
        try:
            import os as _os
            import sys as _sys
            from PyQt5.QtGui import QPixmap
            from styles import CrowEyeStyles
            _res = getattr(_sys, "_MEIPASS", None) or _os.path.dirname(_os.path.dirname(_os.path.dirname(
                _os.path.abspath(__file__))))
            pix = QPixmap(_os.path.join(_res, "GUI Resources", "the Eye AI agent transparent.png"))
            if not pix.isNull():
                pix = CrowEyeStyles._trim_transparent(pix).scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                mark.setPixmap(pix)
        except Exception:
            pass
        mark.setStyleSheet("QLabel { background: rgba(99, 102, 241, 0.12); border: 3px solid #323475;"
                           " border-radius: 16px; }")
        keep_style(mark)
        header.addWidget(mark, 0, Qt.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        title = QLabel(title_text)
        set_role(title, "title")
        titles.addWidget(title)
        subtitle = QLabel(subtitle_text)
        subtitle.setWordWrap(True)
        set_role(subtitle, "muted")
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        main_layout.addLayout(header)

        # The four fields
        self.investigation_reason_input = QTextEdit()
        self.investigation_reason_input.setPlaceholderText(
            "e.g. Suspected data exfiltration by an insider\n"
            "e.g. Malware infection: reconstruct the timeline\n"
            "e.g. Unauthorized access to financial systems")
        self.investigation_reason_input.setMinimumHeight(118)
        self.primary_suspects_input = QLineEdit()
        self.primary_suspects_input.setPlaceholderText("e.g. John Doe, Jane Smith, External IP 192.168.1.100")
        self.investigation_objectives_input = QTextEdit()
        self.investigation_objectives_input.setPlaceholderText(
            "One per line, e.g.\n- Identify every file the suspect accessed\n"
            "- Determine the timeline of the activity\n- Find evidence of exfiltration")
        self.investigation_objectives_input.setMinimumHeight(118)
        self.expected_evidence_types_input = QLineEdit()
        self.expected_evidence_types_input.setPlaceholderText("Pick below or type, comma-separated")

        # two columns that size on their own: the free-text cards on the left,
        # the short suspects field and the evidence picks on the right
        columns = QHBoxLayout()
        columns.setSpacing(16)
        left, right = QVBoxLayout(), QVBoxLayout()
        left.setSpacing(16)
        right.setSpacing(16)
        left.addWidget(self._card(1, "Investigation reason", "required",
                                  "The primary objective or question driving this investigation.",
                                  self.investigation_reason_input), 1)
        left.addWidget(self._card(3, "Investigation objectives", "optional",
                                  "What you need to establish, one per line.",
                                  self.investigation_objectives_input), 1)
        right.addWidget(self._card(2, "Primary suspects", "optional",
                                   "People, accounts, hosts or addresses under investigation, comma-separated.",
                                   self.primary_suspects_input))
        right.addWidget(self._card(4, "Expected evidence types", "optional",
                                   "The artifacts you expect to matter. The Eye looks at these first.",
                                   self.expected_evidence_types_input, self._evidence_picks()), 1)
        for card in extra_cards:
            right.addWidget(card)
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        main_layout.addLayout(columns, 1)

        # Footer: what the main button is waiting for, then the two buttons
        footer = QHBoxLayout()
        footer.setSpacing(12)
        self._ready_text = ready_text
        self._start_hint = QLabel()
        set_role(self._start_hint, "muted")
        footer.addWidget(self._start_hint, 1)
        self.cancel_button = QPushButton("Cancel")
        set_variant(self.cancel_button, "ghost")
        self.cancel_button.setMinimumWidth(140)
        self.cancel_button.clicked.connect(self._on_cancel)
        footer.addWidget(self.cancel_button)
        primary = QPushButton(primary_text)
        set_variant(primary, "primary")
        primary.setMinimumWidth(200)
        primary.setDefault(True)
        primary.clicked.connect(on_primary)
        footer.addWidget(primary)
        main_layout.addLayout(footer)
        self._primary_button = primary

        self.investigation_reason_input.textChanged.connect(self._update_start)
        self.expected_evidence_types_input.textEdited.connect(self._sync_picks_from_text)
        return primary

    def _card(self, number, title, need, help_text, field, extra=None):
        """One numbered field card: badge, title, a Required / Optional / Read-only
        chip, help, field."""
        from ui.app_theme import set_role, set_card, keep_style
        card = QFrame()
        set_card(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 18)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(10)
        badge = QLabel(str(number))
        badge.setFixedSize(30, 30)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet("QLabel { background: rgba(99, 102, 241, 0.16); color: #A5B4FC; border: 3px solid #323475;"
                            " border-radius: 15px; font-weight: 800; font-size: 13px; }")
        keep_style(badge)
        head.addWidget(badge)
        name = QLabel(title)
        set_role(name, "subtitle")
        head.addWidget(name)
        head.addStretch(1)
        chip = QLabel({"required": "Required", "optional": "Optional", "readonly": "Kept by the Eye"}[need])
        if need == "required":
            chip.setStyleSheet("QLabel { color: #A5B4FC; background: rgba(99, 102, 241, 0.14);"
                               " border: 3px solid #323475; border-radius: 10px; padding: 1px 9px;"
                               " font-size: 11px; font-weight: 700; }")
        else:
            chip.setStyleSheet("QLabel { color: #94A3B8; background: transparent;"
                               " border: 3px solid #2C2D31; border-radius: 10px; padding: 1px 9px;"
                               " font-size: 11px; font-weight: 600; }")
        keep_style(chip)
        head.addWidget(chip)
        lay.addLayout(head)
        hint = QLabel(help_text)
        hint.setWordWrap(True)
        set_role(hint, "muted")
        lay.addWidget(hint)
        lay.addWidget(field, 1 if isinstance(field, QTextEdit) else 0)
        if extra is not None:
            lay.addWidget(extra)
        if not isinstance(field, QTextEdit):
            lay.addStretch(1)
        return card

    def _evidence_picks(self):
        """Checkable artifact pills that fill the evidence field; typed entries are kept."""
        from ui.app_theme import set_variant
        try:
            from ui.artifact_icons import artifact_icon, ON_DARK
        except Exception:
            artifact_icon = None
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        self._evidence_pills = []
        for i, (label, drawing) in enumerate(self.EVIDENCE_PICKS):
            # '&' marks a keyboard mnemonic on a button: shown doubled, the real
            # name kept as a property
            pill = QPushButton(label.replace("&", "&&"))
            pill.setProperty("evidence", label)
            pill.setCheckable(True)
            set_variant(pill, "pill")
            if artifact_icon is not None:
                icon = artifact_icon(drawing, ON_DARK)
                if icon is not None:
                    pill.setIcon(icon)
                    pill.setIconSize(QSize(14, 14))
            pill.toggled.connect(self._sync_text_from_picks)
            grid.addWidget(pill, i // 3, i % 3)
            self._evidence_pills.append(pill)
        return box

    def _typed_evidence(self):
        names = {p.property("evidence").lower() for p in self._evidence_pills}
        return [x.strip() for x in self.expected_evidence_types_input.text().split(",")
                if x.strip() and x.strip().lower() not in names]

    def _sync_text_from_picks(self, _checked=False):
        """Picked pills, in their order, then anything typed that is not a pill."""
        if getattr(self, "_syncing", False):
            return
        picked = [p.property("evidence") for p in self._evidence_pills if p.isChecked()]
        self._syncing = True
        try:
            self.expected_evidence_types_input.setText(", ".join(picked + self._typed_evidence()))
        finally:
            self._syncing = False

    def _sync_picks_from_text(self, text):
        """Typing a pill's name ticks it; removing it unticks it."""
        if getattr(self, "_syncing", False):
            return
        typed = {x.strip().lower() for x in text.split(",") if x.strip()}
        self._syncing = True
        try:
            for p in self._evidence_pills:
                p.setChecked(p.property("evidence").lower() in typed)
        finally:
            self._syncing = False

    def _update_start(self):
        """The main button waits for the investigation reason; the footer says so."""
        ready = bool(self.investigation_reason_input.toPlainText().strip())
        self._primary_button.setEnabled(ready)
        self._start_hint.setText(self._ready_text if ready else "Add the investigation reason to continue.")

    def _apply_styling(self):
        """The site look (ui/app_theme.py): one sheet, roles for every part."""
        try:
            from ui.app_theme import apply_theme
            apply_theme(self)
        except Exception:
            pass

    def _validate_inputs(self) -> bool:
        """The Investigation Reason is required (the main button also waits for it)."""
        if not self.investigation_reason_input.toPlainText().strip():
            QMessageBox.warning(
                self,
                "Required Field Missing",
                "Investigation Reason is required.\n\n"
                "Please describe the primary objective or question driving this investigation."
            )
            self.investigation_reason_input.setFocus()
            return False
        return True

    def _parse_comma_separated(self, text: str) -> str:
        """Comma-separated input, trimmed, empty entries dropped."""
        if not text.strip():
            return ""
        return ", ".join(item.strip() for item in text.split(",") if item.strip())

    def _parse_line_separated(self, text: str) -> str:
        """Line-separated input, trimmed, empty lines dropped."""
        if not text.strip():
            return ""
        return "\n".join(line.strip() for line in text.split("\n") if line.strip())

    def showEvent(self, event):
        """Force layout refresh on show."""
        super().showEvent(event)
        self.updateGeometry()
        if self.layout():
            self.layout().activate()


class CaseSetupDialog(_CaseContextForm, QDialog):
    """
    Dialog for first-time case context initialization.

    Prompts investigators to enter case-specific information that will be used
    to tailor the Eye's responses to the investigation objectives. The Investigation
    Reason field is required, while other fields are optional.
    """

    case_context_initialized = pyqtSignal(dict)  # Emits case context on completion

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self.case_context = {
            "investigation_reason": "",
            "primary_suspects": "",
            "investigation_objectives": "",
            "expected_evidence_types": ""
        }
        self._init_ui()
        self._apply_styling()

    def _init_ui(self):
        self.start_button = self._build_form(
            "Case Setup - Eye", "Initialize Case Context",
            "Tell the Eye what this investigation is about. It uses this to focus its "
            "searches, questions and reports on your case objectives.",
            "Start Investigation", self._on_start_investigation,
            "Ready. The other fields are optional and can be edited later.")
        self._update_start()

    def _on_start_investigation(self):
        """Validate, collect the case context and emit it."""
        if not self._validate_inputs():
            return
        self.case_context["investigation_reason"] = self.investigation_reason_input.toPlainText().strip()
        self.case_context["primary_suspects"] = self._parse_comma_separated(self.primary_suspects_input.text())
        self.case_context["investigation_objectives"] = self._parse_line_separated(
            self.investigation_objectives_input.toPlainText())
        self.case_context["expected_evidence_types"] = self._parse_comma_separated(
            self.expected_evidence_types_input.text())
        self.case_context_initialized.emit(self.case_context)
        self.accept()

    def _on_cancel(self):
        """Ask first: without a context the Eye cannot focus on the case."""
        reply = QMessageBox.question(
            self,
            "Cancel Case Setup",
            "Are you sure you want to cancel case setup?\n\n"
            "The Eye will not be able to give case-specific help without this information.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.reject()

    def get_case_context(self) -> dict:
        """The collected case context (investigation_reason, primary_suspects,
        investigation_objectives, expected_evidence_types)."""
        return self.case_context


class CaseContextEditDialog(_CaseContextForm, QDialog):
    """
    Dialog for editing existing case context.

    The same cards as CaseSetupDialog, filled from the current context, plus the
    case variables the Eye keeps during the investigation (read-only here, and
    preserved on save).
    """

    case_context_updated = pyqtSignal(dict)  # Emits updated case context

    def __init__(self, current_context: dict, parent=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self.current_context = current_context or {}
        self.updated_context = {}
        self._init_ui()
        self._apply_styling()
        self._populate_fields()

    def _init_ui(self):
        from ui.app_theme import set_role
        self.case_variables_display = QTextEdit()
        self.case_variables_display.setReadOnly(True)
        self.case_variables_display.setPlaceholderText("No case variables set")
        self.case_variables_display.setFixedHeight(92)
        set_role(self.case_variables_display, "mono")
        variables = self._card(5, "Case variables", "readonly",
                               "Values the Eye records while it investigates. Saving keeps them as they are.",
                               self.case_variables_display)
        self.save_button = self._build_form(
            "Edit Case Context - Eye", "Edit Case Context",
            "Update what the Eye knows about this investigation. Changes apply to its next answers.",
            "Save Changes", self._on_save_changes,
            "Ready to save.", extra_cards=(variables,))

    def _populate_fields(self):
        """Fill the cards from the current case context."""
        self.investigation_reason_input.setPlainText(self.current_context.get("investigation_reason", ""))
        self.primary_suspects_input.setText(self.current_context.get("primary_suspects", ""))
        self.investigation_objectives_input.setPlainText(self.current_context.get("investigation_objectives", ""))
        evidence = self.current_context.get("expected_evidence_types", "")
        self.expected_evidence_types_input.setText(evidence)
        self._sync_picks_from_text(evidence)
        case_variables = self.current_context.get("case_variables", {})
        if case_variables:
            self.case_variables_display.setPlainText(
                "\n".join(f"{key}: {value}" for key, value in case_variables.items()))
        else:
            self.case_variables_display.setPlainText("No case variables set")
        self._update_start()

    def _on_save_changes(self):
        """Validate, collect the updated context (case variables kept) and emit it."""
        if not self._validate_inputs():
            return
        self.updated_context = {
            "investigation_reason": self.investigation_reason_input.toPlainText().strip(),
            "primary_suspects": self._parse_comma_separated(self.primary_suspects_input.text()),
            "investigation_objectives": self._parse_line_separated(
                self.investigation_objectives_input.toPlainText()),
            "expected_evidence_types": self._parse_comma_separated(self.expected_evidence_types_input.text()),
            # Preserve case variables (not editable in this dialog)
            "case_variables": self.current_context.get("case_variables", {})
        }
        self.case_context_updated.emit(self.updated_context)
        self.accept()

    def _on_cancel(self):
        """Ask first: unsaved changes are lost."""
        reply = QMessageBox.question(
            self,
            "Cancel Changes",
            "Are you sure you want to cancel?\n\n"
            "Any changes you made will be lost.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.reject()

    def get_updated_context(self) -> dict:
        """The updated case context (the four fields and case_variables)."""
        return self.updated_context
