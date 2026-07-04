"""
Extraction of structured fields from parsed Windows event-log rows.

The WinLog parser stores each event's EventData values as a comma-joined
string in the ``Keywords`` column (the ``EventDescription`` column only
holds the template sentence, e.g. "An account was successfully logged on.").
Field meaning is therefore positional per Event ID, matching the EventData
order of that event type. Verified against real case rows:

  4624: S-1-5-18,DAN$,WORKGROUP,0x3e7,S-1-5-18,SYSTEM,NT AUTHORITY,0x3e7,5,...
  4634: S-1-5-21-...-1001,Gass3,DAN,0x5fc1d,7
  4688: S-1-5-18,-,-,0x3e7,0x398,C:\\Windows\\System32\\lsass.exe,%%1936,...

Fields that can themselves contain commas (command lines, privilege lists)
are only ever recovered by anchoring from the payload's stable head/tail —
positions after such a field are never trusted blindly. Any parse failure
returns an empty dict; callers treat that as "no attribution" (never guess).
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

LOGON_TYPE_LABELS = {
    "2": "local interactive logon",
    "3": "network logon",
    "4": "scheduled batch logon",
    "5": "service logon",
    "7": "workstation unlock",
    "8": "network cleartext logon",
    "9": "run-as with new credentials",
    "10": "remote desktop logon",
    "11": "cached interactive logon",
}

# Logon types that prove a human was at the keyboard / remote console.
INTERACTIVE_LOGON_TYPES = {"2", "7", "10", "11"}


def _split(keywords) -> List[str]:
    if not keywords or keywords in ("N/A", "-"):
        return []
    return [p.strip() for p in str(keywords).split(",")]


def parse_4624(keywords) -> Dict[str, str]:
    """Successful logon. Returns target account + logon type + logon id."""
    parts = _split(keywords)
    if len(parts) < 9:
        return {}
    info = {
        "subject_sid": parts[0],
        "target_sid": parts[4],
        "target_user": parts[5],
        "target_domain": parts[6],
        "logon_id": parts[7],
        "logon_type": parts[8],
        "logon_type_label": LOGON_TYPE_LABELS.get(parts[8], "logon type {}".format(parts[8])),
    }
    # ProcessName sits at a stable position before any comma-capable field.
    if len(parts) > 17 and ("\\" in parts[17] or parts[17] == "-"):
        info["process_name"] = parts[17]
    return info


def parse_4634(keywords) -> Dict[str, str]:
    """Logoff. Payload: TargetUserSid, TargetUserName, TargetDomainName,
    TargetLogonId, LogonType."""
    parts = _split(keywords)
    if len(parts) < 5:
        return {}
    return {
        "target_sid": parts[0],
        "target_user": parts[1],
        "target_domain": parts[2],
        "logon_id": parts[3],
        "logon_type": parts[4],
    }


def parse_4688(keywords) -> Dict[str, str]:
    """Process creation. CommandLine (idx 8) may contain commas, so the
    fields after it are anchored from the tail: the payload ends with
    TargetUserSid, TargetUserName, TargetDomainName, TargetLogonId,
    ParentProcessName, MandatoryLabel (6 fields)."""
    parts = _split(keywords)
    if len(parts) < 15:
        return {}
    info = {
        "subject_sid": parts[0],
        "subject_user": parts[1],
        "subject_domain": parts[2],
        "logon_id": parts[3],
        "new_process_name": parts[5],
        "command_line": ",".join(parts[8:-6]).strip(),
        "parent_process_name": parts[-2],
    }
    # Sanity: process paths must look like paths (or be empty placeholders).
    for key in ("new_process_name", "parent_process_name"):
        value = info.get(key, "")
        if value and value != "-" and "\\" not in value and "/" not in value:
            info.pop(key, None)
    return info


def parse_4648(keywords) -> Dict[str, str]:
    """Explicit-credential logon (run-as)."""
    parts = _split(keywords)
    if len(parts) < 7:
        return {}
    return {
        "subject_sid": parts[0],
        "subject_user": parts[1],
        "subject_domain": parts[2],
        "target_user": parts[5],
        "target_domain": parts[6],
    }


def parse_4672(keywords) -> Dict[str, str]:
    """Special privileges assigned to new logon."""
    parts = _split(keywords)
    if len(parts) < 4:
        return {}
    return {
        "subject_sid": parts[0],
        "subject_user": parts[1],
        "subject_domain": parts[2],
        "logon_id": parts[3],
    }


def parse_4798_4799(keywords) -> Dict[str, str]:
    """User's local group membership / security group membership enumerated.
    Payload: TargetUserName, TargetDomainName, TargetSid, SubjectUserSid,
    SubjectUserName, SubjectDomainName, SubjectLogonId, CallerProcessId,
    CallerProcessName."""
    parts = _split(keywords)
    if len(parts) < 7:
        return {}
    info = {
        "target_user": parts[0],
        "subject_sid": parts[3],
        "subject_user": parts[4],
    }
    if len(parts) >= 9 and ("\\" in parts[-1] or parts[-1] == "-"):
        info["caller_process"] = parts[-1]
    return info


_ACCOUNT_SID_RE = None  # lazy


def parse_account_target(keywords) -> Dict[str, str]:
    """Account-management events that name a target account and the subject
    who acted on it (4720 created, 4722 enabled, 4724 password-reset,
    4725 disabled, 4726 deleted, 4738 changed).

    The field order differs between events (4738 carries a leading dummy
    field that 4720/4724 do not), so anchor on the SIDs instead of fixed
    positions: TargetSid is the first account/well-known SID; TargetUserName
    is two tokens before it; SubjectUserSid is the next SID after it and
    SubjectUserName the token following that. Verified against real 4720
    (`Gass3,Dan,S-1-5-21-…-1001,S-1-5-18,DAN$,…`) and 4738
    (`-,Gass3,Dan,S-1-5-21-…-1001,S-1-5-18,DAN$,…`)."""
    parts = _split(keywords)
    if len(parts) < 5:
        return {}
    import re
    sid_re = re.compile(r"^S-1-\d")
    sid_idx = [i for i, p in enumerate(parts) if sid_re.match(p)]
    if len(sid_idx) < 2:
        # Fall back to the simple layout.
        return {"target_user": parts[0], "target_sid": parts[2] if len(parts) > 2 else "",
                "subject_sid": parts[3] if len(parts) > 3 else "",
                "subject_user": parts[4] if len(parts) > 4 else ""}
    t_sid_i = sid_idx[0]
    s_sid_i = sid_idx[1]
    return {
        "target_user": parts[t_sid_i - 2] if t_sid_i >= 2 else "",
        "target_sid": parts[t_sid_i],
        "subject_sid": parts[s_sid_i],
        "subject_user": parts[s_sid_i + 1] if s_sid_i + 1 < len(parts) else "",
    }


def parse_group_member(keywords) -> Dict[str, str]:
    """Member added to a group (4732 local, 4728 global).

    Payload (verified): MemberName, MemberSid, TargetGroupName,
    TargetDomainName, TargetSid, SubjectUserSid, SubjectUserName, ...
    e.g. '-,S-1-5-21-…-1001,Administrators,Builtin,S-1-5-32-544,S-1-5-18,DAN$,…'
    """
    parts = _split(keywords)
    if len(parts) < 7:
        return {}
    return {
        "member_name": parts[0],
        "member_sid": parts[1],
        "group_name": parts[2],
        "subject_sid": parts[5],
        "subject_user": parts[6],
    }


PARSERS = {
    4624: parse_4624,
    4634: parse_4634,
    4688: parse_4688,
    4648: parse_4648,
    4672: parse_4672,
    4798: parse_4798_4799,
    4799: parse_4798_4799,
    4720: parse_account_target,
    4722: parse_account_target,
    4724: parse_account_target,
    4725: parse_account_target,
    4726: parse_account_target,
    4738: parse_account_target,
    4728: parse_group_member,
    4732: parse_group_member,
}


def parse_payload(event_id, keywords) -> Dict[str, str]:
    """Parse the Keywords payload for a supported Event ID.

    Returns {} for unsupported ids or malformed payloads — callers must
    treat an empty result as "attribution unavailable".
    """
    parser = PARSERS.get(int(event_id) if event_id is not None else -1)
    if not parser:
        return {}
    try:
        return parser(keywords)
    except Exception as e:  # defensive: never let a payload crash the engine
        logger.debug("UBA: payload parse failed for EID %s: %s", event_id, e)
        return {}
