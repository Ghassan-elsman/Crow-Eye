/**
 * Heuristic Data Flattener
 * Stabilizes malformed forensic data by extracting arrays or wrapping single items.
 */
export function heuristicFlatten(input) {
  if (Array.isArray(input)) return input;
  if (!input || typeof input !== 'object') return [];

  // Surface explicit backend errors if present
  if (input._ERROR_) {
    console.error('[Bridge Error]', input._ERROR_);
    return [];
  }

  // Iterative stack-based flattening to prevent stack overflows
  const extractedArrays = [];
  const stack = [input];
  const seen = new Set(); // Prevent circular reference loops

  while (stack.length > 0) {
    const current = stack.pop();
    if (!current || typeof current !== 'object') continue;
    
    // Safety check for circular refs (rare in JSON but good for resilience)
    if (seen.has(current)) continue;
    seen.add(current);

    for (const key in current) {
      if (Object.prototype.hasOwnProperty.call(current, key)) {
        const val = current[key];
        if (Array.isArray(val)) {
          extractedArrays.push(...val);
        } else if (val && typeof val === 'object') {
          stack.push(val);
        }
      }
    }
  }

  if (extractedArrays.length > 0) return extractedArrays;

  // Final fallback for single artifact objects
  // Task 20.1: Exhaustive field check based on master manifest
  const forensicFields = [
    'timestamp', 'path', 'type', 'artifact_type', 'source_table', 'executable_name', 
    'original_filename', 'computer_name', 'display_name', 'app_name', 'search_term', 
    'program_path', 'file_name', 'command', 'network_name', 'application', 'filename', 
    'name', 'driver_name', 'fn_filename', 'install_date', 'installation_date', 
    'link_date', 'driver_last_write_time', 'driver_time_stamp', 'last_executed', 
    'run_times', 'deletion_time', 'last_execution', 'access_date', 'focus_time', 
    'created_date', 'modified_date', 'accessed_date', 'connection_date', 
    'last_modified', 'last_modified_readable', 'si_creation_time', 'usn_timestamp'
  ];
  
  if (forensicFields.some(f => input[f] != null)) {
    return [input];
  }

  return [];
}
