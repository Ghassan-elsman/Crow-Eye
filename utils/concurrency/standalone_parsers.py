import multiprocessing
import os
import sys
import concurrent.futures
import time
from typing import Callable, Any, Optional

# Parse-status buckets for the log line (values of utils.parse_status.ParseStatus).
_NEUTRAL_STATUSES = {"NO_RECORDS", "SOURCE_NOT_FOUND", "FEATURE_DISABLED", "NOT_RUN"}
_FAILURE_STATUSES = {"UNSUPPORTED_FORMAT", "ACCESS_DENIED", "DEPENDENCY_MISSING",
                     "PARTIAL", "FAILED"}

# Stages that are only meaningful when others succeeded. Correlating MFT and
# USN after the MFT parse failed produced an empty correlation reported as if
# it had run; now it is reported as not run, with the reason.
STAGE_DEPENDS = {"mft_usn_correlation": ("mft", "usn")}
_USABLE = {"PARSED", "PARTIAL"}

# How long cancelled pool workers get to stop on their own before their
# process trees are ended.
CANCEL_GRACE_SECONDS = 3.0

# Tests swap this for a builder of their own dummy tasks.
_TASK_BUILDER = None

# MFT and USN run in a process of their own (killable on cancel). Tests swap
# this for an in-process executor factory: their stub MFT_Claw / USN_Claw live
# in THIS process's sys.modules, which a spawned process does not share - a
# spawned worker would import, and run, the real parsers.
_HEAVY_EXECUTOR = None

# What the bar says when each of the two finishes (the pool says COLLECTED).
_HEAVY_DONE = {"mft": "PARSED MASTER FILE TABLE", "usn": "PARSED USN JOURNAL"}


def is_cancelled(cancel_event):
    """Safely check if cancellation event is set, handling cases where manager might be shut down."""
    if cancel_event is None:
        return False
    try:
        return cancel_event.is_set()
    except Exception:
        # If manager is shut down or connection lost, assume not cancelled
        # or just stop checking to avoid crashing the whole process
        return False


def _error_dict(e):
    """A task's failure as data - whatever was raised.

    SystemExit included: amcacheparser and Regclaw call sys.exit() when they
    cannot go on. Caught as `except Exception` it escaped, came back out of
    future.result() and ended the whole collector - MFT, USN and correlation
    never ran and no error was reported.
    """
    import traceback
    out = {"error": str(e) or type(e).__name__, "error_type": type(e).__name__,
           "traceback": traceback.format_exc()}
    if isinstance(e, SystemExit):
        out["exit_code"] = e.code
        out["error"] = "the parser stopped itself (sys.exit(%r))" % (e.code,)
    winerror = getattr(e, "winerror", None)
    if winerror is not None:
        out["winerror"] = winerror
    return out


def run_task(task_func, *args, **kwargs):
    """Helper to run a task and catch exceptions for the pool."""
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

    try:
        return task_func(*args, **kwargs)
    except KeyboardInterrupt:
        raise
    except BaseException as e:
        return _error_dict(e)

def run_task_logged(message_queue, artifact, label, source, task_func, *args, **kwargs):
    """run_task, framed by artifact_run and logging back to the GUI process.

    The pool workers are processes of their own: nothing they print or log
    reaches the case unless it is sent back over the queue.
    """
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
    try:
        from utils.parse_logging import (artifact_run, flush_child_logging,
                                         install_child_logging, records_from_result)
    except Exception:
        return run_task(task_func, *args, **kwargs)
    install_child_logging(message_queue)

    def _progress(event):
        try:
            message_queue.put({"type": "artifact_progress", "event": event})
        except Exception:
            pass

    holder = {}
    try:
        with artifact_run(artifact, label, source=source, mode="live", progress=_progress) as run:
            holder["run"] = run
            result = task_func(*args, **kwargs)
            run.set_records(records_from_result(result))
            return with_excerpt(result, run)
    except KeyboardInterrupt:
        raise
    except BaseException as e:
        return with_excerpt(_error_dict(e), holder.get("run"))
    finally:
        # A pool worker exits without atexit: send the tail of the log now.
        flush_child_logging()


def with_excerpt(result, run):
    """The result plus the warning / error lines the parser printed.

    They reached parsers.log and the loading dialog's tooltip, and were then
    dropped: the Parse Status report could only say "Parser exited with code
    1". Unwrapped by the collector (unwrap_task_result) before the outcome is
    classified.
    """
    return {"__task_result__": True, "result": result,
            "log_excerpt": list(getattr(run, "excerpt", None) or [])}


def unwrap_task_result(res):
    """(result, log excerpt) from a with_excerpt() wrapper, or (res, [])."""
    if isinstance(res, dict) and res.get("__task_result__"):
        return res.get("result"), list(res.get("log_excerpt") or [])
    return res, []


def run_claw_in_case(case_root, root_dir, module_name):
    """MFT_Claw / USN_Claw main() for the live parse, in a worker process.

    Both write to ./Target_Artifacts, so the case must be the working
    directory - and os.chdir() is process-wide, which is why they run in a
    process of their own rather than on a thread of the collector.
    """
    path = os.path.join(root_dir, "Artifacts_Collectors", "MFT and USN journal")
    if path not in sys.path:
        sys.path.insert(0, path)
    import importlib
    module = importlib.import_module(module_name)
    before = os.getcwd()
    os.chdir(case_root)
    try:
        code = module.main()
        if isinstance(code, dict):
            return code
        # The exit code AND what the run read / added (main() only returns the
        # code; the module keeps the counts in LAST_COUNTS).
        out = {"exit_code": code}
        out.update(getattr(module, "LAST_COUNTS", None) or {})
        return out
    finally:
        os.chdir(before)


def _run_heavy_inline(artifact, label, source, module_name, case_root, root_dir, progress):
    """run_claw_in_case in this process (the _HEAVY_EXECUTOR path), with the
    same contract as run_task_logged: framed by artifact_run, never raises."""
    try:
        from utils.parse_logging import artifact_run, records_from_result
        with artifact_run(artifact, label, source=source, mode="live", progress=progress) as run:
            result = run_claw_in_case(case_root, root_dir, module_name)
            run.set_records(records_from_result(result))
            return with_excerpt(result, run)
    except KeyboardInterrupt:
        raise
    except BaseException as e:
        return _error_dict(e)


def _worker_init(ctx):
    """Every pool worker, before its first task.

    The worker is a process of its own, so what the collector set up does not
    reach it: temporary files would go to the target's %TEMP%, its reads and
    shadow-copy use would be missing from the run's custody record, and it
    would not know which snapshot the collector made for the run.
    """
    root = ctx.get("root_dir")
    if root and root not in sys.path:
        sys.path.insert(0, root)
    tmp = ctx.get("tmp_dir")
    if tmp:
        try:
            import tempfile
            os.makedirs(tmp, exist_ok=True)
            os.environ["TMP"] = os.environ["TEMP"] = tmp
            tempfile.tempdir = tmp
        except OSError:
            pass
    if ctx.get("case_root") and ctx.get("run_id"):
        try:
            from utils import custody
            custody.begin_fragment(ctx["case_root"], ctx["run_id"])
        except Exception:
            pass
    if ctx.get("shared_snapshots"):
        try:
            from Artifacts_Collectors.crow_claw.core.vss_access_strategy import register_shared_snapshots
            register_shared_snapshots(ctx["shared_snapshots"])
        except Exception:
            pass


def run_shimcache_global(db):
    """Global wrapper for ShimCache to allow multiprocessing to pickle it."""
    from Artifacts_Collectors.shimcash_claw import ShimCacheParser
    p = ShimCacheParser(db)
    # The result (records / new / already present), which Parse Status reads.
    return p.run()

def standalone_collect_live_artifacts(case_paths, windows_partition, message_queue, cancel_event=None,
                                      custody_run_id=None):
    """Run the live collection, and ALWAYS tell the GUI it has ended.

    The cancel checks used to `return` without sending DONE, and an
    exception escaping the handler did the same: the GUI's reporter then
    waited for ever, the dialog sat on "CANCELLING...", and every later Parse
    All was refused because the previous one looked still running.
    """
    rec = _begin_live_custody(case_paths, windows_partition, message_queue,
                              run_id=custody_run_id, cancel_event=cancel_event)
    status = "failed"
    try:
        _collect_live_artifacts(case_paths, windows_partition, message_queue, cancel_event,
                                run_id=getattr(rec, "run_id", None) or custody_run_id)
        status = "cancelled" if is_cancelled(cancel_event) else "completed"
    finally:
        _end_live_custody(rec, status, message_queue)
        try:
            from utils.parse_logging import flush_child_logging
            flush_child_logging()
        except Exception:
            pass
        try:
            if is_cancelled(cancel_event):
                message_queue.put({"type": "log_message",
                                   "message": "[Cancelled] Live collection stopped by the investigator.",
                                   "is_log_update": True})
            message_queue.put({"type": "DONE"})
        except Exception:
            pass


def _post_line(message_queue, text):
    try:
        message_queue.put({"type": "log_message", "message": text, "is_log_update": True})
    except Exception:
        pass


def _begin_live_custody(case_paths, windows_partition, message_queue, run_id=None, cancel_event=None):
    """Open the chain-of-custody record for a live parse, with its source inventory.

    Never raises: a record that cannot be written is reported, and the parse
    goes ahead - refusing to parse because a log could not be opened would
    trade the evidence for the paperwork. Journaled, so the pool workers'
    fragments merge into it and a killed run can be salvaged.
    """
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)
    try:
        from utils import custody
        case_root = (case_paths or {}).get('case_root') or (case_paths or {}).get('artifacts_dir')
        if not case_root:
            return None
        rec = custody.begin(case_root, "live parse",
                            options={"windows_partition": windows_partition, "mode": "Parse All (live)"},
                            output_dir=(case_paths or {}).get('artifacts_dir'),
                            run_id=run_id, journal=True)
        for warning in rec.data["warnings"]:
            _post_line(message_queue, "[WARNING] " + warning)
        if os.name == "nt":
            _post_line(message_queue, "[Custody] Recording the evidence files before they are read...")
            n = rec.inventory(custody.live_source_patterns(windows_partition or "C:"),
                              should_stop=lambda: is_cancelled(cancel_event))
            _post_line(message_queue, "[Custody] %d source file(s) recorded (size, times, SHA-256 "
                                      "where readable)." % n)
        return rec
    except Exception as e:
        _post_line(message_queue, "[WARNING] Chain-of-custody record not started: %s" % e)
        return None


# Outcomes that are not a failure of the run: parsed, or nothing there to parse.
_CUSTODY_OK = {"PARSED", "NO_RECORDS", "SOURCE_NOT_FOUND", "FEATURE_DISABLED"}


def _custody_outcome(outcome):
    """Each artifact's Parse Status outcome, into the run's custody record.

    Every artifact is listed (records, status, message); anything other than
    parsed / not on this machine is also a failure entry. A record that said
    "0 failures" while Parse Status showed failed and partial artifacts was
    the record being wrong, not the run being clean.
    """
    try:
        from utils import custody
        rec = custody.active()
        if rec is None or not isinstance(outcome, dict):
            return
        item = {k: outcome.get(k) for k in ("artifact", "status", "records", "message",
                                             "duration_seconds", "inserted", "duplicates",
                                             "rows_before", "rows_after", "error")
                if outcome.get(k) not in (None, "")}
        if outcome.get("log_excerpt") and str(outcome.get("status")) not in _CUSTODY_OK:
            item["log_excerpt"] = list(outcome["log_excerpt"])[-30:]
        if outcome.get("indexes_created"):
            item["indexes_created"] = list(outcome["indexes_created"])
        with rec._lock:
            rec.data.setdefault("artifacts", []).append(item)
        status = str(outcome.get("status") or "")
        if status and status not in _CUSTODY_OK:
            rec.add_failure(outcome.get("artifact"), outcome.get("message") or status.lower(),
                            method="parse", status=status, error=outcome.get("error") or None)
    except Exception:
        pass


def _end_live_custody(rec, status, message_queue):
    """Delete the shadow copies this parse created, hash what it wrote, then
    close the record."""
    try:
        from Artifacts_Collectors.crow_claw.core.shadow_copy_manager import delete_created_shadow_copies
    except Exception:
        try:
            from crow_claw.core.shadow_copy_manager import delete_created_shadow_copies
        except Exception:
            delete_created_shadow_copies = None
    if delete_created_shadow_copies is not None:
        try:
            for sid, gone in delete_created_shadow_copies().items():
                _post_line(message_queue,
                           ("[Custody] Deleted the shadow copy this parse created: %s" if gone
                            else "[WARNING] Could not delete shadow copy %s - it is still on the target")
                           % sid)
                if gone:
                    try:
                        message_queue.put({"type": "shadow_copy_deleted", "id": sid})
                    except Exception:
                        pass
        except Exception as e:
            _post_line(message_queue, "[WARNING] Shadow copy cleanup failed: %s" % e)
    if rec is None:
        return
    try:
        _post_line(message_queue, "[Custody] Hashing the databases this parse wrote...")
        n = rec.record_outputs(progress=lambda p: _post_line(
            message_queue, "[Custody] SHA-256 %s" % os.path.basename(p)))
        _post_line(message_queue, "[Custody] %d output file(s) recorded." % n)
    except Exception as e:
        _post_line(message_queue, "[WARNING] Output databases not hashed: %s" % e)
    try:
        from utils import custody
        path = custody.end(status, rec=rec)
        if path:
            _post_line(message_queue, "[Custody] Record written: %s" % path)
    except Exception as e:
        _post_line(message_queue, "[WARNING] Chain-of-custody record not written: %s" % e)


def _build_parallel_tasks(case_paths, windows_partition):
    """(func, args, kwargs, label, step, artifact) for every independent collector."""
    if _TASK_BUILDER is not None:
        return _TASK_BUILDER(case_paths, windows_partition)
    case_root = case_paths.get('case_root') if case_paths else None
    artifacts_dir = case_paths.get('artifacts_dir') if case_paths else None
    tasks = []

    # Registry
    from Artifacts_Collectors.Regclaw import parse_live_registry
    reg_db = os.path.join(artifacts_dir, 'registry_data.db') if artifacts_dir else None
    tasks.append((parse_live_registry, (case_root, reg_db), {}, "Registry Hives & Execution Data", 2, "registry"))

    # LNK / Jump Lists
    from Artifacts_Collectors.A_CJL_LNK_Claw import A_CJL_LNK_Claw
    tasks.append((A_CJL_LNK_Claw, (), {'case_path': case_root, 'offline_mode': False, 'direct_parse': True}, "LNK & Jump Lists", 4, "lnk_jumplist"))

    # Prefetch
    from Artifacts_Collectors.Prefetch_claw import prefetch_claw
    tasks.append((prefetch_claw, (case_root, False, windows_partition), {}, "Prefetch evidence", 5, "prefetch"))

    # Event Logs
    from Artifacts_Collectors.WinLog_Claw import main as collect_logs
    tasks.append((collect_logs, (case_root,), {}, "Windows Event Logs", 6, "evtx"))

    # ShimCache
    shim_db = os.path.join(artifacts_dir, 'shimcache.db') if artifacts_dir else 'shimcache.db'
    tasks.append((run_shimcache_global, (shim_db,), {}, "ShimCache (AppCompatCache)", 7, "shimcache"))

    # Amcache
    from Artifacts_Collectors.amcacheparser import parse_amcache_hive
    am_db = os.path.join(artifacts_dir, 'amcache.db') if artifacts_dir else 'amcache.db'
    tasks.append((parse_amcache_hive, (), {
        'case_path': case_root, 'offline_mode': False, 'db_path': am_db, 'windows_partition': windows_partition
    }, "Amcache data", 8, "amcache"))

    # RecycleBin
    from Artifacts_Collectors.recyclebin_claw import parse_recycle_bin
    tasks.append((parse_recycle_bin, (case_root,), {}, "RecycleBin artifacts", 9, "recyclebin"))

    # SRUM
    from Artifacts_Collectors.SRUM_Claw import parse_srum_data
    if artifacts_dir:
        tasks.append((parse_srum_data, (), {
            'case_artifacts_dir': artifacts_dir, 'windows_partition': windows_partition
        }, "SRUM network & execution data", 10, "srum"))

    # Browser (Chromium / Gecko / Electron)
    from Artifacts_Collectors.Browser_Claw import parse_browser_data
    if artifacts_dir:
        tasks.append((parse_browser_data, (), {
            'case_artifacts_dir': artifacts_dir, 'windows_partition': windows_partition
        }, "Browser data", 11, "browser"))
    return tasks


def _make_run_snapshot(tasks, windows_partition, message_queue):
    """One shadow copy for the whole run, made before the workers start. List of IDs.

    Only when it can help (registry or SRUM is scheduled - the parsers that
    read locked files through VSS), Crow-Eye is elevated, and the analyst's
    snapshot setting allows creation. Every worker then reads from this one
    snapshot instead of each finding or making its own.
    """
    if os.name != "nt" or not any(t[5] in ("registry", "srum") for t in tasks):
        return []
    try:
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            return []
    except Exception:
        return []
    try:
        from config.case_history_manager import read_global_setting
        if not read_global_setting("parser_allow_snapshot_creation", True):
            return []
    except Exception:
        pass
    try:
        from Artifacts_Collectors.crow_claw.core.shadow_copy_manager import create_run_snapshot
        sid = create_run_snapshot(windows_partition or "C:")
    except Exception as e:
        _post_line(message_queue, "[WARNING] No shadow copy for this run: %s" % e)
        return []
    if not sid:
        return []
    _post_line(message_queue, "[Custody] Shadow copy %s created for this run; every parser reads "
                              "from it, and it is deleted when the run ends." % sid)
    try:
        message_queue.put({"type": "shadow_copy_created", "id": sid,
                           "volume": (windows_partition or "C:")[:2]})
    except Exception:
        pass
    return [sid]


def _end_pool(executor, cancelled, log_callback):
    """Shut the pool down; on cancel, without waiting for queued work, and end
    any worker that does not stop within the grace period (a parser in the
    middle of a hive or a database does not check the cancel flag)."""
    if not cancelled:
        executor.shutdown(wait=True)
        return
    from utils.concurrency.process_tree import kill_tree, snapshot_tree, end_processes
    procs = list(getattr(executor, "_processes", {}) .values()) if getattr(executor, "_processes", None) else []
    # The workers' own children (esentutl, PowerShell, a parser subprocess),
    # taken NOW: a worker the executor ends during the grace period orphans
    # them, and an orphan can no longer be found through its parent.
    descendants = []
    for p in procs:
        descendants += snapshot_tree(p.pid, include_parent=False)
    executor.shutdown(wait=False, cancel_futures=True)
    deadline = time.time() + CANCEL_GRACE_SECONDS
    for p in procs:
        try:
            p.join(timeout=max(0.0, deadline - time.time()))
        except Exception:
            pass
    alive = [p for p in procs if _alive(p)]
    ended = set()
    for p in alive:
        try:
            ended.update(kill_tree(p.pid, grace=1.0))
        except Exception:
            pass
    # Orphans: ended by identity (pid + creation time), never by a bare pid
    # that may have been reused since the snapshot.
    ended.update(end_processes([d for d in descendants if d.pid not in ended], grace=1.0))
    if ended:
        log_callback("[Cancelled] Ended %d parser process(es) that were still running." % len(ended))


def _alive(p):
    try:
        return p.is_alive()
    except Exception:
        return False


def _collect_live_artifacts(case_paths, windows_partition, message_queue, cancel_event=None, run_id=None):
    """
    Standalone function for parsing live artifacts in a separate multiprocessing.Process.
    Optimized: Uses parallel execution with granular real-time reporting and strict
    sequential ordering for MFT and USN Journal correlation.
    """
    # Force stdout and stderr to utf-8 to prevent charmap UnicodeEncodeError on Windows
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

    # Ensure the project root is in sys.path for imports
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    # This process has no case logging; its records go to the GUI process.
    import logging
    from utils.parse_logging import artifact_run, install_child_logging, records_from_result
    install_child_logging(message_queue)
    run_log = logging.getLogger("Artifacts_Collectors.run")

    def _artifact_progress(event):
        try:
            message_queue.put({"type": "artifact_progress", "event": event})
        except Exception:
            pass

    def step_callback(step_index, step_message):
        message_queue.put({
            "type": "simple_progress",
            "step_index": step_index,
            "message": step_message,
            "is_step_update": True
        })

    # The honest count. step_callback carries each task's hard-coded step
    # CONSTANT, and the parallel pool completes out of order, so a bar driven
    # from it runs backwards - 6/16 then 3/16. This carries how many tasks have
    # actually finished out of how many there are, which only ever increases.
    _progress_state = {"done": 0, "total": 0}

    def set_total_tasks(total):
        _progress_state["total"] = int(total)

    def task_done(label=""):
        _progress_state["done"] += 1
        message_queue.put({
            "type": "task_progress",
            "completed": _progress_state["done"],
            "total": _progress_state["total"],
            "message": label,
        })

    def log_callback(message):
        message_queue.put({
            "type": "log_message",
            "message": message,
            "is_log_update": True
        })
        # Not logged here: the dialog files every line it shows under
        # crow_eye.parsing, and logging it twice would double the case log.

    # Parse status: one outcome per artifact, sent to the GUI process, which
    # records it (utils/parse_status.py). Everything here is best-effort - a
    # status report must never be the thing that stops a collection.
    def _probe(artifact, partition):
        try:
            from utils.parse_status import probe_sources
            return probe_sources(artifact, "live", partition or "C:")
        except Exception as e:
            return {"sources": [], "status": None, "message": f"probe failed: {e}"}

    rows_before = {}

    def _report(artifact, res, exc, started, probe, cancelled=False):
        res, excerpt = unwrap_task_result(res)
        try:
            from utils.parse_status import collect_live_outcome
            outcome = collect_live_outcome(
                artifact, case_paths.get('case_root') if case_paths else None,
                windows_partition, raw_result=res, exc=exc, started=started,
                probe=probe, cancelled=cancelled, rows_before=rows_before.get(artifact),
                log_excerpt=excerpt).to_dict()
        except Exception as e:
            outcome = {"artifact": artifact, "mode": "live", "status": "FAILED",
                       "records": 0, "message": f"status could not be determined: {e}"}
        message_queue.put({"type": "parse_status", "outcome": outcome})
        _custody_outcome(outcome)
        return outcome

    def _report_not_run(artifact, reason):
        outcome = {"artifact": artifact, "mode": "live", "status": "NOT_RUN",
                   "records": 0, "message": reason}
        message_queue.put({"type": "parse_status", "outcome": outcome})
        _custody_outcome(outcome)
        return outcome

    stage_status = {}

    def _run_stage(artifact, label, step, step_msg, func, done_label):
        """One of the ordered stages (MFT, USN, correlation). Never raises."""
        if is_cancelled(cancel_event):
            stage_status[artifact] = _report(artifact, None, None, time.time(),
                                             None, cancelled=True).get("status")
            task_done(done_label)
            return
        needs = STAGE_DEPENDS.get(artifact, ())
        missing = [d for d in needs if stage_status.get(d) not in _USABLE]
        if missing:
            reason = ("Skipped: %s not parsed (%s), so there is nothing to correlate."
                      % (" and ".join(m.upper() for m in missing),
                         ", ".join(str(stage_status.get(m)) for m in missing)))
            log_callback("[Skipped] %s - %s" % (label, reason))
            stage_status[artifact] = _report_not_run(artifact, reason).get("status")
            task_done(done_label)
            return
        step_callback(step, step_msg)
        started, res, exc = time.time(), None, None
        try:
            res = func()
            log_callback("[Completed] %s" % label)
        except KeyboardInterrupt:
            raise
        except BaseException as e:      # SystemExit too: it must not end the collector
            exc = e
            log_callback("[%s Error] %s" % (label, e))
        finally:
            stage_status[artifact] = (_report(artifact, res, exc, started,
                                              _probe(artifact, windows_partition)) or {}).get("status")
            task_done(done_label)

    try:
        log_callback("[Open Case] Starting full parallel live analysis...")

        case_root = case_paths.get('case_root') if case_paths else None
        artifacts_dir = case_paths.get('artifacts_dir') if case_paths else None

        # Step 0: Initialization
        step_callback(0, "INITIALIZING ARTIFACT COLLECTION")

        parallel_tasks_info = _build_parallel_tasks(case_paths, windows_partition)

        # Three tasks beyond the pool: MFT and USN (run beside it, in a process
        # of their own) and the correlation that follows both.
        SEQUENTIAL_STAGES = 3
        set_total_tasks(len(parallel_tasks_info) + SEQUENTIAL_STAGES)
        log_callback(f"[Parallel] Launching {len(parallel_tasks_info)} collectors in parallel pool...")

        # Probe every source in THIS process before the pool starts: several
        # collectors return None when their source is missing, so the probe is
        # what tells "not on this machine" apart from "the parser broke".
        probes = {}
        for _f, _a, _k, _n, _s, artifact in parallel_tasks_info:
            probes[artifact] = _probe(artifact, windows_partition)

        # Each artifact's database total before anything runs: with the total
        # after, Parse Status says what THIS run added (it used to report the
        # whole database - "MFT 19,090,321" was four tables summed - and a
        # re-parse looked like a bigger parse). The correlation is rebuilt,
        # not added to, so it is left out.
        try:
            from utils.parse_status import artifact_db_rowcount
            for artifact in [t[5] for t in parallel_tasks_info] + ["mft", "usn"]:
                rows_before[artifact] = artifact_db_rowcount(case_root, artifact) or 0
        except Exception as e:
            log_callback("[WARNING] Row counts before the parse not taken: %s" % e)

        shared = _make_run_snapshot(parallel_tasks_info, windows_partition, message_queue)
        tmp_dir = os.path.join(case_root, "tmp") if case_root else None
        worker_ctx = {"root_dir": root_dir, "tmp_dir": tmp_dir, "case_root": case_root,
                      "run_id": run_id, "shared_snapshots": shared}
        pool_started = time.time()

        executor = concurrent.futures.ProcessPoolExecutor(
            max_workers=min(os.cpu_count() or 2, 4),
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_worker_init, initargs=(worker_ctx,))
        # MFT then USN, in one process of their own, from the start. They ran
        # after the whole pool: on one case the pool's slowest member (the
        # browser, 447 s) finished at 09:21 and the MFT (231 s) only began
        # then. They read the raw volume, not the files the pool reads, so
        # they do not compete with it; one worker keeps them in order.
        if _HEAVY_EXECUTOR is not None:
            heavy = _HEAVY_EXECUTOR()
        else:
            heavy = concurrent.futures.ProcessPoolExecutor(
                max_workers=1, mp_context=multiprocessing.get_context("spawn"),
                initializer=_worker_init, initargs=(worker_ctx,))
        for _artifact in ("mft", "usn"):
            probes[_artifact] = _probe(_artifact, windows_partition)
        cancelled = False
        reported = set()
        try:
            future_to_task = {}
            if case_root and not is_cancelled(cancel_event):
                for module_name, artifact, name, step in (
                        ("MFT_Claw", "mft", "Master File Table (MFT)", 12),
                        ("USN_Claw", "usn", "USN Journal", 13)):
                    if _HEAVY_EXECUTOR is not None:
                        future = heavy.submit(_run_heavy_inline, artifact, name, windows_partition,
                                              module_name, case_root, root_dir, _artifact_progress)
                    else:
                        future = heavy.submit(run_task_logged, message_queue, artifact, name,
                                              windows_partition, run_claw_in_case,
                                              case_root, root_dir, module_name)
                    future_to_task[future] = (name, step, artifact)
            for func, args, kwargs, name, step, artifact in parallel_tasks_info:
                if is_cancelled(cancel_event):
                    log_callback("[Cancelled] Stopping parallel pool submission.")
                    break
                future = executor.submit(run_task_logged, message_queue, artifact, name,
                                         windows_partition, func, *args, **kwargs)
                future_to_task[future] = (name, step, artifact)

            completed_count = 0
            pending = set(future_to_task)
            while pending:
                # Polled, not blocked on: as_completed() waited for the next
                # parser to finish before it could notice a cancel.
                if is_cancelled(cancel_event):
                    cancelled = True
                    break
                done, pending = concurrent.futures.wait(
                    pending, timeout=0.5, return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    name, step, artifact = future_to_task[future]
                    completed_count += 1
                    try:
                        res, exc = future.result(), None
                    except KeyboardInterrupt:
                        raise
                    except BaseException as e:      # a worker that died outright
                        res, exc = None, e
                    outcome = _report(artifact, res, exc, pool_started, probes.get(artifact))
                    reported.add(artifact)
                    status = outcome.get("status") if outcome else None
                    stage_status[artifact] = status          # correlation reads mft / usn
                    # A failed collector is still a finished one. Leaving it out
                    # would strand the bar short of its own total.
                    if status in _FAILURE_STATUSES:
                        log_callback(f"[Error] {name}: {outcome.get('message')}")
                        task_done(f"{name.upper()} FAILED")
                    elif status in _NEUTRAL_STATUSES:
                        log_callback(f"[Not found] {name}: {outcome.get('message')} "
                                     f"(not a failure)")
                        step_callback(step, f"NO {name.upper()} ON THIS SYSTEM")
                        task_done(f"NO {name.upper()} ON THIS SYSTEM")
                    else:
                        log_callback(f"[Completed] {name} ({completed_count}/{len(future_to_task)})")
                        done_label = _HEAVY_DONE.get(artifact, f"COLLECTED {name.upper()}")
                        step_callback(step, done_label)
                        task_done(done_label)
        finally:
            _end_pool(executor, cancelled or is_cancelled(cancel_event), log_callback)
            _end_pool(heavy, cancelled or is_cancelled(cancel_event), log_callback)

        # Anything never reported was cancelled before it finished.
        for artifact in [t[5] for t in parallel_tasks_info] + ["mft", "usn"]:
            if artifact not in reported:
                stage_status[artifact] = (_report(artifact, None, None, pool_started,
                                                  probes.get(artifact), cancelled=True)
                                          or {}).get("status")

        # --- Correlation: after MFT and USN, which ran beside the pool ---
        # It depends on both (STAGE_DEPENDS); USN does not need MFT.
        mft_usn_path = os.path.join(root_dir, 'Artifacts_Collectors', 'MFT and USN journal')
        if mft_usn_path not in sys.path:
            sys.path.insert(0, mft_usn_path)

        def _correlate():
            from mft_usn_correlator import MFTUSNCorrelator
            # This runs in a spawned process, so print() reaches nobody: the
            # loading dialog captures stdout in the PARENT. The queue callbacks
            # above are the only route to the GUI.
            def _correlation_status(status=None, log=None):
                if log:
                    log_callback(log)
                if status:
                    step_callback(14, status)

            correlator = MFTUSNCorrelator(case_directory=case_root,
                                          status_callback=_correlation_status)
            with artifact_run("mft_usn_correlation", "MFT & USN correlation",
                              source=case_root, mode="live", progress=_artifact_progress):
                correlator.correlate_existing()     # the names too, not the join alone
                correlator.generate_forensic_report()
            # Derived data, rebuilt on every run: its size, not "new" rows.
            try:
                from utils.parse_status import artifact_db_rowcount
                n = artifact_db_rowcount(case_root, "mft_usn_correlation") or 0
            except Exception:
                n = 0
            return {"success": True, "records": n,
                    "warnings": [] if n else ["The correlation produced no rows"]}

        # MFT and USN ran beside the pool (above); only the correlation,
        # which needs both, is left.
        _run_stage("mft_usn_correlation", "MFT and USN Journal correlation", 14,
                   "CORRELATING MFT & USN DATA", _correlate, "CORRELATED MFT & USN DATA")

        if not is_cancelled(cancel_event):
            message_queue.put({"type": "task_complete", "task_id": "live_artifacts", "result": "Success"})
    except Exception as e:
        import traceback
        run_log.error("Live collection stopped: %s", e, exc_info=True)
        message_queue.put({
            "type": "task_error",
            "task_id": "live_artifacts",
            "error": str(e),
            "traceback": traceback.format_exc()
        })
