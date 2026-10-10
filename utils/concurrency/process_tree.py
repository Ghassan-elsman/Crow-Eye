"""Ending a parse's processes - all of them.

A live Parse All is a tree: the collector process, its ProcessPoolExecutor
workers, and whatever those start (esentutl, vssadmin, powershell). On
Windows, terminating the collector does not end its children: the pool
workers carried on as orphans, writing their databases after the analyst had
cancelled, and kept going after Crow-Eye was closed.

JobObject   groups the collector and everything it starts, so one call ends
            the lot. Deliberately NOT kill-on-close: if the GUI itself
            crashes, the collector must still be able to delete the shadow
            copy it created and close its custody record.
kill_tree   the portable fallback: psutil, children snapshotted BEFORE the
            parent dies (its PPID link goes with it), several passes to catch
            late spawns.
run_with_timeout  a subprocess call that cannot hang Crow-Eye, and kills the
            whole tree on timeout (npm under shell=True runs in cmd.exe -
            killing cmd.exe alone leaves node running).
"""
import logging
import os
import subprocess
import time

logger = logging.getLogger(__name__)


class JobObject(object):
    """A Windows job object; a no-op elsewhere (kill_tree covers POSIX)."""

    def __init__(self):
        self.handle = None
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes
            self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._k32.CreateJobObjectW.restype = wintypes.HANDLE
            self._k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            self._k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            self._k32.AssignProcessToJobObject.restype = wintypes.BOOL
            self._k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            self._k32.TerminateJobObject.restype = wintypes.BOOL
            self._k32.OpenProcess.restype = wintypes.HANDLE
            self._k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            self._k32.CloseHandle.argtypes = [wintypes.HANDLE]
            self.handle = self._k32.CreateJobObjectW(None, None)
        except Exception as e:
            logger.debug("job object unavailable: %s", e)
            self.handle = None

    def assign(self, pid):
        """Put a process (and every process it starts afterwards) in the job."""
        if not self.handle:
            return False
        PROCESS_SET_QUOTA, PROCESS_TERMINATE = 0x0100, 0x0001
        h = self._k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, int(pid))
        if not h:
            return False
        try:
            return bool(self._k32.AssignProcessToJobObject(self.handle, h))
        finally:
            self._k32.CloseHandle(h)

    def terminate(self, exit_code=1):
        if self.handle:
            try:
                return bool(self._k32.TerminateJobObject(self.handle, exit_code))
            except Exception:
                return False
        return False

    def close(self):
        if self.handle:
            try:
                self._k32.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None


def snapshot_tree(pid, include_parent=True):
    """psutil.Process objects for ``pid``'s descendants (and ``pid``), now.

    Objects, not pids: each carries its creation time, so ending it later can
    never hit an unrelated process that was given the same pid in between.
    """
    try:
        import psutil
        root = psutil.Process(int(pid))
        procs = root.children(recursive=True)
        if include_parent:
            procs.append(root)
        return procs
    except Exception:
        return []


def end_processes(procs, grace=3.0):
    """Terminate, wait ``grace``, kill. Only processes still the same ones."""
    try:
        import psutil
    except ImportError:
        return []
    procs = [p for p in procs if _running(p)]
    if not procs:
        return []
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    _gone, alive = psutil.wait_procs(procs, timeout=max(0.1, grace))
    for p in alive:
        try:
            p.kill()
        except Exception:
            pass
    psutil.wait_procs(alive, timeout=2)
    return sorted(p.pid for p in procs)


def kill_tree(pid, grace=3.0, include_parent=True):
    """End ``pid`` and every descendant. Returns the pids that were ended."""
    ended = set()
    for _pass in range(3):
        got = end_processes(snapshot_tree(pid, include_parent), grace)
        if not got:
            break
        ended.update(got)
    return sorted(ended)


def _running(p):
    try:
        return p.is_running()
    except Exception:
        return False


def child_pids(pid):
    try:
        import psutil
        return [c.pid for c in psutil.Process(int(pid)).children(recursive=True)]
    except Exception:
        return []


def run_with_timeout(cmd, timeout, **kwargs):
    """subprocess.run, but a timeout ends the whole process tree.

    Returns a CompletedProcess; raises subprocess.TimeoutExpired after the tree
    has been ended.
    """
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    proc = subprocess.Popen(cmd, **kwargs)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(proc.pid, grace=2.0)
        try:
            proc.communicate(timeout=5)
        except Exception:
            pass
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
