import os
import sys
import time
from typing import List, Optional, Callable
import traceback

# Add imports for components
try:
    from .image_parser import ImageParser
    from .file_system_accessor import FileSystemAccessor
except ImportError:
    from image_parser import ImageParser
    from file_system_accessor import FileSystemAccessor

# Import artifact definitions
try:
    from Artifacts_Collectors.crow_claw.core.artifacts import get_all_artifacts
except ImportError:
    # Try absolute if needed
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from Artifacts_Collectors.crow_claw.core.artifacts import get_all_artifacts


from typing import List, Optional, Callable, Union

def extract_artifacts_from_image(
    image_source: Union[str, List[str]],
    case_root: str,
    selected_partitions: List[int],
    artifact_type_filter: Optional[str] = None,
    progress_callback: Optional[Callable] = None
) -> str:
    """
    Extracts artifacts from the forensic image using dissect (via ImageParser).
    Copies files to case_root/live_acquisition/image_export/
    
    Returns the path to the exported directory.
    """
    output_dir = os.path.join(case_root, 'live_acquisition', 'image_export')
    os.makedirs(output_dir, exist_ok=True)
    
    primary_path = image_source[0] if isinstance(image_source, list) else image_source
    
    parser = ImageParser()
    strategy = parser.get_strategy(file_source=image_source)
    
    if not strategy:
        raise ValueError(f"Could not find a strategy to parse image: {primary_path}")
        
    # Open the image using the strategy
    if not strategy._open_image(image_source):
        raise IOError(f"Failed to open image: {primary_path}")
        
    img_info = strategy.get_img_info()
    fs_accessor = FileSystemAccessor(img_info)
    
    # Get all artifact definitions
    all_artifacts = get_all_artifacts()
    if artifact_type_filter:
        all_artifacts = [a for a in all_artifacts if a.artifact_type.value == artifact_type_filter or a.name == artifact_type_filter]
        
    # Collect all search paths and resolve them to linux-like paths used by dissect
    search_paths = []
    for artifact in all_artifacts:
        for path in artifact.get_all_paths():
            # Basic resolution of variables
            p = path.replace('%SystemRoot%', 'Windows').replace('%UserProfile%', 'Users')
            p = p.replace('%SystemDrive%', '')
            # Convert backslashes to forward slashes for dissect
            p = p.replace('\\', '/')
            if p.startswith('C:/') or p.startswith('c:/'):
                p = p[2:]
            if not p.startswith('/'):
                p = '/' + p
            search_paths.append((artifact.name, p))
    
    total_files_extracted = 0
    
    for partition_num in selected_partitions:
        # Find offset for this partition number
        partitions = strategy.list_partitions()
        part_offset = next((p.start_offset for p in partitions if p.partition_number == partition_num), 0)
        
        if progress_callback:
            progress_callback(f"Opening Partition {partition_num}...")
            
        if not fs_accessor.open_partition(part_offset):
            if progress_callback:
                progress_callback(f"[WARNING] Could not open partition {partition_num}")
            continue
            
        part_dir = os.path.join(output_dir, f"vol_{partition_num}")
        os.makedirs(part_dir, exist_ok=True)
        
        for art_name, path in search_paths:
            # Check if file exists. We could also support wildcards.
            # dissect path matching can be tricky with wildcards.
            try:
                # If the path has wildcards, we would need to implement globbing for dissect
                if '*' in path:
                    # Simple single-level wildcard resolution for Users/*
                    if 'Users/*' in path:
                        users_dir = '/Users'
                        if fs_accessor.file_exists(users_dir):
                            for user_entry in fs_accessor.list_directory(users_dir):
                                if user_entry.is_directory:
                                    user_path = path.replace('Users/*', f'Users/{user_entry.file_path.split("/")[-1]}')
                                    if fs_accessor.file_exists(user_path):
                                        dest = os.path.join(part_dir, user_path.lstrip('/'))
                                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                                        if progress_callback: progress_callback(f"Extracting: {user_path}")
                                        fs_accessor.read_file_streaming(user_path, dest)
                                        total_files_extracted += 1
                else:
                    if fs_accessor.file_exists(path):
                        dest = os.path.join(part_dir, path.lstrip('/'))
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        if progress_callback: progress_callback(f"Extracting: {path}")
                        fs_accessor.read_file_streaming(path, dest)
                        total_files_extracted += 1
            except Exception as e:
                # Ignore failures for missing files
                continue
                
    # Close resources
    fs_accessor.close()
    strategy._close_image()
    
    if progress_callback:
        progress_callback(f"Extraction complete. Total artifacts directly extracted: {total_files_extracted}")
        
    return output_dir
