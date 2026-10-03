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
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}

def run_shimcache_global(db):
    """Global wrapper for ShimCache to allow multiprocessing to pickle it."""
    from Artifacts_Collectors.shimcash_claw import ShimCacheParser
    p = ShimCacheParser(db)
    p.run()

def standalone_collect_live_artifacts(case_paths, windows_partition, message_queue, cancel_event=None):
    """
    Standalone function for parsing live artifacts in a separate multiprocessing.Process.
    Optimized: Uses parallel execution with granular real-time reporting and strict
    sequential ordering for MFT and USN Journal correlation.
    """
    # Force stdout and stderr to utf-8 to prevent charmap UnicodeEncodeError on Windows
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    
    # Ensure the project root is in sys.path for imports
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)
        
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

    # Parse status: one outcome per artifact, sent to the GUI process, which
    # records it (utils/parse_status.py). Everything here is best-effort - a
    # status report must never be the thing that stops a collection.
    def _probe(artifact, partition):
        try:
            from utils.parse_status import probe_sources
            return probe_sources(artifact, "live", partition or "C:")
        except Exception as e:
            return {"sources": [], "status": None, "message": f"probe failed: {e}"}

    def _report(artifact, res, exc, started, probe, cancelled=False):
        try:
            from utils.parse_status import collect_live_outcome
            outcome = collect_live_outcome(
                artifact, case_paths.get('case_root') if case_paths else None,
                windows_partition, raw_result=res, exc=exc, started=started,
                probe=probe, cancelled=cancelled).to_dict()
        except Exception as e:
            outcome = {"artifact": artifact, "mode": "live", "status": "FAILED",
                       "records": 0, "message": f"status could not be determined: {e}"}
        message_queue.put({"type": "parse_status", "outcome": outcome})
        return outcome

    try:
        log_callback("[Open Case] Starting full parallel live analysis...")

        case_root = case_paths.get('case_root') if case_paths else None
        artifacts_dir = case_paths.get('artifacts_dir') if case_paths else None
        
        # Step 0: Initialization
        step_callback(0, "INITIALIZING ARTIFACT COLLECTION")
        
        # Define parallel tasks and their associated UI steps
        parallel_tasks_info = []
        
        # Registry
        from Artifacts_Collectors.Regclaw import parse_live_registry
        reg_db = os.path.join(artifacts_dir, 'registry_data.db') if artifacts_dir else None
        parallel_tasks_info.append((parse_live_registry, (case_root, reg_db), {}, "Registry Hives & Execution Data", 2, "registry"))
        
        # LNK / Jump Lists
        from Artifacts_Collectors.A_CJL_LNK_Claw import A_CJL_LNK_Claw
        parallel_tasks_info.append((A_CJL_LNK_Claw, (), {'case_path': case_root, 'offline_mode': False, 'direct_parse': True}, "LNK & Jump Lists", 4, "lnk_jumplist"))
        
        # Prefetch
        from Artifacts_Collectors.Prefetch_claw import prefetch_claw
        parallel_tasks_info.append((prefetch_claw, (case_root, False, windows_partition), {}, "Prefetch evidence", 5, "prefetch"))
        
        # Event Logs
        from Artifacts_Collectors.WinLog_Claw import main as collect_logs
        parallel_tasks_info.append((collect_logs, (case_root,), {}, "Windows Event Logs", 6, "evtx"))
        
        # ShimCache
        shim_db = os.path.join(artifacts_dir, 'shimcache.db') if artifacts_dir else 'shimcache.db'
        parallel_tasks_info.append((run_shimcache_global, (shim_db,), {}, "ShimCache (AppCompatCache)", 7, "shimcache"))
        
        # Amcache
        from Artifacts_Collectors.amcacheparser import parse_amcache_hive
        am_db = os.path.join(artifacts_dir, 'amcache.db') if artifacts_dir else 'amcache.db'
        parallel_tasks_info.append((parse_amcache_hive, (), {
            'case_path': case_root, 'offline_mode': False, 'db_path': am_db, 'windows_partition': windows_partition
        }, "Amcache data", 8, "amcache"))
        
        # RecycleBin
        from Artifacts_Collectors.recyclebin_claw import parse_recycle_bin
        parallel_tasks_info.append((parse_recycle_bin, (case_root,), {}, "RecycleBin artifacts", 9, "recyclebin"))
        
        # SRUM
        from Artifacts_Collectors.SRUM_Claw import parse_srum_data
        if artifacts_dir:
            parallel_tasks_info.append((parse_srum_data, (), {
                'case_artifacts_dir': artifacts_dir, 'windows_partition': windows_partition
            }, "SRUM network & execution data", 10, "srum"))

        # Browser (Chromium / Gecko / Electron)
        from Artifacts_Collectors.Browser_Claw import parse_browser_data
        if artifacts_dir:
            parallel_tasks_info.append((parse_browser_data, (), {
                'case_artifacts_dir': artifacts_dir, 'windows_partition': windows_partition
            }, "Browser data", 11, "browser"))

        # Three sequential stages follow the pool: MFT, USN, correlation.
        SEQUENTIAL_STAGES = 3
        set_total_tasks(len(parallel_tasks_info) + SEQUENTIAL_STAGES)
        log_callback(f"[Parallel] Launching {len(parallel_tasks_info)} collectors in parallel pool...")
        
        # Probe every source in THIS process before the pool starts: several
        # collectors return None when their source is missing, so the probe is
        # what tells "not on this machine" apart from "the parser broke".
        probes = {}
        for _f, _a, _k, _n, _s, artifact in parallel_tasks_info:
            probes[artifact] = _probe(artifact, windows_partition)
        pool_started = time.time()

        with concurrent.futures.ProcessPoolExecutor(max_workers=min(os.cpu_count(), 4)) as executor:
            future_to_task = {}
            for func, args, kwargs, name, step, artifact in parallel_tasks_info:
                if is_cancelled(cancel_event):
                    log_callback("[Cancelled] Stopping parallel pool submission.")
                    break
                future = executor.submit(run_task, func, *args, **kwargs)
                future_to_task[future] = (name, step, artifact)

            completed_count = 0
            reported = set()
            for future in concurrent.futures.as_completed(future_to_task):
                if is_cancelled(cancel_event):
                    # We can't easily kill running futures, but we can stop processing results
                    break
                name, step, artifact = future_to_task[future]
                completed_count += 1
                try:
                    res, exc = future.result(), None
                except Exception as e:          # a worker that died outright
                    res, exc = None, e
                outcome = _report(artifact, res, exc, pool_started, probes.get(artifact))
                reported.add(artifact)
                status = outcome.get("status") if outcome else None
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
                    log_callback(f"[Completed] {name} ({completed_count}/{len(parallel_tasks_info)})")
                    step_callback(step, f"COLLECTED {name.upper()}")
                    task_done(f"COLLECTED {name.upper()}")

            # Anything never reported was cancelled before it finished.
            for _f, _a, _k, _n, _s, artifact in parallel_tasks_info:
                if artifact not in reported:
                    _report(artifact, None, None, pool_started, probes.get(artifact),
                            cancelled=True)

        # --- Final Heavy Sequential Tasks: MFT and USN Journal ---
        # These MUST be in order: Parse MFT -> Parse USN -> Correlate
        
        # Step 12: MFT Parsing
        if is_cancelled(cancel_event):
            return

        step_callback(12, "PARSING MASTER FILE TABLE (MFT)")
        stage_started, stage_res, stage_exc = time.time(), None, None
        try:
            mft_usn_path = os.path.join(root_dir, 'Artifacts_Collectors', 'MFT and USN journal')
            if mft_usn_path not in sys.path:
                sys.path.insert(0, mft_usn_path)
            from MFT_Claw import main as mft_main
            original_cwd = os.getcwd()
            try:
                os.chdir(case_root)
                stage_res = mft_main()
            finally:
                os.chdir(original_cwd)
            log_callback("[Completed] MFT Parsing")
        except Exception as e:
            stage_exc = e
            log_callback(f"[MFT Error] {str(e)}")
        finally:
            _report("mft", stage_res, stage_exc, stage_started,
                    _probe("mft", windows_partition))
            # Counted whether it parsed or raised - the stage is over either way.
            task_done("PARSED MASTER FILE TABLE")

        # Step 13: USN Journal Parsing
        if is_cancelled(cancel_event):
            return

        step_callback(13, "PARSING USN JOURNAL")
        stage_started, stage_res, stage_exc = time.time(), None, None
        try:
            from USN_Claw import main as usn_main
            original_cwd = os.getcwd()
            try:
                os.chdir(case_root)
                stage_res = usn_main()
            finally:
                os.chdir(original_cwd)
            log_callback("[Completed] USN Journal Parsing")
        except Exception as e:
            stage_exc = e
            log_callback(f"[USN Error] {str(e)}")
        finally:
            _report("usn", stage_res, stage_exc, stage_started,
                    _probe("usn", windows_partition))
            task_done("PARSED USN JOURNAL")

        # Step 14: Correlation
        if is_cancelled(cancel_event):
            return

        step_callback(14, "CORRELATING MFT & USN DATA")
        stage_started, stage_exc = time.time(), None
        try:
            mft_usn_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'Artifacts_Collectors', 'MFT and USN journal')
            if mft_usn_path not in sys.path:
                sys.path.insert(0, mft_usn_path)
            from mft_usn_correlator import MFTUSNCorrelator
            # This runs in a spawned process, so print() reaches nobody: the
            # loading dialog captures stdout in the PARENT. The queue callbacks
            # above are the only route to the GUI, which is why the log line is
            # forwarded here rather than left to stdout capture as it is on the
            # in-process path.
            def _correlation_status(status=None, log=None):
                if log:
                    log_callback(log)
                if status:
                    step_callback(14, status)

            correlator = MFTUSNCorrelator(case_directory=case_root,
                                          status_callback=_correlation_status)
            # Use run_complete_analysis but skip parsers since we just ran them
            correlator.create_correlated_database()
            correlator.generate_forensic_report()
            log_callback("[Completed] MFT and USN Journal correlation")
        except Exception as e:
            stage_exc = e
            log_callback(f"[Correlation Error] {str(e)}")
        finally:
            _report("mft_usn_correlation", None, stage_exc, stage_started,
                    _probe("mft_usn_correlation", windows_partition))
            task_done("CORRELATED MFT & USN DATA")

        message_queue.put({"type": "task_complete", "task_id": "live_artifacts", "result": "Success"})
        message_queue.put({"type": "DONE"})
    except Exception as e:
        import traceback
        message_queue.put({
            "type": "task_error", 
            "task_id": "live_artifacts", 
            "error": str(e), 
            "traceback": traceback.format_exc()
        })
        message_queue.put({"type": "DONE"})
