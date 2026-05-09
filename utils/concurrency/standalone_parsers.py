import multiprocessing
import os
import sys
import concurrent.futures
from typing import Callable, Any, Optional

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

    def log_callback(message):
        message_queue.put({
            "type": "log_message",
            "message": message,
            "is_log_update": True
        })

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
        parallel_tasks_info.append((parse_live_registry, (case_root, reg_db), {}, "Registry Hives & Execution Data", 2))
        
        # LNK / Jump Lists
        from Artifacts_Collectors.A_CJL_LNK_Claw import A_CJL_LNK_Claw
        parallel_tasks_info.append((A_CJL_LNK_Claw, (), {'case_path': case_root, 'offline_mode': False, 'direct_parse': True}, "LNK & Jump Lists", 4))
        
        # Prefetch
        from Artifacts_Collectors.Prefetch_claw import prefetch_claw
        parallel_tasks_info.append((prefetch_claw, (case_root, False, windows_partition), {}, "Prefetch evidence", 5))
        
        # Event Logs
        from Artifacts_Collectors.WinLog_Claw import main as collect_logs
        parallel_tasks_info.append((collect_logs, (case_root,), {}, "Windows Event Logs", 6))
        
        # ShimCache
        shim_db = os.path.join(artifacts_dir, 'shimcache.db') if artifacts_dir else 'shimcache.db'
        parallel_tasks_info.append((run_shimcache_global, (shim_db,), {}, "ShimCache (AppCompatCache)", 7))
        
        # Amcache
        from Artifacts_Collectors.amcacheparser import parse_amcache_hive
        am_db = os.path.join(artifacts_dir, 'amcache.db') if artifacts_dir else 'amcache.db'
        parallel_tasks_info.append((parse_amcache_hive, (), {
            'case_path': case_root, 'offline_mode': False, 'db_path': am_db, 'windows_partition': windows_partition
        }, "Amcache data", 8))
        
        # RecycleBin
        from Artifacts_Collectors.recyclebin_claw import parse_recycle_bin
        parallel_tasks_info.append((parse_recycle_bin, (case_root,), {}, "RecycleBin artifacts", 9))
        
        # SRUM
        from Artifacts_Collectors.SRUM_Claw import parse_srum_data
        if artifacts_dir:
            parallel_tasks_info.append((parse_srum_data, (), {
                'case_artifacts_dir': artifacts_dir, 'windows_partition': windows_partition
            }, "SRUM network & execution data", 10))

        log_callback(f"[Parallel] Launching {len(parallel_tasks_info)} collectors in parallel pool...")
        
        with concurrent.futures.ProcessPoolExecutor(max_workers=min(os.cpu_count(), 4)) as executor:
            future_to_task = {}
            for func, args, kwargs, name, step in parallel_tasks_info:
                if is_cancelled(cancel_event):
                    log_callback("[Cancelled] Stopping parallel pool submission.")
                    break
                future = executor.submit(run_task, func, *args, **kwargs)
                future_to_task[future] = (name, step)
            
            completed_count = 0
            for future in concurrent.futures.as_completed(future_to_task):
                if is_cancelled(cancel_event):
                    # We can't easily kill running futures, but we can stop processing results
                    break
                name, step = future_to_task[future]
                completed_count += 1
                res = future.result()
                if isinstance(res, dict) and res.get("success") is False:
                    error_info = res.get("error") or res.get("errors")
                    log_callback(f"[Error] Failed to collect {name}: {error_info}")
                else:
                    log_callback(f"[Completed] {name} ({completed_count}/{len(parallel_tasks_info)})")
                    step_callback(step, f"COLLECTED {name.upper()}")

        # --- Final Heavy Sequential Tasks: MFT and USN Journal ---
        # These MUST be in order: Parse MFT -> Parse USN -> Correlate
        
        # Step 11: MFT Parsing
        if is_cancelled(cancel_event):
            return
            
        step_callback(11, "PARSING MASTER FILE TABLE (MFT)")
        try:
            mft_usn_path = os.path.join(root_dir, 'Artifacts_Collectors', 'MFT and USN journal')
            if mft_usn_path not in sys.path:
                sys.path.insert(0, mft_usn_path)
            from MFT_Claw import main as mft_main
            original_cwd = os.getcwd()
            try:
                os.chdir(case_root)
                mft_main()
            finally:
                os.chdir(original_cwd)
            log_callback("[Completed] MFT Parsing")
        except Exception as e:
            log_callback(f"[MFT Error] {str(e)}")

        # Step 12: USN Journal Parsing
        if is_cancelled(cancel_event):
            return
            
        step_callback(12, "PARSING USN JOURNAL")
        try:
            from USN_Claw import main as usn_main
            original_cwd = os.getcwd()
            try:
                os.chdir(case_root)
                usn_main()
            finally:
                os.chdir(original_cwd)
            log_callback("[Completed] USN Journal Parsing")
        except Exception as e:
            log_callback(f"[USN Error] {str(e)}")

        # Step 13: Correlation
        if is_cancelled(cancel_event):
            return
            
        step_callback(13, "CORRELATING MFT & USN DATA")
        try:
            mft_usn_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'Artifacts_Collectors', 'MFT and USN journal')
            if mft_usn_path not in sys.path:
                sys.path.insert(0, mft_usn_path)
            from mft_usn_correlator import MFTUSNCorrelator
            correlator = MFTUSNCorrelator(case_directory=case_root)
            # Use run_complete_analysis but skip parsers since we just ran them
            correlator.create_correlated_database()
            correlator.generate_forensic_report()
            log_callback("[Completed] MFT and USN Journal correlation")
        except Exception as e:
            log_callback(f"[Correlation Error] {str(e)}")

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
