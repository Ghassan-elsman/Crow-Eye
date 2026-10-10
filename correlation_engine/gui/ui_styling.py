"""
Styling for the Correlation Engine - the website's look (ui/site_theme.py).

The engine used to carry its own palette three times over (this module's
sheets, crow_eye_styles.qss, and per-widget strings in every view), with three
greens, two cyans and nine different tab bars. Now every engine window takes
the ONE site sheet (begin_site_theme / apply_site_theme) plus the few rules of
its own below (ENGINE_EXTRA), and colour that carries meaning - scores,
severities, statuses - comes from the site's meaning colours.

Kept here: the colour names other modules read (SCORE_*, MATCHED_*, TEXT_*),
the icon painters, and the two helpers other windows call
(apply_progress_dialog_style, apply_evidence_detail_styling), now thin
wrappers over the site theme.
"""

from PyQt5.QtWidgets import QPushButton
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor

try:
    from ui import site_theme as _site
except Exception:                                         # pragma: no cover
    _site = None

_S = getattr(_site, "SCORE_COLORS", {"high": "#4ADE80", "medium": "#FBBF24",
                                     "low": "#FDA4AF", "none": "#64748B"})
_M = getattr(_site, "STATUS_COLORS", {"ok": "#4ADE80", "warn": "#FBBF24", "bad": "#FDA4AF",
                                      "info": "#22D3EE", "accent": "#A5B4FC",
                                      "neutral": "#94A3B8"})


def engine_extra():
    """The engine's own rules, added to the site sheet once per window.

    * Result trees: the branch guide-lines and chevrons (CrowEyeIcons SVGs),
      once here instead of one sheet per tree.
    * Result trees and tables are dense views: 12px, not the site's 13px.
    """
    try:
        from correlation_engine.gui.crow_eye_icons import CrowEyeIcons
        vline = CrowEyeIcons.icon_path("branch_vline")
        more = CrowEyeIcons.icon_path("branch_more")
        end = CrowEyeIcons.icon_path("branch_end")
        closed = CrowEyeIcons.icon_path("branch_closed")
        opened = CrowEyeIcons.icon_path("branch_open")
    except Exception:
        return ""
    return """
QTreeWidget, QTableWidget, QTreeView, QTableView { font-size: 12px; }
QTreeWidget::item { min-height: 24px; }
QTreeWidget::branch { background: transparent; }
QTreeWidget::branch:has-siblings:!adjoins-item { border-image: url(%(vline)s) 0; }
QTreeWidget::branch:has-siblings:adjoins-item { border-image: url(%(more)s) 0; }
QTreeWidget::branch:!has-children:!has-siblings:adjoins-item { border-image: url(%(end)s) 0; }
QTreeWidget::branch:has-children:!has-siblings:closed,
QTreeWidget::branch:closed:has-children:has-siblings { border-image: none; image: url(%(closed)s); }
QTreeWidget::branch:open:has-children:!has-siblings,
QTreeWidget::branch:open:has-children:has-siblings { border-image: none; image: url(%(opened)s); }
""" % dict(vline=vline, more=more, end=end, closed=closed, opened=opened)


class CorrelationEngineStyles:
    """Colour names and helpers for the Correlation Engine, on site tokens."""

    # Score interpretation (meaning colours, site tones)
    SCORE_CONFIRMED = _S["high"]
    SCORE_PROBABLE = _S["medium"]
    SCORE_WEAK = _S["low"]
    SCORE_INSUFFICIENT = _S["none"]
    SCORE_DEFAULT = _M["accent"]

    # Behind a score / matched row: dark tints, readable under light text.
    # (The old light pastels - #E8F5E9 - made matched rows unreadable.)
    SCORE_CONFIRMED_BG = "#12301F"
    SCORE_PROBABLE_BG = "#33270B"
    SCORE_WEAK_BG = "#3A1520"
    SCORE_INSUFFICIENT_BG = "#1E293B"

    MATCHED_COLOR = _M["ok"]
    MATCHED_BG = "#12301F"
    UNMATCHED_COLOR = "#64748B"

    TEXT_PRIMARY = "#E2E8F0"
    TEXT_SECONDARY = "#94A3B8"
    TEXT_MUTED = "#64748B"
    TEXT_ACCENT = "#A5B4FC"

    @staticmethod
    def interpretation_kind(text):
        """'high' / 'medium' / 'low' / 'none' for a score interpretation, in
        the words the engines actually emit (Strong / Good / Partial / Weak
        Match; Critical / High / Medium / Low / Minimal) and the older ones
        (Confirmed / Probable / Likely / Weak / Insufficient)."""
        t = str(text or "").lower()
        if any(k in t for k in ("confirmed", "strong", "critical", "high")):
            return "high"
        if any(k in t for k in ("probable", "likely", "good", "medium")):
            return "medium"
        if any(k in t for k in ("partial", "weak", "low", "minimal")):
            return "low"
        return "none"

    @staticmethod
    def interpretation_color(text):
        return _S[CorrelationEngineStyles.interpretation_kind(text)]

    # ============================================================================
    # ICONS (painted)
    # ============================================================================

    @staticmethod
    def create_icon(icon_type: str, size: int = 16, color: str = None) -> QIcon:
        """
        Create a simple icon programmatically.
        
        Args:
            icon_type: Type of icon ('check', 'cross', 'info', 'warning', 'error', 
                      'add', 'remove', 'edit', 'save', 'load', 'execute', 'settings')
            size: Icon size in pixels
            color: Icon color (hex string)
            
        Returns:
            QIcon object
        """
        if color is None:
            color = CorrelationEngineStyles.TEXT_PRIMARY
        
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        pen_color = QColor(color)
        painter.setPen(pen_color)
        painter.setBrush(pen_color)
        
        # Draw different icon types
        if icon_type == 'check':
            # Checkmark
            painter.setPen(QColor(color))
            painter.drawLine(size//4, size//2, size//2, size*3//4)
            painter.drawLine(size//2, size*3//4, size*3//4, size//4)
        
        elif icon_type == 'cross':
            # X mark
            painter.drawLine(size//4, size//4, size*3//4, size*3//4)
            painter.drawLine(size*3//4, size//4, size//4, size*3//4)
        
        elif icon_type == 'info':
            # Info circle
            painter.drawEllipse(2, 2, size-4, size-4)
            painter.drawText(0, 0, size, size, Qt.AlignCenter, 'i')
        
        elif icon_type == 'warning':
            # Warning triangle
            from PyQt5.QtCore import QPoint
            from PyQt5.QtGui import QPolygon
            points = QPolygon([
                QPoint(size//2, size//4),
                QPoint(size//4, size*3//4),
                QPoint(size*3//4, size*3//4)
            ])
            painter.drawPolygon(points)
            painter.drawText(0, 0, size, size, Qt.AlignCenter, '!')
        
        elif icon_type == 'error':
            # Error circle with X
            painter.drawEllipse(2, 2, size-4, size-4)
            painter.drawLine(size//3, size//3, size*2//3, size*2//3)
            painter.drawLine(size*2//3, size//3, size//3, size*2//3)
        
        elif icon_type == 'add':
            # Plus sign
            painter.drawLine(size//2, size//4, size//2, size*3//4)
            painter.drawLine(size//4, size//2, size*3//4, size//2)
        
        elif icon_type == 'remove':
            # Minus sign
            painter.drawLine(size//4, size//2, size*3//4, size//2)
        
        elif icon_type == 'edit':
            # Pencil
            painter.drawLine(size//4, size*3//4, size*3//4, size//4)
            painter.drawRect(size//4-2, size*3//4-2, 4, 4)
        
        elif icon_type == 'save':
            # Floppy disk
            painter.drawRect(size//4, size//4, size//2, size//2)
            painter.drawLine(size//2, size//4, size//2, size*3//4)
        
        elif icon_type == 'load':
            # Folder
            painter.drawRect(size//4, size//3, size//2, size//2)
            painter.drawLine(size//4, size//3, size//3, size//4)
        
        elif icon_type == 'execute':
            # Play button
            from PyQt5.QtCore import QPoint
            from PyQt5.QtGui import QPolygon
            points = QPolygon([
                QPoint(size//3, size//4),
                QPoint(size//3, size*3//4),
                QPoint(size*2//3, size//2)
            ])
            painter.drawPolygon(points)
        
        elif icon_type == 'settings':
            # Gear
            painter.drawEllipse(size//3, size//3, size//3, size//3)
            for i in range(8):
                angle = i * 45
                painter.save()
                painter.translate(size//2, size//2)
                painter.rotate(angle)
                painter.drawRect(-2, -size//2, 4, size//6)
                painter.restore()
        
        painter.end()
        
        return QIcon(pixmap)


    @staticmethod
    def add_button_icon(button: QPushButton, icon_type: str, color: str = None):
        """Add a painted icon to a button."""
        icon = CorrelationEngineStyles.create_icon(icon_type, 16, color)
        button.setIcon(icon)
        button.setIconSize(QSize(16, 16))

    # ============================================================================
    # WINDOWS
    # ============================================================================

    @staticmethod
    def apply_progress_dialog_style(dialog):
        """A QProgressDialog in the site look: the gradient bar with its
        percentage, the site card, a ghost Cancel. Same window flags and
        minimum size as before."""
        dialog.setMinimumWidth(450)
        dialog.setMinimumHeight(150)
        dialog.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint
                              | Qt.WindowCloseButtonHint)
        if _site is None:
            return
        _site.apply_site_theme(dialog)
        for b in dialog.findChildren(QPushButton):
            _site.set_variant(b, "ghost")

    @staticmethod
    def apply_evidence_detail_styling(dialog, clear_inline=False):
        """The site look on a detail dialog (Full Log, Parse Status, the
        engine's own dialogs). By default the dialog's own sheets are kept
        (theirs carry status colours); the engine's dialogs pass
        clear_inline=True and get roles instead."""
        if _site is None:
            return
        _site.apply_site_theme(dialog, clear_inline=clear_inline, extra=engine_extra())
        for b in dialog.findChildren(QPushButton):
            if b.property("variant") is None:
                label = (b.text() or "").lower()
                if any(k in label for k in ("close", "cancel", "dismiss")):
                    _site.set_variant(b, "ghost")


# Crow Eye.py's Anatomy offline dialog imports this name from the module
# (`from correlation_engine.gui.ui_styling import apply_evidence_detail_styling`);
# it only ever existed on the class, so the ImportError was swallowed and that
# dialog stayed unstyled. One function, two ways in.
apply_evidence_detail_styling = CorrelationEngineStyles.apply_evidence_detail_styling
