# Forensic Methodology & Investigative Guidance

This guide provides the underlying "Why" and "How" for forensic analysis within the Crow-eye system, following the Ghassan Protocol.

## The "Why" of Forensic Evidence
Forensic evidence is gathered to establish a **non-repudiable timeline** of user or system activity. We query specific artifacts because:
- **Registry**: Proves system configuration and persistent user preferences.
- **Event Logs**: Provide a chronological, system-verified record of discrete actions (Logins, Process Starts).
- **Execution Artifacts (Prefetch/Amcache)**: Prove that a specific binary was physically loaded into memory, refuting claims that "the file was just sitting there."
- **File System (MFT/USN)**: Proves the physical existence and lifecycle (creation/deletion) of data.

## The "How" of Analysis (Ghassan Protocol)
1. **Pillar 0 (Awareness)**: Always check the Triage Summary first to identify the "Pulse" of the system.
2. **Anchor Evidence**: Find a primary artifact (e.g., a login event).
3. **Cross-Correlate**: If you find a login (Security Log), immediately check for concurrent process execution (Prefetch/UserAssist) and file access (LNK/JumpLists).
4. **Verify Integrity**: Compare MFT timestamps with Registry 'Last Write' times to detect timestamp manipulation (Timestomping).

## Interpretation Guidance
- **Why do we see multiple entries?**: Artifacts like Network_list or USBDevices are cumulative. Cross-reference `last_connected` with `EventID 4624` to confirm if a connection was active during a specific timeframe.
- **Clarifying "Deleted" status**: A file being in the Recycle Bin proves user intent to delete. A file entry in the USN Journal with `File_Delete` proves the physical removal from the file system.
