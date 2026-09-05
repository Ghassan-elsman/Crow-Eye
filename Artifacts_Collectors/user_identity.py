"""Canonical user identity for the registry parsers.

One implementation, imported by BOTH the live parser and the offline parser, so
a machine yields the same account list and the same user names whichever way it
was acquired. That parity is the point: this module deliberately works from hive
FILES via python-registry rather than from the live API.

Two rules it exists to enforce:

1. **Never resolve a SID against the analyst's machine.** `LookupAccountSid`
   answers about the host running Crow-Eye, not about the evidence. Names here
   come from the evidence: SAM for account names, ProfileList for profile paths,
   and the SYSTEM hive for the computer name.

2. **HKLM\\SAM is unreadable via winreg even when elevated** (WinError 5). The
   collector already copies SAM out (`crow_claw` collects
   `{PARTITION}\\Windows\\System32\\config\\SAM`), so both paths read that copy.
   When collection has not run, the live parser exports SAM to a TEMPORARY file
   for the duration of the parse - see `live_sam_hive()`. It must never write a
   hive into the case: producing collected artifacts is the collector's job, and
   `Target_Artifacts/Registry_Hives` is the collector's output directory.
   Without SAM the account list still builds from ProfileList alone, and `source`
   records what was available.
"""
import contextlib
import logging
import os
import shutil
import struct
import tempfile

try:
    from Registry import Registry
    REGISTRY_AVAILABLE = True
except ImportError:                                     # pragma: no cover
    REGISTRY_AVAILABLE = False
    logging.warning("python-registry not available - SAM account data will be skipped")

try:
    from Artifacts_Collectors import registry_transaction_log
except ModuleNotFoundError:                           # pragma: no cover
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from Artifacts_Collectors import registry_transaction_log

try:
    from Artifacts_Collectors import registry_binary_parser
except ModuleNotFoundError:                             # pragma: no cover
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from Artifacts_Collectors import registry_binary_parser

try:
    from utils.time_utils import format_forensic_timestamp, get_current_utc
except ModuleNotFoundError:                             # pragma: no cover
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.time_utils import format_forensic_timestamp, get_current_utc

BS = chr(92)            # backslash, kept out of the f-strings below

# Service accounts: real SIDs, but not people. Constant across every Windows box.
WELL_KNOWN_SIDS = {
    "S-1-5-18": ("SYSTEM", "Local System"),
    "S-1-5-19": ("LOCAL SERVICE", "Local Service"),
    "S-1-5-20": ("NETWORK SERVICE", "Network Service"),
}

# Group and logon-type SIDs that turn up as members of a local group but are
# not accounts. Kept apart from WELL_KNOWN_SIDS on purpose: that map decides
# how UserAccounts classifies a SID, and these do not belong in an account
# list - "Authenticated Users is in Users" is a membership fact, not a person.
WELL_KNOWN_GROUP_SIDS = {
    "S-1-1-0": "Everyone",
    "S-1-2-0": "LOCAL",
    "S-1-2-1": "CONSOLE LOGON",
    "S-1-5-2": "NT AUTHORITY\\NETWORK",
    "S-1-5-4": "NT AUTHORITY\\INTERACTIVE",
    "S-1-5-6": "NT AUTHORITY\\SERVICE",
    "S-1-5-7": "NT AUTHORITY\\ANONYMOUS LOGON",
    "S-1-5-9": "NT AUTHORITY\\ENTERPRISE DOMAIN CONTROLLERS",
    "S-1-5-11": "NT AUTHORITY\\Authenticated Users",
    "S-1-5-13": "NT AUTHORITY\\TERMINAL SERVER USER",
    "S-1-5-14": "NT AUTHORITY\\REMOTE INTERACTIVE LOGON",
    "S-1-5-15": "NT AUTHORITY\\This Organization",
    "S-1-5-17": "NT AUTHORITY\\IUSR",
    "S-1-5-18": "NT AUTHORITY\\SYSTEM",
    "S-1-5-19": "NT AUTHORITY\\LOCAL SERVICE",
    "S-1-5-20": "NT AUTHORITY\\NETWORK SERVICE",
    "S-1-5-32-544": "BUILTIN\\Administrators",
    "S-1-5-32-545": "BUILTIN\\Users",
    "S-1-5-32-546": "BUILTIN\\Guests",
    "S-1-5-32-555": "BUILTIN\\Remote Desktop Users",
    "S-1-5-32-562": "BUILTIN\\Distributed COM Users",
    "S-1-5-32-580": "BUILTIN\\Remote Management Users",
    "S-1-5-113": "NT AUTHORITY\\Local account",
    "S-1-5-114": "NT AUTHORITY\\Local account and member of Administrators group",
}

# Built-in accounts, identified by RID rather than by name - the names are
# localised and Administrator/Guest can be renamed, but the RID never changes.
WELL_KNOWN_RIDS = {
    500: "Built-in Administrator",
    501: "Built-in Guest",
    502: "KRBTGT",
    503: "Default Account",
    504: "WDAG Utility Account",
}

PROFILE_LIST = BS.join(["Microsoft", "Windows NT", "CurrentVersion", "ProfileList"])


def _open(hive_path):
    if not hive_path or not REGISTRY_AVAILABLE or not os.path.exists(hive_path):
        return None
    try:
        # Recovered copy when the logs apply, the original otherwise.
        return Registry.Registry(
            registry_transaction_log.hive_for_reading(hive_path))
    except Exception as e:
        logging.warning("Could not open hive %s: %s", hive_path, e)
        return None


def get_active_controlset_name(system_hive):
    """'ControlSetNNN' for the control set the machine last booted from.

    CurrentControlSet is a runtime alias that does not exist in an offline hive;
    Select/Current names the real one.
    """
    reg = _open(system_hive)
    if not reg:
        return "ControlSet001"
    try:
        for v in reg.open("Select").values():
            if v.name() == "Current":
                return "ControlSet%03d" % v.value()
    except Exception as e:
        logging.debug("Select/Current unreadable: %s", e)
    return "ControlSet001"


def get_machine_name(system_hive):
    """NetBIOS computer name, read from the EVIDENCE's SYSTEM hive."""
    reg = _open(system_hive)
    if not reg:
        return ""
    cs = get_active_controlset_name(system_hive)
    try:
        key = reg.open(BS.join([cs, "Control", "ComputerName", "ComputerName"]))
        for v in key.values():
            if v.name() == "ComputerName":
                return str(v.value())
    except Exception as e:
        logging.debug("ComputerName unreadable: %s", e)
    return ""


def get_machine_sid(sam_hive):
    """The machine SID, from the Account domain's V value.

    The last 12 bytes are the three sub-authorities. A local account's SID is
    this plus '-<RID>'.
    """
    reg = _open(sam_hive)
    if not reg:
        return ""
    try:
        key = reg.open(BS.join(["SAM", "Domains", "Account"]))
        for v in key.values():
            if v.name() == "V":
                data = v.value()
                if data and len(data) >= 12:
                    a, b, c = struct.unpack("<III", data[-12:])
                    return "S-1-5-21-%d-%d-%d" % (a, b, c)
    except Exception as e:
        logging.debug("Machine SID unreadable: %s", e)
    return ""


def _sam_accounts(sam_hive):
    """[{rid, username, full_name, comment, ...}] from SAM, or []."""
    reg = _open(sam_hive)
    if not reg:
        return []
    out = []
    try:
        users = reg.open(BS.join(["SAM", "Domains", "Account", "Users"]))
    except Exception as e:
        logging.debug("SAM Users unreadable: %s", e)
        return []

    for key in users.subkeys():
        if key.name() == "Names":
            continue
        try:
            key_rid = int(key.name(), 16)
        except ValueError:
            continue

        v_data = f_data = None
        for v in key.values():
            if v.name() == "V":
                v_data = v.value()
            elif v.name() == "F":
                f_data = v.value()

        strings = registry_binary_parser.parse_user_account_v_value(v_data) if v_data else {}
        facts = registry_binary_parser.parse_user_account_f_value(f_data) if f_data else {}

        # The RID in F must match the key name. A mismatch means the offsets do
        # not fit this hive, so the rest of the record cannot be trusted - say so
        # rather than writing plausible-looking numbers.
        f_rid = facts.get("rid", 0)
        trusted = (f_rid == key_rid)
        if f_data and not trusted:
            logging.warning(
                "SAM F record for RID %d reports RID %d - offsets do not fit this "
                "hive; timestamps and counters dropped", key_rid, f_rid)

        acct = {
            "rid": key_rid,
            "username": strings.get("username", ""),
            "full_name": strings.get("full_name", ""),
            "comment": strings.get("comment", ""),
            "last_logon": facts.get("last_logon", "") if trusted else "",
            "password_last_set": facts.get("password_last_set", "") if trusted else "",
            "account_expires": facts.get("account_expires", "") if trusted else "",
            "last_incorrect_password": facts.get("last_incorrect_password", "") if trusted else "",
            "login_count": facts.get("login_count", 0) if trusted else 0,
            "bad_password_count": facts.get("bad_password_count", 0) if trusted else 0,
            "account_flags": facts.get("account_flags", "") if trusted else "",
            "account_enabled": facts.get("account_enabled", 0) if trusted else None,
        }
        out.append(acct)
    return out


def _sam_aliases(sam_hive):
    """[{scope, rid, name, comment, members, ...}] of local groups, or [].

    Two scopes hold aliases and both matter: Builtin carries Administrators and
    Remote Desktop Users, while Account carries groups an installer created
    (docker-users, __vmware__). Reading only Builtin would miss the second set
    entirely, and reading only Account would miss the ones that matter most.
    """
    reg = _open(sam_hive)
    if not reg:
        return []
    out = []
    for scope, base in (("Builtin", ["SAM", "Domains", "Builtin", "Aliases"]),
                        ("Account", ["SAM", "Domains", "Account", "Aliases"])):
        try:
            aliases = reg.open(BS.join(base))
        except Exception as e:
            logging.debug("SAM %s aliases unreadable: %s", scope, e)
            continue
        for key in aliases.subkeys():
            # Names/ maps a group name to its RID and Members/ is an index; the
            # per-RID subkeys are the records.
            if key.name() in ("Names", "Members"):
                continue
            try:
                key_rid = int(key.name(), 16)
            except ValueError:
                continue
            c_data = None
            for v in key.values():
                if v.name() == "C":
                    c_data = v.value()
            if not isinstance(c_data, bytes):
                continue
            parsed = registry_binary_parser.parse_alias_c_value(c_data)
            if not parsed:
                continue
            if parsed.get("rid") != key_rid:
                logging.warning(
                    "SAM alias C record under %s reports RID %s - offsets do "
                    "not fit this hive; skipped", key.name(), parsed.get("rid"))
                continue
            try:
                last_write = format_forensic_timestamp(key.timestamp())
            except Exception:
                last_write = ""
            parsed.update({"scope": scope, "last_write": last_write})
            out.append(parsed)
    return out


def _profile_list(software_hive):
    """{sid: profile_path} from ProfileList, or {}."""
    reg = _open(software_hive)
    if not reg:
        return {}
    out = {}
    try:
        pl = reg.open(PROFILE_LIST)
    except Exception as e:
        logging.debug("ProfileList unreadable: %s", e)
        return {}
    for key in pl.subkeys():
        path = ""
        for v in key.values():
            if v.name() == "ProfileImagePath":
                path = str(v.value())
        out[key.name()] = path
    return out


def _profile_list_live():
    """{sid: profile_path} read from the running system's ProfileList.

    Only used when no SOFTWARE hive copy is available. ProfileList is a
    machine-wide key describing THIS machine, so reading it live is sound - the
    thing that must never happen is resolving a SID from an image against the
    live host, and that is a different operation.
    """
    out = {}
    try:
        import winreg
    except ImportError:
        return out
    try:
        flags = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        # PROFILE_LIST is hive-relative (the SOFTWARE hive file IS "SOFTWARE").
        # Through winreg the same key needs the SOFTWARE\ prefix, and without it
        # the open fails silently and every account looks unresolved.
        live_path = "SOFTWARE" + BS + PROFILE_LIST
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, live_path, 0, flags) as key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                sid = winreg.EnumKey(key, i)
                try:
                    with winreg.OpenKey(key, sid, 0, flags) as sub:
                        path, _ = winreg.QueryValueEx(sub, "ProfileImagePath")
                        out[sid] = str(path)
                except OSError:
                    out[sid] = ""
    except OSError as e:
        logging.debug("Live ProfileList unreadable: %s", e)
    return out


def _machine_name_live():
    """This machine's NetBIOS name, for the live path only."""
    name = os.environ.get("COMPUTERNAME", "")
    if name:
        return name
    try:
        import socket
        return socket.gethostname().split(".")[0].upper()
    except Exception:
        return ""


def _account_type(sid, rid):
    if sid in WELL_KNOWN_SIDS:
        return "service"
    if rid in WELL_KNOWN_RIDS:
        return "built-in"
    return "local"


def build_user_accounts(sam_hive=None, software_hive=None, system_hive=None,
                        allow_live_fallback=False):
    """Merge SAM and ProfileList into one account list.

    Returns (accounts, sid_to_display_name).

    Accounts appear even when they have never logged on and own no profile - a
    built-in Administrator that suddenly shows a logon count is exactly the sort
    of thing that matters, and it is invisible if the list is profile-driven.
    """
    machine = get_machine_name(system_hive)
    machine_sid = get_machine_sid(sam_hive)
    profiles = _profile_list(software_hive)
    sam = _sam_accounts(sam_hive)
    stamp = format_forensic_timestamp(get_current_utc())

    # Live fallback: with no collected SOFTWARE/SYSTEM hive there is nothing to
    # read, and the account list would otherwise be empty on a live run. Only
    # reached when the corresponding hive is absent, so an offline parse - which
    # always supplies hives - can never fall through to the analyst's machine.
    if allow_live_fallback:
        if not profiles:
            profiles = _profile_list_live()
        if not machine:
            machine = _machine_name_live()
        if not machine_sid:
            # Derive it from any local profile SID: strip the trailing RID.
            for sid in profiles:
                if sid.startswith("S-1-5-21-"):
                    machine_sid = sid.rsplit("-", 1)[0]
                    break

    def display(name, sid=None):
        # Service accounts are domain-qualified NT AUTHORITY, not machine
        # accounts: "NT AUTHORITY\SYSTEM", never "MACHINE\SYSTEM".
        if not name:
            return ""
        if sid in WELL_KNOWN_SIDS:
            return "NT AUTHORITY" + BS + name
        return (machine + BS + name) if machine else name

    accounts = {}

    # 1. SAM first - it is the authority on names, flags and logon counts.
    for a in sam:
        sid = ("%s-%d" % (machine_sid, a["rid"])) if machine_sid else ""
        rec = dict(a)
        rec["user_sid"] = sid
        rec["display_name"] = display(a["username"], sid)
        rec["account_type"] = _account_type(sid, a["rid"])
        rec["well_known"] = WELL_KNOWN_RIDS.get(a["rid"], "")
        rec["profile_path"] = profiles.get(sid, "")
        rec["profile_loaded"] = 1 if profiles.get(sid) else 0
        rec["source"] = "SAM"
        rec["parsed_at"] = stamp
        accounts[sid or ("RID-%d" % a["rid"])] = rec

    # 2. ProfileList adds anyone SAM does not describe: domain accounts, and
    #    the service profiles.
    for sid, path in profiles.items():
        if sid in accounts:
            accounts[sid]["source"] = "SAM+ProfileList"
            continue
        name = WELL_KNOWN_SIDS.get(sid, (os.path.basename(path.rstrip(BS)) if path else "", ""))[0]
        try:
            rid = int(sid.rsplit("-", 1)[-1])
        except (ValueError, AttributeError):
            rid = 0
        accounts[sid] = {
            "user_sid": sid,
            "rid": rid,
            "username": name,
            "display_name": display(name, sid),
            "full_name": "", "comment": "",
            "account_type": _account_type(sid, rid),
            "well_known": WELL_KNOWN_SIDS.get(sid, ("", ""))[1] or WELL_KNOWN_RIDS.get(rid, ""),
            "account_enabled": None,
            "account_flags": "",
            "last_logon": "", "password_last_set": "", "account_expires": "",
            "last_incorrect_password": "",
            "login_count": 0, "bad_password_count": 0,
            "profile_path": path,
            "profile_loaded": 1 if path else 0,
            "source": "ProfileList",
            "parsed_at": stamp,
        }

    sid_to_name = {sid: rec["display_name"]
                   for sid, rec in accounts.items() if rec.get("display_name")}
    return list(accounts.values()), sid_to_name


def identify_ntuser_hive(hive_path):
    """Which user does this NTUSER.DAT belong to? Returns a username or ''.

    Needed because every user's hive is collected under the same base name, so
    the filename carries no attribution once they are in one directory.

    Order matters, most reliable first:

    1. `Explorer\\Shell Folders` - the EXPANDED profile paths
       (C:\\Users\\jcloudy\\Desktop). `User Shell Folders` is the wrong key: it
       stores %USERPROFILE%\\Desktop, which names nobody.
    2. The path the hive was collected from, when it retains the profile
       directory (\\Users\\<name>\\NTUSER.DAT).

    `Volatile Environment` looks ideal and is not: it is volatile, so it is
    absent from every hive read off disk.
    """
    reg = _open(hive_path)
    if reg:
        try:
            key = reg.open(BS.join(["Software", "Microsoft", "Windows",
                                    "CurrentVersion", "Explorer", "Shell Folders"]))
            for v in key.values():
                val = str(v.value() or "")
                low = val.lower()
                marker = BS + "users" + BS
                if marker in low:
                    rest = val[low.index(marker) + len(marker):]
                    name = rest.split(BS)[0].strip()
                    if name:
                        return name
        except Exception as e:
            logging.debug("Shell Folders unreadable in %s: %s", hive_path, e)

    # Path fallback, and it must be strict: only when the hive sits DIRECTLY in
    # a profile directory (.../Users/<name>/NTUSER.DAT).
    #
    # Scanning the whole path for a "Users" component is unsafe - a hive staged
    # under C:\Users\<analyst>\AppData\Local\Temp\<case>\ matches the ANALYST,
    # and evidence gets attributed to the examiner. Observed doing exactly that.
    parts = os.path.normpath(hive_path or "").split(os.sep)
    if len(parts) >= 3 and parts[-3].lower() == "users":
        return parts[-2]
    return ""


# What a row means when no user applies to it at all.
#
# Distinct from unattributed_label, which says "this hive has an owner and we
# could not resolve it". A machine-wide autostart key - HKLM Lsa, BootExecute,
# print monitors - has no owner to resolve, and leaving the cell blank makes
# "no user applies" look identical to "attribution failed". They are different
# findings and must not read the same.
MACHINE_WIDE_LABEL = "(machine-wide)"


def machine_wide_label():
    """The user_name a machine-wide row carries."""
    return MACHINE_WIDE_LABEL


# The hives under HKEY_USERS that belong to no human. .DEFAULT is the profile
# that applies before anyone logs on - a genuine persistence location, and one
# neither parser read until now - and the three well-known service SIDs are the
# accounts Windows itself runs as.
#
# They get their own names rather than a resolved account name, because these
# rows sit in the same per-user tables as real user activity and "LocalSystem
# opened this document" and "Ghassan opened this document" must never look
# alike. Deliberately distinct from MACHINE_WIDE_LABEL: a value under
# HKU\S-1-5-18 was set for an account, not for the machine.
SYSTEM_ACCOUNT_LABELS = {
    ".DEFAULT": "(.DEFAULT profile)",
    "S-1-5-18": "(LocalSystem)",
    "S-1-5-19": "(LocalService)",
    "S-1-5-20": "(NetworkService)",
}


def system_account_label(sid_or_key):
    """The label for a non-human HKU key, or "" if it is a real account.

    Callers use the empty return as "resolve this one normally", so a SID this
    does not recognise still goes through the usual account lookup.
    """
    return SYSTEM_ACCOUNT_LABELS.get(str(sid_or_key or "").strip(), "")


def is_system_account_key(sid_or_key):
    """Whether an HKEY_USERS subkey name is one of the non-human hives."""
    return str(sid_or_key or "").strip() in SYSTEM_ACCOUNT_LABELS


def unattributed_label(hive_path):
    """What a hive whose owner cannot be resolved is called.

    Not an empty string. An image can legitimately contain a hive with no owner -
    the Default profile template (C:\\Users\\Default\\NTUSER.DAT) is the common
    one, and it does hold values - and '' reads as a parser that failed rather
    than as a finding. Naming the file keeps the row usable and makes it
    impossible to mistake for a real account's activity.
    """
    base = os.path.basename(hive_path or "") or "unknown hive"
    return "(unattributed: %s)" % base


def display_owner(hive_path, accounts):
    """The FINAL user_name a hive's rows should carry: 'MACHINE\\username'.

    Must agree with what apply_identity() normalises to. A parser that dedups on
    one form while the identity pass stores another re-inserts every row on the
    next parse - the same defect that made UserAssist duplicate.

    UsrClass hives identify themselves by SID, NTUSER by profile name; both are
    resolved to the one display name here. A hive with no resolvable owner gets
    the unattributed label - applied here rather than at each call site, so no
    caller can forget it and silently write ''.
    """
    owner = identify_hive_owner(hive_path)
    if not owner:
        return unattributed_label(hive_path)
    low = owner.lower()
    for a in accounts or []:
        if (a.get("user_sid") or "").lower() == low:
            return a.get("display_name") or owner
        if (a.get("username") or "").lower() == low:
            return a.get("display_name") or owner
    return owner


_OWNER_CACHE = {}


def identify_hive_owner(hive_path):
    """Owner of a per-user hive, whichever kind it is. Cached.

    Shellbags are read from both NTUSER.DAT and UsrClass.dat, and the recursive
    walker only knows the hive path, so this dispatches on what the hive
    actually is rather than on the caller knowing. Results are memoised because
    the walker would otherwise reopen the hive at every level of recursion.
    """
    if not hive_path:
        return ""
    if hive_path in _OWNER_CACHE:
        return _OWNER_CACHE[hive_path]
    sid = identify_usrclass_hive(hive_path)
    owner = sid or identify_ntuser_hive(hive_path)
    _OWNER_CACHE[hive_path] = owner
    return owner


def identify_usrclass_hive(hive_path):
    """The SID a UsrClass.dat belongs to, or ''.

    UsrClass hives name themselves: the root key is '<SID>_Classes'.
    """
    reg = _open(hive_path)
    if not reg:
        return ""
    try:
        root = reg.root().name()
        if root and root.endswith("_Classes"):
            return root[:-len("_Classes")]
    except Exception as e:
        logging.debug("UsrClass root unreadable in %s: %s", hive_path, e)
    return ""


CREATE_USER_ACCOUNTS_SQL = """
CREATE TABLE IF NOT EXISTS UserAccounts (
    user_sid TEXT PRIMARY KEY,
    rid INTEGER,
    username TEXT,
    display_name TEXT,
    full_name TEXT,
    comment TEXT,
    account_type TEXT,
    well_known TEXT,
    account_enabled INTEGER,
    account_flags TEXT,
    last_logon TEXT,
    password_last_set TEXT,
    account_expires TEXT,
    last_incorrect_password TEXT,
    login_count INTEGER,
    bad_password_count INTEGER,
    profile_path TEXT,
    profile_loaded INTEGER,
    source TEXT,
    parsed_at TEXT
)"""

_COLUMNS = ["user_sid", "rid", "username", "display_name", "full_name", "comment",
            "account_type", "well_known", "account_enabled", "account_flags",
            "last_logon", "password_last_set", "account_expires",
            "last_incorrect_password", "login_count", "bad_password_count",
            "profile_path", "profile_loaded", "source", "parsed_at"]


def write_user_accounts(cursor, accounts):
    """Create UserAccounts and insert. Returns the number of rows written."""
    cursor.execute(CREATE_USER_ACCOUNTS_SQL)
    sql = ("INSERT OR REPLACE INTO UserAccounts (%s) VALUES (%s)"
           % (", ".join(_COLUMNS), ", ".join("?" * len(_COLUMNS))))
    n = 0
    for a in accounts:
        cursor.execute(sql, tuple(a.get(c) for c in _COLUMNS))
        n += 1
    return n


CREATE_LOCAL_GROUPS_SQL = """CREATE TABLE IF NOT EXISTS local_groups (
    scope TEXT, rid INTEGER, group_name TEXT, comment TEXT,
    member_sid TEXT, member_name TEXT, member_count INTEGER,
    last_write TEXT, parsed_at TEXT,
    PRIMARY KEY (scope, rid, member_sid))"""


def write_local_groups(cursor, aliases, sid_to_name, stamp):
    """One row per group MEMBER, plus one for each empty group.

    A row per member rather than a joined member list, because the question
    asked of this table is "which groups was this SID in" as often as "who was
    in Administrators", and a comma-joined column answers only the second.

    Empty groups still get a row with a null member: "Administrators has one
    member" and "this group was never parsed" must not look the same, and the
    stock set of empty built-in groups is itself the baseline a deviation shows
    against.
    """
    cursor.execute(CREATE_LOCAL_GROUPS_SQL)
    sql = ("INSERT OR REPLACE INTO local_groups (scope, rid, group_name, "
           "comment, member_sid, member_name, member_count, last_write, "
           "parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")
    n = 0
    for a in aliases:
        base = (a.get("scope", ""), a.get("rid", 0), a.get("name", ""),
                a.get("comment", ""))
        members = a.get("members") or []
        if not members:
            cursor.execute(sql, base + ("", "", a.get("member_count", 0),
                                        a.get("last_write", ""), stamp))
            n += 1
            continue
        for sid in members:
            # A local account resolves through the accounts just built; the
            # rest are group and logon-type SIDs, which have no SAM entry and
            # would otherwise leave the column blank next to a bare SID.
            name = sid_to_name.get(sid) or WELL_KNOWN_GROUP_SIDS.get(sid, "")
            cursor.execute(sql, base + (sid, name,
                                        a.get("member_count", 0),
                                        a.get("last_write", ""), stamp))
            n += 1
    return n


# Columns that hold a raw SID and should read "SID (MACHINE\username)".
SID_COLUMNS = (
    ("UserAssist", "user_sid"),
    ("BAM", "sid"),
    ("DAM", "sid"),
)

# Per-user artifact tables that carry a user_name column.
USER_NAME_TABLES = (
    "RecentDocs", "RunMRU", "TypedPaths", "MUICache", "OpenSaveMRU",
    "LastSaveMRU", "Shellbags", "WordWheelQuery",
)


def sid_matches_clause(column):
    """SQL that matches a SID whether or not it has been enriched.

    apply_identity() rewrites SID columns to "SID (MACHINE\\username)". Any
    dedup check that compares to the bare SID stops matching once that has
    happened, so the next parse re-inserts every row it already has - silently,
    and only visible as a table that keeps growing.

    Returns (sql_fragment, param_builder) where param_builder(sid) gives the
    parameters in order.
    """
    frag = "(%s = ? OR %s LIKE ?)" % (column, column)
    return frag, (lambda sid: (sid, "%s (%%" % sid))


def row_exists_for_sid(cursor, table, other_cols, other_vals, sid_col, sid):
    """True when a row already exists for these columns and this SID.

    Matches both the raw SID and the enriched "SID (name)" form, so re-parsing a
    case does not duplicate rows that the identity pass has already renamed.
    """
    frag, params = sid_matches_clause(sid_col)
    where = " AND ".join("%s = ?" % c for c in other_cols)
    sql = "SELECT 1 FROM %s WHERE %s%s%s LIMIT 1" % (
        table, where, " AND " if other_cols else "", frag)
    try:
        cursor.execute(sql, tuple(other_vals) + params(sid))
        return cursor.fetchone() is not None
    except Exception as e:
        logging.debug("row_exists_for_sid(%s): %s", table, e)
        return False


def resolve_hive_owner_sid(hive_path, accounts, is_usrclass=False):
    """The SID that owns an NTUSER.DAT or UsrClass.dat, or '' when unknown.

    Both parsers must store the same KIND of value in a SID column. Offline used
    to store a bare username here while live stored a SID, so one column carried
    two different meanings depending on how the evidence was acquired - and the
    enrichment pass skipped offline entirely, because a username is not a SID.

    UsrClass names its own SID in the root key. NTUSER does not, so its owner is
    resolved by name against the accounts already built from SAM/ProfileList.
    """
    if is_usrclass:
        return identify_usrclass_hive(hive_path)
    name = identify_ntuser_hive(hive_path)
    if not name:
        return ""
    low = name.lower()
    for a in accounts or []:
        if (a.get("username") or "").lower() == low:
            return a.get("user_sid") or ""
        profile = a.get("profile_path") or ""
        if profile and os.path.basename(profile.rstrip(BS)).lower() == low:
            return a.get("user_sid") or ""
    return ""


def _table_exists(cursor, table):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cursor.fetchone() is not None


def _ensure_column(cursor, table, column, decl="TEXT"):
    if not _table_exists(cursor, table):
        return False
    cursor.execute("PRAGMA table_info(%s)" % table)
    if column in [c[1] for c in cursor.fetchall()]:
        return False
    cursor.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, decl))
    return True


def describe_synthetic_sid(sid):
    """Name the SIDs Windows generates per-session rather than per-person."""
    if not sid:
        return ""
    if sid.startswith("S-1-5-90-"):
        return "Window Manager (DWM)"
    if sid.startswith("S-1-5-96-"):
        return "Font Driver Host (UMFD)"
    if sid.startswith("S-1-5-80-"):
        return "Service account (NT SERVICE)"
    if sid.startswith("S-1-5-82-"):
        return "IIS Application Pool"
    return ""


def _discover_artifact_sids(cursor, known_sids):
    """SIDs that appear in artifacts but in neither SAM nor ProfileList.

    A user SID in BAM with no matching account is a real finding: the account
    was deleted, or its profile was removed, or it is a domain account whose
    profile never landed on this machine. Recording it keeps the activity
    attributable instead of leaving an orphan SID in a column.
    """
    found = {}
    for table, column in SID_COLUMNS:
        if not _table_exists(cursor, table):
            continue
        cursor.execute("PRAGMA table_info(%s)" % table)
        if column not in [c[1] for c in cursor.fetchall()]:
            continue
        cursor.execute("SELECT DISTINCT %s FROM %s" % (column, table))
        for (raw,) in cursor.fetchall():
            if not raw or not isinstance(raw, str):
                continue
            sid = raw.split(" (")[0].strip()
            if not sid.startswith("S-1-") or sid in known_sids or sid in found:
                continue
            found[sid] = table
    return found


def apply_identity(cursor, sam_hive=None, software_hive=None, system_hive=None,
                   default_user=None, allow_live_fallback=False):
    """Build UserAccounts and make every SID column readable.

    Called by BOTH parsers with the same arguments, so live and offline output
    agree by construction rather than by two implementations happening to match.

    Returns (account_count, enriched_row_count).
    """
    accounts, sid_to_name = build_user_accounts(
        sam_hive, software_hive, system_hive, allow_live_fallback)

    # Accounts visible only through the activity they left behind.
    stamp = format_forensic_timestamp(get_current_utc())
    known = {a["user_sid"] for a in accounts if a.get("user_sid")}
    for sid, seen_in in _discover_artifact_sids(cursor, known).items():
        synthetic = describe_synthetic_sid(sid)
        well_known = WELL_KNOWN_SIDS.get(sid)
        try:
            rid = int(sid.rsplit("-", 1)[-1])
        except ValueError:
            rid = 0
        accounts.append({
            "user_sid": sid, "rid": rid,
            "username": well_known[0] if well_known else "",
            "display_name": ("NT AUTHORITY" + BS + well_known[0]) if well_known else "",
            "full_name": "", "comment": "seen in %s" % seen_in,
            "account_type": ("service" if well_known
                             else "synthetic" if synthetic else "unresolved"),
            "well_known": (well_known[1] if well_known else synthetic
                           or "no matching SAM or ProfileList entry - "
                              "deleted account, removed profile, or domain user"),
            "account_enabled": None, "account_flags": "",
            "last_logon": "", "password_last_set": "", "account_expires": "",
            "last_incorrect_password": "", "login_count": 0, "bad_password_count": 0,
            "profile_path": "", "profile_loaded": 0,
            "source": "Artifact", "parsed_at": stamp,
        })

    written = write_user_accounts(cursor, accounts)

    # Local group membership. Written here so both parsers get it from the one
    # call they already make, and so member SIDs resolve through the same
    # sid_to_name map the accounts above were built from.
    try:
        groups = _sam_aliases(sam_hive) if sam_hive else []
        if groups:
            write_local_groups(cursor, groups, sid_to_name, stamp)
    except Exception as e:
        logging.warning("local group membership unavailable: %s", e)

    enriched = 0
    for table, column in SID_COLUMNS:
        if not _table_exists(cursor, table):
            continue
        cursor.execute("PRAGMA table_info(%s)" % table)
        if column not in [c[1] for c in cursor.fetchall()]:
            continue
        for sid, name in sid_to_name.items():
            if not sid or not name:
                continue
            # Idempotent: a second parse into the same database must not produce
            # "SID (name) (name)".
            cursor.execute(
                "UPDATE %s SET %s = ? WHERE %s = ?" % (table, column, column),
                ("%s (%s)" % (sid, name), sid))
            enriched += cursor.rowcount or 0

    for table in USER_NAME_TABLES:
        _ensure_column(cursor, table, "user_name")
        if not _table_exists(cursor, table):
            continue

        # user_name must hold a NAME. Some sources only yield a SID - UsrClass
        # hives name themselves by SID, so Shellbags arrives that way - and a
        # column holding a name for some rows and a SID for others is the same
        # defect as a SID column that sometimes holds a username.
        for sid, name in sid_to_name.items():
            if sid and name:
                cursor.execute(
                    "UPDATE %s SET user_name = ? WHERE user_name = ?" % table,
                    (name, sid))

        if default_user:
            cursor.execute(
                "UPDATE %s SET user_name = ? WHERE user_name IS NULL OR user_name = ''"
                % table, (default_user,))

    return written, enriched


@contextlib.contextmanager
def live_hive_export(reg_path, hive_name, validate_key, prefix):
    r"""Yield a path to a temporary copy of a live registry hive, or ''.

    Some hives cannot be read through winreg even elevated. HKLM\SAM opens at
    the top but denies SAM\SAM and everything below it; HKLM\SECURITY denies its
    root key outright. Either way the data is unreachable in place.

    RegistryHivesLive in amcacheparser already solves this: it holds
    SeBackupPrivilege and calls NtSaveKeyEx, which writes the whole subtree past
    the ACLs that block winreg, falling back to a backup-semantics open for keys
    whose root itself is denied. Reused rather than adding a second way.

    The hive is written to a TEMPORARY directory and removed on the way out.
    Writing it into the case would make the parser a collector: Registry_Hives
    is the collector's output directory, sits in the case layout beside Prefetch
    and MFT, and is consumed by the offline path - a lone hive there looks like
    a partial collection. SAM holds password hashes and SECURITY holds LSA
    secrets, so a copy that lives for one parse is a smaller exposure than one
    that persists.

    Follows the pattern SRUM_Claw already uses for the locked SRUM database:
    tempfile.mkdtemp, work in it, shutil.rmtree on the way out.

    Never raises. These hives are an enhancement - a live parse must still
    finish without them on a machine where the export is not permitted.

    Args:
        reg_path:     e.g. "HKLM\\SAM"
        hive_name:    filename to write inside the temp directory
        validate_key: key path that must open in the export, as a list of
                      components - a truncated file still "exists", and parsing
                      one produces a confidently empty result rather than an error
        prefix:       temp directory prefix
    """
    tmpdir = None
    try:
        if os.name != "nt":
            yield ""
            return
        try:
            import ctypes
            if not ctypes.windll.shell32.IsUserAnAdmin():
                logging.info("%s export skipped: not elevated", hive_name)
                yield ""
                return
        except Exception as e:
            logging.debug("elevation check failed: %s", e)
            yield ""
            return

        try:
            from Artifacts_Collectors import amcacheparser
        except ModuleNotFoundError:
            import sys
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from Artifacts_Collectors import amcacheparser

        tmpdir = tempfile.mkdtemp(prefix=prefix)
        dest = os.path.join(tmpdir, hive_name)

        # An explicit path is required: with FilePath=None the helper sets
        # FILE_FLAG_DELETE_ON_CLOSE and the file disappears the moment the
        # handle closes, before anything can read it.
        hives = amcacheparser.RegistryHivesLive()
        handle = hives.open_hive_by_key(reg_path, dest)
        try:
            handle.close()
        except Exception as e:
            logging.debug("%s export handle close: %s", hive_name, e)

        if not REGISTRY_AVAILABLE:
            raise RuntimeError("python-registry unavailable to validate the export")
        Registry.Registry(dest).open(BS.join(validate_key))

        logging.info("%s exported to %s (%d bytes)", hive_name, dest,
                     os.path.getsize(dest))
        yield dest

    except Exception as e:
        logging.warning("%s export failed: %s", hive_name, e)
        yield ""

    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


@contextlib.contextmanager
def live_sam_hive():
    r"""Temporary copy of HKLM\SAM, or ''. See live_hive_export()."""
    with live_hive_export("HKLM" + BS + "SAM", "SAM",
                          ["SAM", "Domains", "Account", "Users"],
                          "regclaw_sam_") as path:
        yield path


@contextlib.contextmanager
def live_security_hive():
    r"""Temporary copy of HKLM\SECURITY, or ''. See live_hive_export().

    Validated on Policy rather than a leaf: Policy\Secrets and Cache are both
    legitimately absent on some machines - Cache only exists once a domain
    account has logged on - so validating on either would reject a good export
    from a standalone host.
    """
    with live_hive_export("HKLM" + BS + "SECURITY", "SECURITY",
                          ["Policy"], "regclaw_security_") as path:
        yield path



def find_hive_dir(start_path):
    """Locate the collected Registry_Hives directory near a case path.

    The live parser writes its database into <case>/Target_Artifacts, and the
    collector drops hives in a sibling or child directory whose name varies
    between acquisitions ("Registry_Hives", "Registry Hives").
    """
    if not start_path:
        return None
    base = start_path if os.path.isdir(start_path) else os.path.dirname(start_path)
    candidates = []
    for parent in (base, os.path.dirname(base), os.path.dirname(os.path.dirname(base))):
        if not parent:
            continue
        for name in ("Registry_Hives", "Registry Hives", "RegistryHives"):
            candidates.append(os.path.join(parent, name))
            candidates.append(os.path.join(parent, "Target_Artifacts", name))
            candidates.append(os.path.join(parent, "live_acquisition", name))
    for c in candidates:
        if os.path.isdir(c):
            return c
    return None


def locate_hives(hive_dir):
    """{'sam','security','software','system'} -> path, for hives in hive_dir."""
    found = {}
    if not hive_dir or not os.path.isdir(hive_dir):
        return found
    wanted = {"sam": "sam", "security": "security",
              "software": "software", "system": "system"}
    for entry in os.listdir(hive_dir):
        low = entry.lower()
        for key, stem in wanted.items():
            if key in found:
                continue
            if low == stem or low.startswith(stem + "."):
                full = os.path.join(hive_dir, entry)
                if os.path.isfile(full):
                    found[key] = full
    return found
