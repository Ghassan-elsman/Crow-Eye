# EYE UI Components

This directory contains the user interface components for the EYE AI Forensic Assistant.

## Components

### HitL Dialogs (`hitl_dialogs.py`)

Human-in-the-Loop (HitL) approval dialogs for sensitive operations that require explicit user approval.

#### SemanticMappingApprovalDialog

Dialog for approving AI-proposed semantic mapping rules.

**Features:**
- Displays proposed rule in formatted JSON
- Read-only view by default
- Edit button to enable JSON editing
- Approve button to accept the rule (validates JSON)
- Reject button to cancel the operation
- Dark theme styling consistent with Crow-eye

**Usage Example:**

```python
from eye.ui.hitl_dialogs import SemanticMappingApprovalDialog

# Proposed rule from AI
proposed_rule = {
    "rule_id": "ai-001",
    "name": "Suspicious Process",
    "semantic_value": "Malicious Activity",
    "conditions": [...],
    "severity": "high"
}

# Show approval dialog
dialog = SemanticMappingApprovalDialog(parent_window, proposed_rule)
result = dialog.exec_()

# Check result
if dialog.was_approved():
    approved_rule = dialog.get_approved_rule()
    # Save to configs/semantic_mapping_config.json
    save_semantic_rule(approved_rule)
else:
    # User rejected the rule
    print("Rule rejected by user")
```


**Pattern:**
Follows the design pattern from `correlation_engine/wings/ui/semantic_mapping_dialog.py`

## Testing

Run unit tests:
```bash
python -m pytest eye/ui/test_hitl_dialogs.py -v
```

Run demo:
```bash
python eye/examples/demo_hitl_dialog.py
```

## Future Components

Additional HitL dialogs to be implemented:

## React Components

The `react/` subdirectory contains the React-based chat interface and report builder components.
