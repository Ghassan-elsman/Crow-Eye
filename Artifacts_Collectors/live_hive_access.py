r"""Get a live registry hive as a FILE, past whatever ACL is in the way.

A live parse reads the running registry through winreg, which is right for most
of it: the merged view, volatile keys, CurrentControlSet and the redirected
32-bit view exist nowhere else. But some things are only in the hive FILE, and
some keys deny winreg outright even to an elevated administrator.

Measured on a live machine, elevated: walking
`HKLM\SYSTEM\CurrentControlSet\Enum\USB` through winreg reached **110 keys**
where the same hive read as a file yields **868**. Every device `Properties`
subkey is denied, and those hold the FILETIMEs that say when a USB device was
last connected. So a live parse reported no USB connection times at all - not
because the evidence was absent, but because the door was shut.

Crow-Eye already had the answer twice over, and neither was reachable from the
registry parser:

  * `crow_claw`'s FileAccessor - standard copy, then VSS, then raw disk - which
    yields the REAL file, freed cells and all
  * `user_identity.live_hive_export()` - SeBackupPrivilege plus NtSaveKeyEx,
    already how HKLM\SAM and HKLM\SECURITY are read

They are not interchangeable. NtSaveKeyEx writes a fresh copy of the live tree,
so it defeats the ACLs but contains no freed cells: carving an export finds
nothing, and would report "no deleted keys" for a hive full of them. The real
file is tried first for that reason, and the route is recorded so a case can
say which one it got.

Nothing here writes into the case. Acquired hives go to a temporary directory
and are removed, for the reason `live_hive_export` already gives: a hive left
in `Registry_Hives` makes the parser look like a collector that stopped early.
"""

import contextlib
import logging
import os
import shutil
import tempfile

logger = logging.getLogger(__name__)

# Where Windows keeps the machine hives. hivelist in the registry names these
# too, and the parser reads it, but a path is needed BEFORE the parse gets that
# far - and these have not moved since Windows NT.
SYSTEM_ROOT = os.environ.get("SystemRoot", r"C:\Windows")
CONFIG_DIR = os.path.join(SYSTEM_ROOT, "System32", "config")

STANDARD_HIVES = {
    "SYSTEM": os.path.join(CONFIG_DIR, "SYSTEM"),
    "SOFTWARE": os.path.join(CONFIG_DIR, "SOFTWARE"),
    "SAM": os.path.join(CONFIG_DIR, "SAM"),
    "SECURITY": os.path.join(CONFIG_DIR, "SECURITY"),
    "DEFAULT": os.path.join(CONFIG_DIR, "DEFAULT"),
    # AmCache is a hive like any other and Crow-Eye parses it, so it belongs
    # on this list rather than being a special case its own parser handles.
    "AmCache": os.path.join(SYSTEM_ROOT, "AppCompat", "Programs", "Amcache.hve"),
}

# What each hive is called through the registry API, for the export fallback.
REG_PATHS = {
    "SYSTEM": r"HKLM\SYSTEM",
    "SOFTWARE": r"HKLM\SOFTWARE",
    "SAM": r"HKLM\SAM",
    "SECURITY": r"HKLM\SECURITY",
    "DEFAULT": r"HKU\.DEFAULT",
    # AmCache is not mounted under any HKEY, so there is no API route to it:
    # the file is the only way in, which is why it has no entry here.
}

# A key that must open in an acquired hive before it is believed. A truncated
# copy still "exists", and parsing one produces a confidently empty result
# rather than an error - the failure mode this whole effort keeps meeting.
VALIDATE = {
    "SYSTEM": ["Select"],
    "SOFTWARE": ["Microsoft"],
    "SAM": ["SAM", "Domains", "Account", "Users"],
    "SECURITY": ["Policy"],
    "DEFAULT": ["Software"],
    "NTUSER.DAT": ["Software"],
    # UsrClass's root IS Software\Classes, so its own tree starts
    # at Local Settings rather than at Software.
    "UsrClass.dat": ["Local Settings"],
    "AmCache": ["Root"],
}

# Routes, in the order they are tried. Recorded per hive because it decides how
# to read the result: carved tables that are empty mean "nothing was deleted"
# after a file route, and "this route cannot see deletions" after an export.
ROUTE_FILE = "file:%s"              # %s is standard / vss / raw_disk
ROUTE_EXPORT = "export:ntsavekeyex"
ROUTE_API = "api:winreg"


def _kind(hive_label):
    """SYSTEM from "SYSTEM", NTUSER.DAT from "NTUSER.DAT[Ghass]".

    Per-user labels carry the profile so two users' hives do not collide in the
    case, but the validation and export tables are keyed on the hive KIND -
    without this, a per-user hive is validated against nothing and silently
    accepted however broken it is.
    """
    return hive_label.split("[", 1)[0] if hive_label else hive_label


def _is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _validates(path, components):
    """Does this file open as a hive, and does the key that must be there open?"""
    try:
        from Registry import Registry
    except ImportError:
        # Cannot check, so do not claim it passed. The caller decides.
        return True
    try:
        reg = Registry.Registry(path)
        if components:
            reg.open("\\".join(components))
        return True
    except Exception as exc:
        logger.debug("acquired hive %s did not validate: %s", path, exc)
        return False


def _try_file_ladder(source, dest, allow_snapshot_creation):
    """(path, route) from crow_claw's accessor, or ('', '').

    This is the route that yields the REAL file, which is the only one carving
    can use.
    """
    try:
        from Artifacts_Collectors.crow_claw.core.file_accessor import FileAccessor
    except Exception:
        try:
            from crow_claw.core.file_accessor import FileAccessor
        except Exception as exc:
            logger.debug("FileAccessor unavailable: %s", exc)
            return "", ""

    try:
        accessor = FileAccessor(is_admin=_is_admin())
        # The accessor prints its progress, which belongs in a collection log
        # and not in the middle of a parse's output.
        accessor._report_progress = lambda message: logger.debug("%s", message)

        if not allow_snapshot_creation:
            _forbid_snapshot_creation(accessor)

        result = accessor.access_file_with_retry(source, dest, "Registry Hives")
        if getattr(result, "success", False) and os.path.exists(dest):
            return dest, ROUTE_FILE % (getattr(result, "strategy_used", "") or "unknown")
    except Exception as exc:
        logger.debug("file ladder failed for %s: %s", source, exc)
    return "", ""


def _forbid_snapshot_creation(accessor):
    """Let the VSS strategy use snapshots that exist, and create none.

    A parse reads; whether it may also write to the machine under investigation
    is the analyst's call, and this is the half of that setting the accessor
    has no flag for. Setting it on the instance leaves the collector's own
    behaviour alone.
    """
    for strategy in getattr(accessor, "strategies", []):
        if type(strategy).__name__ == "VSSAccessStrategy":
            strategy.allow_snapshot_creation = False


@contextlib.contextmanager
def acquire_hive(hive_label, on_disk_path=None, allow_snapshot_creation=True):
    """Yield (path, route) for a live hive. Never raises.

    The path is empty when nothing worked, and `route` then says why in the
    same field the case records - so "we could not read it" is a value in the
    data rather than a silence.

    Args:
        hive_label: SYSTEM, SOFTWARE, SAM, SECURITY or DEFAULT
        on_disk_path: override for the source file, e.g. from hivelist
        allow_snapshot_creation: may a shadow copy be CREATED if none exists.
            Default True. Off, existing snapshots are still used.
    """
    workspace = None
    try:
        if os.name != "nt":
            yield "", ROUTE_API
            return

        source = on_disk_path or STANDARD_HIVES.get(_kind(hive_label), "")
        workspace = tempfile.mkdtemp(prefix="crow_eye_hive_")
        dest = os.path.join(workspace, hive_label)

        # 1. The real file, which is the only route carving can use.
        if source:
            path, route = _try_file_ladder(source, dest, allow_snapshot_creation)
            if path and _validates(path, VALIDATE.get(_kind(hive_label))):
                # Same replay as the memoised path. Two acquisition entry
                # points that disagree about whether the logs were applied
                # would produce two different registries from one machine.
                path, route = _replay_if_dirty(
                    source, path, route, allow_snapshot_creation)
                yield path, route
                return
            if path:
                # It copied something that is not a usable hive. Keep going
                # rather than hand back a file that parses to nothing.
                logger.debug("%s came back by %s but did not validate", hive_label, route)

        # 2. NtSaveKeyEx, which defeats the ACLs but writes a clean tree - so
        #    everything except carving still works.
        reg_path = REG_PATHS.get(_kind(hive_label))
        if reg_path:
            try:
                from Artifacts_Collectors import user_identity
            except Exception:
                user_identity = None
            if user_identity is not None:
                try:
                    with user_identity.live_hive_export(
                            reg_path, hive_label, VALIDATE.get(_kind(hive_label)),
                            "crow_eye_export_") as exported:
                        if exported:
                            yield exported, ROUTE_EXPORT
                            return
                except Exception as exc:
                    logger.debug("export failed for %s: %s", hive_label, exc)

        # 3. Nothing. The caller falls back to reading through the API, which
        #    is what it did before any of this existed.
        yield "", ROUTE_API
    except Exception as exc:                                # pragma: no cover
        logger.error("hive acquisition failed for %s: %s", hive_label, exc)
        yield "", ROUTE_API
    finally:
        if workspace:
            shutil.rmtree(workspace, ignore_errors=True)


# ---------------------------------------------------------------------------
# One acquisition per hive, shared across a parse.
#
# A live parse wants the same hive in more than one place - the USB section
# needs the device property timestamps, the structure walk needs the whole file
# - and acquiring SYSTEM costs about two seconds through VSS. Memoised, the way
# registry_transaction_log memoises its replays, so the second caller pays
# nothing.
# ---------------------------------------------------------------------------

_acquired = {}
_workspace = None


def _shared_workspace():
    global _workspace
    if _workspace is None:
        import atexit
        _workspace = tempfile.mkdtemp(prefix="crow_eye_hives_")
        atexit.register(shutil.rmtree, _workspace, True)
    return _workspace


def acquired_hive(hive_label, on_disk_path=None, allow_snapshot_creation=True):
    """(path, route) for a live hive, acquired once and reused.

    Same contract as acquire_hive, without the context manager: the copies live
    until the process exits, because several parts of one parse want them and
    re-acquiring is the expensive half. Call release() to drop them sooner.
    """
    if hive_label in _acquired:
        return _acquired[hive_label]

    result = ("", ROUTE_API)
    try:
        if os.name == "nt":
            source = on_disk_path or STANDARD_HIVES.get(_kind(hive_label), "")
            dest = os.path.join(_shared_workspace(), hive_label)
            if source:
                path, route = _try_file_ladder(source, dest, allow_snapshot_creation)
                if path and _validates(path, VALIDATE.get(_kind(hive_label))):
                    # Bring the logs and replay them. A hive Windows has open is
                    # mid-transaction, and reading it as found reports a
                    # registry that is quietly stale - the outstanding changes
                    # are in the .LOG1/.LOG2 beside it, not in the file.
                    path, route = _replay_if_dirty(
                        source, path, route, allow_snapshot_creation)
                    result = (path, route)

            if not result[0]:
                # The export cleans up after itself, so its copy is taken out of
                # the context manager and into the shared workspace to outlive it.
                reg_path = REG_PATHS.get(_kind(hive_label))
                if reg_path:
                    try:
                        from Artifacts_Collectors import user_identity
                        with user_identity.live_hive_export(
                                reg_path, hive_label, VALIDATE.get(_kind(hive_label)),
                                "crow_eye_export_") as exported:
                            if exported:
                                keep = os.path.join(_shared_workspace(),
                                                    hive_label + ".export")
                                shutil.copy2(exported, keep)
                                result = (keep, ROUTE_EXPORT)
                    except Exception as exc:
                        logger.debug("export failed for %s: %s", hive_label, exc)
    except Exception as exc:                                # pragma: no cover
        logger.error("hive acquisition failed for %s: %s", hive_label, exc)

    _acquired[hive_label] = result
    return result


def release():
    """Drop the acquired copies. Called at exit anyway; this is for tests."""
    global _workspace
    _acquired.clear()
    if _workspace:
        shutil.rmtree(_workspace, ignore_errors=True)
        _workspace = None


def _replay_if_dirty(source_hive, acquired, route, allow_snapshot_creation):
    """(path, route) after applying the hive's transaction logs, if it needs them.

    Carving must run on the REPLAYED copy, not the acquired one: a key freed by
    a transaction still sitting in the log is only visible once that log is
    applied, and every table in the case should describe one state rather than
    two.

    A hive whose logs cannot be acquired is returned unchanged, and the route
    says so. That is the offline path's rule as well: parse what is there, and
    record that it may not be the final registry, rather than dropping evidence
    for being incomplete.
    """
    try:
        from Artifacts_Collectors import registry_transaction_log as rtl
    except Exception:
        return acquired, route

    try:
        base = rtl.read_base_block(acquired)
        if not base or not base.get("is_dirty"):
            return acquired, route

        acquire_logs(source_hive, acquired, allow_snapshot_creation)

        recovered_path = acquired + ".recovered"
        outcome = rtl.recover_hive(acquired, recovered_path)
        if outcome.recovered:
            return outcome.recovered_path, route + "+replayed"
        return acquired, route + "+dirty-not-replayed"
    except Exception as exc:
        logger.debug("replay failed for %s: %s", acquired, exc)
        return acquired, route


def user_hives():
    """[(label, path)] for every per-user hive on this machine.

    NTUSER.DAT and UsrClass.dat are where Shellbags, RecentDocs, UserAssist,
    MuiCache and TypedPaths live - the per-user activity most investigations
    turn on - and the live parser was reading none of it as a file. Profiles
    come from ProfileList, which is what the offline path uses too, so the two
    agree on which users exist.
    """
    found = []
    if os.name != "nt":
        return found

    profiles = {}
    try:
        from Artifacts_Collectors import user_identity
        profiles = user_identity._profile_list_live() or {}
    except Exception as exc:
        logger.debug("could not read ProfileList: %s", exc)

    if not profiles:
        # ProfileList is the right answer; the Users directory is the fallback
        # for a machine where it could not be read, so a live parse still sees
        # per-user hives rather than none.
        users_root = os.path.join(os.path.splitdrive(SYSTEM_ROOT)[0] + "\\", "Users")
        try:
            profiles = {name: os.path.join(users_root, name)
                        for name in os.listdir(users_root)
                        if os.path.isdir(os.path.join(users_root, name))}
        except OSError:
            profiles = {}

    # The service accounts keep their profiles elsewhere and each carries a Run
    # entry on a stock machine, so a parse that skips them misses persistence.
    service_root = os.path.join(SYSTEM_ROOT, "ServiceProfiles")
    for account in ("LocalService", "NetworkService"):
        profiles.setdefault("ServiceProfiles-" + account,
                            os.path.join(service_root, account))

    for owner, profile_path in profiles.items():
        if not profile_path:
            continue
        label_owner = os.path.basename(str(profile_path).rstrip("\\/")) or str(owner)
        ntuser = os.path.join(profile_path, "NTUSER.DAT")
        usrclass = os.path.join(profile_path, "AppData", "Local", "Microsoft",
                                "Windows", "UsrClass.dat")
        if os.path.exists(ntuser):
            found.append(("NTUSER.DAT[%s]" % label_owner, ntuser))
        if os.path.exists(usrclass):
            found.append(("UsrClass.dat[%s]" % label_owner, usrclass))
    return found


def acquire_logs(source_hive, acquired_hive, allow_snapshot_creation=True):
    """Copy a hive's .LOG1/.LOG2 next to the acquired copy. Returns what landed.

    They land as `<acquired hive>.LOG1` and `.LOG2` because that is how
    registry_transaction_log.find_logs_for() finds them: beside the hive, same
    basename. Anywhere else and the replay reports a dirty hive with no logs.

    Replay needs these, and they sit under the same ACLs as the hive, so the
    same ladder gets them. Without them a live parse reads the hive as found
    and misses the most recent registry activity there is - which is the whole
    point of the journal.
    """
    landed = []
    for extension in (".LOG1", ".LOG2"):
        source = source_hive + extension
        if not os.path.exists(source):
            continue
        path, _route = _try_file_ladder(source, acquired_hive + extension,
                                        allow_snapshot_creation)
        if path:
            landed.append(path)
    return landed


def route_can_carve(route):
    """Only the real file carries freed cells.

    An NtSaveKeyEx export is a fresh write of the live tree, so carving it finds
    nothing - and reporting that as "no deleted keys" would be a confident wrong
    answer about a hive that may hold thousands.
    """
    return bool(route) and route.startswith("file:")
