"""
Clear Python cache files to ensure latest code is loaded.
"""

import os
import shutil

print("\n" + "="*80)
print("Clearing Python Cache Files")
print("="*80)

# Find and remove __pycache__ directories
cache_dirs_removed = 0
pyc_files_removed = 0

for root, dirs, files in os.walk('Crow-Eye-master'):
    # Remove __pycache__ directories
    if '__pycache__' in dirs:
        cache_path = os.path.join(root, '__pycache__')
        try:
            shutil.rmtree(cache_path)
            print(f"✓ Removed: {cache_path}")
            cache_dirs_removed += 1
        except Exception as e:
            print(f"✗ Failed to remove {cache_path}: {e}")
    
    # Remove .pyc files
    for file in files:
        if file.endswith('.pyc'):
            pyc_path = os.path.join(root, file)
            try:
                os.remove(pyc_path)
                print(f"✓ Removed: {pyc_path}")
                pyc_files_removed += 1
            except Exception as e:
                print(f"✗ Failed to remove {pyc_path}: {e}")

print("\n" + "="*80)
print(f"Cache Cleanup Complete")
print(f"  Removed {cache_dirs_removed} __pycache__ directories")
print(f"  Removed {pyc_files_removed} .pyc files")
print("="*80)
print("\nPlease restart Crow Eye application and try opening the timeline again.")
print("="*80)
