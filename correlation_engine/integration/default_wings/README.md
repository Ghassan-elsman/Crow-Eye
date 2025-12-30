# Default Wings

This directory contains pre-configured correlation Wings that provide immediate value for forensic analysis.

## Available Default Wings

### 1. Execution Proof Correlation

**File:** `Execution_Proof_Correlation.json`  
**Wing ID:** `default_wing_execution_001`  
**Purpose:** Proves program execution using weighted scoring based on forensic strength of evidence

#### What It Proves
This Wing establishes that a program was executed on the system by correlating multiple execution artifacts with varying levels of forensic confidence.

#### Scoring Tiers

**Tier 1: Direct Execution Evidence (Weight: 0.65)**
- **Prefetch** (0.40) - Strongest evidence of execution
- **ShimCache** (0.25) - Strong evidence of execution or file interaction

**Tier 2: Strong Supporting Evidence (Weight: 0.45)**
- **AmCache - InventoryApplication** (0.15)
- **AmCache - InventoryApplicationFile** (0.15)
- **AmCache - InventoryApplicationShortcut** (0.15)

**Tier 3: User-Triggered Execution Traces (Weight: 0.30)**
- **LNK Files** (0.10)
- **Automatic Jumplists** (0.10)
- **Custom Jumplists** (0.10)

**Tier 4: Runtime + Behavior Correlation (Weight: 0.10)**
- **SRUM Application Usage** (0.10)

#### Score Interpretation

| Score Range | Interpretation | Meaning |
|-------------|----------------|---------|
| ≥ 0.70 | **Confirmed Execution** | High confidence - multiple strong artifacts present |
| 0.40 - 0.69 | **Probable Execution** | Moderate confidence - some strong artifacts present |
| 0.20 - 0.39 | **Weak / Partial** | Low confidence - only weak artifacts present |
| < 0.20 | **Not Proven** | Insufficient evidence |

#### Configuration
- **Time Window:** 5 minutes
- **Minimum Matches:** 1
- **Anchor Priority:** Prefetch → ShimCache → AmCache → LNK → Jumplists → SRUM

---

### 2. User Activity Correlation

**File:** `User_Activity_Correlation.json`  
**Wing ID:** `default_wing_activity_001`  
**Purpose:** Proves user activity using weighted scoring based on user interaction evidence strength

#### What It Proves
This Wing establishes that a user actively interacted with the system by correlating user-generated artifacts that indicate explicit interaction.

#### Scoring Tiers

**Tier 1: Explicit User Interaction (Weight: 0.90)**
- **UserAssist** (0.30) - Direct evidence of GUI program execution
- **RecentDocs** (0.20) - Recent document access
- **OpenSaveMRU** (0.20) - File open/save dialogs
- **LastSaveMRU** (0.20) - Last saved file locations

**Tier 2: Navigation & Exploration (Weight: 0.25)**
- **ShellBags** (0.15) - Folder navigation and window positions
- **TypedPaths** (0.10) - Manually typed paths in Explorer

**Tier 3: Temporal System Confirmation (Weight: 0.05)**
- **Security Logs** (0.05) - Login/logout events for temporal context

#### Score Interpretation

| Score Range | Interpretation | Meaning |
|-------------|----------------|---------|
| ≥ 0.60 | **Confirmed User Activity** | High confidence - multiple explicit interaction artifacts |
| 0.35 - 0.59 | **Likely User Activity** | Moderate confidence - some interaction artifacts present |
| < 0.35 | **Insufficient Evidence** | Not enough evidence to confirm user activity |

#### Configuration
- **Time Window:** 5 minutes
- **Minimum Matches:** 1
- **Anchor Priority:** Registry → Logs

#### Semantic Mappings
This Wing includes pre-configured semantic mappings for Security Log Event IDs:
- 4624 → "User Login"
- 4634 → "User Logoff"
- 4647 → "User Logoff"
- 4800 → "Session Locked"
- 4801 → "Session Unlocked"
- 4648 → "Account Switch"

---

## Usage

### Loading Default Wings

Default Wings are automatically loaded when:
1. The application starts (copied to user config directory)
2. A new case is opened (copied to case Wings directory)
3. The Correlation Engine tab is accessed

### Customizing Default Wings

You can customize default Wings by:
1. Copying them to your case's `Correlation/wings/` directory
2. Editing the JSON file to adjust weights, thresholds, or Feathers
3. Saving with a new name to preserve the original

### Creating New Wings Based on Defaults

Use default Wings as templates:
1. Copy a default Wing JSON file
2. Rename it (change `wing_id` and `wing_name`)
3. Adjust Feathers, weights, and scoring thresholds
4. Save to your case's Wings directory

---

## Technical Details

### Weighted Scoring Algorithm

The weighted scoring system calculates match confidence as:

```
Total Score = Σ (Weight of Matched Feather)
```

Each Feather contributes its weight only if it has a matching record within the time window.

### Score Breakdown

When viewing results, you'll see:
- **Overall Score:** Total weighted score (0.0 - 1.0+)
- **Interpretation:** Human-readable confidence level
- **Breakdown:** Per-Feather contribution showing:
  - Matched status (✓ or ✗)
  - Weight assigned
  - Contribution to total score
  - Tier and tier name

### Time Window

The 5-minute time window means:
- All correlated records must occur within 5 minutes of the anchor record
- The anchor is selected based on the `anchor_priority` list
- Earlier artifacts in the priority list are preferred as anchors

---

## Best Practices

### When to Use Execution Proof Correlation

Use this Wing when you need to:
- Establish that a specific program was executed
- Determine execution timeline
- Correlate execution across multiple artifact types
- Build evidence for malware execution
- Investigate program execution in intrusion cases

### When to Use User Activity Correlation

Use this Wing when you need to:
- Prove user interaction (vs. automated execution)
- Establish user session activity
- Investigate data theft or insider threats
- Correlate user actions across artifacts
- Determine if activity was user-initiated

### Combining Wings

For comprehensive analysis:
1. Run both Wings on the same dataset
2. Compare results to distinguish user-initiated vs. automated execution
3. Use Execution Proof for "what ran"
4. Use User Activity for "who did it"

---

## Maintenance

### Updating Default Wings

To update default Wings:
1. Edit the JSON files in this directory
2. Increment the `version` field
3. Update `last_modified` timestamp
4. Test with sample data
5. Document changes in this README

### Adding New Default Wings

To add a new default Wing:
1. Create a new JSON file in this directory
2. Follow the structure of existing Wings
3. Add the filename to `DEFAULT_WING_FILES` in `default_wings_loader.py`
4. Document it in this README
5. Test thoroughly before committing

---

## Version History

### Version 1.0 (2024-12-23)
- Initial release
- Execution Proof Correlation Wing
- User Activity Correlation Wing
- Weighted scoring system
- Semantic mappings for Security Logs

---

## Support

For questions or issues with default Wings:
1. Check the Correlation Engine documentation
2. Review the Wing configuration format
3. Test with sample data
4. Consult the Crow-Eye team

---

**Last Updated:** December 23, 2024  
**Maintained By:** Crow-Eye Team
