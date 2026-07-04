"""
SID normalization and classification for actor attribution.

Real-case data quirks handled here:
- SRUM rows sometimes store SIDs as ``PySID:S-1-5-...`` (parser artifact) —
  the prefix is stripped.
- Well-known SIDs (S-1-5-18/19/20, window manager, font driver host, ...)
  identify the operating system or a service, never a human user.
- Machine accounts (``NAME$``) and pseudo accounts (DWM-1, UMFD-0) reported
  in event logs are system actors.
"""

import re
from typing import Optional

_PYSID_PREFIX = "PySID:"

# Exact well-known SIDs -> friendly label
WELL_KNOWN_SIDS = {
    "S-1-5-18": "Local System",
    "S-1-5-19": "Local Service",
    "S-1-5-20": "Network Service",
    "S-1-0-0": "Nobody",
    "S-1-5-7": "Anonymous",
}

# SID prefixes that always denote OS/service principals
_SYSTEM_SID_PREFIXES = (
    "S-1-5-80-",   # service SIDs
    "S-1-5-90-",   # Window Manager (DWM)
    "S-1-5-96-",   # Font Driver Host (UMFD)
    "S-1-5-32-",   # BUILTIN groups
    "S-1-16-",     # mandatory integrity labels
    "S-1-5-6",     # Service
)

# Account names in event logs that are never humans
_SYSTEM_ACCOUNT_NAMES = {
    "SYSTEM", "LOCAL SERVICE", "NETWORK SERVICE", "ANONYMOUS LOGON",
    "BUILTIN", "N/A", "-", "",
}
_PSEUDO_ACCOUNT_RE = re.compile(r"^(DWM|UMFD)-\d+$", re.IGNORECASE)

_HUMAN_SID_RE = re.compile(r"^S-1-5-21-\d+-\d+-\d+-(\d+)$")

# RIDs below 1000 in the S-1-5-21 domain are built-in (Administrator=500,
# Guest=501, ...). They are still accounts a human can use, so they remain
# human candidates; well-known service RIDs do not appear in this range.


def normalize_sid(sid) -> str:
    """Strip parser artifacts and whitespace; return '' for non-values."""
    if not sid:
        return ""
    sid = str(sid).strip()
    if sid.startswith(_PYSID_PREFIX):
        sid = sid[len(_PYSID_PREFIX):].strip()
    if sid in ("-", "N/A"):
        return ""
    return sid


def classify_sid(sid) -> str:
    """Classify a SID as 'system' | 'human_candidate' | 'unknown'.

    'human_candidate' means the SID has the local/domain account shape
    (S-1-5-21-...) — whether it maps to a real person is decided by the
    UserProfiles lookup, never assumed here.
    """
    sid = normalize_sid(sid)
    if not sid:
        return "unknown"
    if sid in WELL_KNOWN_SIDS:
        return "system"
    for prefix in _SYSTEM_SID_PREFIXES:
        if sid.startswith(prefix):
            return "system"
    if _HUMAN_SID_RE.match(sid):
        return "human_candidate"
    return "unknown"


def is_machine_account(account_name) -> bool:
    """Machine accounts end with '$' (e.g. 'DAN$', 'DESKTOP-BGU9AOP$')."""
    return bool(account_name) and str(account_name).strip().endswith("$")


def is_system_account_name(account_name) -> bool:
    """True when the event-log account name denotes the OS or a service."""
    if account_name is None:
        return False
    name = str(account_name).strip()
    if is_machine_account(name):
        return True
    if name.upper() in _SYSTEM_ACCOUNT_NAMES:
        return True
    return bool(_PSEUDO_ACCOUNT_RE.match(name))


def is_human_account_name(account_name) -> bool:
    """True when the name could plausibly belong to a person.

    Note: 'could plausibly' — attribution still requires corroboration
    (UserProfiles / SID match); this only rejects obvious system names.
    """
    if account_name is None:
        return False
    name = str(account_name).strip()
    return bool(name) and not is_system_account_name(name)


def well_known_label(sid) -> Optional[str]:
    return WELL_KNOWN_SIDS.get(normalize_sid(sid))
