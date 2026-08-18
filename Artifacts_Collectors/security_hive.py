# -*- coding: utf-8 -*-
r"""Parse the SECURITY hive - LSA policy, audit policy and secret metadata.

The SECURITY hive has always been collected (crow_claw lists
`{PARTITION}\Windows\System32\config\SECURITY`) and never opened, so audit
policy, the machine SID as LSA holds it, the primary domain and the list of
LSA secrets were unavailable from a case.

Shared by BOTH parsers, the way user_identity.py is: the live parser exports
HKLM\SECURITY to a temporary hive and passes the path, the offline parser
passes the collected file, and from there the code is identical. Live and
offline agree by construction rather than by two implementations happening to
match.

What this deliberately does NOT do
----------------------------------
It does not decrypt `Policy\Secrets`. Doing so needs the boot key assembled
from the class names of SYSTEM\CurrentControlSet\Control\Lsa\{JD,Skew1,GBG,Data}
and then AES or RC4 over the secret blobs, and it yields live service-account
passwords in plaintext. Recording WHICH secrets exist, how large they are and
when they were last written answers the forensic question - is there a cached
service credential, was it changed during the incident window - without the
parser becoming a credential dumper.

It does not invent an audit-policy decode either. See parse_audit_policy().
"""
import logging
import os
import struct

try:
    from Registry import Registry
    REGISTRY_AVAILABLE = True
except ImportError:                                   # pragma: no cover
    Registry = None
    REGISTRY_AVAILABLE = False

try:
    from Artifacts_Collectors import registry_binary_parser
except ModuleNotFoundError:                           # pragma: no cover
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from Artifacts_Collectors import registry_binary_parser

try:
    from utils.time_utils import filetime_to_datetime, format_forensic_timestamp
except ModuleNotFoundError:                           # pragma: no cover
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.time_utils import filetime_to_datetime, format_forensic_timestamp

BS = "\\"

CREATE_SQL = (
    """CREATE TABLE IF NOT EXISTS lsa_policy (
        name TEXT, key_path TEXT, value TEXT, meaning TEXT,
        last_write TEXT, parsed_at TEXT,
        PRIMARY KEY (name))""",
    """CREATE TABLE IF NOT EXISTS audit_policy (
        name TEXT, key_path TEXT, decoded TEXT, raw_hex TEXT, raw_size INTEGER,
        last_write TEXT, note TEXT, parsed_at TEXT,
        PRIMARY KEY (name))""",
    """CREATE TABLE IF NOT EXISTS lsa_secrets (
        secret_name TEXT, key_path TEXT, value_kind TEXT, size_bytes INTEGER,
        updated TEXT, last_write TEXT, parsed_at TEXT,
        PRIMARY KEY (secret_name, value_kind))""",
    """CREATE TABLE IF NOT EXISTS cached_domain_logons (
        slot TEXT, key_path TEXT, size_bytes INTEGER, occupied INTEGER,
        last_write TEXT, parsed_at TEXT,
        PRIMARY KEY (slot))""",
)


def _open(hive_path):
    if not hive_path or not REGISTRY_AVAILABLE or not os.path.exists(hive_path):
        return None
    try:
        return Registry.Registry(hive_path)
    except Exception as e:
        logging.debug("SECURITY hive unreadable (%s): %s", hive_path, e)
        return None


def _key(reg, path):
    try:
        return reg.open(path)
    except Exception:
        return None


def _default_value(key):
    """The key's default value, or None.

    python-registry reports a default value as the literal name "(default)",
    lowercase, where winreg gives an empty name. Every SECURITY policy value is
    stored as the default of its own key, so matching the wrong spelling here
    would return nothing at all from a hive that is perfectly readable.
    """
    if key is None:
        return None
    for v in key.values():
        if not v.name() or str(v.name()).lower() == "(default)":
            return v.value()
    return None


def _last_write(key):
    try:
        return format_forensic_timestamp(key.timestamp())
    except Exception:
        return ""


def parse_lsa_unicode_string(blob):
    """Text from an LSA policy string blob, or ''.

    Layout confirmed against PolPrDmN and PolAcDmN on a live host:

        0x00  WORD   length in BYTES of the string
        0x02  WORD   maximum length
        0x04  DWORD  offset-ish field, 8 on every sample seen
        0x08  WCHAR[] the string itself

    The length is a byte count, so "WORKGROUP" reads 18 rather than 9. Treating
    it as a character count would silently halve every name.
    """
    if not isinstance(blob, (bytes, bytearray)) or len(blob) < 8:
        return ""
    try:
        length = struct.unpack_from("<H", blob, 0)[0]
        if length == 0:
            return ""
        end = 8 + length
        if end > len(blob):
            end = len(blob)
        return bytes(blob[8:end]).decode("utf-16-le", errors="replace").rstrip("\x00")
    except Exception as e:
        logging.debug("LSA string decode failed: %s", e)
        return ""


def parse_audit_policy(blob):
    """(decoded, note) for a PolAdtEv blob.

    The pre-Vista layout is well known - an enabled flag, a category count,
    then that many DWORDs of 0=none/1=success/2=failure/3=both. On this
    Windows 11 host the blob is 152 bytes and does not fit it: the third DWORD
    reads 134, which is not a valid setting, so the modern layout is something
    else and is not publicly settled.

    Guessing would produce a confident, wrong audit policy - the worst possible
    output for a table whose entire job is telling an examiner what was being
    logged. So the legacy decode is applied ONLY when the blob validates
    against it, and otherwise the raw bytes are kept with a note saying where
    the real answer lives.
    """
    if not isinstance(blob, (bytes, bytearray)) or len(blob) < 8:
        return "", "empty or truncated value"
    b = bytes(blob)
    try:
        enabled = struct.unpack_from("<I", b, 0)[0]
        count = struct.unpack_from("<I", b, 4)[0]
        legacy_fits = (
            enabled in (0, 1)
            and 1 <= count <= 16
            and len(b) >= 8 + 4 * count
            and all(struct.unpack_from("<I", b, 8 + 4 * i)[0] in (0, 1, 2, 3)
                    for i in range(count))
        )
        if not legacy_fits:
            return "", ("layout is not the legacy AuditEventCount form; on "
                        "Vista+ the effective per-subcategory policy lives in "
                        "the LSA policy database, not here - raw bytes kept, "
                        "and the key's last-write time still dates the last "
                        "policy change")
        names = ("System", "Logon/Logoff", "Object Access", "Privilege Use",
                 "Detailed Tracking", "Policy Change", "Account Management",
                 "Directory Service Access", "Account Logon")
        setting = {0: "No Auditing", 1: "Success", 2: "Failure",
                   3: "Success and Failure"}
        parts = []
        for i in range(count):
            v = struct.unpack_from("<I", b, 8 + 4 * i)[0]
            label = names[i] if i < len(names) else "Category %d" % i
            parts.append("%s=%s" % (label, setting[v]))
        return ("Auditing %s; " % ("on" if enabled else "off")) + ", ".join(parts), \
               "legacy AuditEventCount layout, validated against this blob"
    except Exception as e:
        logging.debug("audit policy decode failed: %s", e)
        return "", "decode failed: %s" % e


def _filetime(blob):
    """Forensic timestamp from an 8-byte FILETIME value, or ''."""
    if not isinstance(blob, (bytes, bytearray)) or len(blob) < 8:
        return ""
    try:
        raw = struct.unpack_from("<Q", bytes(blob), 0)[0]
        if not raw:
            return ""
        return format_forensic_timestamp(filetime_to_datetime(raw))
    except Exception:
        return ""


# name -> (key under Policy, what it means)
_POLICY_VALUES = (
    ("MachineSID", "PolAcDmS", "sid",
     "the machine SID as LSA holds it - every local account SID is this plus a RID"),
    ("AccountDomainName", "PolAcDmN", "string",
     "the local account domain, which on a workgroup machine is the computer name"),
    ("PrimaryDomainName", "PolPrDmN", "string",
     "the domain this machine belongs to, or WORKGROUP when it belongs to none"),
    ("PrimaryDomainSID", "PolPrDmS", "sid",
     "the domain SID, present only when the machine is joined"),
    ("DnsDomainName", "PolDnDDN", "string", "the DNS domain name when joined"),
    ("DnsTreeName", "PolDnTrN", "string", "the AD forest root when joined"),
    ("PolicyRevision", "PolRevision", "hex", "LSA policy database revision"),
)


def parse_security(cursor, security_hive, check_exists, stamp):
    """Write the four SECURITY tables. Returns {table: rows written}.

    check_exists is passed in rather than imported so both parsers use their own
    guard, matching every other table they write - these tables carry primary
    keys, but an INSERT OR REPLACE still has to agree with the rest.
    """
    counts = {"lsa_policy": 0, "audit_policy": 0,
              "lsa_secrets": 0, "cached_domain_logons": 0}
    for sql in CREATE_SQL:
        cursor.execute(sql)

    reg = _open(security_hive)
    if reg is None:
        logging.info("SECURITY hive not available - skipping LSA tables")
        return counts

    if _key(reg, "Policy") is None:
        logging.warning("SECURITY hive has no Policy key - not a SECURITY hive?")
        return counts

    # ---------------------------------------------------------- LSA policy
    for name, sub, kind, meaning in _POLICY_VALUES:
        key = _key(reg, "Policy" + BS + sub)
        if key is None:
            continue
        blob = _default_value(key)
        if kind == "sid":
            text, _ = registry_binary_parser.binary_sid_to_string(blob or b"")
            text = text or ""
        elif kind == "string":
            text = parse_lsa_unicode_string(blob)
        else:
            text = bytes(blob).hex() if isinstance(blob, (bytes, bytearray)) else str(blob or "")
        if not text:
            continue
        cursor.execute(
            "INSERT OR REPLACE INTO lsa_policy "
            "(name, key_path, value, meaning, last_write, parsed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, "SECURITY" + BS + "Policy" + BS + sub, text, meaning,
             _last_write(key), stamp))
        counts["lsa_policy"] += 1

    # -------------------------------------------------------- audit policy
    for sub, label in (("PolAdtEv", "AuditEventPolicy"),
                       ("PolAdtLg", "AuditLogPolicy")):
        key = _key(reg, "Policy" + BS + sub)
        if key is None:
            continue
        blob = _default_value(key)
        if not isinstance(blob, (bytes, bytearray)):
            continue
        b = bytes(blob)
        decoded, note = parse_audit_policy(b) if sub == "PolAdtEv" else \
            ("", "audit log retention and size policy, layout not decoded")
        cursor.execute(
            "INSERT OR REPLACE INTO audit_policy "
            "(name, key_path, decoded, raw_hex, raw_size, last_write, note, "
            "parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (label, "SECURITY" + BS + "Policy" + BS + sub, decoded,
             b[:512].hex(), len(b), _last_write(key), note, stamp))
        counts["audit_policy"] += 1

    # ---------------------------------------------------------- LSA secrets
    secrets = _key(reg, "Policy" + BS + "Secrets")
    if secrets is not None:
        for s in secrets.subkeys():
            wrote = False
            for kind, time_kind in (("CurrVal", "CupdTime"), ("OldVal", "OupdTime")):
                vk = _key(reg, "Policy" + BS + "Secrets" + BS + s.name() + BS + kind)
                blob = _default_value(vk) if vk is not None else None
                size = len(blob) if isinstance(blob, (bytes, bytearray)) else 0
                tk = _key(reg, "Policy" + BS + "Secrets" + BS + s.name() + BS + time_kind)
                updated = _filetime(_default_value(tk)) if tk is not None else ""
                if vk is None and not updated:
                    continue
                cursor.execute(
                    "INSERT OR REPLACE INTO lsa_secrets (secret_name, key_path, "
                    "value_kind, size_bytes, updated, last_write, parsed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (s.name(),
                     "SECURITY" + BS + "Policy" + BS + "Secrets" + BS + s.name(),
                     kind, size, updated, _last_write(s), stamp))
                counts["lsa_secrets"] += 1
                wrote = True
            if not wrote:
                cursor.execute(
                    "INSERT OR REPLACE INTO lsa_secrets (secret_name, key_path, "
                    "value_kind, size_bytes, updated, last_write, parsed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (s.name(),
                     "SECURITY" + BS + "Policy" + BS + "Secrets" + BS + s.name(),
                     "(present)", 0, "", _last_write(s), stamp))
                counts["lsa_secrets"] += 1

    # ------------------------------------------------- cached domain logons
    # Absent entirely on a machine no domain account has logged on to, which is
    # a finding in itself rather than a gap - hence the explicit no-rows case.
    cache = _key(reg, "Cache")
    if cache is not None:
        lw = _last_write(cache)
        for v in cache.values():
            nm = v.name() or "(default)"
            if not nm.upper().startswith("NL$"):
                continue
            d = v.value()
            size = len(d) if isinstance(d, (bytes, bytearray)) else 0
            # An empty slot is all zeroes rather than absent, so size alone
            # would count 25 cached logons on a machine that has none.
            occupied = 1 if (isinstance(d, (bytes, bytearray))
                             and any(bytes(d)[:16])) else 0
            cursor.execute(
                "INSERT OR REPLACE INTO cached_domain_logons "
                "(slot, key_path, size_bytes, occupied, last_write, parsed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (nm, "SECURITY" + BS + "Cache", size, occupied, lw, stamp))
            counts["cached_domain_logons"] += 1

    return counts
