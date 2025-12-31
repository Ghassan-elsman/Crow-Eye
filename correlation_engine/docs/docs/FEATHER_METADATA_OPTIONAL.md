# Feather Metadata-Optional Processing

## Overview

The Crow-Eye Correlation Engine now supports feather databases with or without metadata tables. This enhancement allows you to use databases from external tools or legacy sources without requiring manual metadata creation.

## Detection Priority

When you add a feather database, the system detects the artifact type using this priority:

1. **Metadata Table** (Highest Priority)
   - Reads `artifact_type` from `feather_metadata` table
   - Confidence: High
   - Icon: ✓

2. **Table Names**
   - Matches table names against known patterns
   - Confidence: High/Medium
   - Icon: ●

3. **Filename**
   - Matches database filename against patterns
   - Confidence: Medium/Low
   - Icon: ○

## Confidence Levels

- **High (✓)**: Exact match from metadata or table name
- **Medium (●)**: Partial match from table name or filename
- **Low (○)**: Generic fallback or unknown

## Using the Feather Creator

### Creating a Feather with Metadata

1. Open Feather Creator
2. Enter feather name and select save location
3. The system auto-detects artifact type from filename
4. Review and change artifact type if needed
5. Import your data
6. Artifact type is automatically saved to `feather_metadata` table

### Editing Existing Feathers

When you open an existing feather database:
- If metadata exists, it's displayed as "from existing metadata"
- You can change the artifact type and it will update the metadata
- Changes are saved when you import new data

## Using the Wings Creator

### Adding Feathers to Wings

1. Click "Add Feather" in Wings Creator
2. Browse and select your feather database
3. System detects artifact type with priority: metadata → table name → filename
4. Detection result shows confidence level and method
5. You can override the detected type if incorrect
6. Save the wing configuration

### Detection Examples

**With Metadata:**
```
✓ Prefetch (high confidence - from metadata)
```

**From Table Name:**
```
● Prefetch (high confidence - from table name)
```

**From Filename:**
```
○ Prefetch (medium confidence - from filename)
```

**Manual Override:**
```
✓ SystemLog (manually selected, was Prefetch)
```

## Troubleshooting

### "No data tables found"
- **Cause**: Database contains only system tables
- **Solution**: Verify the database contains forensic artifact data

### "Data table contains no rows"
- **Cause**: Table exists but is empty
- **Solution**: Verify the database was populated correctly

### "No name or path columns detected"
- **Cause**: Cannot extract identifiers without proper columns
- **Solution**: Verify table contains columns like 'name', 'executable', 'path', etc.

### Low Confidence Detection
- **Cause**: Filename or table name doesn't match known patterns
- **Solution**: Manually select the correct artifact type from the dropdown

## Best Practices

1. **Use Feather Creator**: Always create feathers using the Feather Creator to ensure proper metadata
2. **Verify Detection**: Check the auto-detected artifact type before saving
3. **Name Consistently**: Use descriptive names like "prefetch.db", "srum.db" for better detection
4. **Add Metadata**: For legacy databases, open in Feather Creator and save to add metadata

## Supported Artifact Types

The system recognizes these artifact types:
- Prefetch
- SystemLog / Logs
- MFT
- SRUM
- AmCache
- UserAssist
- RecycleBin
- Registry
- BrowserHistory
- ShellBags
- LNK
- Jumplists

## Technical Details

### Table Name Patterns

Exact matches (high confidence):
- `prefetch`, `prefetch_data` → Prefetch
- `systemlog`, `system_log` → SystemLog
- `mft`, `mft_records` → MFT
- `srum`, `srum_data` → SRUM

Partial matches (medium confidence):
- Contains "prefetch" → Prefetch
- Contains "log" or "event" → SystemLog
- Contains "mft" → MFT
- Contains "cache" → AmCache

### Metadata Table Structure

```sql
CREATE TABLE feather_metadata (
    artifact_type TEXT,
    created_date TEXT,
    description TEXT
)
```

The `artifact_type` field is used for detection when present.
