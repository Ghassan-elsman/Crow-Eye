"""Running without Administrator rights: what it costs, and getting them back.

A live parse reads files Windows protects. Unelevated, those reads are
refused, and the parse used to carry on and report the refusals as failures
in a report nobody was prompted to open. Now:

* before a live parse that needs rights, the analyst is asked
  (ui/elevation_dialog.py, "before"): restart as Administrator, run anyway,
  or cancel;
* after a parse whose artifacts were refused, ONE pop-up names them and offers
  the restart ("after") - in place of the Parse Status report, never as well;
* the restart reopens the same case (``--open-case``).

Nothing here touches Qt; the decisions are plain functions so they can be
tested without a window.
"""
import os
import sys

# artifact -> (need, why). "required": nothing can be read unelevated.
# "partial": some of it can (the user's own data), the rest is refused.
ADMIN_NEEDS = {
    "mft": ("required", "raw reads of the NTFS volume"),
    "usn": ("required", "raw reads of the NTFS volume"),
    "mft_usn_correlation": ("required", "built from the MFT and the USN journal"),
    "prefetch": ("required", "C:\\Windows\\Prefetch is readable by Administrators only"),
    "srum": ("required", "SRUDB.dat is held open by Windows"),
    "amcache": ("required", "Amcache.hve is held open by Windows"),
    "evtx": ("partial", "the Security log and several others need elevation"),
    "registry": ("partial", "the SAM and SECURITY hives and other users' hives need elevation"),
    "browser": ("partial", "other users' browser profiles need elevation"),
    "recyclebin": ("partial", "other users' Recycle Bin folders need elevation"),
}

ENV_NO_SELF_ELEVATE = "CROWEYE_NO_SELF_ELEVATE"
OPEN_CASE_ARG = "--open-case"


def is_elevated():
    """True when this process holds Administrator (Windows) or root (POSIX) rights."""
    if os.name == "nt":
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def self_elevate_disabled():
    """Developer switch: start unelevated from source, to see what an analyst
    without rights sees (the start-up UAC prompt is skipped)."""
    return os.environ.get(ENV_NO_SELF_ELEVATE) == "1"


def admin_needs(artifacts):
    """(required, partial) artifact lists out of ``artifacts``, in the given order."""
    required, partial = [], []
    for a in artifacts or ():
        need = ADMIN_NEEDS.get(a, (None,))[0]
        if need == "required":
            required.append(a)
        elif need == "partial":
            partial.append(a)
    return required, partial


def precheck_needed(artifacts, elevated=None):
    """Should the "before" question be asked for this live parse?"""
    if elevated is None:
        elevated = is_elevated()
    if elevated:
        return False
    required, partial = admin_needs(artifacts)
    return bool(required or partial)


def denied_outcomes(outcomes):
    """The ACCESS_DENIED outcomes of a run."""
    from utils.parse_status import ParseStatus
    return [o for o in outcomes or () if getattr(o, "status", None) == ParseStatus.ACCESS_DENIED]


def elevation_popup_needed(outcomes, mode, elevated=None):
    """The outcomes to name in the "after" pop-up, or [] for no pop-up.

    Only for a LIVE run, only when Crow-Eye is not elevated (restarting
    elevated is the remedy the pop-up offers - when it already is, a refusal
    is a lock or an ACL, and the Parse Status report explains it), and only
    when something was actually refused.
    """
    if mode != "live":
        return []
    if elevated is None:
        elevated = is_elevated()
    if elevated:
        return []
    return denied_outcomes(outcomes)


def can_relaunch():
    """Is a self-restart with elevation possible here? (Windows only.)"""
    return os.name == "nt"


def relaunch_command(case_root=None, argv=None, frozen=None, executable=None):
    """(executable, parameters) for an elevated restart that reopens ``case_root``.

    Source: python.exe "<Crow Eye.py>" <args>; frozen: Crow-Eye.exe <args>.
    Any earlier --open-case is replaced.
    """
    argv = list(sys.argv if argv is None else argv)
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    executable = executable or sys.executable
    rest = []
    skip = False
    for a in argv[1:]:
        if skip:
            skip = False
            continue
        if a == OPEN_CASE_ARG:
            skip = True
            continue
        if a.startswith(OPEN_CASE_ARG + "="):
            continue
        rest.append(a)
    if case_root:
        rest += [OPEN_CASE_ARG, case_root]
    if not frozen:
        rest = [os.path.abspath(argv[0])] + rest
    return executable, " ".join(_quote(a) for a in rest)


def _quote(arg):
    """Windows command-line quoting for one argument (CommandLineToArgvW rules)."""
    if arg and not any(c in arg for c in ' \t"'):
        return arg
    out, slashes = ['"'], 0
    for c in arg:
        if c == "\\":
            slashes += 1
            continue
        if c == '"':
            out.append("\\" * (slashes * 2 + 1) + '"')
        else:
            out.append("\\" * slashes + c)
        slashes = 0
    out.append("\\" * (slashes * 2) + '"')
    return "".join(out)


def relaunch_elevated(case_root=None):
    """Start an elevated Crow-Eye on ``case_root``. True when UAC was accepted.

    The caller quits this instance only on True: when the analyst declines the
    UAC prompt, ShellExecuteW returns 5 and Crow-Eye simply carries on.
    """
    if not can_relaunch():
        return False
    exe, params = relaunch_command(case_root)
    try:
        import ctypes
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    except Exception:
        return False
    return rc > 32


def open_case_from_argv(argv=None):
    """The case folder named by --open-case, if it exists."""
    argv = list(sys.argv if argv is None else argv)
    for i, a in enumerate(argv):
        path = None
        if a == OPEN_CASE_ARG and i + 1 < len(argv):
            path = argv[i + 1]
        elif a.startswith(OPEN_CASE_ARG + "="):
            path = a.split("=", 1)[1]
        if path and os.path.isdir(path):
            return path
    return None
