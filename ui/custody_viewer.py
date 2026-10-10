"""Chain-of-custody viewer: one run's record (utils/custody.py), readable.

The record is a JSON file in <case>/logs/ with a SHA-256 beside it. It was only
shown as raw JSON in Settings -> Logs; a live run lists over a thousand
sources there, and nothing said whether the file was still the one written.

CustodyViewerDialog(path)  header card with the integrity check, summary chips,
                           and a tab per section: Sources (filterable,
                           sortable, CSV export), Footprint, Shadow copies,
                           Failures, Warnings, Raw JSON.
latest_record(case_root)   the newest record of a case, for the Case menu.
"""
import csv
import datetime as _dt
import html
import json
import os

from PyQt5 import QtCore, QtGui, QtWidgets

# The site's meaning colours (ui/site_theme.STATUS_COLORS) - same meanings, site tones
GREEN, RED, AMBER, CYAN, SLATE, BLUE = "#4ADE80", "#FDA4AF", "#FBBF24", "#22D3EE", "#94A3B8", "#38BDF8"


def records_in(case_root):
    """Custody record paths of a case, newest first."""
    logs = os.path.join(case_root or "", "logs")
    try:
        names = [n for n in os.listdir(logs) if n.startswith("custody_") and n.endswith(".json")]
    except OSError:
        return []
    return [os.path.join(logs, n) for n in sorted(names, reverse=True)]


def latest_record(case_root):
    found = records_in(case_root)
    return found[0] if found else None


def interrupted_runs(case_root):
    """Run ids with journal parts but no closed record (rebuilt on next case open)."""
    parts = os.path.join(case_root or "", "logs", "custody_parts")
    try:
        runs = sorted(os.listdir(parts))
    except OSError:
        return []
    return [r for r in runs
            if not os.path.exists(os.path.join(case_root, "logs", "custody_%s.json" % r))]


def _size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


def _when(text):
    """'2026-10-08T06:13:34.134776Z' -> '2026-10-08 06:13:34'."""
    if not text:
        return ""
    return str(text).replace("T", " ").rstrip("Z").split(".")[0]


def _duration(a, b):
    try:
        fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
        secs = (_dt.datetime.strptime(b, fmt) - _dt.datetime.strptime(a, fmt)).total_seconds()
    except (TypeError, ValueError):
        return ""
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)


def verdict(entry):
    """(word, colour, explanation) for one source entry."""
    if "copy" in entry:
        v = entry.get("verified")
        if v is True:
            return "Copy verified", GREEN, "The copy's SHA-256 equals the source's."
        if v is False:
            return "MISMATCH", RED, entry.get("mismatch") or "The copy's SHA-256 differs from the source's."
        why = entry.get("copy_hash_error") or entry.get("source_hash_error") or \
            "No independent hash of the source (a raw-disk read or a file locked against a second read)."
        return "Copy not verifiable", AMBER, why
    if entry.get("source_sha256"):
        return "Read in place, hashed", CYAN, "Hashed before the parse read it."
    why = entry.get("note") or entry.get("source_hash_error") or "not hashed"
    return "Read in place, not hashed", SLATE, why


def _os_text(osb):
    """'Windows 11, build 10.0.26300 (AMD64)' from the record's os block.

    It used to join keys the record never writes (product, build) and showed
    '11 10.0.26300'."""
    if not osb:
        return "-"
    name = (osb.get("platform") or "").split("-")[0] or "Windows"
    build = osb.get("windows_build") or osb.get("version") or ""
    text = "%s %s" % (name, osb.get("release") or "")
    if build:
        text += ", build %s" % build
    if osb.get("machine"):
        text += " (%s)" % osb["machine"]
    return text.strip()


def _ledger_details(event, f):
    """One readable line for a ledger entry's fields."""
    def sha(v):
        return (str(v)[:12] + "...") if v else "-"
    try:
        if event == "run started":
            return "%s  -  run %s" % (f.get("kind", ""), f.get("run_id", ""))
        if event == "run ended":
            return "%s  -  %s  (SHA-256 %s)" % (f.get("status", ""), f.get("record", ""),
                                               sha(f.get("record_sha256")))
        if event == "export written":
            return "%s: %s  (%s, SHA-256 %s)" % (f.get("what", ""), f.get("path", ""),
                                                _size(f.get("size")), sha(f.get("sha256")))
        if event == "settings changed":
            ch = f.get("changes") or {}
            return "%s: " % f.get("scope", "settings") + "; ".join(
                "%s %s -> %s" % (k, v[0], v[1]) for k, v in list(ch.items())[:6]) + (
                " ..." if len(ch) > 6 else "")
        if event == "evidence imported":
            return "%s -> %s  (SHA-256 %s)" % (f.get("source", ""), f.get("dest", ""),
                                              sha(f.get("dest_sha256")))
        if event == "evidence import failed":
            return "%s: %s" % (f.get("source", ""), f.get("error", ""))
        if event == "database changed":
            return "%s: %s  -  %s, %ss, %s" % (
                f.get("what", ""), f.get("path", ""),
                "changed" if f.get("changed") else "unchanged", f.get("seconds", ""),
                f.get("outcome", ""))
        if event in ("case opened", "case created"):
            return "Crow-Eye %s%s" % (f.get("tool_version", ""),
                                      ", elevated" if f.get("elevated") else "")
        if event == "image scanned":
            return "%s  (%s, %s partition(s))" % (", ".join(os.path.basename(p) for p in
                                                           f.get("image") or []),
                                                 f.get("format", ""), f.get("partitions", ""))
    except Exception:
        pass
    return json.dumps(f, default=str)[:300]


def _chip(text, color):
    lbl = QtWidgets.QLabel(text)
    lbl.setStyleSheet(
        "QLabel { color: %s; border: 1px solid %s; border-radius: 9px; padding: 4px 12px;"
        " background: transparent; font-size: 13px; font-weight: 700; }" % (color, color))
    lbl.setProperty("keepStyle", True)          # the verdict pill: its colour is the meaning
    return lbl


def _item(texts, numeric=()):
    item = _SortItem([str(t) if t is not None else "" for t in texts])
    for col in numeric:
        item.setTextAlignment(col, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
    return item


class _SortItem(QtWidgets.QTreeWidgetItem):
    """Sorts on a hidden key (size as a number) where one is set."""

    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        a = self.data(col, QtCore.Qt.UserRole)
        b = other.data(col, QtCore.Qt.UserRole)
        if a is not None and b is not None:
            try:
                return float(a) < float(b)
            except (TypeError, ValueError):
                pass
        return self.text(col).lower() < other.text(col).lower()


class CustodyViewerDialog(QtWidgets.QDialog):
    # The verdict next to the path: it is what a reviewer reads first.
    SOURCE_HEADERS = ["Source", "Verdict", "Method", "Size", "Modified (UTC)", "Source SHA-256",
                      "Copy", "Copy SHA-256"]

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle("Crow-Eye - Chain of Custody")
        self.setObjectName("CustodyViewerDialog")
        self.resize(1240, 760)
        self.setMinimumSize(860, 520)
        self.error = None
        try:
            with open(path, encoding="utf-8") as fh:
                self.data = json.load(fh)
        except (OSError, ValueError) as e:
            self.data, self.error = {}, str(e)
        try:
            from utils.custody import verify_record
            self.intact = verify_record(path)
        except Exception:
            self.intact = False
        self.case_root = self.data.get("case_dir") or os.path.dirname(os.path.dirname(path))
        try:
            from ui.site_theme import begin_site_theme
            begin_site_theme(self)              # the sheet before the children exist
        except Exception:
            pass
        self._build()
        self._finish_styling()

    # -- layout ---------------------------------------------------------------------
    def _build(self):
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)
        d = self.data

        top = QtWidgets.QHBoxLayout()
        heading = QtWidgets.QLabel("Chain of Custody")
        try:
            from ui.site_theme import set_role
            set_role(heading, "title")
        except Exception:
            heading.setStyleSheet("QLabel { color: #E2E8F0; font-size: 22px; font-weight: 800; }")
        top.addWidget(heading)
        top.addStretch(1)
        if self.error:
            badge = _chip("Record unreadable", RED)
        elif self.intact:
            badge = _chip("Record intact - SHA-256 matches", GREEN)
            badge.setToolTip("The JSON still hashes to the value written beside it when the run "
                             "closed (%s.sha256)." % os.path.basename(self.path))
        else:
            badge = _chip("Modified after closing - SHA-256 differs", RED)
            badge.setToolTip("The JSON no longer matches %s.sha256, or that file is missing. "
                             "Treat this record as altered." % os.path.basename(self.path))
        badge.setObjectName("integrityBadge")
        top.addWidget(badge)
        lay.addLayout(top)

        if self.error:
            msg = QtWidgets.QLabel("Could not read %s:\n%s" % (self.path, self.error))
            msg.setStyleSheet("QLabel { color: #FCA5A5; font-size: 14px; }")
            lay.addWidget(msg)
            lay.addStretch(1)
            self._buttons(lay)
            return

        lay.addWidget(self._header_card())
        lay.addLayout(self._chips())
        orphans = [r for r in interrupted_runs(self.case_root) if r != d.get("run_id")]
        if orphans:
            note = QtWidgets.QLabel(
                "%d interrupted run(s) have journal parts but no record yet (%s). They are "
                "rebuilt when the case is next opened." % (len(orphans), ", ".join(orphans[:3])
                                                            + (" ..." if len(orphans) > 3 else "")))
            note.setWordWrap(True)
            note.setStyleSheet("QLabel { color: %s; font-size: 13px; }" % AMBER)
            lay.addWidget(note)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._sources_tab(), "Sources (%d)" % len(d.get("sources") or []))
        if d.get("artifacts"):
            self.tabs.addTab(self._artifacts_tab(), "Artifacts (%d)" % len(d.get("artifacts") or []))
        self.tabs.addTab(self._outputs_tab(), "Outputs (%d)" % len(d.get("outputs") or []))
        self.tabs.addTab(self._footprint_tab(), "Footprint (%d)" % len(d.get("footprint") or []))
        self.tabs.addTab(self._shadow_tab(), "Shadow copies (%d)" % len(d.get("shadow_copies") or []))
        self.tabs.addTab(self._failures_tab(), "Failures (%d)" % len(d.get("failures") or []))
        self.tabs.addTab(self._warnings_tab(), "Warnings (%d)" % len(d.get("warnings") or []))
        ledger_tab, n_ledger = self._ledger_tab()
        self.tabs.addTab(ledger_tab, "Case ledger (%d)" % n_ledger)
        self.tabs.addTab(self._raw_tab(), "Raw JSON")
        lay.addWidget(self.tabs, 1)
        self._buttons(lay)

    def _header_card(self):
        d = self.data
        card = QtWidgets.QFrame()
        card.setObjectName("custodyCard")
        card.setProperty("card", True)          # the site card
        grid = QtWidgets.QGridLayout(card)
        grid.setContentsMargins(14, 10, 14, 10)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(4)
        tool = d.get("tool") or {}
        host = d.get("host") or {}
        osb = d.get("os") or {}
        status = d.get("status") or "?"
        status_col = {"completed": GREEN, "cancelled": AMBER, "interrupted": AMBER}.get(status, RED)
        os_text = _os_text(osb)
        env = d.get("environment") or {}
        libs = env.get("libraries") or {}
        env_text = ";  ".join(x for x in (
            ("time zone %s (UTC%s)" % (env.get("timezone"), env.get("utc_offset")))
            if env.get("timezone") else "",
            ("locale %s" % env.get("locale")) if env.get("locale") else "",
            ("%d decoding libraries - hover" % len(libs)) if libs else "") if x) or "-"
        rows = [
            ("Run", "%s  -  %s" % (d.get("run_id", ""), d.get("kind", ""))),
            ("Status", "<span style='color:%s;font-weight:700'>%s</span>" % (status_col, html.escape(status))),
            ("Examiner", "%s on %s%s" % (d.get("examiner", ""), host.get("name", ""),
                                         "  (elevated)" if d.get("elevated") else "  (not elevated)")),
            ("Tool", "%s %s  -  %s, Python %s" % (tool.get("name", "Crow-Eye"), tool.get("version", ""),
                                                  "packaged build" if tool.get("frozen") else "from source",
                                                  tool.get("python", ""))),
            ("Started (UTC)", _when(d.get("started_utc"))),
            ("Finished (UTC)", "%s   (%s)" % (_when(d.get("finished_utc")),
                                             _duration(d.get("started_utc"), d.get("finished_utc")))),
            ("Operating system", os_text),
            ("Options", ", ".join("%s=%s" % kv for kv in (d.get("options") or {}).items()) or "-"),
            ("Case", d.get("case_dir") or ""),
            ("Output", d.get("output_dir") or "-"),
            ("Environment", env_text),
            ("Temporary files", d.get("temp_dir") or "-"),
        ]
        per_col = (len(rows) + 1) // 2
        for i, (k, v) in enumerate(rows):
            key = QtWidgets.QLabel(k)
            key.setStyleSheet("QLabel { color: #94A3B8; font-size: 12px; font-weight: 700; }")
            val = QtWidgets.QLabel(v if k == "Status" else html.escape(str(v)))
            val.setTextFormat(QtCore.Qt.RichText)
            val.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            val.setStyleSheet("QLabel { color: #E2E8F0; font-size: 13px; }")
            if k == "Environment" and libs:
                val.setToolTip("<br>".join("%s %s" % (html.escape(n), html.escape(str(v)))
                                           for n, v in sorted(libs.items())))
            r, c = i % per_col, (i // per_col) * 2
            grid.addWidget(key, r, c)
            grid.addWidget(val, r, c + 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        return card

    def _chips(self):
        d = self.data
        s = d.get("sources") or []
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        verified = sum(1 for e in s if e.get("verified") is True)
        mismatch = sum(1 for e in s if e.get("verified") is False)
        unverif = sum(1 for e in s if "copy" in e and e.get("verified") is None)
        in_place_hashed = sum(1 for e in s if "copy" not in e and e.get("source_sha256"))
        not_hashed = sum(1 for e in s if "copy" not in e and not e.get("source_sha256"))
        shadows = d.get("shadow_copies") or []
        created = sum(1 for v in shadows if v.get("action") == "created")
        try:
            from utils.custody import _left_behind
            left = len(_left_behind(shadows))
        except Exception:
            left = 0
        processes = sum(1 for f in d.get("footprint") or [] if f.get("kind") == "process")
        row.addWidget(_chip("Sources  %d" % len(s), BLUE))
        if in_place_hashed or not_hashed:
            row.addWidget(_chip("Read in place, hashed  %d" % in_place_hashed, CYAN))
            row.addWidget(_chip("Not hashed  %d" % not_hashed, SLATE))
        if verified or mismatch or unverif:
            row.addWidget(_chip("Copies verified  %d" % verified, GREEN))
            if mismatch:
                row.addWidget(_chip("Mismatched  %d" % mismatch, RED))
            if unverif:
                row.addWidget(_chip("Not verifiable  %d" % unverif, AMBER))
        row.addWidget(_chip("Failures  %d" % len(d.get("failures") or []),
                            RED if d.get("failures") else SLATE))
        row.addWidget(_chip("Processes  %d" % processes, SLATE))
        if created or left:
            row.addWidget(_chip("Shadow copies  %d created, %d left behind" % (created, left),
                                RED if left else GREEN))
        row.addStretch(1)
        return row

    def _tree(self, headers, widths=()):
        tree = QtWidgets.QTreeWidget()
        tree.setHeaderLabels(headers)
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setSortingEnabled(True)
        tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        # Paths keep both ends (drive and file name) when cut.
        tree.setTextElideMode(QtCore.Qt.ElideMiddle)
        for i, w in enumerate(widths):
            tree.setColumnWidth(i, w)
        return tree

    def _sources_tab(self):
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(0, 8, 0, 0)
        bar = QtWidgets.QHBoxLayout()
        self.source_filter = QtWidgets.QLineEdit()
        self.source_filter.setPlaceholderText("Filter by path, method or hash...")
        self.source_filter.textChanged.connect(self._apply_source_filter)
        bar.addWidget(self.source_filter, 1)
        self.problems_only = QtWidgets.QCheckBox("Problems only")
        self.problems_only.setToolTip("Mismatched copies, copies that could not be verified, and "
                                      "sources read without a hash")
        self.problems_only.toggled.connect(self._apply_source_filter)
        bar.addWidget(self.problems_only)
        self.source_count = QtWidgets.QLabel("")
        self.source_count.setStyleSheet("QLabel { color: #94A3B8; }")
        bar.addWidget(self.source_count)
        v.addLayout(bar)
        tree = self._tree(self.SOURCE_HEADERS, (430, 190, 110, 80, 150, 170, 220, 170))
        tree.setSortingEnabled(False)
        for e in self.data.get("sources") or []:
            word, colour, why = verdict(e)
            times = e.get("times") or {}
            item = _item([e.get("source", ""), word, e.get("method", ""), _size(times.get("size")),
                          _when(times.get("modified_utc")), e.get("source_sha256", ""),
                          e.get("copy", ""), e.get("copy_sha256", "")], numeric=(3,))
            item.setData(3, QtCore.Qt.UserRole, times.get("size") or 0)
            item.setForeground(1, QtGui.QBrush(QtGui.QColor(colour)))
            tip = [html.escape(e.get("source", ""))]
            if e.get("read_from"):
                tip.append("Read from: %s" % html.escape(e["read_from"]))
            if e.get("shadow_copy_id"):
                tip.append("Shadow copy %s (created %s UTC)" % (
                    html.escape(e["shadow_copy_id"]), html.escape(_when(e.get("shadow_copy_created_utc")))))
            tip.append("<b style='color:%s'>%s</b>: %s" % (colour, word, html.escape(why)))
            if times.get("created_utc"):
                tip.append("Created %s, accessed %s UTC" % (_when(times.get("created_utc")),
                                                             _when(times.get("accessed_utc"))))
            item.setToolTip(0, "<br>".join(tip))
            item.setToolTip(1, "<br>".join(tip))
            item.setData(0, QtCore.Qt.UserRole + 1, word)
            tree.addTopLevelItem(item)
        tree.setSortingEnabled(True)
        tree.sortByColumn(0, QtCore.Qt.AscendingOrder)
        self.sources_tree = tree
        v.addWidget(tree, 1)
        self._apply_source_filter()
        return page

    def _apply_source_filter(self, *_):
        text = (self.source_filter.text() or "").lower()
        problems = self.problems_only.isChecked()
        shown = 0
        tree = self.sources_tree
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            word = item.data(0, QtCore.Qt.UserRole + 1) or ""
            ok = not problems or word in ("MISMATCH", "Copy not verifiable", "Read in place, not hashed")
            if ok and text:
                ok = any(text in item.text(c).lower() for c in (0, 1, 2, 5, 6, 7))
            item.setHidden(not ok)
            shown += ok
        self.source_count.setText("%d of %d" % (shown, tree.topLevelItemCount()))

    def _footprint_tab(self):
        tree = self._tree(["Kind", "What", "Purpose", "Return code", "PID", "Process", "Recorded (UTC)"],
                          (90, 520, 220, 90, 70, 120, 150))
        for f in self.data.get("footprint") or []:
            rc = f.get("returncode")
            item = _item([f.get("kind", ""), f.get("detail", ""), f.get("purpose", ""),
                          "" if rc is None else rc, f.get("pid", "") or "",
                          f.get("process") or "main", _when(f.get("recorded_utc"))])
            if rc not in (None, 0, "0"):
                item.setForeground(3, QtGui.QBrush(QtGui.QColor(AMBER)))
            item.setToolTip(1, html.escape(str(f.get("detail", ""))))
            tree.addTopLevelItem(item)
        # Honest about what it knows: an empty list means nothing was RECORDED.
        # A record from before the worker journals existed said "nothing was
        # started" for a run that had started PowerShell to create a snapshot.
        return self._or_empty(tree, "No process, service or file outside the case was recorded "
                                    "for this run.")

    def _artifacts_tab(self):
        tree = self._tree(["Artifact", "Outcome", "Records", "New", "Already present", "Message"],
                          (200, 150, 100, 90, 130, 560))
        for a in self.data.get("artifacts") or []:
            status = str(a.get("status") or "")
            item = _item([a.get("artifact", "") or a.get("name", ""), status or a.get("status", ""),
                          a.get("records", a.get("files", "")),
                          "" if a.get("inserted") is None else "{:,}".format(a["inserted"]),
                          "" if a.get("duplicates") is None else "{:,}".format(a["duplicates"]),
                          (a.get("error") or a.get("message", "")) if status in ("FAILED", "PARTIAL")
                          else (a.get("message", "") or "; ".join(a.get("errors") or []))],
                         numeric=(2, 3, 4))
            if a.get("log_excerpt"):
                item.setToolTip(5, "<pre>%s</pre>" % html.escape("\n".join(a["log_excerpt"][-20:])))
            item.setData(2, QtCore.Qt.UserRole, a.get("records") or a.get("files") or 0)
            colour = (GREEN if status in ("PARSED", "success", "completed") else
                      SLATE if status in ("NO_RECORDS", "SOURCE_NOT_FOUND", "FEATURE_DISABLED",
                                          "NOT_RUN") else AMBER if status in (
                          "PARTIAL", "ACCESS_DENIED", "UNSUPPORTED_FORMAT", "DEPENDENCY_MISSING")
                      else RED)
            item.setForeground(1, QtGui.QBrush(QtGui.QColor(colour)))
            if not a.get("log_excerpt"):
                item.setToolTip(5, html.escape(str(item.text(5))))
            tree.addTopLevelItem(item)
        return self._or_empty(tree, "No per-artifact outcome was recorded for this run.")

    def _outputs_tab(self):
        tree = self._tree(["File", "Kind", "Size", "Modified (UTC)", "SHA-256", "Note"],
                          (430, 80, 90, 150, 470, 200))
        for o in self.data.get("outputs") or []:
            item = _item([o.get("path", ""), o.get("kind", ""), _size(o.get("size")),
                          _when(o.get("modified_utc")), o.get("sha256", ""),
                          o.get("note") or o.get("hash_error") or o.get("error") or ""], numeric=(2,))
            item.setData(2, QtCore.Qt.UserRole, o.get("size") or 0)
            tree.addTopLevelItem(item)
        return self._or_empty(tree, "This record lists no output files (runs recorded before "
                                    "Crow-Eye hashed its outputs, or a run that wrote none).")

    def _ledger_tab(self):
        """The case's ledger (every run, export, import and settings change),
        with the result of walking its hash chain."""
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(0, 8, 0, 0)
        try:
            from utils import custody
            entries = custody.read_ledger(self.case_root)
            check = custody.verify_ledger(self.case_root)
        except Exception as e:
            entries, check = [], {"ok": False, "problems": ["Ledger not readable: %s" % e], "notes": []}
        if not entries:
            v.addWidget(self._or_empty(QtWidgets.QListWidget(),
                                       "This case has no ledger yet: it starts with the next case "
                                       "open, run, export or import."))
            return page, 0
        if check.get("ok"):
            badge = _chip("Ledger intact - %d entries, hash chain verified" % len(entries), GREEN)
        else:
            badge = _chip("Ledger altered - %d problem(s)" % len(check.get("problems") or []), RED)
        badge.setObjectName("ledgerBadge")
        top = QtWidgets.QHBoxLayout()
        top.addWidget(badge)
        top.addStretch(1)
        v.addLayout(top)
        for text, colour in ([(p, "#FCA5A5") for p in check.get("problems") or []]
                             + [(n, SLATE) for n in check.get("notes") or []])[:12]:
            lbl = QtWidgets.QLabel(text)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("QLabel { color: %s; font-size: 12px; }" % colour)
            v.addWidget(lbl)
        tree = self._tree(["#", "Time (UTC)", "Event", "Details", "Examiner", "Host"],
                          (50, 150, 150, 640, 100, 120))
        colours = {"run started": BLUE, "run ended": GREEN, "export written": CYAN,
                   "evidence imported": CYAN, "evidence import failed": RED,
                   "settings changed": AMBER, "database changed": AMBER,
                   "case opened": SLATE, "case created": SLATE, "image scanned": SLATE}
        for e in entries:
            if "damaged" in e:
                item = _item(["?", "", "damaged line", e["damaged"], "", ""])
                item.setForeground(2, QtGui.QBrush(QtGui.QColor(RED)))
                tree.addTopLevelItem(item)
                continue
            fields = e.get("fields") or {}
            item = _item([e.get("seq", ""), _when(e.get("utc")), e.get("event", ""),
                          _ledger_details(e.get("event"), fields), e.get("examiner", ""),
                          e.get("host", "")], numeric=(0,))
            item.setData(0, QtCore.Qt.UserRole, e.get("seq") or 0)
            item.setForeground(2, QtGui.QBrush(QtGui.QColor(colours.get(e.get("event"), SLATE))))
            item.setToolTip(3, "<pre>%s</pre>" % html.escape(
                json.dumps(fields, indent=1, default=str)[:4000]))
            tree.addTopLevelItem(item)
        tree.sortByColumn(0, QtCore.Qt.DescendingOrder)
        self.ledger_tree = tree
        v.addWidget(tree, 1)
        return page, len(entries)

    def _shadow_tab(self):
        tree = self._tree(["Action", "Shadow copy", "Volume", "Created (UTC)", "Result", "Recorded (UTC)",
                           "Detail"], (120, 300, 80, 150, 120, 150, 300))
        try:
            from utils.custody import _left_behind
            left = set(_left_behind(self.data.get("shadow_copies") or []))
        except Exception:
            left = set()
        colours = {"created": BLUE, "used-existing": CYAN, "deleted": GREEN, "delete-failed": RED,
                   "evicted-by-windows": AMBER}
        for v in self.data.get("shadow_copies") or []:
            action = v.get("action", "")
            sid = v.get("shadow_copy_id", "") or ""
            item = _item([action, sid, v.get("volume", ""), _when(v.get("created_utc")),
                          "ok" if v.get("ok", True) else "failed", _when(v.get("recorded_utc")),
                          v.get("detail", "") or v.get("command", "")])
            item.setForeground(0, QtGui.QBrush(QtGui.QColor(colours.get(action, SLATE))))
            if sid in left and action == "created":
                item.setText(4, "LEFT BEHIND")
                item.setForeground(4, QtGui.QBrush(QtGui.QColor(RED)))
            tree.addTopLevelItem(item)
        tree.sortByColumn(5, QtCore.Qt.AscendingOrder)
        return self._or_empty(tree, "No shadow copy was recorded as created or used in this run.")

    def _failures_tab(self):
        tree = self._tree(["Source", "Reason", "Method", "Status", "Recorded (UTC)"],
                          (380, 520, 110, 130, 150))
        for f in self.data.get("failures") or []:
            item = _item([f.get("source", ""), f.get("reason", ""), f.get("method", "") or "",
                          f.get("status", "") or "", _when(f.get("recorded_utc"))])
            item.setForeground(1, QtGui.QBrush(QtGui.QColor("#FCA5A5")))
            item.setToolTip(1, html.escape(str(f.get("reason", ""))))
            tree.addTopLevelItem(item)
        return self._or_empty(tree, "No failure was recorded for this run.")

    def _warnings_tab(self):
        lst = QtWidgets.QListWidget()
        lst.setWordWrap(True)
        for w in self.data.get("warnings") or []:
            it = QtWidgets.QListWidgetItem(str(w))
            it.setForeground(QtGui.QBrush(QtGui.QColor("#FDE68A")))
            lst.addItem(it)
        return self._or_empty(lst, "No warnings.")

    def _raw_tab(self):
        view = QtWidgets.QPlainTextEdit()
        view.setReadOnly(True)
        view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        try:
            from ui.site_theme import log_view_sheet, keep_style
            view.setStyleSheet(log_view_sheet())
            keep_style(view)
        except Exception:
            pass
        try:
            with open(self.path, encoding="utf-8") as fh:
                view.setPlainText(fh.read())
        except OSError as e:
            view.setPlainText(str(e))
        try:
            from ui.log_highlighter import LogHighlighter
            self._raw_hl = LogHighlighter(view.document(), json_mode=True)
        except Exception:
            pass
        return view

    def _or_empty(self, widget, text):
        count = widget.topLevelItemCount() if isinstance(widget, QtWidgets.QTreeWidget) else widget.count()
        if count:
            return widget
        lbl = QtWidgets.QLabel(text)
        lbl.setAlignment(QtCore.Qt.AlignCenter)
        lbl.setStyleSheet("QLabel { color: #94A3B8; font-size: 14px; }")
        return lbl

    def _buttons(self, lay):
        row = QtWidgets.QHBoxLayout()
        self.export_btn = QtWidgets.QPushButton("Export sources (CSV)")
        self.export_btn.clicked.connect(self._export_csv)
        self.export_btn.setEnabled(not self.error)
        row.addWidget(self.export_btn)
        folder = QtWidgets.QPushButton("Open logs folder")
        folder.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(os.path.dirname(self.path))))
        row.addWidget(folder)
        hint = QtWidgets.QLabel("%s  -  checked against %s.sha256" % (
            os.path.basename(self.path), os.path.basename(self.path)))
        hint.setStyleSheet("QLabel { color: #64748B; font-size: 12px; }")
        row.addWidget(hint, 1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)

    # -- actions ------------------------------------------------------------------------
    def export_csv(self, out_path):
        """Every source with its hashes and verdict; returns the row count."""
        rows = 0
        with open(out_path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["source", "method", "size", "created_utc", "modified_utc", "accessed_utc",
                        "source_sha256", "copy", "copy_sha256", "verdict", "explanation", "read_from",
                        "shadow_copy_id", "recorded_utc"])
            for e in self.data.get("sources") or []:
                word, _c, why = verdict(e)
                t = e.get("times") or {}
                w.writerow([e.get("source", ""), e.get("method", ""), t.get("size", ""),
                            t.get("created_utc", ""), t.get("modified_utc", ""), t.get("accessed_utc", ""),
                            e.get("source_sha256", ""), e.get("copy", ""), e.get("copy_sha256", ""),
                            word, why, e.get("read_from", ""), e.get("shadow_copy_id", ""),
                            e.get("recorded_utc", "")])
                rows += 1
        return rows

    def _export_csv(self):
        default = os.path.join(os.path.dirname(self.path),
                               "custody_%s_sources.csv" % self.data.get("run_id", "run"))
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export sources", default, "CSV (*.csv)")
        if not path:
            return
        try:
            n = self.export_csv(path)
            QtWidgets.QMessageBox.information(self, "Export sources", "%d source(s) written to\n%s" % (n, path))
        except OSError as e:
            QtWidgets.QMessageBox.warning(self, "Export sources", "Could not write the file:\n%s" % e)

    def _finish_styling(self):
        """The site look: the cleared inline sheets read back into roles, the
        buttons in the role family, the trees in Parse Status' readable size.
        (No QSS font-weight on tabs: it clipped their labels.)"""
        try:
            from styles import CrowEyeStyles as _CES
            _CES.give_window_a_taskbar_button(self)
        except Exception:
            pass
        try:
            from ui.site_theme import apply_site_theme, set_variant
            from ui.parse_status_dialog import _readable
            apply_site_theme(self)
            for b in self.findChildren(QtWidgets.QPushButton):
                if b.property("variant") is None:
                    set_variant(b, "ghost")
            _readable(self)
        except Exception:
            pass
