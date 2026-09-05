r"""The registry keys neither parser used to read.

The anatomy page listing every key Crow-Eye opens made the opposite question
answerable - what does it NOT open - and nineteen keys came back that hold real
data on a reference system and were read by nothing.

One of them changes a finding rather than adding one. Explorer records in
StartupApproved whether each autostart entry is actually allowed to launch, and
six of ten HKCU Run entries on the reference system are disabled. Without this
key, AutoStartPrograms reports all ten as live persistence.

The collectors here take a `values(key_path)` and a `subkeys(key_path)`
callable, so the live parser can pass its winreg readers and the offline parser
its hive readers, and the two produce the same rows from the same code. Neither
knows how the other opens a hive, and neither needs to.

Every collector returns a list of dicts and never raises: a key that is absent
on this Windows build is a shorter list, not a failed parse.
"""

import logging
import struct

logger = logging.getLogger(__name__)

try:
    from Artifacts_Collectors import registry_binary_parser
except ImportError:                                     # pragma: no cover
    import registry_binary_parser

BS = chr(92)

# Where each thing lives, relative to its hive root. The live parser prefixes
# the hive and resolves CurrentControlSet; the offline one resolves the control
# set from Select. Kept here so the two cannot drift apart.
EXPLORER = BS.join(["Microsoft", "Windows", "CurrentVersion", "Explorer"])
CURRENT = BS.join(["Microsoft", "Windows", "CurrentVersion"])
WINNT = BS.join(["Microsoft", "Windows NT", "CurrentVersion"])

KEYS = {
    "startup_approved_hklm": BS.join([EXPLORER, "StartupApproved"]),
    "startup_approved_hkcu": BS.join(["Software", EXPLORER, "StartupApproved"]),
    "app_paths":             BS.join([CURRENT, "App Paths"]),
    "safe_boot":             BS.join(["Control", "SafeBoot"]),
    "zone_map":              BS.join(["Software", CURRENT, "Internet Settings",
                                      "ZoneMap"]),
    "consent_store":         BS.join([CURRENT, "CapabilityAccessManager",
                                      "ConsentStore"]),
    "shared_dlls":           BS.join([CURRENT, "SharedDLLs"]),
    "hid":                   BS.join(["Enum", "HID"]),
    "network_cards":         BS.join([WINNT, "NetworkCards"]),
    "power":                 BS.join(["Control", "Session Manager", "Power"]),
    "nls_language":          BS.join(["Control", "Nls", "Language"]),
    # Not collected as a table - read only for SystemRoot, so a
    # %SystemRoot% in another value can be expanded from the EVIDENCE
    # rather than from the machine the examiner happens to be using.
    "winnt_current_version": WINNT,
    "w32time":               BS.join(["Services", "W32Time", "Parameters"]),
    "tcpip":                 BS.join(["Services", "Tcpip", "Parameters"]),
    "search_gather":         BS.join(["Microsoft", "Windows Search", "Gather"]),
    "shell_folders":         BS.join(["Software", EXPLORER, "Shell Folders"]),
    "taskband":              BS.join(["Software", EXPLORER, "Taskband"]),
    "attachments":           BS.join(["Software", CURRENT, "Policies",
                                      "Attachments"]),
    "device_guard":          BS.join(["Control", "DeviceGuard"]),
    "lanman_workstation":    BS.join(["Services", "LanmanWorkstation",
                                      "Parameters"]),
}

ZONE_NAMES = {
    "0": "My Computer", "1": "Local Intranet", "2": "Trusted Sites",
    "3": "Internet", "4": "Restricted Sites",
}


def display_path(tagged):
    """Turn an internal `HIVE|body` routing path into a real registry path.

    The collectors are handed paths carrying a hive tag so that one pair of
    readers can serve keys living in different hives. That tag is plumbing, and
    it was going into the `key_path` column of all 573 rows - stored as evidence
    and shown to an analyst as `SOFTWARE|Microsoft\\Windows\\...`, which is not a
    path that exists anywhere.

    It cost more than looks. `key_path` is what the last_written / time_basis
    pass resolves back to a key, so every one of those rows came out undated
    while the pass reported no error - the plan had said this table would be
    covered "without further work", and the tell was a `dated` count of zero,
    not a failure.

    Both parsers land on the same text, which is what lets live and offline be
    compared on this column:

      SOFTWARE|Microsoft\\...   -> SOFTWARE\\Microsoft\\...
      NTUSER|Software\\...      -> Software\\...            (already hive-rooted)
      SYSTEM|Control\\...       -> SYSTEM\\CurrentControlSet\\Control\\...
      SYSTEM|ControlSet001\\... -> SYSTEM\\CurrentControlSet\\...

    The last of those is the offline form, which names the control set it
    actually read. It is rewritten to `CurrentControlSet` deliberately: the
    seventeen SecurityPosture rows already in the database use that spelling,
    and a column that says ControlSet001 offline and CurrentControlSet live
    cannot be diffed between the two parsers.
    """
    if not tagged or "|" not in tagged:
        return tagged
    tag, body = tagged.split("|", 1)
    if tag == "SYSTEM":
        head, sep, rest = body.partition(BS)
        if head.lower().startswith("controlset") or head.lower() == "currentcontrolset":
            body = rest if sep else ""
        return BS.join(x for x in ("SYSTEM", "CurrentControlSet", body) if x)
    if tag == "SOFTWARE":
        return BS.join(x for x in ("SOFTWARE", body) if x)
    return body


def with_display_paths(rows):
    """Rewrite `key_path` on every row a collector produced."""
    for row in rows or []:
        if row.get("key_path"):
            row["key_path"] = display_path(row["key_path"])
    return rows


def default_value(vals):
    """A key's default value, whichever of the four spellings the reader used.

    winreg returns the default value under the empty name. python-registry
    calls it `(default)` - lowercase - and some readers title-case it. Matching
    on one spelling is not a small bug here: `app_paths.executable_path` and
    `safe_boot_services.entry_type` are both stored in the default value and
    nowhere else, so 269 rows came out with an empty column offline and a
    correct one live, with no error on either side. The row count matched
    exactly, which is why only a column-level comparison found it.

    Case-insensitive because offline value-name matching is case-sensitive and
    winreg's is not - the same asymmetry that once made Winlogon's VMApplet
    appear live and vanish offline.
    """
    if not vals:
        return ""
    for name in ("", "(Default)", "(default)", "(DEFAULT)"):
        if name in vals:
            return _text(vals[name])
    for name in vals:
        if str(name).strip().lower() in ("", "(default)"):
            return _text(vals[name])
    return ""


def _text(item):
    """A reader may hand back a bare value or a (data, type) pair."""
    if item is None:
        return ""
    if isinstance(item, (tuple, list)):
        item = item[0] if item else ""
    return "" if item is None else str(item)


def _render(item):
    """Text for a value of any type, with REG_BINARY as hex rather than repr.

    `str()` on a bytes object gives `b'\\x01\\x00\\x00\\x00...'`, and eight power
    and network policy blobs were being stored exactly that way. That is a
    Python expression sitting in an evidence column: an analyst reading it sees
    the language the parser happens to be written in, and anyone comparing two
    cases is diffing repr escaping. Hex is what the rest of the codebase stores
    and what every registry tool prints.

    The byte count is kept because the text is truncated downstream, and a
    truncated blob with no length silently loses the one fact still legible
    about it.
    """
    value = item[0] if isinstance(item, (tuple, list)) and item else item
    if isinstance(value, (bytes, bytearray)):
        data = bytes(value)
        return "%s (%d bytes)" % (data.hex().upper(), len(data))
    return _text(item)


def _raw(item):
    if isinstance(item, (tuple, list)):
        item = item[0] if item else b""
    if isinstance(item, (bytes, bytearray)):
        return bytes(item)
    if isinstance(item, str):
        try:
            return item.encode("latin-1")
        except Exception:
            return b""
    if isinstance(item, int) and not isinstance(item, bool):
        # A REG_QWORD arrives as a Python int, not as bytes - winreg decodes it
        # and python-registry does the same. Returning b"" for it made every
        # ConsentStore row come out with no last-used time: all 17 rows of
        # app_permissions were empty for last_used_start and last_used_stop
        # while the registry plainly held LastUsedTimeStart, and nothing
        # errored because parse_filetime declines an empty buffer quietly.
        #
        # A FILETIME is a little-endian 64-bit count either way, so packing it
        # back gives the decoders the 8 bytes they expect.
        try:
            return struct.pack("<Q", item if item >= 0 else 0)
        except struct.error:
            return b""
    return b""


def startup_approved(values, subkeys, base, hive_label):
    """Which autostart entries are allowed to launch, and when one was not.

    The reason this key matters: a Run value is a request, and this is the
    answer. Six of ten HKCU Run entries on the reference system are disabled,
    and two have been since February.
    """
    out = []
    for scope in (subkeys(base) or []):
        path = base + BS + str(scope)
        for name, item in (values(path) or {}).items():
            state = registry_binary_parser.parse_startup_approved(_raw(item))
            out.append({
                "hive": hive_label,
                "scope": str(scope),
                "entry_name": str(name),
                "state": state["state"],
                "state_byte": state["state_byte"],
                "disabled_at": state["disabled_at"],
                "key_path": path,
            })
    return out


def app_paths(values, subkeys, base):
    """How a bare command name resolves. Change it and the name runs elsewhere."""
    out = []
    for app in (subkeys(base) or []):
        path = base + BS + str(app)
        vals = values(path) or {}
        out.append({
            "app_name": str(app),
            # The executable is the key's DEFAULT value. Asking for it by name
            # matters: another value usually enumerates first.
            "executable_path": default_value(vals),
            "app_dir": _text(vals.get("Path", "")),
            "key_path": path,
        })
    return out


def safe_boot_services(values, subkeys, base):
    """What still starts in Safe Mode - the boot used to clean a machine."""
    out = []
    for mode in (subkeys(base) or []):
        mode_path = base + BS + str(mode)
        for entry in (subkeys(mode_path) or []):
            path = mode_path + BS + str(entry)
            vals = values(path) or {}
            out.append({
                "boot_mode": str(mode),
                "entry_name": str(entry),
                "entry_type": default_value(vals),
                "key_path": path,
            })
    return out


def zone_map(values, subkeys, base):
    """Hosts and protocols assigned to a security zone.

    Three shapes live under ZoneMap and the first version of this read only
    one of them, so the table came out EMPTY on a machine where the key holds
    data - the silent failure a new table is most likely to have.

      Domains / EscDomains   per-site assignments. The interesting ones, and
                             absent on a machine where nobody has added a site.
      ProtocolDefaults       the zone a protocol falls into by default.
      ZoneMap's own values   policy settings, which are recorded as settings
                             rather than here, so this table stays one thing.
    """
    out = []
    for scope in (subkeys(base) or []):
        scope_name = str(scope)
        scope_path = base + BS + scope_name

        if scope_name.lower() == "protocoldefaults":
            for protocol, item in (values(scope_path) or {}).items():
                if str(protocol).lower() in ("(default)", ""):
                    continue
                zone = _text(item)
                out.append({
                    "scope": "ProtocolDefaults", "host": "(any)",
                    "protocol": str(protocol), "zone": zone,
                    "zone_name": ZONE_NAMES.get(zone, ""),
                    "key_path": scope_path,
                })
            continue

        if scope_name.lower() not in ("domains", "escdomains", "ranges"):
            continue

        for domain in (subkeys(scope_path) or []):
            path = scope_path + BS + str(domain)
            for protocol, item in (values(path) or {}).items():
                if str(protocol).lower() in ("(default)", ""):
                    continue
                zone = _text(item)
                out.append({
                    "scope": scope_name, "host": str(domain),
                    "protocol": str(protocol), "zone": zone,
                    "zone_name": ZONE_NAMES.get(zone, ""),
                    "key_path": path,
                })
            # A subdomain carries its own assignment one level further down.
            for sub in (subkeys(path) or []):
                sub_path = path + BS + str(sub)
                for protocol, item in (values(sub_path) or {}).items():
                    if str(protocol).lower() in ("(default)", ""):
                        continue
                    zone = _text(item)
                    out.append({
                        "scope": scope_name,
                        "host": "%s.%s" % (sub, domain),
                        "protocol": str(protocol), "zone": zone,
                        "zone_name": ZONE_NAMES.get(zone, ""),
                        "key_path": sub_path,
                    })
    return out


def app_permissions(values, subkeys, base):
    """Which application holds consent for a capability, and when it last used it."""
    out = []
    for capability in (subkeys(base) or []):
        cap_path = base + BS + str(capability)
        for app in (subkeys(cap_path) or []):
            app_path = cap_path + BS + str(app)
            vals = values(app_path) or {}
            if str(app).lower() == "nonpackaged":
                # Desktop programs sit one level further down, keyed by their
                # path with separators replaced. Packaged apps do not.
                for exe in (subkeys(app_path) or []):
                    exe_path = app_path + BS + str(exe)
                    ev = values(exe_path) or {}
                    out.append(_permission_row(capability, exe, 0, ev, exe_path))
                continue
            out.append(_permission_row(capability, app, 1, vals, app_path))
    return out


def _permission_row(capability, app, packaged, vals, path):
    return {
        "capability": str(capability),
        "app": str(app).replace("#", BS),
        "packaged": packaged,
        "permission": _text(vals.get("Value", "")),
        "last_used_start": registry_binary_parser.parse_filetime(
            _raw(vals.get("LastUsedTimeStart"))) if "LastUsedTimeStart" in vals else "",
        "last_used_stop": registry_binary_parser.parse_filetime(
            _raw(vals.get("LastUsedTimeStop"))) if "LastUsedTimeStop" in vals else "",
        "key_path": path,
    }


def shared_dlls(values, base):
    out = []
    for dll, item in (values(base) or {}).items():
        try:
            count = int(_text(item) or 0)
        except (TypeError, ValueError):
            count = 0
        out.append({"dll_path": str(dll), "reference_count": count,
                    "key_path": base})
    return out


def hid_devices(values, subkeys, base):
    out = []
    for device in (subkeys(base) or []):
        dev_path = base + BS + str(device)
        for instance in (subkeys(dev_path) or []):
            path = dev_path + BS + str(instance)
            vals = values(path) or {}
            out.append({
                "device_id": str(device), "instance_id": str(instance),
                "device_desc": _text(vals.get("DeviceDesc", "")),
                "manufacturer": _text(vals.get("Mfg", "")),
                "service": _text(vals.get("Service", "")),
                "key_path": path,
            })
    return out


def network_cards(values, subkeys, base):
    out = []
    for index in (subkeys(base) or []):
        path = base + BS + str(index)
        vals = values(path) or {}
        out.append({
            "card_index": str(index),
            "description": _text(vals.get("Description", "")),
            "service_name": _text(vals.get("ServiceName", "")),
            "key_path": path,
        })
    return out


# Settings whose meaning is worth stating, by value name. Anything not listed
# is still recorded - an unexplained setting is better than a missing one.
MEANINGS = {
    "HiberbootEnabled": ("fast startup - when on, a shutdown is a partial "
                         "hibernate and does not flush what a real shutdown "
                         "would"),
    "HibernateEnabled": "hibernation, and therefore whether hiberfil.sys exists",
    "Type": "how the clock is disciplined - NTP, domain hierarchy or none",
    "NtpServer": "the time source this machine trusts",
    "Hostname": "the name this machine answers to on the network",
    "Domain": "the DNS domain appended to bare names",
    "NameServer": "statically configured DNS servers",
    "SearchList": "DNS suffixes tried for an unqualified name",
    "Default": "the system locale",
    "InstallLanguage": "the language Windows was installed in",
    "IntranetName": "whether bare hostnames count as the intranet zone",
    "UNCAsIntranet": "whether a UNC path counts as the intranet zone",
    "AutoDetect": "whether zone membership is detected automatically",
    "ProxyByPass": "whether proxy bypass implies the intranet zone",
}

# Which flat key belongs to which area of the machine.
CONFIG_AREAS = [
    ("power", "power"),
    ("nls_language", "locale"),
    ("w32time", "time source"),
    ("tcpip", "network identity"),
    ("search_gather", "search index"),
    ("shell_folders", "shell folders"),
    ("taskband", "taskbar"),
    ("zone_policy", "zone policy"),
]


def _decoded(setting, item, env=None):
    """The decoded form of one config value, from the shared decoder.

    The decoding itself lives in registry_binary_parser beside the timezone and
    networklist rules - it belongs with the other value decoders, and putting it
    there is what makes a locale or a switch decode the same way in every table
    rather than only in this one.
    """
    data = item[0] if isinstance(item, (tuple, list)) and item else item
    vtype = item[1] if isinstance(item, (tuple, list)) and len(item) > 1 else None
    try:
        return registry_binary_parser.render_registry_value(
            "system_configuration", setting, data, vtype, env) or ""
    except Exception:
        return ""


def _evidence_environment(values, resolved):
    """%SystemRoot% and friends, read from the hive being parsed.

    The environment of the machine the evidence came from, never the one the
    examiner is sitting at. Returns {} when the key is not reachable, and an
    empty environment means nothing gets expanded - which is the right answer,
    because a wrong expansion is indistinguishable from a right one on screen.
    """
    env = {}
    for key_name in ("winnt_current_version", "system_environment"):
        path = resolved.get(key_name)
        if not path:
            continue
        for name, item in (values(path) or {}).items():
            text = _text(item)
            if text and str(name).lower() in (
                    "systemroot", "windir", "programfiles", "programdata",
                    "commonprogramfiles", "path"):
                env.setdefault(str(name), text)
    return env


def system_configuration(values, resolved):
    """Flat configuration values, one row each.

    Same shape as SecurityPosture, which holds the security-relevant subset.
    A value is recorded whether or not there is a sentence to say about it.
    """
    out = []
    env = _evidence_environment(values, resolved)
    for name, area in CONFIG_AREAS:
        path = resolved.get(name)
        if not path:
            continue
        for setting, item in (values(path) or {}).items():
            raw = _render(item)
            out.append({
                "setting": str(setting),
                "value_raw": raw[:400],
                # Empty when there is nothing to say, never a copy of the
                # raw value - see _decoded.
                "value_decoded": _decoded(str(setting), item, env)[:400],
                "area": area,
                "meaning": MEANINGS.get(str(setting), ""),
                "key_path": path,
            })
    return out


# The security-relevant settings, for SecurityPosture rather than here, so no
# value is stored in two places. (setting, key name, default, meaning-if-default,
# meaning-if-changed)
POSTURE = [
    ("attachments", "SaveZoneInformation", "1 / absent",
     "downloads keep their Mark of the Web",
     "Mark of the Web is suppressed - downloaded files lose their origin"),
    ("device_guard", "EnableVirtualizationBasedSecurity", "0 / absent",
     "virtualisation-based security not enabled",
     "virtualisation-based security enabled"),
    ("device_guard", "LsaCfgFlags", "0 / absent",
     "LSA not running protected",
     "Credential Guard protects LSASS"),
    ("lanman_workstation", "RequireSecuritySignature", "1 / absent",
     "SMB signing required",
     "SMB signing not required - traffic can be relayed"),
    ("lanman_workstation", "AllowInsecureGuestAuth", "0 / absent",
     "insecure guest logons refused",
     "insecure guest logons allowed - unauthenticated SMB access"),
    ("power", "HiberbootEnabled", "1 / absent",
     "fast startup on - a shutdown is not a full shutdown",
     "fast startup off - a shutdown is a real one"),
]


def security_posture(values, resolved):
    """The security-relevant subset, shaped for the SecurityPosture table."""
    out = []
    for key_name, setting, default, if_default, if_changed in POSTURE:
        path = resolved.get(key_name)
        if not path:
            continue
        vals = values(path) or {}
        if setting in vals:
            raw = _text(vals.get(setting))
            # Same rule as system_configuration: decode it, or say nothing.
            # Every one of these settings is a boolean, so this resolves to
            # "enabled"/"disabled" rather than repeating the digit back.
            decoded = _decoded(setting, vals.get(setting))
            assessment = "changed"
            meaning = if_changed
            # An explicit value matching the default is still the default.
            if raw.strip() in ("0", "") and default.startswith("0"):
                assessment, meaning = "default", if_default
            elif raw.strip() == "1" and default.startswith("1"):
                assessment, meaning = "default", if_default
        else:
            raw, decoded = "(absent)", "absent (Windows default)"
            assessment, meaning = "default", if_default
        out.append({
            "setting": setting, "value_raw": raw[:200],
            "value_decoded": decoded[:200], "default_value": default,
            "assessment": assessment, "meaning": meaning, "key_path": path,
        })
    return out
