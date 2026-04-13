"""
Offline ShimCache Parser Wrapper for Crow-eye
=============================================

This module provides a dedicated offline wrapper for the ShimCache parser,
allowing for the extraction of AppCompatCache data from offline SYSTEM hives.
"""

import os
import sys
import logging
from Registry import Registry

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from shimcash_claw import ShimCacheParser
except ImportError:
    try:
        from Artifacts_Collectors.shimcash_claw import ShimCacheParser
    except ImportError:
        # Final fallback: if we are running from the parent of Artifacts_Collectors
        grandparent_dir = os.path.dirname(parent_dir)
        if grandparent_dir not in sys.path:
            sys.path.insert(0, grandparent_dir)
        from Artifacts_Collectors.shimcash_claw import ShimCacheParser

class OfflineShimCacheParser(ShimCacheParser):
    """Extended ShimCacheParser with offline hive support."""
    
    def get_offline_registry_data(self, system_hive_path: str) -> list:
        """
        Extract ShimCache data from an offline SYSTEM hive.
        
        Args:
            system_hive_path: Path to the SYSTEM registry hive
            
        Returns:
            list of (data_bytes, control_set_path)
        """
        if not os.path.exists(system_hive_path):
            print(f"❌ SYSTEM hive not found at: {system_hive_path}")
            return []

        results = []
        try:
            reg = Registry.Registry(system_hive_path)
            
            # Paths to check in the SYSTEM hive
            # Note: These are relative to the hive root
            paths = [
                r"ControlSet001\Control\Session Manager\AppCompatCache",
                r"ControlSet002\Control\Session Manager\AppCompatCache",
                r"Select" # To find CurrentControlSet if needed, but usually we scan all CS
            ]
            
            # First, try to find all ControlSets
            root = reg.root()
            for key in root.subkeys():
                if key.name().startswith("ControlSet"):
                    try:
                        target_path = f"{key.name()}\\Control\\Session Manager\\AppCompatCache"
                        target_key = reg.open(target_path)
                        value = target_key.value("AppCompatCache")
                        if value:
                            results.append((value.value(), target_path))
                            print(f"✓ Found ShimCache data in {target_path}")
                    except Exception:
                        continue
                        
            return results
        except Exception as e:
            print(f"❌ Error reading offline hive: {e}")
            return []

    def run_offline(self, system_hive_path: str, db_path: str = None):
        """Run analysis on an offline hive."""
        print(f"🚀 Starting Offline ShimCache Analysis: {system_hive_path}")
        
        # Store db_path for return value
        output_db = db_path if db_path else getattr(self, 'db_path', 'shimcache.db')
        
        all_data = self.get_offline_registry_data(system_hive_path)
        if not all_data:
            print("❌ No ShimCache data found in hive")
            return {"success": False, "records": 0, "output_path": output_db}
            
        all_entries = []
        for data, path in all_data:
            print(f"📊 Parsing {len(data):,} bytes from {path}...")
            entries = self.parse_shimcache_data(data)
            for entry in entries:
                entry.extract_filename()
                entry.format_timestamp()
                all_entries.append(entry)
                
        if all_entries:
            self.save_to_database(all_entries)
            print(f"✅ Successfully parsed {len(all_entries)} total entries")
            return {"success": True, "records": len(all_entries), "output_path": output_db}
        else:
            return {"success": False, "records": 0, "output_path": output_db}

def run_offline_shimcache(case_path):
    """
    Wrapper function for Offline Importer integration.
    """
    # Try multiple possible registry directory locations (input from live_acquisition)
    possible_dirs = [
        os.path.join(case_path, "live_acquisition", "Registry_Hives"),
        os.path.join(case_path, "live_acquisition", "registry"),
        os.path.join(case_path, "live_acquisition", "ShimCache"),
    ]
    
    system_hive = None
    for dir_path in possible_dirs:
        hive_path = os.path.join(dir_path, "SYSTEM")
        if os.path.exists(hive_path):
            system_hive = hive_path
            break
    
    if not system_hive:
        # Default to first option if none found
        system_hive = os.path.join(possible_dirs[0], "SYSTEM")
    
    # Match live parser location: Target_Artifacts/shimcache.db
    db_path = os.path.join(case_path, "Target_Artifacts", "shimcache.db")
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    parser = OfflineShimCacheParser(db_path)
    result = parser.run_offline(system_hive, db_path)
    
    # Ensure output_path is included in result
    if 'output_path' not in result:
        result['output_path'] = db_path
    
    return result

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python offline_ShimCacheClaw.py <system_hive_path> [db_path]")
        sys.exit(1)
    
    hive = sys.argv[1]
    db = sys.argv[2] if len(sys.argv) > 2 else "shimcache_offline.db"
    
    p = OfflineShimCacheParser(db)
    p.run_offline(hive)
