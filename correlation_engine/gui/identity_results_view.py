"""
Identity-Based Correlation Results View - Compact Design

Features:
- Compact layout with summary and filters on same row
- Tree view matching app background
- Smaller tab text
- Compact statistics tables
- Weighted scoring display
- Semantic mapping information
"""

import logging
from collections import defaultdict
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QLineEdit, QPushButton, QGroupBox, QDialog, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QMessageBox, QTextEdit, QTabWidget, QFrame, QProgressDialog, QApplication
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QColor, QFont, QBrush
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


# Identity grouping — canonical implementations live in
# correlation_engine.engine.identity_grouping (shared with the engine's
# cross-wing run reconciler). Aliased here so call sites keep working.
from correlation_engine.engine.identity_grouping import ( # noqa: F401
    sub_identity_key as _sub_identity_key,
    display_grouping_key,
    extract_original_name,
)
from .crow_eye_icons import CrowEyeIcons, apply_status_to_label


# Record-level timestamp fields, in priority order (mirrors the engine's
# timestamp_field_patterns). ONLY the record's own fields count — a record
# without its own timestamp shows no time (never the anchor/match time:
# no info is better than wrong info).
_RECORD_TIME_FIELDS = [
    'timestamp', 'Timestamp', 'timestamp_utc', 'event_time', 'EventTime',
    'event_timestamp', 'TimeCreated', 'logged',
    'last_executed', 'last_run', 'run_time', 'first_run', 'run_count_time',
    'last_modified', 'modified_time', 'created_time', 'creation_time',
    'access_time', 'last_access',
    'last_write_time', 'LastWriteTime', 'key_last_write', 'write_time',
    'SourceCreated', 'datetime', 'DateTime', 'date', 'Date', 'time', 'Time',
]


def _extract_record_own_time(data: dict) -> tuple:
    """Extract a record's OWN timestamp from its raw fields.

    Returns (display_str, full_str_or_None). display_str is "" when the
    record carries no time of its own — deliberately never falls back to
    the anchor/match central time.
    """
    raw = None
    if isinstance(data, dict):
        for field in _RECORD_TIME_FIELDS:
            value = data.get(field)
            if value:
                raw = str(value)
                break
        if raw is None:
            # Generic sweep: any column whose name mentions time/date
            for key, value in data.items():
                if value and isinstance(key, str) and not key.startswith('_') \
                        and ('time' in key.lower() or 'date' in key.lower()):
                    raw = str(value)
                    break
    if not raw:
        return "", None
    display = raw.replace('T', ' ')[:19]
    return display, (raw if raw != display else None)


def _extract_evidence_display_time(evidence: dict) -> tuple:
    """Display time for a record row (role-aware).

    The PRIMARY (anchor) record is the one the anchor's central time is
    derived from, so for it the anchor/match timestamp genuinely IS its own
    time and is shown. SECONDARY records show only their own field time; if
    they carry none the cell stays EMPTY (never the anchor's time — a
    secondary must not look like it happened at the anchor's moment).
    Returns (display_str, full_str_or_None).
    """
    own = _extract_record_own_time(evidence.get('data', {}))
    if own[0]:
        return own
    if evidence.get('role') == 'primary':
        ts = evidence.get('timestamp')
        if ts:
            raw = str(ts)
            display = raw.replace('T', ' ')[:19]
            return display, (raw if raw != display else None)
    return own


def _make_evidence_row(fid: str, match, data: dict) -> dict:
    """Build an evidence-row dict and PRECOMPUTE its display time once.

    The role-aware time scan (~30 field probes + a full-key sweep) is otherwise
    re-run for every record during tree building on the UI thread; doing it here
    (during the off-thread convert) keeps the row-build cheap.
    """
    row = {
        'feather_id': fid,
        'artifact': match.anchor_artifact_type,
        'timestamp': match.timestamp,
        'data': data,
        'role': 'primary' if fid == match.anchor_feather_id else 'secondary',
    }
    disp, full = _extract_evidence_display_time(row)
    row['_display_time'] = disp
    row['_display_time_full'] = full
    return row


def _iter_record_dicts(ev: dict):
    """Yield the record dict(s) held by an evidence row's polymorphic ``data``.

    ``data`` may be a single record dict, a list of record dicts (the identity
    adapter flattens ``feather_records[fid]`` to a list), or a non-dict (a
    double-encoded string). Non-dicts yield a single empty dict so the row still
    renders its identity / feather / time / role columns.
    """
    if not isinstance(ev, dict):
        return
    d = ev.get('data')
    if isinstance(d, dict):
        yield d
    elif isinstance(d, list):
        found = False
        for x in d:
            if isinstance(x, dict):
                found = True
                yield x
        if not found:
            yield {}
    else:
        yield {}


def _record_display_time(ev: dict, rec_data: dict) -> str:
    """Non-empty per-record display time: the record's own time, else the row's
    role-aware ``_display_time``, else the anchor/match ``timestamp``."""
    if isinstance(rec_data, dict):
        own, _ = _extract_record_own_time(rec_data)
        if own:
            return own
    disp = ev.get('_display_time') if isinstance(ev, dict) else None
    if disp:
        return disp
    ts = ev.get('timestamp') if isinstance(ev, dict) else None
    if ts:
        return str(ts).replace('T', ' ')[:19]
    return ''


def _feather_base_name(feather_id) -> str:
    """The real artifact/feather name for display — strips any path prefix and a
    trailing numeric shard suffix (``prefetch_0`` -> ``prefetch``)."""
    fid = str(feather_id or '')
    name = fid.split('/')[-1] if '/' in fid else fid
    if '_' in name and name.rsplit('_', 1)[-1].isdigit():
        name = name.rsplit('_', 1)[0]
    return name


def convert_matches_to_identities(matches, normalize_for_grouping, display_name_for_gui,
                                  progress=None, progress_cb=None, is_canceled=None) -> List[Dict]:
    """Convert correlation matches into the identity hierarchy (PURE DATA — no
    Qt widgets), so it can run on a background load thread.

    ``normalize_for_grouping`` / ``display_name_for_gui`` are the two pure name
    helpers (IdentityResultsView static methods). Optional hooks:
      - ``progress``: a QProgressDialog to drive on the UI-thread path (existing behavior).
      - ``progress_cb``: callable(done, total) for a worker to report progress off-thread.
      - ``is_canceled``: callable() -> bool to abort early.
    """
    identity_map = {}

    if not matches:
        logger.info(f"[IdentityResultsView] convert_matches: No matches provided (matches is {type(matches)})")
        return []

    total_matches = len(matches)
    match_count = 0
    for match in matches:
        match_count += 1

        if match_count % 100 == 0:
            if progress is not None:
                percentage = int((match_count / total_matches) * 80)  # 0-80% for processing
                progress.setValue(percentage)
                progress.setLabelText(f"Loading identity data: {match_count}/{total_matches} identities...")
                QApplication.processEvents()
                if progress.wasCanceled():
                    return []
            if progress_cb is not None:
                progress_cb(match_count, total_matches)
            if is_canceled is not None and is_canceled():
                return []

        # Normalize the application name for grouping so trivial variants collapse.
        raw_app = match.matched_application or "Unknown"
        main_app = normalize_for_grouping(raw_app)

        if main_app not in identity_map:
            display_name = display_name_for_gui(raw_app)
            identity_map[main_app] = {
                'identity_id': main_app,
                'identity_type': 'name',
                'primary_name': display_name,
                'sub_identities': {},
                'feathers_found': set(),
                'wings_found': set(),
            }

        identity_map[main_app]['feathers_found'].update(match.feather_records.keys())
        match_wing_name = getattr(match, 'wing_name', None) or 'Unknown Wing'
        identity_map[main_app]['wings_found'].add(match_wing_name)

        original_name = extract_original_name(raw_app, match.feather_records)
        sub_key = _sub_identity_key(original_name) or original_name.strip().lower()
        if sub_key not in identity_map[main_app]['sub_identities']:
            identity_map[main_app]['sub_identities'][sub_key] = {
                'original_name': original_name,
                'sub_key': sub_key,
                'name_variants': set(),
                'anchors': [],
                'feathers_found': set(),
                'wings_found': set(),
            }

        sub_identity = identity_map[main_app]['sub_identities'][sub_key]
        sub_identity['name_variants'].add(original_name)
        sub_identity['feathers_found'].update(match.feather_records.keys())
        sub_identity['wings_found'].add(match_wing_name)

        anchor_start_time = getattr(match, 'anchor_start_time', match.timestamp)
        anchor_end_time = getattr(match, 'anchor_end_time', match.timestamp)
        anchor_record_count = getattr(match, 'anchor_record_count', len(match.feather_records))

        anchor = {
            'anchor_id': match.match_id,
            'wing_name': getattr(match, 'wing_name', None),
            'start_time': anchor_start_time,
            'end_time': anchor_end_time,
            'record_count': anchor_record_count,
            'feathers': list(match.feather_records.keys()),
            'primary_artifact': match.anchor_artifact_type,
            'evidence_count': match.feather_count,
            'weighted_score': getattr(match, 'weighted_score', None),
            'score_breakdown': getattr(match, 'score_breakdown', None),
            'confidence_score': getattr(match, 'confidence_score', None),
            'confidence_category': getattr(match, 'confidence_category', None),
            'semantic_data': getattr(match, 'semantic_data', None),
            'evidence_rows': [
                _make_evidence_row(fid, match, data)
                for fid, data in match.feather_records.items()
            ],
        }
        sub_identity['anchors'].append(anchor)

    # Finalize: dict -> list, set -> sorted list, compute identity overall score.
    result = []
    for identity in identity_map.values():
        identity['feathers_found'] = list(identity['feathers_found'])
        if isinstance(identity.get('wings_found'), set):
            identity['wings_found'] = sorted(identity['wings_found'])
        sub_list = []
        for sub in identity['sub_identities'].values():
            sub['feathers_found'] = list(sub['feathers_found'])
            if isinstance(sub.get('name_variants'), set):
                sub['name_variants'] = sorted(sub['name_variants'])
            if isinstance(sub.get('wings_found'), set):
                sub['wings_found'] = sorted(sub['wings_found'])
            sub_list.append(sub)
        identity['sub_identities'] = sub_list

        all_scores = []
        for sub in sub_list:
            for anchor in sub.get('anchors', []):
                ws = anchor.get('weighted_score')
                if isinstance(ws, dict) and 'score' in ws:
                    s = ws['score']
                    if isinstance(s, (int, float)) and 0.0 <= s <= 1.0:
                        all_scores.append(s)
        if not all_scores:
            for anchor in identity.get('anchors', []):
                ws = anchor.get('weighted_score')
                if isinstance(ws, dict) and 'score' in ws:
                    s = ws['score']
                    if isinstance(s, (int, float)) and 0.0 <= s <= 1.0:
                        all_scores.append(s)

        avg = sum(all_scores) / len(all_scores) if all_scores else 0.0
        mx = max(all_scores) if all_scores else 0.0
        if avg >= 0.7:
            interp = "High"
        elif avg >= 0.4:
            interp = "Medium"
        elif avg > 0:
            interp = "Low"
        else:
            interp = "None"
        identity['overall_score'] = {
            'average': avg, 'max': mx,
            'evidence_count': len(all_scores), 'interpretation': interp,
        }
        result.append(identity)

    logger.info(f"[IdentityResultsView] convert_matches: {match_count} matches -> {len(result)} identities")
    return result


def _search_semantic_data(semantic_data: dict, search_term: str) -> bool:
    """
    Search for a term in semantic data structures.
    
    Handles all three semantic data structures:
    1. semantic_mappings array (current structure)
    2. Direct semantic_value field (legacy structure)
    3. String values (legacy structure)
    
    Args:
        semantic_data: Dictionary containing semantic data fields
        search_term: Search term (already lowercased)
    
    Returns:
        True if search term found in any semantic value or rule name, False otherwise
    """
    if not semantic_data or not isinstance(semantic_data, dict):
        return False
    
    for key, value in semantic_data.items():
        # Skip internal keys
        if key.startswith('_'):
            continue
        
        # Check for semantic_mappings array (current structure)
        if isinstance(value, dict) and 'semantic_mappings' in value:
            mappings = value['semantic_mappings']
            if isinstance(mappings, list) and len(mappings) > 0:
                first_mapping = mappings[0]
                if isinstance(first_mapping, dict) and 'semantic_value' in first_mapping:
                    sem_val = str(first_mapping['semantic_value']).lower()
                    rule_name = first_mapping.get('rule_name', key).lower()
                    if search_term in sem_val or search_term in rule_name:
                        return True
        
        # Check for direct semantic_value field (legacy structure)
        elif isinstance(value, dict) and 'semantic_value' in value:
            sem_val = str(value['semantic_value']).lower()
            rule_name = value.get('rule_name', key).lower()
            if search_term in sem_val or search_term in rule_name:
                return True
        
        # Check for string value (legacy structure)
        elif isinstance(value, str):
            if search_term in value.lower() or search_term in key.lower():
                return True
    
    return False


def _format_semantic_findings(semantic_data: dict, max_findings: int = 6) -> list:
    """Render stored semantic_data as lines a person reads.

    The tooltip used to be built with `f" {key}: {value}"` where `value` is the
    whole nested entry, so it rendered by repr() - 1,332 characters of raw
    Python dict for a single finding, with the rule's regex printed twice. What
    an analyst needs is what was found, what matched, and where it came from.

    The rule's `rule_pattern` is deliberately never shown: it is the rule's own
    regex, not evidence, and printing it as though it were is the mistake this
    replaces. Handles the legacy shapes too - a direct `semantic_value` dict, or
    a bare string - because old case databases still carry them.
    """
    lines = []
    if not semantic_data or not isinstance(semantic_data, dict):
        return lines

    try:
        from ..config.attack_catalog import technique_name
    except Exception:
        technique_name = None

    for key, value in semantic_data.items():
        if key.startswith('_') or not value:
            continue
        if len(lines) >= max_findings:
            lines.append(" ...")
            break

        if isinstance(value, str):
            lines.append(" %s: %s" % (key, value))
            continue
        if not isinstance(value, dict):
            continue

        mappings = value.get('semantic_mappings')
        mapping = mappings[0] if isinstance(mappings, list) and mappings else value
        if not isinstance(mapping, dict):
            continue

        headline = mapping.get('semantic_value') or value.get('semantic_value') or key
        rule_name = mapping.get('rule_name')
        confidence = mapping.get('confidence')
        severity = mapping.get('severity')
        bits = [b for b in (rule_name,
                            ("confidence %.2f" % confidence)
                            if isinstance(confidence, (int, float)) else None,
                            severity if severity and severity != 'info' else None)
                if b]
        lines.append(" %s%s" % (headline, ("  (%s)" % ", ".join(bits)) if bits else ""))

        # What actually matched, and in which source.
        hits = value.get('matched_fields')
        if isinstance(hits, list) and hits:
            for hit in hits[:3]:
                if not isinstance(hit, dict):
                    continue
                where = hit.get('feather') or '?'
                field = hit.get('field') or '?'
                lines.append("    matched %r in %s.%s"
                             % (str(hit.get('value', '')), where, field))
        else:
            matched = mapping.get('technical_value') or value.get('identity_value')
            if matched:
                feathers = mapping.get('matched_feathers') or []
                where = ", ".join(str(f) for f in feathers) if feathers else None
                lines.append("    matched %r%s"
                             % (str(matched), (" in %s" % where) if where else ""))

        techniques = mapping.get('technique_id') or value.get('technique_id') or []
        tactics = mapping.get('tactic') or value.get('tactic') or []
        if techniques:
            named = []
            for t in techniques[:4]:
                label = technique_name(t) if technique_name else None
                named.append("%s (%s)" % (t, label) if label else str(t))
            line = "    ATT&CK " + ", ".join(named)
            if tactics:
                line += "  [%s]" % ", ".join(str(t) for t in tactics)
            lines.append(line)

    return lines


class IdentityResultsView(QWidget):
    """Compact Identity-Based Correlation Results View with Pagination and Scoring."""
    
    # VERSION STAMP - to verify correct file is loaded
    SEMANTIC_FIX_VERSION = "2026-01-24-v3-IDENTITY-FIX"
    
    match_selected = pyqtSignal(dict)
    
    # Pagination settings
    PAGE_SIZE = 100 # Load 100 identities at a time
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.identities = []
        self.filtered_identities = []
        self.current_results = None
        self.current_page = 0
        self.scoring_enabled = False
        self.semantic_enabled = False
        
        # Load configuration
        try:
            # Absolute, like engine/time_based_engine.py and the semantic
            # controller. `...config` climbs above `correlation_engine`,
            # which is the top-level package, so it always raised
            # "attempted relative import beyond top-level package" - the
            # except below swallowed it, the manager stayed None, and the
            # analyst's cascade-tree-expansion setting was never read.
            from config.case_history_manager import CaseHistoryManager
            self.case_history_manager = CaseHistoryManager()
        except Exception as e:
            logger.error(f"Failed to load CaseHistoryManager: {e}")
            self.case_history_manager = None
        
        # Debounce timer for search filter
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300) # 300ms delay
        self.search_timer.timeout.connect(self._apply_filters)
        
        self.setup_ui()
    
    def setup_ui(self):
        """Setup compact UI with labeled filters."""
        # Print version stamp to console
        logger.info(f"[IdentityResultsView] VERSION: {self.SEMANTIC_FIX_VERSION}")
        logger.info(f"[IdentityResultsView] Semantic fix is ACTIVE")
        
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(4)
        main_layout.setContentsMargins(4, 4, 4, 4)
        
        # Set widget background
        self.setStyleSheet("background-color: #0B1220;")
        
        # === TOP: Summary + Filters (single compact row) ===
        top_frame = QFrame()
        top_frame.setMaximumHeight(36)
        top_frame.setStyleSheet("""
            QFrame {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 6px;
            }
        """)
        top_layout = QHBoxLayout(top_frame)
        top_layout.setSpacing(10)
        top_layout.setContentsMargins(8, 4, 8, 4)
        
        # Summary labels (compact)
        self.identities_lbl = QLabel("Identities: 0")
        self.identities_lbl.setStyleSheet("color: #00FFFF; font-weight: bold; font-size: 9pt;")
        top_layout.addWidget(self.identities_lbl)
        
        self.anchors_lbl = QLabel("Anchors: 0")
        self.anchors_lbl.setStyleSheet("font-size: 8pt; color: #94A3B8;")
        top_layout.addWidget(self.anchors_lbl)
        
        self.evidence_lbl = QLabel("Records: 0")
        self.evidence_lbl.setStyleSheet("font-size: 8pt; color: #94A3B8;")
        top_layout.addWidget(self.evidence_lbl)
        
        self.feathers_used_lbl = QLabel("Feathers: 0")
        self.feathers_used_lbl.setStyleSheet("color: #4CAF50; font-size: 8pt; font-weight: bold;")
        top_layout.addWidget(self.feathers_used_lbl)
        
        # Scoring indicator
        self.scoring_lbl = QLabel("Scoring: Off")
        self.scoring_lbl.setStyleSheet("font-size: 8pt; color: #94A3B8;")
        top_layout.addWidget(self.scoring_lbl)

        # MITRE ATT&CK coverage rollup (from advanced/semantic rule hits).
        # Annotation only — hidden until at least one technique is covered.
        self.attack_lbl = QLabel("ATT&CK: —")
        self.attack_lbl.setStyleSheet("font-size: 8pt; color: #9C27B0; font-weight: bold;")
        self.attack_lbl.setVisible(False)
        top_layout.addWidget(self.attack_lbl)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #334155;")
        top_layout.addWidget(sep)
        
        # Filters with labels
        search_lbl = QLabel("Search:")
        search_lbl.setStyleSheet("font-size: 8pt; color: #94A3B8;")
        top_layout.addWidget(search_lbl)
        
        self.identity_filter = QLineEdit()
        self.identity_filter.setPlaceholderText("Search name or semantic value...")
        self.identity_filter.setMaximumWidth(250)
        self.identity_filter.setStyleSheet("""
            QLineEdit {
                font-size: 8pt; 
                padding: 2px 4px;
                background-color: #0B1220;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #E2E8F0;
            }
            QLineEdit:focus {
                border: 1px solid #00FFFF;
            }
        """)
        self.identity_filter.textChanged.connect(self._on_search_text_changed)
        top_layout.addWidget(self.identity_filter)
        
        feather_lbl = QLabel("Feather:")
        feather_lbl.setStyleSheet("font-size: 8pt; color: #94A3B8;")
        top_layout.addWidget(feather_lbl)
        
        self.feather_filter = QComboBox()
        self.feather_filter.addItem("All")
        self.feather_filter.setMaximumWidth(100)
        self.feather_filter.setStyleSheet("""
            QComboBox {
                font-size: 8pt;
                background-color: #0B1220;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #E2E8F0;
                padding: 2px 4px;
            }
            QComboBox:hover {
                border: 1px solid #00FFFF;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #1E293B;
                color: #E2E8F0;
                selection-background-color: #334155;
            }
        """)
        self.feather_filter.currentTextChanged.connect(self._apply_filters)
        top_layout.addWidget(self.feather_filter)
        
        min_lbl = QLabel("Min:")
        min_lbl.setStyleSheet("font-size: 8pt; color: #94A3B8;")
        top_layout.addWidget(min_lbl)
        
        self.min_filter = QComboBox()
        self.min_filter.addItems(["1", "2", "3", "5", "10"])
        self.min_filter.setMaximumWidth(50)
        self.min_filter.setStyleSheet("""
            QComboBox {
                font-size: 8pt;
                background-color: #0B1220;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #E2E8F0;
                padding: 2px 4px;
            }
            QComboBox:hover {
                border: 1px solid #00FFFF;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #1E293B;
                color: #E2E8F0;
                selection-background-color: #334155;
            }
        """)
        self.min_filter.currentTextChanged.connect(self._apply_filters)
        top_layout.addWidget(self.min_filter)
        
        reset_btn = QPushButton("Reset")
        reset_btn.setMaximumWidth(50)
        reset_btn.setStyleSheet("""
            QPushButton {
                font-size: 8pt; 
                padding: 2px 6px;
                background-color: #334155;
                border: 1px solid #475569;
                border-radius: 4px;
                color: #E2E8F0;
            }
            QPushButton:hover {
                background-color: #475569;
                border: 1px solid #00FFFF;
            }
        """)
        reset_btn.clicked.connect(self._reset_filters)
        top_layout.addWidget(reset_btn)
        
        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("color: #334155;")
        top_layout.addWidget(sep2)
        
        # Pagination controls
        self.prev_btn = QPushButton("<")
        self.prev_btn.setMaximumWidth(24)
        self.prev_btn.setStyleSheet("""
            QPushButton {
                font-size: 8pt; 
                padding: 2px;
                background-color: #334155;
                border: 1px solid #475569;
                border-radius: 4px;
                color: #E2E8F0;
            }
            QPushButton:hover {
                background-color: #475569;
                border: 1px solid #00FFFF;
            }
        """)
        self.prev_btn.clicked.connect(self._prev_page)
        top_layout.addWidget(self.prev_btn)
        
        self.page_lbl = QLabel("1/1")
        self.page_lbl.setStyleSheet("font-size: 8pt; color: #94A3B8;")
        top_layout.addWidget(self.page_lbl)
        
        self.next_btn = QPushButton(">")
        self.next_btn.setMaximumWidth(24)
        self.next_btn.setStyleSheet("""
            QPushButton {
                font-size: 8pt; 
                padding: 2px;
                background-color: #334155;
                border: 1px solid #475569;
                border-radius: 4px;
                color: #E2E8F0;
            }
            QPushButton:hover {
                background-color: #475569;
                border: 1px solid #00FFFF;
            }
        """)
        self.next_btn.clicked.connect(self._next_page)
        top_layout.addWidget(self.next_btn)
        
        top_layout.addStretch()
        main_layout.addWidget(top_frame)
        
        # === MIDDLE: Results Tree ===
        self.results_tree = self._create_tree()
        main_layout.addWidget(self.results_tree, stretch=1)
        
        # === BOTTOM: Stats Section with compact tables ===
        stats_frame = QFrame()
        stats_frame.setMinimumHeight(80)
        stats_frame.setMaximumHeight(120)
        stats_frame.setStyleSheet("""
            QFrame {
                background-color: #0B1220;
                border-top: 1px solid #334155;
            }
        """)
        stats_main_layout = QVBoxLayout(stats_frame)
        stats_main_layout.setSpacing(4)
        stats_main_layout.setContentsMargins(4, 4, 4, 4)
        
        # Stats row: Types, Roles, Scores
        bottom_stats = QHBoxLayout()
        bottom_stats.setSpacing(12)
        
        # Correlation results per wing
        self.type_table = self._create_compact_table(["Wing", "Results"])
        bottom_stats.addWidget(self._wrap_table("Wings", self.type_table), stretch=1)
        
        # Evidence Roles
        self.role_table = self._create_compact_table(["Role", "#"])
        bottom_stats.addWidget(self._wrap_table("Roles", self.role_table), stretch=1)
        
        # Scoring Summary
        self.scoring_table = self._create_compact_table(["Score", "#"])
        bottom_stats.addWidget(self._wrap_table("Scores", self.scoring_table), stretch=1)
        
        stats_main_layout.addLayout(bottom_stats)
        main_layout.addWidget(stats_frame)

    def _create_tree(self) -> QTreeWidget:
        """Create tree with app-matching background and score column."""
        tree = QTreeWidget()
        tree.setHeaderLabels(["Identity / Anchor / Record", "Time", "Feathers", "Score", "Semantic", "Rec", "Anchor Number", "Wings"])

        tree.setColumnWidth(0, 280)
        tree.setColumnWidth(1, 150) # Time: anchor range / record's own time
        tree.setColumnWidth(2, 150) # Feathers
        tree.setColumnWidth(3, 60) # Score column
        tree.setColumnWidth(4, 350) # Semantic column - WIDER: Increased to 350 for better readability
        tree.setColumnWidth(5, 40) # Record count
        tree.setColumnWidth(6, 100) # Anchor Number: count on identity/sub rows, ordinal on anchor rows
        tree.setColumnWidth(7, 130) # Wings that found this identity
        
        tree.setAlternatingRowColors(True)
        tree.setIndentation(22)
        tree.itemDoubleClicked.connect(self._on_double_click)
        tree.itemClicked.connect(self._on_item_clicked)
        tree.itemExpanded.connect(self._on_item_expanded)
        tree.itemCollapsed.connect(self._on_item_collapsed)

        # Dark theme + hierarchy visualization: slate guide lines show which
        # row nests under which, and cyan chevrons show expanded/collapsed
        # state on every row that has children.
        vline = CrowEyeIcons.icon_path("branch_vline")
        more = CrowEyeIcons.icon_path("branch_more")
        end = CrowEyeIcons.icon_path("branch_end")
        closed = CrowEyeIcons.icon_path("branch_closed")
        opened = CrowEyeIcons.icon_path("branch_open")
        tree.setStyleSheet(f"""
            QTreeWidget {{
                font-size: 8pt;
                background-color: #0B1220;
                alternate-background-color: #1E293B;
                border: 1px solid #334155;
                color: #E2E8F0;
            }}
            QTreeWidget::item {{
                padding: 4px 2px;
                min-height: 24px;
            }}
            QTreeWidget::item:selected {{
                background-color: #334155;
                color: #00FFFF;
            }}
            QTreeWidget::branch {{
                background-color: transparent;
            }}
            QTreeWidget::branch:has-siblings:!adjoins-item {{
                border-image: url({vline}) 0;
            }}
            QTreeWidget::branch:has-siblings:adjoins-item {{
                border-image: url({more}) 0;
            }}
            QTreeWidget::branch:!has-children:!has-siblings:adjoins-item {{
                border-image: url({end}) 0;
            }}
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:closed:has-children:has-siblings {{
                border-image: none;
                image: url({closed});
            }}
            QTreeWidget::branch:open:has-children:!has-siblings,
            QTreeWidget::branch:open:has-children:has-siblings {{
                border-image: none;
                image: url({opened});
            }}
            QHeaderView::section {{
                background-color: #1E293B;
                color: #00FFFF;
                padding: 6px 4px;
                font-size: 8pt;
                font-weight: bold;
                border: none;
                border-bottom: 2px solid #00FFFF;
                min-height: 26px;
            }}
        """)
        return tree
    
    def _create_compact_table(self, headers: List[str]) -> QTableWidget:
        """Create compact table with smaller sizing."""
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setMaximumHeight(100) # Smaller table
        table.setMinimumHeight(60)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(18) # Compact rows
        table.horizontalHeader().setFixedHeight(22) # Compact header
        table.setStyleSheet("""
            QTableWidget {
                font-size: 8pt;
                background-color: #0B1220;
                alternate-background-color: #1E293B;
                border: 1px solid #334155;
                color: #E2E8F0;
            }
            QTableWidget::item { 
                padding: 2px; 
            }
            QTableWidget::item:selected {
                background-color: #334155;
                color: #00FFFF;
            }
            QHeaderView::section {
                background-color: #1E293B;
                color: #00FFFF;
                padding: 2px;
                font-size: 8pt;
                font-weight: bold;
                border: none;
                border-bottom: 1px solid #00FFFF;
            }
        """)
        return table
    
    def _wrap_table(self, title: str, table: QTableWidget) -> QGroupBox:
        """Wrap table in group box with dark theme styling."""
        group = QGroupBox(title)
        group.setStyleSheet("""
            QGroupBox { 
                font-size: 8pt; 
                font-weight: bold; 
                color: #00FFFF;
                padding-top: 12px; 
                margin-top: 4px;
                border: 1px solid #334155;
                border-radius: 4px;
                background-color: #0B1220;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 1px 6px;
                background-color: #1E293B;
                border-radius: 3px;
            }
        """)
        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(1)
        layout.addWidget(table)
        group.setLayout(layout)
        return group
    
    def load_results(self, results: Dict[str, Any]):
        """Load correlation results with pagination."""
        self.current_results = results
        self.identities = results.get('identities', [])
        self.filtered_identities = self.identities.copy()
        self.current_page = 0
        self._update_summary(results)
        self._update_feather_filter(results)
        self._populate_current_page()
        self._update_stats(results)
    
    def load_from_correlation_result(self, result, show_progress=True, identities=None):
        """Load from CorrelationResult object with progress indicator.

        Args:
            result: CorrelationResult object
            show_progress: If False, suppresses the progress dialog (useful when parent already shows progress)
            identities: Optionally the already-converted identity list (produced
                off the UI thread by a background load worker). When provided the
                UI thread skips the heavy `_convert_matches` step entirely.
        """
        logger.info(f"[IdentityResultsView] load_from_correlation_result called with {result.total_matches} matches")
        
        # Show progress dialog if we have many matches and show_progress is True
        progress = None
        if show_progress and result.total_matches > 100:
            progress = QProgressDialog("Loading identity data...", "Cancel", 0, 100, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setWindowTitle("Loading Results")
            
            # Apply Crow Eye styling
            from .ui_styling import CorrelationEngineStyles
            CorrelationEngineStyles.apply_progress_dialog_style(progress)
            progress.show()
            QApplication.processEvents()
        
        try:
            # Use the pre-converted list (from a background worker) when given;
            # otherwise convert on this (UI) thread as before.
            if identities is None:
                identities = self._convert_matches(result.matches, progress)

            if progress and progress.wasCanceled():
                logger.info("[IdentityResultsView] Loading cancelled by user")
                return
            
            logger.info(f"[IdentityResultsView] Converted to {len(identities)} identities")
            
            # Use feather_metadata from result if available (contains records_loaded and identities_found)
            feather_metadata = result.feather_metadata if hasattr(result, 'feather_metadata') and result.feather_metadata else {}
            
            # Filter out non-dict metadata entries
            filtered_metadata = {}
            for fid, data in feather_metadata.items():
                if isinstance(data, dict):
                    filtered_metadata[fid] = data
            feather_metadata = filtered_metadata
            
            # If feather_metadata doesn't have the right format, build it from matches
            if feather_metadata and not any('records_loaded' in v for v in feather_metadata.values() if isinstance(v, dict)):
                # Old format - convert
                new_metadata = {}
                for fid, data in feather_metadata.items():
                    if isinstance(data, dict):
                        new_metadata[fid] = {
                            'records_loaded': data.get('records', data.get('records_loaded', 0)),
                            'artifact_type': data.get('artifact', data.get('artifact_type', 'Unknown')),
                            'identities_found': data.get('identities_found', 0)
                        }
                feather_metadata = new_metadata
            
            # Calculate total anchors properly for new format
            total_anchors = 0
            for identity in identities:
                sub_identities = identity.get('sub_identities', [])
                if sub_identities:
                    for sub in sub_identities:
                        total_anchors += len(sub.get('anchors', []))
                else:
                    total_anchors += len(identity.get('anchors', []))
            
            results_dict = {
                'identities': identities,
                'statistics': {
                    'total_identities': len(identities),
                    'total_anchors': total_anchors,
                    'total_evidence': result.total_records_scanned,
                    'execution_time': result.execution_duration_seconds,
                    'feathers_used': result.feathers_processed
                },
                'wing_name': result.wing_name,
                'feather_metadata': feather_metadata
            }
            
            if progress:
                progress.setLabelText("Displaying results...")
                progress.setValue(90)
                QApplication.processEvents()
            
            logger.info(f"[IdentityResultsView] Calling load_results with {len(identities)} identities, {total_anchors} anchors")
            self.load_results(results_dict)
            logger.info(f"[IdentityResultsView] load_results completed, tree has {self.results_tree.topLevelItemCount()} items")
            
            if progress:
                progress.setValue(100)
                progress.close()
                
        except Exception as e:
            if progress:
                progress.close()
            logger.info(f"[Error] Failed to load results: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Load Error", f"Failed to load results:\n{str(e)}")
    
    def _convert_matches(self, matches, progress=None) -> List[Dict]:
        """Convert matches to identity format (delegates to the module-level
        pure function so the SAME logic can run on a background load thread)."""
        return convert_matches_to_identities(
            matches,
            self._normalize_for_grouping,
            self._get_display_name_for_gui,
            progress=progress,
        )
    
    @staticmethod
    def _normalize_for_grouping(name: str) -> str:
        """
        Normalize application name for identity grouping.
        
        Uses the SAME aggressive normalization as the identity engine to ensure
        identities are grouped correctly in the GUI.
        
        This ensures "chrome.exe", "CHROME~1.EXE", "chrome123.exe" all become "chrome"
        and are grouped together under the same main identity.
        
        LIMITATION: Only ASCII alphanumeric characters are preserved. Unicode characters
        (accents, non-Latin scripts) are removed during normalization. This is acceptable
        for Windows forensics where most application names use ASCII.
        
        Examples:
        - "chrome.exe" → "chrome"
        - "CHROME~1.EXE" → "chrome"
        - "chrome123.exe" → "chrome"
        - "Naïve.exe" → "nave" (accent removed)
        
        Args:
            name: Raw application name
        
        Returns:
            Aggressively normalized name for grouping (ASCII alphanumeric only)
        """
        # Canonical implementation now lives in engine.identity_grouping so
        # the engine-side cross-wing reconciler groups EXACTLY like this view.
        return display_grouping_key(name)
    
    @staticmethod
    def _get_display_name_for_gui(raw_name: str) -> str:
        """
        Get a clean, readable display name from the raw name for GUI display.
        
        This is used for the primary_name field to show a user-friendly version
        while the aggressive normalization is used for grouping.
        
        Removes:
        - File extensions (.exe, .lnk, etc.)
        - Copy indicators: (1), (2), - Copy
        - Version indicators: v1, v2, v1.0
        - Tilde and everything after it (~1, ~123)
        
        Preserves:
        - Original capitalization
        - Spaces and readable formatting
        
        Examples:
        - "Chrome.exe" → "Chrome"
        - "CHROME~1.EXE" → "CHROME"
        - "Microsoft Edge.exe" → "Microsoft Edge"
        - "chrome-browser (1).exe" → "chrome-browser"
        
        Args:
            raw_name: Original application name
        
        Returns:
            Clean, readable display name
        """
        if not raw_name:
            return "Unknown"
        
        import re
        
        result = raw_name.strip()
        
        # Step -1: Handle Prefetch filenames (APPNAME.EXE HASH.pf)
        # Extract just the APPNAME.EXE part before the hash
        # Pattern: ends with space + 8 hex chars + .pf
        # Examples: "BRAVE.EXE 3118B3E3.pf" → "BRAVE.EXE"
        # "chrome.exe AF43252D.pf" → "chrome.exe"
        if result.lower().endswith('.pf'):
            # Check if there's a space followed by hex hash before .pf
            match = re.match(r'^(.+?)\s+[0-9A-Fa-f]{8}\.pf$', result, re.IGNORECASE)
            if match:
                result = match.group(1) # Extract just the app name part
        
        # Step 0: Remove ~ and everything after it (FIRST)
        if '~' in result:
            result = result.split('~')[0]
        
        # Step 1: Remove common file extensions (case-insensitive)
        extensions = [
            '.exe', '.lnk', '.dll', '.msi', '.bat', '.cmd', '.ps1', '.vbs', '.js',
            '.com', '.scr', '.pif', '.application', '.gadget', '.msp', '.hta',
            '.cpl', '.msc', '.jar', '.py', '.pyc', '.pyw'
        ]
        lower_result = result.lower()
        for ext in extensions:
            if lower_result.endswith(ext):
                result = result[:-len(ext)]
                break
        
        # Step 2: Remove copy indicators like (1), (2), (3), etc.
        result = re.sub(r'[\s_]*\(\d+\)\s*$', '', result)
        
        # Step 3: Remove " - Copy", "_copy", " copy" at the end
        result = re.sub(r'[\s_]*[-_]?\s*[Cc]opy\s*\d*\s*$', '', result)
        
        # Step 4: Remove version patterns like v1, v2, v1.0, 1.0.0 at the end
        # FIXED: More specific pattern - requires space/underscore OR 'v' prefix
        # This prevents removing numbers that are part of the name (e.g., "chrome1")
        result = re.sub(r'[\s_]+[vV]?\d+(\.\d+)*\s*$', '', result) # Requires space/underscore
        result = re.sub(r'[vV]\d+(\.\d+)*\s*$', '', result) # OR explicit v prefix without space
        
        # Step 5: Clean up trailing special characters
        result = result.rstrip(' _-.')
        
        # Step 6: Normalize multiple spaces to single space
        result = re.sub(r'\s+', ' ', result)
        
        return result.strip() if result else "Unknown"
    
    def _update_summary(self, results: Dict):
        """Update summary labels with cancelled indicator if applicable."""
        stats = results.get('statistics', {})
        
        # Check if execution was cancelled
        status = results.get('status', 'Completed')
        is_cancelled = status == "Cancelled"
        
        # Update identity label with cancelled indicator
        identity_count = stats.get('total_identities', len(self.identities))
        if is_cancelled:
            apply_status_to_label(self.identities_lbl, "WARN", f"Identities: {identity_count:,} (Cancelled)")
            self.identities_lbl.setStyleSheet("color: #FF9800; font-weight: bold; font-size: 9pt;")
            self.identities_lbl.setToolTip("Execution was cancelled by user. Showing partial results.")
        else:
            self.identities_lbl.setText(f"Identities: {identity_count:,}")
            self.identities_lbl.setStyleSheet("color: #00FFFF; font-weight: bold; font-size: 9pt;")
            self.identities_lbl.setToolTip("")
        
        self.anchors_lbl.setText(f"Anchors: {stats.get('total_anchors', 0):,}")
        self.evidence_lbl.setText(f"Records: {stats.get('total_evidence', 0):,}")
        
        # Show feathers used with details
        feather_metadata = results.get('feather_metadata', {})
        feathers_used = stats.get('feathers_used', len(feather_metadata))
        if feather_metadata:
            # Build tooltip with feather details
            tooltip_lines = ["Feather Details:"]
            for fid, meta in sorted(feather_metadata.items(), 
                                    key=lambda x: x[1].get('records_loaded', 0), 
                                    reverse=True):
                records = meta.get('records_loaded', meta.get('records', 0))
                identities = meta.get('identities_found', 0)
                tooltip_lines.append(f" {fid}: {records:,} records, {identities} identities")
            self.feathers_used_lbl.setToolTip("\n".join(tooltip_lines))
        
        self.feathers_used_lbl.setText(f"Feathers: {feathers_used}")
    
    def _update_feather_filter(self, results: Dict):
        """Update feather filter."""
        self.feather_filter.clear()
        self.feather_filter.addItem("All")
        
        feathers = set()
        for identity in self.identities:
            # Handle both old format (anchors) and new format (sub_identities)
            sub_identities = identity.get('sub_identities', [])
            if sub_identities:
                for sub in sub_identities:
                    for anchor in sub.get('anchors', []):
                        feathers.update(anchor.get('feathers', []))
            else:
                for anchor in identity.get('anchors', []):
                    feathers.update(anchor.get('feathers', []))
        
        # Group feathers by base name (remove numeric suffix like _0, _1, _2)
        base_feathers = set()
        for f in feathers:
            # Remove path prefix (e.g., "feathers/") from display name
            display_name = f.split('/')[-1] if '/' in f else f
            # Extract base name by removing numeric suffix (_0, _1, etc.)
            base_name = display_name.rsplit('_', 1)[0] if '_' in display_name and display_name.rsplit('_', 1)[-1].isdigit() else display_name
            base_feathers.add(base_name)
        
        for base_name in sorted(base_feathers):
            self.feather_filter.addItem(base_name)
    
    def _populate_tree(self, identities: List[Dict]):
        """Populate tree with given identities (used internally)."""
        # Suppress per-insert repaints/signals while bulk-building the tree — a
        # page of identities is thousands of items and each addChild otherwise
        # triggers layout/paint work, freezing the window.
        self.results_tree.setUpdatesEnabled(False)
        self.results_tree.blockSignals(True)
        try:
            self.results_tree.clear()

            if not identities:
                # Show a message when there are no results (8 columns)
                empty_item = QTreeWidgetItem(["No correlation matches found", "", "", "", "", "", "", ""])
                empty_item.setForeground(0, QBrush(QColor("#64748B")))
                empty_item.setFont(0, QFont("Segoe UI", 9, QFont.Normal))
                self.results_tree.addTopLevelItem(empty_item)
                return

            for identity in identities:
                item = self._create_identity_item(identity)
                self.results_tree.addTopLevelItem(item)

            # Expand first 3
            for i in range(min(3, self.results_tree.topLevelItemCount())):
                self.results_tree.topLevelItem(i).setExpanded(True)
        finally:
            self.results_tree.blockSignals(False)
            self.results_tree.setUpdatesEnabled(True)
    
    def _populate_current_page(self):
        """Populate tree with current page of identities."""
        total = len(self.filtered_identities)
        total_pages = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        
        start = self.current_page * self.PAGE_SIZE
        end = min(start + self.PAGE_SIZE, total)
        
        page_identities = self.filtered_identities[start:end]
        self._populate_tree(page_identities)
        
        # Update pagination controls
        self.page_lbl.setText(f"Page {self.current_page + 1}/{total_pages} ({total} total)")
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(self.current_page < total_pages - 1)
    
    def _prev_page(self):
        """Go to previous page."""
        if self.current_page > 0:
            self.current_page -= 1
            self._populate_current_page()
    
    def _next_page(self):
        """Go to next page."""
        total_pages = max(1, (len(self.filtered_identities) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self._populate_current_page()
    
    def _create_identity_item(self, identity: Dict) -> QTreeWidgetItem:
        """Create identity tree item with sub-identities."""
        # Calculate totals across all sub-identities
        feathers = set(identity.get('feathers_found', []))
        total_evidence = 0
        total_anchors = 0
        
        sub_identities = identity.get('sub_identities', [])
        
        # If no sub_identities, use old format (anchors directly)
        if not sub_identities:
            for a in identity.get('anchors', []):
                feathers.update(a.get('feathers', []))
                total_evidence += a.get('evidence_count', len(a.get('evidence_rows', [])))
                total_anchors += 1
        else:
            for sub in sub_identities:
                feathers.update(sub.get('feathers_found', []))
                for a in sub.get('anchors', []):
                    total_evidence += a.get('evidence_count', len(a.get('evidence_rows', [])))
                    total_anchors += 1
        
        # Group feathers by base name (remove numeric suffix)
        base_feathers = set()
        for f in feathers:
            display_name = f.split('/')[-1] if '/' in f else f
            base_name = display_name.rsplit('_', 1)[0] if '_' in display_name and display_name.rsplit('_', 1)[-1].isdigit() else display_name
            base_feathers.add(base_name)
        
        name = identity.get('primary_name', 'Unknown')
        feather_str = ", ".join(sorted(base_feathers)[:2]) + ("..." if len(base_feathers) > 2 else "")
        sub_count = len(sub_identities) if sub_identities else 0
        
        # Use pre-computed overall score (falls back to on-the-fly calculation)
        overall = identity.get('overall_score')
        if overall:
            avg_score = overall.get('average', 0.0)
        else:
            avg_score = self._calculate_identity_score(identity)
        score_str = f"{avg_score:.2f}" if avg_score > 0 else "-"
        
        # Task 6.2: Get aggregated semantic value for identity with error handling
        try:
            semantic_value, semantic_tooltip = self._get_identity_semantic_value(identity)
        except Exception as e:
            logger.error(f"Error getting identity semantic value: {e}")
            semantic_value, semantic_tooltip = "Error", "Error retrieving semantic data"
        
        # Task 6.2: Check if identity has semantic data (tag icon on the
        # Semantic column instead of the old "[S] " text marker)
        try:
            has_semantic = semantic_value not in ["-", "Error", "Fallback", None, ""]
        except Exception as e:
            logger.warning(f"Error checking semantic indicator: {e}")
            has_semantic = False

        wings = identity.get('wings_found', []) or []

        # Main identity item (7 columns - removed Time, added Wings). Per-row icon
        # comes from CrowEyeIcons; Qt draws its own expand chevron when children exist.
        item = QTreeWidgetItem([
            f"{name}" + (f" ({sub_count} variants)" if sub_count > 1 else ""),
            "", # Time: shown on anchor/record rows
            feather_str,
            score_str,
            semantic_value, # Semantic column with aggregated value
            str(total_evidence),
            f"{total_anchors} anchors",
            self._format_wings(wings)
        ])
        item.setIcon(0, CrowEyeIcons.identity()) # fingerprint: the tracked actor/app
        if has_semantic:
            # Descriptive tag icon on the Semantic column (replaces "[S] ")
            item.setIcon(4, CrowEyeIcons.tag())
        item.setFont(0, QFont("Segoe UI", 9, QFont.Bold))
        item.setForeground(0, QBrush(QColor("#2196F3")))
        self._decorate_wings_column(item, wings)

        # Color score based on value
        if avg_score >= 0.7:
            item.setForeground(3, QBrush(QColor("#4CAF50"))) # Green - high score
        elif avg_score >= 0.4:
            item.setForeground(3, QBrush(QColor("#FF9800"))) # Orange - medium score
        elif avg_score > 0:
            item.setForeground(3, QBrush(QColor("#F44336"))) # Red - low score

        # Task 6.2: Color semantic column with error handling
        try:
            if semantic_value == "Error":
                item.setForeground(4, QBrush(QColor("#F44336"))) # Red for errors
                item.setToolTip(4, "Error retrieving semantic data")
            elif semantic_value == "Fallback":
                item.setForeground(4, QBrush(QColor("#FF9800"))) # Orange for fallback
                item.setToolTip(4, "Using fallback semantic data")
            elif semantic_value != "-":
                item.setForeground(4, QBrush(QColor("#9C27B0"))) # Purple for semantic values
                if semantic_tooltip:
                    item.setToolTip(4, semantic_tooltip)
        except Exception as e:
            logger.warning(f"Error setting semantic column color: {e}")
        
        item.setData(0, Qt.UserRole, {'type': 'identity', 'data': identity})
        
        # Add sub-identities if present
        if sub_identities:
            for sub in sub_identities:
                sub_item = self._create_sub_identity_item(sub)
                item.addChild(sub_item)
        else:
            # Old format - add anchors directly (numbered per identity)
            for anchor_number, anchor in enumerate(identity.get('anchors', []), 1):
                item.addChild(self._create_anchor_item(anchor, anchor_number))

        return item
    
    @staticmethod
    def _format_wings(wings) -> str:
        """Format the list of wings that found an identity for the Wings column.

        Shows up to two wing names, then "+N" for the rest (full list goes in
        the tooltip via _decorate_wings_column).
        """
        wings = sorted(wings) if wings else []
        if not wings:
            return "-"
        if len(wings) <= 2:
            return ", ".join(wings)
        return ", ".join(wings[:2]) + f" +{len(wings) - 2}"

    def _decorate_wings_column(self, item: QTreeWidgetItem, wings):
        """Attach full wing list tooltip and multi-wing accent to column 6."""
        wings = sorted(wings) if wings else []
        if not wings:
            return
        item.setToolTip(7, "Found by:\n" + "\n".join(f"- {w}" for w in wings))
        if len(wings) > 1:
            # Cyan accent highlights identities corroborated by multiple wings
            item.setForeground(7, QBrush(QColor("#00BCD4")))

    def _calculate_identity_score(self, identity: Dict) -> float:
        """Calculate average weighted score for an identity across all evidence."""
        scores = []
        sub_identities = identity.get('sub_identities', [])

        if sub_identities:
            for sub in sub_identities:
                for anchor in sub.get('anchors', []):
                    weighted_score = anchor.get('weighted_score')
                    if isinstance(weighted_score, dict) and 'score' in weighted_score:
                        s = weighted_score['score']
                        if isinstance(s, (int, float)) and 0.0 <= s <= 1.0:
                            scores.append(s)
        else:
            for anchor in identity.get('anchors', []):
                weighted_score = anchor.get('weighted_score')
                if isinstance(weighted_score, dict) and 'score' in weighted_score:
                    s = weighted_score['score']
                    if isinstance(s, (int, float)) and 0.0 <= s <= 1.0:
                        scores.append(s)

        return sum(scores) / len(scores) if scores else 0.0
    
    def _get_identity_semantic_value(self, identity: Dict) -> tuple:
        """
        Extract aggregated semantic value from all anchors in an identity.
        
        Returns:
            Tuple of (display_value, tooltip_text) where:
            - display_value: Short string for the Semantic column
            - tooltip_text: Detailed tooltip with all semantic values
        """
        semantic_values = []
        seen_vals = set()  # O(1) dedup instead of rebuilding [v[0] ...] each check
        sub_identities = identity.get('sub_identities', [])
        
        # Collect semantic data from all anchors
        anchors_to_check = []
        if sub_identities:
            for sub in sub_identities:
                anchors_to_check.extend(sub.get('anchors', []))
        else:
            anchors_to_check = identity.get('anchors', [])
        
        for anchor in anchors_to_check:
            semantic_data = anchor.get('semantic_data')
            if semantic_data and isinstance(semantic_data, dict) and not semantic_data.get('_unavailable'):
                for key, value in semantic_data.items():
                    if key.startswith('_'):
                        continue
                    
                    # NEW: Check for semantic_mappings array (current structure)
                    if isinstance(value, dict) and 'semantic_mappings' in value:
                        mappings = value['semantic_mappings']
                        if isinstance(mappings, list) and len(mappings) > 0:
                            first_mapping = mappings[0]
                            if isinstance(first_mapping, dict) and 'semantic_value' in first_mapping:
                                sem_val = str(first_mapping['semantic_value'])
                                rule_name = first_mapping.get('rule_name', key)
                                if sem_val and sem_val not in seen_vals:
                                    seen_vals.add(sem_val)
                                    semantic_values.append((sem_val, rule_name))

                    # LEGACY: Direct semantic_value in value dict
                    elif isinstance(value, dict) and 'semantic_value' in value:
                        sem_val = str(value['semantic_value'])
                        rule_name = value.get('rule_name', key)
                        if sem_val and sem_val not in seen_vals:
                            seen_vals.add(sem_val)
                            semantic_values.append((sem_val, rule_name))

                    # LEGACY: String value
                    elif isinstance(value, str) and value:
                        if value not in seen_vals:
                            seen_vals.add(value)
                            semantic_values.append((value, key))
        
        if not semantic_values:
            return ("-", "")
        
        # Build display value (first value + count if multiple)
        first_value = semantic_values[0][0]
        if len(semantic_values) == 1:
            display_value = first_value
        else:
            display_value = f"{first_value} (+{len(semantic_values)-1})"
        
        # Build tooltip with all values
        tooltip_lines = ["Semantic Values:"]
        for sem_val, rule_name in semantic_values:
            tooltip_lines.append(f" • {rule_name}: {sem_val}")
        
        return (display_value, "\n".join(tooltip_lines))
    
    def _get_semantic_value(self, anchor: Dict) -> str:
        """
        Extract semantic value from anchor data with comprehensive error handling.
        
        Task 6.2: Handle corrupted or invalid semantic_data gracefully
        Requirements: 7.3, 7.4 - Prevent crashes when semantic values are malformed
        
        Checks:
        1. Anchor-level semantic_data field (new structure with semantic_mappings)
        2. Evidence rows for _semantic_mappings key (legacy)
        
        Returns:
            Semantic value string or "-" if not available
        """
        try:
            # Task 6.2: Check anchor-level semantic data with error handling
            semantic_data = anchor.get('semantic_data')
            if semantic_data:
                # Task 6.2: Handle corrupted semantic_data gracefully
                if not isinstance(semantic_data, dict):
                    logger.warning(f"Invalid semantic_data type: {type(semantic_data)}, expected dict")
                    return "Error: Invalid data"
                
                # Check for unavailable marker
                if semantic_data.get('_unavailable'):
                    return "-"
                
                # Check for error metadata
                metadata = semantic_data.get('_metadata', {})
                if isinstance(metadata, dict):
                    if metadata.get('error'):
                        return "Error"
                    if metadata.get('fallback_reason'):
                        return "Fallback"
                
                # Extract semantic values with error handling
                # New structure: field_info contains semantic_mappings array
                for field_name, field_info in semantic_data.items():
                    # Skip metadata and internal keys
                    if field_name.startswith('_'):
                        continue
                    
                    try:
                        # NEW: Check for semantic_mappings array (current structure)
                        if isinstance(field_info, dict) and 'semantic_mappings' in field_info:
                            semantic_mappings = field_info['semantic_mappings']
                            if isinstance(semantic_mappings, list) and len(semantic_mappings) > 0:
                                first_mapping = semantic_mappings[0]
                                if isinstance(first_mapping, dict) and 'semantic_value' in first_mapping:
                                    semantic_value = first_mapping['semantic_value']
                                    if semantic_value is not None:
                                        return str(semantic_value)
                        
                        # LEGACY: Direct semantic_value in field_info
                        elif isinstance(field_info, dict) and 'semantic_value' in field_info:
                            semantic_value = field_info['semantic_value']
                            if semantic_value is not None:
                                return str(semantic_value)
                        
                        # LEGACY: String value
                        elif isinstance(field_info, str) and field_name != '_reason':
                            return field_info
                        
                        # Fallback: Convert to string
                        elif field_info is not None:
                            return str(field_info)
                    except Exception as e:
                        logger.warning(f"Error processing semantic field {field_name}: {e}")
                        continue
            
            # Task 6.2: Check evidence rows for semantic mappings with error handling
            evidence_rows = anchor.get('evidence_rows', [])
            if not isinstance(evidence_rows, list):
                logger.warning(f"Invalid evidence_rows type: {type(evidence_rows)}, expected list")
                return "-"
            
            for evidence in evidence_rows:
                try:
                    if not isinstance(evidence, dict):
                        continue
                    
                    data = evidence.get('data', {})
                    if not isinstance(data, dict):
                        continue
                    
                    semantic_mappings = data.get('_semantic_mappings', {})
                    if not isinstance(semantic_mappings, dict):
                        continue
                    
                    for field_name, mapping_info in semantic_mappings.items():
                        # Skip internal keys
                        if field_name.startswith('_'):
                            continue
                        
                        try:
                            if isinstance(mapping_info, dict) and 'semantic_value' in mapping_info:
                                semantic_value = mapping_info['semantic_value']
                                if semantic_value is not None:
                                    return str(semantic_value)
                            elif isinstance(mapping_info, str):
                                return mapping_info
                            elif mapping_info is not None:
                                # Handle unexpected data types gracefully
                                return str(mapping_info)
                        except Exception as e:
                            logger.warning(f"Error processing semantic mapping {field_name}: {e}")
                            continue
                            
                except Exception as e:
                    logger.warning(f"Error processing evidence row: {e}")
                    continue
        
        except Exception as e:
            # Task 6.2: Show appropriate fallback content in semantic column
            # Requirements: 7.3, 7.4 - Never crash, always show something meaningful
            logger.error(f"Critical error in _get_semantic_value: {e}")
            return "Error"
        
        return "-" # Default when no semantic data available
    
    def _create_sub_identity_item(self, sub_identity: Dict) -> QTreeWidgetItem:
        """Create sub-identity tree item (original filename)."""
        feathers = set(sub_identity.get('feathers_found', []))
        evidence = 0
        anchors = sub_identity.get('anchors', [])
        scores = []
        
        for a in anchors:
            feathers.update(a.get('feathers', []))
            evidence += a.get('evidence_count', len(a.get('evidence_rows', [])))
            weighted_score = a.get('weighted_score')
            if isinstance(weighted_score, dict) and 'score' in weighted_score:
                s = weighted_score['score']
                if isinstance(s, (int, float)) and 0.0 <= s <= 1.0:
                    scores.append(s)
        
        # Group feathers by base name (remove numeric suffix)
        base_feathers = set()
        for f in feathers:
            display_name = f.split('/')[-1] if '/' in f else f
            base_name = display_name.rsplit('_', 1)[0] if '_' in display_name and display_name.rsplit('_', 1)[-1].isdigit() else display_name
            base_feathers.add(base_name)
        
        original_name = sub_identity.get('original_name', 'Unknown')
        feather_str = ", ".join(sorted(base_feathers)[:2]) + ("..." if len(base_feathers) > 2 else "")
        avg_score = sum(scores) / len(scores) if scores else 0.0
        score_str = f"{avg_score:.2f}" if avg_score > 0 else "-"
        
        # Sub-identity item. Crow-Eye branch-to-variant icon marks relational
        # sub-grouping; Qt's expand chevron handles children.
        sub_wings = sub_identity.get('wings_found', []) or []
        item = QTreeWidgetItem([
            original_name,
            "", # Time: shown on anchor/record rows
            feather_str,
            score_str,
            "-", # Semantic column (sub-identities don't have semantic values)
            str(evidence),
            f"{len(anchors)} anchors",
            self._format_wings(sub_wings)
        ])
        item.setIcon(0, CrowEyeIcons.sub_identity()) # branch-to-variant: name/version variant
        item.setFont(0, QFont("Segoe UI", 8))
        item.setForeground(0, QBrush(QColor("#FF9800"))) # Orange for sub-identity
        self._decorate_wings_column(item, sub_wings)

        # Color score
        if avg_score >= 0.7:
            item.setForeground(3, QBrush(QColor("#4CAF50")))
        elif avg_score >= 0.4:
            item.setForeground(3, QBrush(QColor("#FF9800")))
        elif avg_score > 0:
            item.setForeground(3, QBrush(QColor("#F44336")))
        
        item.setData(0, Qt.UserRole, {'type': 'sub_identity', 'data': sub_identity})
        
        # Add anchors under sub-identity (numbered 1..N within this sub-identity)
        for anchor_number, anchor in enumerate(anchors, 1):
            item.addChild(self._create_anchor_item(anchor, anchor_number))

        return item

    def _create_anchor_item(self, anchor: Dict, anchor_number: int = 1) -> QTreeWidgetItem:
        """Create anchor tree item with score and time range.

        anchor_number is the anchor's ordinal within its parent identity /
        sub-identity — shown in the "Anchor Number" column.
        """
        start_time = anchor.get('start_time', '')
        end_time = anchor.get('end_time', start_time)
        record_count = anchor.get('record_count', 0)
        
        # Format time display
        if isinstance(start_time, str):
            start_time = start_time[:19] if start_time else ""
        if isinstance(end_time, str):
            end_time = end_time[:19] if end_time else ""
        
        # Show time range if different, otherwise just start time
        if start_time and end_time and start_time != end_time:
            time_display = f"{start_time[:10]} {start_time[11:16]}-{end_time[11:16]}"
        else:
            time_display = start_time
        
        feathers = anchor.get('feathers', [])
        
        # Group feathers by base name (remove numeric suffix)
        base_feathers = set()
        for f in feathers:
            display_name = f.split('/')[-1] if '/' in f else f
            base_name = display_name.rsplit('_', 1)[0] if '_' in display_name and display_name.rsplit('_', 1)[-1].isdigit() else display_name
            base_feathers.add(base_name)
        
        count = anchor.get('evidence_count', len(anchor.get('evidence_rows', [])))
        
        # Get weighted score
        weighted_score = anchor.get('weighted_score', {})
        if isinstance(weighted_score, dict):
            score = weighted_score.get('score', 0)
            interpretation = weighted_score.get('interpretation', '')
            score_str = f"{score:.2f}"
        else:
            score = 0
            interpretation = ''
            score_str = "-"
        
        # Get semantic value for display using the dedicated method
        semantic_value = self._get_semantic_value(anchor)
        
        # Primary artifact/record-count info (moved off the row into the
        # Anchor Number tooltip now that column 6 shows the ordinal)
        artifact_info = anchor.get('primary_artifact', '-')
        if record_count > 0:
            artifact_info = f"{artifact_info} ({record_count} rec)"

        feather_display = ", ".join(sorted(base_feathers)[:2]) + ("..." if len(base_feathers) > 2 else "")

        # Anchor row — anchor+clock icon marks the temporal evidence cluster;
        # Qt's native chevron handles expand state for evidence children.
        item = QTreeWidgetItem([
            f"Anchor {anchor_number}",
            time_display or "-", # Time: the anchor's temporal range
            feather_display,
            score_str,
            semantic_value, # New semantic column
            str(count),
            f"#{anchor_number}", # Anchor Number: this anchor's ordinal
            anchor.get('wing_name') or "-" # Wing that produced this anchor's match
        ])
        item.setIcon(0, CrowEyeIcons.anchor()) # anchor+clock: temporal evidence cluster
        item.setForeground(0, QBrush(QColor("#FFC107")))
        item.setForeground(1, QBrush(QColor("#94A3B8")))
        # Primary artifact type shown in the Anchor Number tooltip
        if artifact_info and artifact_info != '-':
            item.setToolTip(6, f"Primary artifact: {artifact_info}")
        if anchor.get('wing_name'):
            item.setToolTip(7, f"Found by: {anchor['wing_name']}")
        if start_time:
            time_tooltip = f"Start: {start_time}"
            if end_time and end_time != start_time:
                time_tooltip += f"\nEnd:   {end_time}"
            item.setToolTip(1, time_tooltip)

        # Color score and add tooltip
        if score >= 0.7:
            item.setForeground(3, QBrush(QColor("#4CAF50"))) # Green
        elif score >= 0.4:
            item.setForeground(3, QBrush(QColor("#FF9800"))) # Orange
        elif score > 0:
            item.setForeground(3, QBrush(QColor("#F44336"))) # Red
        
        # Build comprehensive tooltip
        tooltip_lines = []
        if start_time:
            tooltip_lines.append(f"Start: {start_time}")
        if end_time and end_time != start_time:
            tooltip_lines.append(f"End: {end_time}")
        if record_count > 0:
            tooltip_lines.append(f"Records: {record_count}")
        
        # Add scoring information
        if score > 0:
            tooltip_lines.append(f"\nScoring:")
            tooltip_lines.append(f" Score: {score:.3f}")
            if interpretation:
                tooltip_lines.append(f" {interpretation}")
        
        # Add confidence information
        confidence_score = anchor.get('confidence_score')
        confidence_category = anchor.get('confidence_category')
        if confidence_score is not None:
            tooltip_lines.append(f" Confidence: {confidence_score:.2f} ({confidence_category or 'Unknown'})")
        
        # Add semantic data if available
        semantic_data = anchor.get('semantic_data')
        if semantic_data and isinstance(semantic_data, dict) and not semantic_data.get('_unavailable'):
            findings = _format_semantic_findings(semantic_data)
            if findings:
                tooltip_lines.append("\nSemantic Mapping:")
                tooltip_lines.extend(findings)
        
        if tooltip_lines:
            item.setToolTip(0, "\n".join(tooltip_lines))
        
        item.setData(0, Qt.UserRole, {'type': 'anchor', 'data': anchor})

        # Records carry their parent anchor's number so the Anchor Number
        # column stays meaningful at the record level too
        for ev in anchor.get('evidence_rows', []):
            item.addChild(self._create_evidence_item(ev, anchor_number))

        return item
    
    def _extract_evidence_time(self, evidence: Dict) -> tuple:
        """Pick the display time for a record: the record's OWN timestamp.

        The PRIMARY (anchor) record is the one the anchor's central time is
        derived from — so for it, the anchor/match timestamp genuinely IS the
        record's own time and is shown. For every SECONDARY record the time
        comes only from that record's own fields; if it carries none the cell
        stays EMPTY (never the anchor's time — a secondary must not be
        presented as if it happened at the anchor's moment). Returns
        (display_str, full_str_or_None).
        """
        # Prefer the value precomputed once in _convert_matches (avoids the
        # per-row field scan during tree building).
        if '_display_time' in evidence:
            return evidence.get('_display_time', ''), evidence.get('_display_time_full')
        return _extract_evidence_display_time(evidence)

    def _create_evidence_item(self, evidence: Dict, anchor_number: int = 1) -> QTreeWidgetItem:
        """Create a record (evidence) tree item.

        anchor_number is the parent anchor's ordinal, echoed in the
        "Anchor Number" column so a record shows which anchor it belongs to.
        """
        # Extract original filename from evidence data
        data = evidence.get('data', {})
        original_name = ""
        
        # Try to get the original filename from various fields
        name_fields = ['name', 'filename', 'file_name', 'fn_filename', 'executable_name', 
                       'Source_Name', 'original_filename', 'app_name', 'value', 'Value',
                       'FileName', 'Name']
        for field in name_fields:
            if field in data and data[field]:
                original_name = str(data[field])
                break
        
        # If no name found, try to extract from path
        if not original_name:
            path_fields = ['path', 'file_path', 'Local_Path', 'app_path', 'full_path', 
                          'reconstructed_path', 'Path', 'FilePath']
            for field in path_fields:
                if field in data and data[field]:
                    path_val = str(data[field])
                    if '\\' in path_val or '/' in path_val:
                        from pathlib import Path
                        original_name = Path(path_val.replace('\\', '/')).name
                        break
        
        # Fallback to artifact type
        if not original_name:
            original_name = evidence.get('artifact', '-')
        
        # Check for semantic info
        semantic_info = evidence.get('semantic_info', {})
        has_semantic = bool(semantic_info)
        
        # Extract semantic value for display
        semantic_value = "-"
        if has_semantic:
            # Get first semantic value
            for field, value in semantic_info.items():
                if value:
                    semantic_value = str(value)
                    break
        
        # Record row — labeled "Record" (NOT the identity's name: repeating
        # the app name here made raw records look like identities). The
        # record's specifics live in the other columns; its source name goes
        # in the tooltip. Wings column blank (record inherits the parent
        # anchor's wing); Time column shows the record's OWN timestamp only.
        evidence_time, evidence_time_full = self._extract_evidence_time(evidence)
        artifact_type = evidence.get('artifact', '-')
        item = QTreeWidgetItem([
            "Record",
            evidence_time, # Time: record's own timestamp, empty when it has none
            evidence.get('feather_id', ''),
            "-", # Score column (records don't have individual scores)
            semantic_value, # New semantic column
            "1",
            f"#{anchor_number}", # Anchor Number: the parent anchor this record belongs to
            "" # Wings: record inherits the parent anchor's wing
        ])
        item.setIcon(0, CrowEyeIcons.evidence()) # record+magnifier: raw artifact record
        item.setForeground(0, QBrush(QColor("#4CAF50")))
        item.setForeground(1, QBrush(QColor("#94A3B8")))
        if evidence_time_full:
            item.setToolTip(1, evidence_time_full)

        # Tooltip: record source name + artifact type + any semantic info
        tooltip_lines = []
        if original_name and original_name != '-':
            tooltip_lines.append(f"Source: {original_name}")
        if artifact_type and artifact_type != '-':
            tooltip_lines.append(f"Artifact: {artifact_type}")
        if has_semantic:
            tooltip_lines.append("Semantic Information:")
            for field, value in semantic_info.items():
                tooltip_lines.append(f" {field}: {value}")
        if tooltip_lines:
            item.setToolTip(0, "\n".join(tooltip_lines))
        
        item.setData(0, Qt.UserRole, {'type': 'evidence', 'data': evidence})
        return item
    
    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle item click to show scoring details.

        Sub-Identity expansion behaviour: clicking a Sub-Identity row cascades
        the expand one level deeper than the default — it opens the Sub-Identity
        itself AND each of its Anchor children, so the user can see the
        underlying evidence (the "identities" beneath each anchor) in a single
        click instead of having to expand every anchor individually. A second
        click on an already-cascaded Sub-Identity collapses the whole subtree.
        """
        data = item.data(0, Qt.UserRole) or {}
        item_type = data.get('type')

        # Toggle expand/collapse when clicking on first column (where the chevron is).
        if column == 0 and item.childCount() > 0:
            if item.isExpanded():
                # Collapse the whole subtree so the next click re-opens
                # cleanly with a single cascade.
                self._set_subtree_expanded(item, False)
            else:
                # Check if cascade expansion is enabled in settings
                cascade_enabled = True # Default
                if self.case_history_manager:
                    cascade_enabled = getattr(self.case_history_manager.global_config, 'cascade_tree_expansion_enabled', True)

                if cascade_enabled:
                    if item_type == 'identity':
                        # Cascade: open Identity + Sub-Identities + Anchors + Evidence
                        # Identity (1) -> Sub-identity (2) -> Anchor (3) -> Evidence (4)
                        self._set_subtree_expanded(item, True, max_depth=4)
                    elif item_type == 'sub_identity':
                        # Cascade: open Sub-Identity + every Anchor child + Evidence
                        # Sub-identity (1) -> Anchor (2) -> Evidence (3)
                        self._set_subtree_expanded(item, True, max_depth=3)
                    else:
                        item.setExpanded(True)
                else:
                    # Standard expansion
                    item.setExpanded(True)
            # After toggling, still fire the selection signal so the
            # detail panel updates to match the row the user clicked.
            if data:
                self.match_selected.emit({'type': item_type, 'data': data.get('data', {})})
            return

        if not data:
            return

        # Emit signal for external handlers
        self.match_selected.emit({'type': item_type, 'data': data.get('data', {})})

    def _set_subtree_expanded(self, item: QTreeWidgetItem, expanded: bool, max_depth: int = 8) -> None:
        """Expand or collapse `item` and recursively apply to its descendants.

        Bounded by `max_depth` to keep the operation fast on giant trees.
        Depth 1 = just this item; depth 2 = this item + its direct children;
        etc. The triangle indicator in column 0 is updated by Qt's
        itemExpanded / itemCollapsed signals, which fire as we walk.
        """
        if item is None or max_depth <= 0:
            return
        item.setExpanded(expanded)
        if max_depth == 1:
            return
        for i in range(item.childCount()):
            child = item.child(i)
            # Only descend into nodes that actually have children — saves work
            # on leaf evidence rows that can never expand.
            if child is not None and child.childCount() > 0:
                self._set_subtree_expanded(child, expanded, max_depth - 1)
    
    def _on_item_expanded(self, item: QTreeWidgetItem):
        """No-op: Qt rotates the native expand chevron automatically."""
        return

    def _on_item_collapsed(self, item: QTreeWidgetItem):
        """No-op: Qt rotates the native expand chevron automatically."""
        return
    
    @staticmethod
    def _collect_rule_results(semantic_data) -> list:
        """Pull rule-result dicts (carrying technique_id/severity) out of an
        anchor's semantic_data, handling every shape the engines write:
        keyed `{value_ruleid: {..., semantic_mappings:[...]}}`, and the
        `semantic_rule_results` / `identity_semantic_results` lists."""
        out = []
        if not isinstance(semantic_data, dict):
            return out
        for key in ('semantic_rule_results', 'identity_semantic_results'):
            lst = semantic_data.get(key)
            if isinstance(lst, list):
                out.extend(r for r in lst if isinstance(r, dict))
        for k, v in semantic_data.items():
            if k in ('semantic_rule_results', 'identity_semantic_results'):
                continue
            if isinstance(v, dict):
                # Top-level entry may carry tags directly
                if v.get('technique_id'):
                    out.append(v)
                for m in v.get('semantic_mappings', []) or []:
                    if isinstance(m, dict) and m.get('technique_id'):
                        out.append(m)
        return out

    def _update_attack_coverage(self):
        """Compute the MITRE ATT&CK coverage across all loaded hits and show
        it in the compact stats-bar label (with a tactic→technique tooltip)."""
        try:
            from ..config.attack_catalog import compute_attack_coverage
            rule_results = []
            seen = set()
            for identity in getattr(self, 'identities', []) or []:
                subs = identity.get('sub_identities', []) or []
                anchor_lists = [s.get('anchors', []) for s in subs] if subs else [identity.get('anchors', [])]
                for anchors in anchor_lists:
                    for anchor in anchors or []:
                        for r in self._collect_rule_results(anchor.get('semantic_data')):
                            # Dedup identical (rule_id, technique_id) contributions
                            key = (r.get('rule_id'), tuple(r.get('technique_id') or []))
                            if key in seen:
                                continue
                            seen.add(key)
                            rule_results.append(r)

            if not rule_results:
                self.attack_lbl.setVisible(False)
                return

            cov = compute_attack_coverage(rule_results)
            n_tech, n_tac = cov['technique_count'], cov['tactic_count']
            if n_tech == 0:
                self.attack_lbl.setVisible(False)
                return

            top = ", ".join(t['technique_id'] for t in cov['techniques'][:3])
            more = f" +{n_tech - 3}" if n_tech > 3 else ""
            self.attack_lbl.setText(f"ATT&CK: {n_tech} tech / {n_tac} tactics — {top}{more}")

            tip = ["MITRE ATT&CK coverage (annotation only)"]
            for tac in cov['tactics']:
                techs = ", ".join(tac['technique_ids'])
                tip.append(f"• {tac['tactic']} [{tac['max_severity']}]: {techs}")
            self.attack_lbl.setToolTip("\n".join(tip))
            self.attack_lbl.setVisible(True)
        except Exception as e:
            logger.warning(f"[IdentityResultsView] ATT&CK coverage failed: {e}")
            try:
                self.attack_lbl.setVisible(False)
            except Exception:
                pass

    def _update_stats(self, results: Dict):
        """Update statistics tables (Types, Roles, Scores only - feather stats are in Summary)."""
        # MITRE ATT&CK coverage rollup (annotation only)
        self._update_attack_coverage()

        # Correlation results (anchors/matches) per wing — counts every wing
        # represented in the viewer (both engine types tag anchors with wing_name).
        wing_counts = {}

        def _count_anchor(anchor, fallback_wings):
            name = anchor.get('wing_name')
            if not name:
                # Anchor lacks a wing name → attribute to the identity's wing(s).
                fw = fallback_wings or []
                name = fw[0] if len(fw) == 1 else 'Unknown Wing'
            wing_counts[name] = wing_counts.get(name, 0) + 1

        for i in self.identities:
            fallback_wings = i.get('wings_found') or []
            sub_identities = i.get('sub_identities', [])
            if sub_identities:
                for sub in sub_identities:
                    for a in sub.get('anchors', []):
                        _count_anchor(a, sub.get('wings_found') or fallback_wings)
            else:
                for a in i.get('anchors', []):
                    _count_anchor(a, fallback_wings)

        # Sort by result count desc, then wing name.
        ordered = sorted(wing_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        self.type_table.setRowCount(len(ordered))
        for row, (wing_name, count) in enumerate(ordered):
            self.type_table.setItem(row, 0, QTableWidgetItem(str(wing_name)))
            self.type_table.setItem(row, 1, QTableWidgetItem(str(count)))
        
        # Evidence roles
        roles = {'Primary': 0, 'Secondary': 0}
        for i in self.identities:
            # Handle both old and new format
            sub_identities = i.get('sub_identities', [])
            if sub_identities:
                for sub in sub_identities:
                    for a in sub.get('anchors', []):
                        for e in a.get('evidence_rows', []):
                            r = e.get('role', 'secondary').capitalize()
                            roles[r] = roles.get(r, 0) + 1
            else:
                for a in i.get('anchors', []):
                    for e in a.get('evidence_rows', []):
                        r = e.get('role', 'secondary').capitalize()
                        roles[r] = roles.get(r, 0) + 1
        
        self.role_table.setRowCount(len(roles))
        for row, (r, c) in enumerate(roles.items()):
            self.role_table.setItem(row, 0, QTableWidgetItem(r))
            self.role_table.setItem(row, 1, QTableWidgetItem(str(c)))
        
        # Scoring statistics
        score_ranges = {'High (≥0.7)': 0, 'Medium (0.4-0.7)': 0, 'Low (<0.4)': 0, 'No Score': 0}
        for i in self.identities:
            sub_identities = i.get('sub_identities', [])
            if sub_identities:
                for sub in sub_identities:
                    for a in sub.get('anchors', []):
                        ws = a.get('weighted_score')
                        if isinstance(ws, dict) and 'score' in ws and isinstance(ws['score'], (int, float)) and 0.0 <= ws['score'] <= 1.0:
                            score = ws['score']
                            if score >= 0.7:
                                score_ranges['High (≥0.7)'] += 1
                            elif score >= 0.4:
                                score_ranges['Medium (0.4-0.7)'] += 1
                            else:
                                score_ranges['Low (<0.4)'] += 1
                        else:
                            score_ranges['No Score'] += 1
            else:
                for a in i.get('anchors', []):
                    ws = a.get('weighted_score')
                    if isinstance(ws, dict) and 'score' in ws and isinstance(ws['score'], (int, float)) and 0.0 <= ws['score'] <= 1.0:
                        score = ws['score']
                        if score >= 0.7:
                            score_ranges['High (≥0.7)'] += 1
                        elif score >= 0.4:
                            score_ranges['Medium (0.4-0.7)'] += 1
                        else:
                            score_ranges['Low (<0.4)'] += 1
                    else:
                        score_ranges['No Score'] += 1
        
        # Update scoring indicator
        total_scored = score_ranges['High (≥0.7)'] + score_ranges['Medium (0.4-0.7)'] + score_ranges['Low (<0.4)']
        if total_scored > 0:
            self.scoring_enabled = True
            self.scoring_lbl.setText(f"Scoring: On ({total_scored})")
            self.scoring_lbl.setStyleSheet("font-size: 7pt; color: #4CAF50;")
        else:
            self.scoring_enabled = False
            self.scoring_lbl.setText("Scoring: Off")
            self.scoring_lbl.setStyleSheet("font-size: 7pt; color: #888;")
        
        # Populate scoring table
        self.scoring_table.setRowCount(len(score_ranges))
        for row, (range_name, count) in enumerate(score_ranges.items()):
            self.scoring_table.setItem(row, 0, QTableWidgetItem(range_name))
            count_item = QTableWidgetItem(str(count))
            # Color code
            if 'High' in range_name:
                count_item.setForeground(QBrush(QColor("#4CAF50")))
            elif 'Medium' in range_name:
                count_item.setForeground(QBrush(QColor("#FF9800")))
            elif 'Low' in range_name:
                count_item.setForeground(QBrush(QColor("#F44336")))
            self.scoring_table.setItem(row, 1, count_item)
    
    # NOTE: an earlier definition of `_on_search_text_changed` was removed here. Python keeps
    # the last one, so it never ran.
    
    def _apply_filters(self):
        """Apply filters with pagination, including semantic value search."""
        text = self.identity_filter.text().lower()
        feather = self.feather_filter.currentText()
        min_ev = int(self.min_filter.currentText())
        
        filtered = []
        for i in self.identities:
            # Search in identity name
            name = i.get('primary_name', '').lower()
            name_match = not text or text in name
            
            # Search in semantic values if name doesn't match
            semantic_match = False
            if text and not name_match:
                # Get all semantic values for this identity
                sub_identities = i.get('sub_identities', [])
                anchors_to_check = []
                if sub_identities:
                    for sub in sub_identities:
                        anchors_to_check.extend(sub.get('anchors', []))
                else:
                    anchors_to_check = i.get('anchors', [])
                
                # Check if search text matches any semantic value using helper
                for anchor in anchors_to_check:
                    semantic_data = anchor.get('semantic_data')
                    if _search_semantic_data(semantic_data, text):
                        semantic_match = True
                        break
            
            # Skip if neither name nor semantic value matches
            if text and not name_match and not semantic_match:
                continue
            
            # Handle both old format (anchors) and new format (sub_identities)
            sub_identities = i.get('sub_identities', [])
            if sub_identities:
                # New format: anchors are inside sub_identities
                all_anchors = []
                for sub in sub_identities:
                    all_anchors.extend(sub.get('anchors', []))
            else:
                # Old format: anchors directly on identity
                all_anchors = i.get('anchors', [])
            
            if feather != "All":
                # Match against base feather name (without numeric suffix)
                has = False
                for a in all_anchors:
                    for f in a.get('feathers', []):
                        # Extract base name from feather
                        display_name = f.split('/')[-1] if '/' in f else f
                        base_name = display_name.rsplit('_', 1)[0] if '_' in display_name and display_name.rsplit('_', 1)[-1].isdigit() else display_name
                        if feather == base_name:
                            has = True
                            break
                    if has:
                        break
                if not has:
                    continue
            
            total = sum(a.get('evidence_count', len(a.get('evidence_rows', []))) for a in all_anchors)
            if total < min_ev:
                continue
            
            filtered.append(i)
        
        self.filtered_identities = filtered
        self.current_page = 0
        self._populate_current_page()
    def _on_search_text_changed(self):
        """Handle search text changes with debouncing."""
        self.search_timer.stop()
        self.search_timer.start()

    
    def _reset_filters(self):
        """Reset filters."""
        self.identity_filter.clear()
        self.feather_filter.setCurrentIndex(0)
        self.min_filter.setCurrentIndex(0)
        self.filtered_identities = self.identities.copy()
        self.current_page = 0
        self._populate_current_page()
    
    def _on_double_click(self, item: QTreeWidgetItem, column: int):
        """Handle double-click — open the detail dialog for the row, never
        letting a data-shape issue surface as an unhandled exception."""
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        try:
            dialog = IdentityDetailDialog(data.get('type'), data.get('data', {}), self)
            dialog.exec_()
        except Exception as e:
            logger.exception("[IdentityResultsView] detail dialog failed to open")
            QMessageBox.warning(
                self, "Detail Unavailable",
                f"Could not open details for this {data.get('type', 'item')}:\n{e}")


class IdentityDetailDialog(QDialog):
    """Compact detail dialog."""
    
    def __init__(self, item_type: str, data: Dict, parent=None):
        super().__init__(parent)
        self.item_type = item_type
        self.data = data
        self.setup_ui()
    
    # Display names for tree levels — the deepest level is a raw artifact
    # RECORD (internally typed 'evidence' for backward compatibility)
    _TYPE_DISPLAY = {
        'identity': 'Identity',
        'sub_identity': 'Sub-Identity',
        'anchor': 'Anchor',
        'evidence': 'Record',
    }

    def setup_ui(self):
        """Setup dialog."""
        display = self._TYPE_DISPLAY.get(self.item_type, self.item_type.capitalize())
        self.setWindowTitle(f"{display} Details")
        self.setMinimumSize(900, 600)
        
        # Get screen size and set maximum to 90%
        from PyQt5.QtWidgets import QDesktopWidget
        screen = QDesktopWidget().screenGeometry()
        max_width = int(screen.width() * 0.9)
        max_height = int(screen.height() * 0.9)
        self.setMaximumSize(max_width, max_height)
        
        # Set initial size to something reasonable
        self.resize(950, 650)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Only add the generic header for anchor and evidence types. Identity
        # and sub-identity build their own header inside their content.
        if self.item_type not in ['identity', 'sub_identity']:
            header = self._create_header()
            layout.addWidget(header)

        # Content
        if self.item_type == 'identity':
            content = self._create_identity_content()
        elif self.item_type == 'sub_identity':
            content = self._create_sub_identity_tab(self.data)
        elif self.item_type == 'anchor':
            content = self._create_anchor_content()
        else:
            content = self._create_evidence_content()
        
        # Ensure content expands to fill available space
        from PyQt5.QtWidgets import QSizePolicy
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(content, stretch=1)
        
        # Close button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setMinimumWidth(100)
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
    
    def _create_header(self) -> QFrame:
        """Create header."""
        frame = QFrame()
        frame.setMaximumHeight(50)
        layout = QHBoxLayout(frame)
        
        if self.item_type == 'identity':
            layout.addWidget(QLabel(f"<b>Identity:</b> {self.data.get('primary_name', 'Unknown')}"))
            layout.addWidget(QLabel(f"<b>Anchors:</b> {len(self.data.get('anchors', []))}"))
        elif self.item_type == 'anchor':
            layout.addWidget(QLabel(f"<b>Time:</b> {self.data.get('start_time', '')}"))
            layout.addWidget(QLabel(f"<b>Feathers:</b> {', '.join(self.data.get('feathers', []))}"))
        else:
            layout.addWidget(QLabel(f"<b>Feather:</b> {self.data.get('feather_id', '')}"))
            layout.addWidget(QLabel(f"<b>Artifact:</b> {self.data.get('artifact', '')}"))
        
        layout.addStretch()
        return frame
    
    def _create_identity_content(self) -> QWidget:
        """Identity content: a SINGLE table of every record across ALL
        sub-identities (no per-feather tabs). Each row is tagged with its
        sub-identity name in the Identity column."""
        sub_identities = self.data.get('sub_identities', []) or []
        specs, timestamps, anchor_count = [], [], 0

        if sub_identities:
            for sub in sub_identities:
                name = sub.get('original_name') or self.data.get('primary_name', 'Unknown')
                anchors = sub.get('anchors', []) or []
                anchor_count += len(anchors)
                timestamps += [a.get('start_time') for a in anchors
                               if isinstance(a, dict) and a.get('start_time')]
                specs.extend(self._row_specs_from_anchors(anchors, name))
        else:
            name = self.data.get('primary_name', 'Unknown')
            anchors = self.data.get('anchors', []) or []
            anchor_count += len(anchors)
            timestamps += [a.get('start_time') for a in anchors
                           if isinstance(a, dict) and a.get('start_time')]
            specs = self._row_specs_from_anchors(anchors, name)

        feathers = sorted({s['feather'] for s in specs if s.get('feather')})
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(6)
        v.addWidget(self._records_header(
            self.data.get('primary_name', 'Unknown'),
            len(sub_identities), anchor_count, len(feathers), timestamps, len(specs)))
        v.addWidget(self._records_table(specs, show_identity=True), stretch=10)
        return container

    @staticmethod
    def _row_specs_from_anchors(anchors, identity_name):
        """Flatten anchors -> evidence rows -> record dicts into flat row specs.
        Handles polymorphic record ``data`` (dict / list-of-dicts / non-dict)."""
        specs = []
        for anchor in anchors or []:
            if not isinstance(anchor, dict):
                continue
            for ev in anchor.get('evidence_rows', []) or []:
                if not isinstance(ev, dict):
                    continue
                feather = _feather_base_name(ev.get('feather_id', ''))
                role = ev.get('role', 'secondary')
                for rec_data in _iter_record_dicts(ev):
                    specs.append({
                        'identity': identity_name,
                        'feather': feather,       # the real artifact (feather name)
                        'role': role,
                        'time': _record_display_time(ev, rec_data),
                        'data': rec_data if isinstance(rec_data, dict) else {},
                    })
        return specs

    @staticmethod
    def _records_header(name, variants, anchors, feathers, timestamps, records):
        parts = [f"<b style='color:#2196F3;'>{name}</b>"]
        if variants:
            parts.append(f"Variants: {variants}")
        parts.append(f"Anchors: {anchors}")
        parts.append(f"Feathers: {feathers}")
        parts.append(f"Records: {records}")
        ts = sorted([str(t)[:19] for t in timestamps if t])
        if ts:
            parts.append(f"Time: {ts[0]} → {ts[-1]}")
        lbl = QLabel(" &nbsp;|&nbsp; ".join(parts))
        lbl.setTextFormat(Qt.RichText)
        lbl.setStyleSheet("font-size: 8pt; color: #aaa; padding: 6px; "
                          "background-color: #1a1a2e; border: 1px solid #333;")
        lbl.setWordWrap(True)
        return lbl

    def _records_table(self, specs, show_identity=True) -> QWidget:
        """Build ONE flat records table from row specs (identity/feather/role/
        time/data), with a live search box. `Artifact` shows the feather (the
        real artifact); `Time` is guaranteed non-empty when the anchor has one."""
        from PyQt5.QtWidgets import QSizePolicy
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        search_box = QLineEdit()
        search_box.setPlaceholderText("Search records...")
        search_box.setStyleSheet("padding: 4px; font-size: 8pt;")
        search_box.setMaximumHeight(30)
        layout.addWidget(search_box)

        # Union of record data fields (skip private/underscore keys).
        all_keys = set()
        for rs in specs:
            d = rs.get('data')
            if isinstance(d, dict):
                all_keys.update(k for k in d.keys() if not str(k).startswith('_'))
        data_cols = sorted(all_keys)
        cols = (['Identity'] if show_identity else []) + ['Artifact', 'Time', 'Role'] + data_cols

        table = QTableWidget()
        table.setColumnCount(len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.setRowCount(len(specs))
        table.setAlternatingRowColors(True)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)

        for row, rs in enumerate(specs):
            c = 0
            if show_identity:
                table.setItem(row, c, QTableWidgetItem(str(rs.get('identity', '')))); c += 1
            table.setItem(row, c, QTableWidgetItem(str(rs.get('feather', '')))); c += 1
            table.setItem(row, c, QTableWidgetItem(str(rs.get('time', '')))); c += 1
            table.setItem(row, c, QTableWidgetItem(str(rs.get('role', 'secondary')).capitalize())); c += 1
            d = rs.get('data') if isinstance(rs.get('data'), dict) else {}
            for key in data_cols:
                val = str(d.get(key, ''))
                item = QTableWidgetItem(val[:80] + '...' if len(val) > 80 else val)
                item.setToolTip(val)
                table.setItem(row, c, item); c += 1

        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.horizontalHeader().setStretchLastSection(True)

        def filter_table(text):
            text = (text or '').lower()
            for r in range(table.rowCount()):
                if not text:
                    table.setRowHidden(r, False)
                    continue
                shown = False
                for cc in range(table.columnCount()):
                    it = table.item(r, cc)
                    if it and text in it.text().lower():
                        shown = True
                        break
                table.setRowHidden(r, not shown)
        search_box.textChanged.connect(filter_table)

        layout.addWidget(table, stretch=10)
        return widget

    def _create_summary_tab(self, sub_identities: list, all_anchors: list, 
                            timestamps: list, feather_records: dict) -> QWidget:
        """Create Summary tab with identity overview."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Identity name header
        name = self.data.get('primary_name', 'Unknown')
        name_lbl = QLabel(f"<h2 style='color: #2196F3;'>{name}</h2>")
        layout.addWidget(name_lbl)
        
        # Statistics frame
        stats_frame = QFrame()
        stats_frame.setStyleSheet("background-color: #1a1a2e; border: 1px solid #333; padding: 8px;")
        stats_layout = QHBoxLayout(stats_frame)
        
        # Sub-identities count
        sub_count = len(sub_identities) if sub_identities else 0
        stats_layout.addWidget(QLabel(f"<b>Variants:</b> {sub_count}"))
        
        # Anchors count
        stats_layout.addWidget(QLabel(f"<b>Anchors:</b> {len(all_anchors)}"))
        
        # Time range
        if timestamps:
            sorted_ts = sorted([t for t in timestamps if t])
            if sorted_ts:
                first = str(sorted_ts[0])[:19]
                last = str(sorted_ts[-1])[:19]
                stats_layout.addWidget(QLabel(f"<b>Time Range:</b> {first} → {last}"))
        
        # Feathers count
        stats_layout.addWidget(QLabel(f"<b>Feathers:</b> {len(feather_records)}"))
        stats_layout.addStretch()
        layout.addWidget(stats_frame)
        
        # Feather contribution table
        feather_group = QGroupBox()
        feather_group.setStyleSheet("""
            QGroupBox { 
                font-size: 9pt; font-weight: bold; color: #aaa;
                padding-top: 12px; margin-top: 8px;
                border: 1px solid #333; background-color: #1a1a2e;
            }
            QGroupBox::title { subcontrol-origin: margin; padding: 0 5px; }
        """)
        feather_layout = QVBoxLayout(feather_group)
        from .crow_eye_icons import group_title_label
        _feather_title = group_title_label("feather", "Feather Contributions", size_px=14)
        _feather_title.setStyleSheet("font-size: 9pt; color: #aaa;")
        feather_layout.addWidget(_feather_title)
        
        # Group feather records by base name
        grouped_feather_records = defaultdict(list)
        for fid, records in feather_records.items():
            # Extract base feather name (remove _number suffix)
            base_name = fid.rsplit('_', 1)[0] if '_' in fid else fid
            grouped_feather_records[base_name].extend(records)
        
        feather_table = QTableWidget()
        feather_table.setColumnCount(2)
        feather_table.setHorizontalHeaderLabels(["Feather", "Records"])
        feather_table.setRowCount(len(grouped_feather_records))
        feather_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        feather_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        feather_table.setAlternatingRowColors(True)
        
        for row, (base_name, records) in enumerate(sorted(grouped_feather_records.items(), 
                                                     key=lambda x: len(x[1]), reverse=True)):
            feather_table.setItem(row, 0, QTableWidgetItem(base_name))
            feather_table.setItem(row, 1, QTableWidgetItem(str(len(records))))
        
        feather_layout.addWidget(feather_table)
        layout.addWidget(feather_group)
        
        # Sub-identities list (if any)
        if sub_identities:
            variants_group = QGroupBox("Filename Variants")
            variants_group.setStyleSheet("""
                QGroupBox { 
                    font-size: 9pt; font-weight: bold; color: #aaa;
                    padding-top: 12px; margin-top: 8px;
                    border: 1px solid #333; background-color: #1a1a2e;
                }
                QGroupBox::title { subcontrol-origin: margin; padding: 0 5px; }
            """)
            variants_layout = QVBoxLayout(variants_group)
            
            variants_table = QTableWidget()
            variants_table.setColumnCount(3)
            variants_table.setHorizontalHeaderLabels(["Original Name", "Anchors", "Feathers"])
            variants_table.setRowCount(len(sub_identities))
            variants_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            variants_table.setAlternatingRowColors(True)
            
            for row, sub in enumerate(sub_identities):
                variants_table.setItem(row, 0, QTableWidgetItem(sub.get('original_name', 'Unknown')))
                variants_table.setItem(row, 1, QTableWidgetItem(str(len(sub.get('anchors', [])))))
                variants_table.setItem(row, 2, QTableWidgetItem(", ".join(sub.get('feathers_found', []))))
            
            variants_layout.addWidget(variants_table)
            layout.addWidget(variants_group)
        
        layout.addStretch()
        return widget
    
    def _create_feather_tab(self, feather_id: str, records: list) -> QWidget:
        """Create tab showing all records from a specific feather with search."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Header - compact, takes minimal space
        header = QLabel(f"<b>{feather_id}</b> - {len(records)} records")
        header.setStyleSheet("font-size: 9pt; color: #aaa; padding: 4px;")
        header.setMaximumHeight(30) # Limit header height
        layout.addWidget(header)
        
        # Search box - compact, takes minimal space
        search_box = QLineEdit()
        search_box.setPlaceholderText("Search records...")
        search_box.setStyleSheet("padding: 4px; font-size: 8pt;")
        search_box.setMaximumHeight(30) # Limit search box height
        layout.addWidget(search_box)
        
        # Collect all unique keys from all records
        all_keys = set()
        for rec in records:
            data = rec.get('data', {})
            if isinstance(data, dict):
                all_keys.update(data.keys())
        
        # Create table with all fields - THIS SHOULD TAKE 75% OF SPACE
        table = QTableWidget()
        cols = ['Timestamp', 'Artifact', 'Role'] + sorted(list(all_keys))
        table.setColumnCount(len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.setRowCount(len(records))
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True) # Enable column sorting
        
        # Set size policy to expand and fill available space
        from PyQt5.QtWidgets import QSizePolicy
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        for row, rec in enumerate(records):
            # Record's OWN timestamp only — never the anchor/match time
            rec_time, _ = _extract_record_own_time(rec.get('data', {}))
            table.setItem(row, 0, QTableWidgetItem(rec_time))
            table.setItem(row, 1, QTableWidgetItem(rec.get('artifact', '')))
            table.setItem(row, 2, QTableWidgetItem(rec.get('role', 'secondary').capitalize()))
            
            data = rec.get('data', {})
            for col, key in enumerate(sorted(list(all_keys)), 3):
                val = str(data.get(key, ''))
                display_val = val[:80] + "..." if len(val) > 80 else val
                item = QTableWidgetItem(display_val)
                item.setToolTip(val) # Full value in tooltip
                table.setItem(row, col, item)
        
        # Enable column resizing
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        
        # Connect search box to filter function
        def filter_table(search_text):
            search_text = search_text.lower()
            for row in range(table.rowCount()):
                match = False
                if not search_text:
                    match = True
                else:
                    for col in range(table.columnCount()):
                        item = table.item(row, col)
                        if item and search_text in item.text().lower():
                            match = True
                            break
                table.setRowHidden(row, not match)
        
        search_box.textChanged.connect(filter_table)
        
        # Add row selection highlighting
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        
        # Add table with stretch factor to take most of the space
        # The stretch factor makes the table expand to fill available space
        layout.addWidget(table, stretch=10) # High stretch factor = takes most space
        
        return widget
    
    def _create_sub_identity_tab(self, sub_identity: Dict) -> QWidget:
        """Sub-identity content: a SINGLE table of every record across all its
        anchors (no per-anchor inner tabs). Same layout as the identity view."""
        name = sub_identity.get('original_name', 'Unknown')
        anchors = sub_identity.get('anchors', []) or []
        specs = self._row_specs_from_anchors(anchors, name)
        timestamps = [a.get('start_time') for a in anchors
                      if isinstance(a, dict) and a.get('start_time')]
        feathers = sorted({s['feather'] for s in specs if s.get('feather')})

        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(6)
        v.addWidget(self._records_header(name, 0, len(anchors), len(feathers), timestamps, len(specs)))
        v.addWidget(self._records_table(specs, show_identity=True), stretch=10)
        return container

    def _create_anchor_table(self, anchor: Dict) -> QWidget:
        """Anchor evidence table — one row per record. Reuses the shared records
        table so it handles polymorphic `data` (dict/list/str) and a filled Time
        column, and shows the feather as the Artifact."""
        specs = []
        for ev in (anchor.get('evidence_rows', []) or []):
            if not isinstance(ev, dict):
                continue
            feather = _feather_base_name(ev.get('feather_id', ''))
            role = ev.get('role', 'secondary')
            for rec_data in _iter_record_dicts(ev):
                specs.append({
                    'feather': feather, 'role': role,
                    'time': _record_display_time(ev, rec_data),
                    'data': rec_data if isinstance(rec_data, dict) else {},
                })
        return self._records_table(specs, show_identity=False)
    
    def _create_anchor_content(self) -> QWidget:
        """Anchor content: the records inside the anchor, plus each record's
        semantic mapping and which rule(s) it matched (and how)."""
        from PyQt5.QtWidgets import QScrollArea

        container = QWidget()
        vlayout = QVBoxLayout(container)
        vlayout.setSpacing(10)
        vlayout.setContentsMargins(4, 4, 4, 4)

        # 1) Records in this anchor (existing raw-record table)
        records_group = QGroupBox("Records in this Anchor")
        records_group.setStyleSheet("""
            QGroupBox {
                font-size: 9pt; font-weight: bold; color: #aaa;
                padding-top: 12px; margin-top: 8px;
                border: 1px solid #333; background-color: #1a1a2e;
            }
            QGroupBox::title { subcontrol-origin: margin; padding: 0 5px; }
        """)
        rg_layout = QVBoxLayout(records_group)
        try:
            rg_layout.addWidget(self._create_anchor_table(self.data))
        except Exception as e:
            logger.exception("[IdentityDetailDialog] anchor records table failed")
            rg_layout.addWidget(QLabel(f"Could not render records: {e}"))
        vlayout.addWidget(records_group)

        # 2) Semantic mapping of the records + which rule(s) they matched
        try:
            vlayout.addWidget(self._create_rule_provenance_section(
                self.data.get('semantic_data', {}),
                self.data.get('evidence_rows', []),
            ))
        except Exception as e:
            logger.exception("[IdentityDetailDialog] rule provenance section failed")
            vlayout.addWidget(QLabel(f"Could not render semantic mapping / rules: {e}"))
        vlayout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: #1a1a2e; }")
        return scroll

    @staticmethod
    def _format_rule_conditions(rule: Dict) -> str:
        """Render a matched rule's conditions in plain English:
        IF a.b equals 'x' AND c.d contains 'y' THEN → "Semantic Value"."""
        conds = [str(c) for c in (rule.get('conditions') or []) if c]
        sv = rule.get('semantic_value', '')
        if conds:
            logic = rule.get('logic_operator', 'AND') or 'AND'
            joined = f" {logic} ".join(conds)
            return f'IF {joined} THEN → "{sv}"'
        return f'→ "{sv}"'

    @staticmethod
    def _extract_semantic_mappings(semantic_data) -> list:
        """Pull the anchor's display-level semantic mappings out of semantic_data,
        handling every shape the engine writes: {field: {semantic_mappings:[...]}},
        {field: {semantic_value: ...}}, and {field: 'value'}. These usually carry
        NO technique_id, so `_collect_rule_results` (rules only) misses them — this
        is what made the dialog say "no semantic mappings" when there were some."""
        out = []
        if not isinstance(semantic_data, dict):
            return out
        for field_name, field_info in semantic_data.items():
            if not isinstance(field_name, str) or field_name.startswith('_'):
                continue
            if field_name in ('semantic_rule_results', 'identity_semantic_results'):
                continue  # rule-result lists are rendered as "Matched rules"
            if isinstance(field_info, dict) and isinstance(field_info.get('semantic_mappings'), list):
                label = field_info.get('identity_type') or field_name
                for m in field_info['semantic_mappings']:
                    if isinstance(m, dict) and m.get('semantic_value'):
                        out.append({
                            'field': str(label),
                            'semantic_value': str(m.get('semantic_value', '')),
                            'rule_name': str(m.get('rule_name', '')),
                            'category': str(m.get('category', '') or ''),
                            'severity': str(m.get('severity', 'info') or 'info'),
                            'confidence': m.get('confidence', ''),
                        })
            elif isinstance(field_info, dict) and field_info.get('semantic_value'):
                out.append({
                    'field': str(field_name),
                    'semantic_value': str(field_info.get('semantic_value', '')),
                    'rule_name': str(field_info.get('rule_name', '')),
                    'category': str(field_info.get('category', '') or ''),
                    'severity': str(field_info.get('severity', 'info') or 'info'),
                    'confidence': field_info.get('confidence', ''),
                })
            elif isinstance(field_info, str) and field_info:
                out.append({'field': str(field_name), 'semantic_value': field_info,
                            'rule_name': '', 'category': '', 'severity': 'info', 'confidence': ''})
        # dedup by (field, semantic_value, rule)
        seen, uniq = set(), []
        for m in out:
            k = (m['field'], m['semantic_value'], m['rule_name'])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(m)
        return uniq

    def _create_rule_provenance_section(self, semantic_data, evidence_rows=None) -> QWidget:
        """Build the "Semantic Mapping & Matched Rules" group: the records'
        field-level semantic mappings and the rule(s) that matched, with each
        rule's conditions/logic shown in plain English."""
        from PyQt5.QtWidgets import QTextEdit

        group = QGroupBox("Semantic Mapping & Matched Rules")
        group.setStyleSheet("""
            QGroupBox {
                font-size: 9pt; font-weight: bold; color: #2196F3;
                padding-top: 12px; margin-top: 8px;
                border: 2px solid #2196F3; background-color: #1a1a2e;
            }
            QGroupBox::title { subcontrol-origin: margin; padding: 0 5px; }
        """)
        layout = QVBoxLayout(group)

        # (0) Anchor-level semantic mappings — the primary "there IS a mapping"
        # source, written onto anchor.semantic_data without a technique_id.
        anchor_mappings = self._extract_semantic_mappings(semantic_data)
        if anchor_mappings:
            layout.addWidget(QLabel("<b>Semantic mappings</b>"))
            amt = QTableWidget()
            amt.setColumnCount(6)
            amt.setHorizontalHeaderLabels(
                ['Field', 'Semantic Value', 'Rule', 'Category', 'Severity', 'Confidence'])
            amt.setRowCount(len(anchor_mappings))
            for r, m in enumerate(anchor_mappings):
                amt.setItem(r, 0, QTableWidgetItem(str(m.get('field', ''))))
                amt.setItem(r, 1, QTableWidgetItem(str(m.get('semantic_value', ''))))
                amt.setItem(r, 2, QTableWidgetItem(str(m.get('rule_name', ''))))
                amt.setItem(r, 3, QTableWidgetItem(str(m.get('category', ''))))
                sev = str(m.get('severity', 'info') or 'info')
                sev_item = QTableWidgetItem(sev.upper())
                if sev == 'high':
                    sev_item.setForeground(QColor('#ff5252'))
                elif sev == 'medium':
                    sev_item.setForeground(QColor('#ffa726'))
                else:
                    sev_item.setForeground(QColor('#66bb6a'))
                amt.setItem(r, 4, sev_item)
                conf = m.get('confidence', '')
                try:
                    conf_str = f"{float(conf):.0%}"
                except (TypeError, ValueError):
                    conf_str = str(conf)
                amt.setItem(r, 5, QTableWidgetItem(conf_str))
            amt.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            amt.horizontalHeader().setStretchLastSection(True)
            amt.setAlternatingRowColors(True)
            amt.setMaximumHeight(200)
            layout.addWidget(amt)

        # (a) Per-record field-level semantic mappings (the record's own mapping).
        # A record's `data` may be a dict, a list of dicts, or a non-dict — never
        # call .get() on it directly (that raised "'str'/'list' has no attribute
        # 'get'"); expand it via _iter_record_dicts first.
        field_rows = []  # (feather, field, raw, semantic)
        for ev in (evidence_rows or []):
            if not isinstance(ev, dict):
                continue
            feather = ev.get('feather_id', '')
            for data in _iter_record_dicts(ev):
                sm = data.get('_semantic_mappings') if isinstance(data, dict) else None
                if isinstance(sm, dict):
                    for field_name, info in sm.items():
                        if isinstance(info, dict) and info.get('semantic_value'):
                            raw = info.get('technical_value', data.get(field_name, ''))
                            field_rows.append((
                                feather, str(field_name),
                                str(raw), str(info.get('semantic_value', '')),
                            ))

        if field_rows:
            layout.addWidget(QLabel("<b>Record field mappings</b>"))
            fmap = QTableWidget()
            fmap.setColumnCount(4)
            fmap.setHorizontalHeaderLabels(['Feather', 'Field', 'Raw Value', 'Semantic Value'])
            fmap.setRowCount(len(field_rows))
            for r, (feather, fld, raw, sem) in enumerate(field_rows):
                fmap.setItem(r, 0, QTableWidgetItem(feather))
                fmap.setItem(r, 1, QTableWidgetItem(fld))
                fmap.setItem(r, 2, QTableWidgetItem(raw))
                fmap.setItem(r, 3, QTableWidgetItem(sem))
            fmap.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            fmap.horizontalHeader().setStretchLastSection(True)
            fmap.setAlternatingRowColors(True)
            fmap.setMaximumHeight(180)
            layout.addWidget(fmap)

        # (b) Matched rules — dedup across the shapes _collect_rule_results returns
        rules = []
        seen = set()
        for r in IdentityResultsView._collect_rule_results(semantic_data):
            # Stringify conditions: some semantic-mapping shapes carry conditions
            # as dicts, which are unhashable and would blow up the set membership.
            key = (r.get('rule_id'), r.get('semantic_value'),
                   tuple(str(c) for c in (r.get('conditions') or [])))
            if key in seen:
                continue
            seen.add(key)
            rules.append(r)

        if rules:
            layout.addWidget(QLabel("<b>Matched rules</b>"))
            rtable = QTableWidget()
            rtable.setColumnCount(6)
            rtable.setHorizontalHeaderLabels([
                'Rule', 'Semantic Value', 'Category', 'Severity', 'Confidence', 'MITRE'
            ])
            rtable.setRowCount(len(rules))
            for r, rule in enumerate(rules):
                rtable.setItem(r, 0, QTableWidgetItem(str(rule.get('rule_name', ''))))
                rtable.setItem(r, 1, QTableWidgetItem(str(rule.get('semantic_value', ''))))
                rtable.setItem(r, 2, QTableWidgetItem(str(rule.get('category', ''))))

                severity = str(rule.get('severity', 'info') or 'info')
                sev_item = QTableWidgetItem(severity.upper())
                if severity == 'high':
                    sev_item.setForeground(QColor('#ff5252'))
                elif severity == 'medium':
                    sev_item.setForeground(QColor('#ffa726'))
                else:
                    sev_item.setForeground(QColor('#66bb6a'))
                rtable.setItem(r, 3, sev_item)

                conf = rule.get('confidence', 0)
                try:
                    conf_str = f"{float(conf):.0%}"
                except (TypeError, ValueError):
                    conf_str = str(conf)
                rtable.setItem(r, 4, QTableWidgetItem(conf_str))

                mitre = ", ".join(str(t) for t in (rule.get('technique_id') or []))
                rtable.setItem(r, 5, QTableWidgetItem(mitre))
            rtable.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            rtable.horizontalHeader().setStretchLastSection(True)
            rtable.setAlternatingRowColors(True)
            rtable.setMaximumHeight(180)
            layout.addWidget(rtable)

            # How each rule matched — conditions in plain English
            layout.addWidget(QLabel("<b>How it matched</b>"))
            explain = QTextEdit()
            explain.setReadOnly(True)
            explain.setMaximumHeight(150)
            explain.setPlainText("\n".join(
                f"• {rule.get('rule_name', '(rule)')}: {self._format_rule_conditions(rule)}"
                for rule in rules
            ))
            layout.addWidget(explain)

        if not anchor_mappings and not field_rows and not rules:
            layout.addWidget(QLabel(
                "No semantic mappings or rule matches were recorded for this anchor."
            ))

        return group

    def _create_evidence_content(self) -> QWidget:
        """Create evidence content with semantic mappings and feather records in table format."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Transform evidence structure to match expected format
        # Evidence from tree: {'feather_id': 'X', 'data': {...}, 'semantic_info': {...}}
        # Expected format: {'feather_records': {'X': {...}}, 'semantic_data': {...}}
        
        feather_id = self.data.get('feather_id', 'Unknown')
        feather_data = self.data.get('data', {}) or {}

        # Build feather_records dict
        feather_records = {feather_id: feather_data} if feather_data else {}

        # Build semantic_data from the record's OWN field-level mappings, which
        # the engine stores under data['_semantic_mappings'] (field -> {semantic_value,
        # technical_value, category, severity, confidence, ...}). The old code read a
        # non-existent 'semantic_info' key, so this section never rendered for records.
        semantic_data = {}
        record_mappings = feather_data.get('_semantic_mappings') if isinstance(feather_data, dict) else None
        if isinstance(record_mappings, dict) and record_mappings:
            mapping_rows = []
            for field_name, info in record_mappings.items():
                if isinstance(info, dict) and info.get('semantic_value'):
                    mapping_rows.append({
                        'semantic_value': str(info.get('semantic_value', '')),
                        'rule_name': str(info.get('rule_name', field_name)),
                        'category': str(info.get('category', 'Unknown') or 'Unknown'),
                        'confidence': info.get('confidence', 1.0),
                        'severity': str(info.get('severity', 'info') or 'info'),
                    })
            if mapping_rows:
                semantic_data[feather_id] = {
                    'identity_type': feather_id,
                    'semantic_mappings': mapping_rows,
                }
        
        # Determine if we have semantic data and feather records to display
        has_semantic_data = bool(semantic_data and isinstance(semantic_data, dict))
        has_feather_records = bool(feather_records and isinstance(feather_records, dict))
        
        # Check if we have semantic_data to display
        if has_semantic_data:
            # Add Semantic Mappings section
            semantic_group = QGroupBox("Semantic Mappings")
            semantic_group.setStyleSheet("""
                QGroupBox { 
                    font-size: 9pt; font-weight: bold; color: #2196F3;
                    padding-top: 12px; margin-top: 8px;
                    border: 2px solid #2196F3; background-color: #1a1a2e;
                }
                QGroupBox::title { subcontrol-origin: margin; padding: 0 5px; }
            """)
            semantic_layout = QVBoxLayout(semantic_group)
            
            # Create semantic mappings table
            semantic_table = QTableWidget()
            semantic_table.setColumnCount(6)
            semantic_table.setHorizontalHeaderLabels([
                'Semantic Value', 'Identity Type', 'Rule Name', 
                'Category', 'Confidence', 'Severity'
            ])
            
            # Count total mappings
            total_mappings = 0
            for entry in semantic_data.values():
                if isinstance(entry, dict) and 'semantic_mappings' in entry:
                    total_mappings += len(entry['semantic_mappings'])
            
            semantic_table.setRowCount(total_mappings)
            
            row = 0
            for key, entry in sorted(semantic_data.items()):
                if isinstance(entry, dict) and 'semantic_mappings' in entry:
                    mappings = entry['semantic_mappings']
                    identity_type = entry.get('identity_type', 'unknown')
                    
                    for mapping in mappings:
                        semantic_table.setItem(row, 0, QTableWidgetItem(mapping.get('semantic_value', '')))
                        semantic_table.setItem(row, 1, QTableWidgetItem(identity_type))
                        semantic_table.setItem(row, 2, QTableWidgetItem(mapping.get('rule_name', '')))
                        semantic_table.setItem(row, 3, QTableWidgetItem(mapping.get('category', '')))
                        
                        confidence = mapping.get('confidence', 0)
                        try:
                            conf_str = f"{float(confidence):.0%}"
                        except (TypeError, ValueError):
                            conf_str = str(confidence)
                        conf_item = QTableWidgetItem(conf_str)
                        semantic_table.setItem(row, 4, conf_item)
                        
                        severity = mapping.get('severity', 'info')
                        sev_item = QTableWidgetItem(severity.upper())
                        # Color code severity
                        if severity == 'high':
                            sev_item.setForeground(QColor('#ff5252'))
                        elif severity == 'medium':
                            sev_item.setForeground(QColor('#ffa726'))
                        else:
                            sev_item.setForeground(QColor('#66bb6a'))
                        semantic_table.setItem(row, 5, sev_item)
                        
                        row += 1
            
            semantic_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            semantic_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            semantic_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            semantic_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
            semantic_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
            semantic_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
            semantic_table.setAlternatingRowColors(True)
            semantic_table.setMaximumHeight(200)
            
            semantic_layout.addWidget(semantic_table)
            # Add with no stretch factor when semantic data exists
            layout.addWidget(semantic_group)
        
        # Check if we have feather_records to display
        if has_feather_records:
            # Add Feather Records section
            feather_group = QGroupBox()
            feather_group.setStyleSheet("""
                QGroupBox { 
                    font-size: 9pt; font-weight: bold; color: #aaa;
                    padding-top: 12px; margin-top: 8px;
                    border: 1px solid #333; background-color: #1a1a2e;
                }
                QGroupBox::title { subcontrol-origin: margin; padding: 0 5px; }
            """)
            feather_layout = QVBoxLayout(feather_group)
            from .crow_eye_icons import group_title_label
            _ce_title = group_title_label("feather", "Feather Records", size_px=14)
            _ce_title.setStyleSheet("font-size: 9pt; color: #aaa;")
            feather_layout.addWidget(_ce_title)
            
            # Create tabs for each feather
            feather_tabs = QTabWidget()
            feather_tabs.setStyleSheet("""
                QTabBar::tab { 
                    font-size: 7pt; 
                    padding: 3px 10px; 
                    background-color: #1a1a2e;
                    color: #777;
                    border: 1px solid #333;
                }
                QTabBar::tab:selected { 
                    background-color: #2a3a5e; 
                    color: #ccc;
                }
            """)
            
            for feather_name, feather_data_item in sorted(feather_records.items()):
                if isinstance(feather_data_item, list) and feather_data_item:
                    # Create table for this feather's records
                    feather_table = self._create_feather_records_table(feather_name, feather_data_item)
                    feather_tabs.addTab(feather_table, f"{feather_name} ({len(feather_data_item)})")
                elif isinstance(feather_data_item, dict):
                    # Single record as dict
                    feather_table = self._create_feather_records_table(feather_name, [feather_data_item])
                    feather_tabs.addTab(feather_table, feather_name)
            
            feather_layout.addWidget(feather_tabs)
            
            # Add with stretch factor 1 to fill remaining space
            # If semantic data exists, this takes remaining space (80%)
            # If no semantic data, this takes all available space (100%)
            layout.addWidget(feather_group, 1)
        
        # Fallback: display basic data if no semantic or feather records
        if not has_semantic_data and not has_feather_records:
            table = QTableWidget()
            table.setColumnCount(2)
            table.setHorizontalHeaderLabels(['Field', 'Value'])
            table.setRowCount(len(self.data))
            
            for row, (k, v) in enumerate(sorted(self.data.items())):
                table.setItem(row, 0, QTableWidgetItem(str(k)))
                val = str(v)[:150]
                item = QTableWidgetItem(val)
                item.setToolTip(str(v))
                table.setItem(row, 1, item)
            
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            table.setAlternatingRowColors(True)
            # Add with stretch factor 1 to fill available space
            layout.addWidget(table, 1)
        
        return widget
    
    def _create_feather_records_table(self, feather_name: str, records: list) -> QWidget:
        """Create a table displaying feather records with vertical layout (fields as rows)."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Handle case where records might be a list with a single dict
        # Database format: {'prefetch': [{'field': 'value', ...}]}
        # Expected format: [{'field': 'value', ...}]
        if records and len(records) == 1 and isinstance(records[0], dict):
            # Check if it's already the correct format (has actual field names)
            first_record = records[0]
            # If it has typical feather fields, it's correct
            if any(key in first_record for key in ['filename', 'executable_name', 'path', 'timestamp', 'name']):
                # Already correct format
                pass
            else:
                # Might be wrapped, but let's use it as-is
                pass
        
        # Collect all unique keys from all records
        all_keys = set()
        for record in records:
            if isinstance(record, dict):
                all_keys.update(record.keys())
        
        # Remove internal/metadata keys
        excluded_keys = {'semantic_data', 'semantic_mappings', '_metadata', '_internal', '_feather_id', '_table'}
        all_keys = sorted([k for k in all_keys if k not in excluded_keys])
        
        # Create table with VERTICAL layout (fields as rows)
        # Columns: Record 1 | Record 2 | ... | Record N
        # Rows: Field names (shown in vertical header)
        table = QTableWidget()
        table.setRowCount(len(all_keys)) # Each field is a row
        table.setColumnCount(len(records)) # One column per record
        
        # Set headers
        headers = [f"Record {i+1}" if len(records) > 1 else "Value" for i in range(len(records))]
        table.setHorizontalHeaderLabels(headers)
        
        # Set vertical headers (field names)
        table.setVerticalHeaderLabels(all_keys)
        
        table.setAlternatingRowColors(True)
        
        # Populate table
        for row, key in enumerate(all_keys):
            # Populate values from each record
            for col, record in enumerate(records):
                if isinstance(record, dict):
                    value = record.get(key, '')
                    
                    # Handle different value types
                    if isinstance(value, (list, dict)):
                        display_val = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
                    else:
                        display_val = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
                    
                    item = QTableWidgetItem(display_val)
                    item.setToolTip(str(value)) # Full value in tooltip
                    table.setItem(row, col, item)
        
        # Enable column resizing
        for i in range(len(records)):
            table.horizontalHeader().setSectionResizeMode(i, QHeaderView.Stretch) # Value columns
        
        # Add row selection highlighting
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        
        layout.addWidget(table)
        return widget