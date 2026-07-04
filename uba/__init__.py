"""
UBA (User Behavior Analytics) package for Crow-Eye.

Reads the parsed artifact databases in a case's Target_Artifacts/ directory,
executes the declarative behavior rule set (Master Behavioral Timeline
Correlation Matrix) and presents a manager/HR-readable activity view in a
React window (QWebEngineView + QWebChannel), styled like the Eye window.

Forensic guarantees:
- Source databases are only ever opened read-only (file:...?mode=ro).
- Every emitted activity carries evidence provenance (db / table / rowid).
- Actor attribution never guesses: User / Application / System or EMPTY.
"""

__version__ = "0.1.0"
