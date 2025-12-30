"""
Tooltips and Help Text for Correlation Engine UI Components

This module provides centralized tooltip and help text definitions for all
correlation engine UI components, ensuring consistent and helpful user guidance.
"""

# ============================================================================
# WEIGHTED SCORING TOOLTIPS
# ============================================================================

WEIGHTED_SCORING_TOOLTIPS = {
    'enable_checkbox': (
        "Enable weighted scoring to calculate match confidence based on the "
        "forensic strength of each Feather. When enabled, each Feather is assigned "
        "a weight (0.0-1.0) representing its evidential value."
    ),
    
    'weights_table': (
        "Assign weights to each Feather based on its forensic strength. "
        "Higher weights (closer to 1.0) indicate stronger evidence. "
        "The sum of matched Feather weights determines the overall match score."
    ),
    
    'weight_column': (
        "Weight value between 0.0 and 1.0. Higher values indicate stronger "
        "forensic evidence. Example: Prefetch (0.40) is stronger than LNK (0.10)."
    ),
    
    'tier_column': (
        "Tier number (1-4) grouping Feathers by evidence strength. "
        "Tier 1 = Direct evidence, Tier 2 = Strong supporting, "
        "Tier 3 = User traces, Tier 4 = Runtime correlation."
    ),
    
    'tier_name_column': (
        "Descriptive name for the tier. Examples: 'Direct execution evidence', "
        "'Strong supporting evidence', 'User-triggered execution traces'."
    ),
    
    'total_weight_label': (
        "Sum of all Feather weights. This represents the maximum possible score "
        "if all Feathers match. Typically should be around 1.0 for balanced scoring."
    ),
    
    'interpretation_table': (
        "Define how match scores should be interpreted. Set minimum score thresholds "
        "for each interpretation level (e.g., ≥0.70 = 'Confirmed Execution')."
    ),
    
    'interpretation_level': (
        "Internal identifier for this interpretation level (e.g., 'confirmed', 'probable')."
    ),
    
    'interpretation_label': (
        "Human-readable label shown in results (e.g., 'Confirmed Execution', "
        "'Probable Execution', 'Weak / Partial')."
    ),
    
    'interpretation_min_score': (
        "Minimum score required for this interpretation. Scores are matched "
        "from highest to lowest threshold."
    ),
}

# ============================================================================
# SEMANTIC MAPPING TOOLTIPS
# ============================================================================

SEMANTIC_MAPPING_TOOLTIPS = {
    'panel_description': (
        "Semantic mappings translate technical values (like Event IDs, status codes) "
        "into human-readable meanings. This makes correlation results easier to understand. "
        "Example: Event ID '4624' → 'User Login'."
    ),
    
    'source_field': (
        "The artifact source containing the technical value. "
        "Examples: SecurityLogs, SystemLogs, Prefetch, Registry, ShimCache."
    ),
    
    'field_field': (
        "The field name within the artifact containing the technical value. "
        "Examples: EventID, Status, Code, Type, Result."
    ),
    
    'technical_value_field': (
        "The actual technical value to map. "
        "Examples: '4624' (Event ID), '0x00000000' (status code), 'Type 2' (logon type)."
    ),
    
    'semantic_value_field': (
        "The human-readable meaning to display. "
        "Examples: 'User Login', 'Success', 'Interactive Logon', 'System Startup'."
    ),
    
    'description_field': (
        "Optional detailed description providing additional context about this mapping. "
        "Shown as a tooltip in correlation results."
    ),
    
    'scope_global': (
        "Global mappings apply to all Wings and Pipelines. "
        "Use for common mappings like Windows Event IDs."
    ),
    
    'scope_wing': (
        "Wing-specific mappings apply only to this Wing and override global mappings. "
        "Use for context-specific interpretations."
    ),
    
    'scope_pipeline': (
        "Pipeline-specific mappings apply to all Wings in this Pipeline. "
        "Use for case-specific interpretations."
    ),
    
    'load_global_button': (
        "Import all global semantic mappings as a starting point for Wing-specific mappings. "
        "You can then modify or add to these mappings."
    ),
    
    'import_button': (
        "Import semantic mappings from a JSON file. "
        "Useful for sharing mappings between cases or team members."
    ),
    
    'export_button': (
        "Export current semantic mappings to a JSON file. "
        "Useful for backup or sharing with team members."
    ),
    
    'reset_button': (
        "Reset all semantic mappings to default values. "
        "This will restore common Windows Event IDs and system event mappings. "
        "⚠ This action cannot be undone!"
    ),
}

# ============================================================================
# WING SELECTION DIALOG TOOLTIPS
# ============================================================================

WING_SELECTION_TOOLTIPS = {
    'dialog_description': (
        "Select which Wings to execute in this correlation run. "
        "Each Wing represents a different correlation hypothesis (e.g., 'Execution Proof', "
        "'User Activity'). You can execute multiple Wings simultaneously."
    ),
    
    'wing_checkbox': (
        "Check to include this Wing in the correlation execution. "
        "Uncheck to skip this Wing."
    ),
    
    'select_all_button': (
        "Select all Wings for execution. "
        "Useful when you want to run all available correlation analyses."
    ),
    
    'deselect_all_button': (
        "Deselect all Wings. "
        "Useful when you want to manually select only specific Wings."
    ),
    
    'execute_button': (
        "Execute correlation analysis for all selected Wings. "
        "Results will be displayed in separate tabs for each Wing."
    ),
}

# ============================================================================
# SCORING BREAKDOWN WIDGET TOOLTIPS
# ============================================================================

SCORING_BREAKDOWN_TOOLTIPS = {
    'overall_score': (
        "Overall weighted match score calculated as the sum of weights from all matched Feathers. "
        "Higher scores indicate stronger evidence for the correlation hypothesis."
    ),
    
    'interpretation': (
        "Human-readable interpretation of the match score based on configured thresholds. "
        "Examples: 'Confirmed Execution', 'Probable Execution', 'Weak / Partial'."
    ),
    
    'match_summary': (
        "Number of Feathers that matched out of total Feathers in the Wing. "
        "Example: (5/7 Feathers matched) means 5 out of 7 Feathers found matching records."
    ),
    
    'breakdown_table': (
        "Detailed breakdown showing each Feather's contribution to the overall score. "
        "Matched Feathers are highlighted in green. Unmatched Feathers are shown in gray."
    ),
    
    'status_column': (
        "✓ = Feather matched (found records within time window)\n"
        "✗ = Feather did not match (no records found)"
    ),
    
    'weight_column_breakdown': (
        "Weight assigned to this Feather. "
        "Represents the forensic strength of this artifact type."
    ),
    
    'contribution_column': (
        "Actual contribution to the overall score. "
        "Equals the weight if matched, 0.0 if not matched."
    ),
    
    'tier_column_breakdown': (
        "Evidence tier grouping. Lower tier numbers indicate stronger evidence. "
        "Tier 1 = Direct evidence, Tier 2 = Strong supporting, etc."
    ),
}

# ============================================================================
# PIPELINE BUILDER TOOLTIPS
# ============================================================================

PIPELINE_BUILDER_TOOLTIPS = {
    'feather_list': (
        "List of Feathers (normalized artifact databases) in this Pipeline. "
        "Double-click a Feather to edit it in the Feather Builder."
    ),
    
    'wing_list': (
        "List of Wings (correlation rules) in this Pipeline. "
        "Double-click a Wing to edit it in the Wings Creator."
    ),
    
    'add_feather_button': (
        "Add an existing Feather to this Pipeline. "
        "Feathers must be created using the Feather Builder before adding them."
    ),
    
    'add_wing_button': (
        "Add an existing Wing to this Pipeline. "
        "Wings must be created using the Wings Creator before adding them."
    ),
    
    'execute_button': (
        "Execute correlation analysis for this Pipeline. "
        "You will be prompted to select which Wings to execute."
    ),
}

# ============================================================================
# RESULTS VIEWER TOOLTIPS
# ============================================================================

RESULTS_VIEWER_TOOLTIPS = {
    'per_wing_tabs': (
        "Each tab shows results for one Wing. "
        "Switch between tabs to view different correlation analyses."
    ),
    
    'wing_summary': (
        "Summary statistics for this Wing's execution: "
        "total matches found, records scanned, execution time, and anchor Feather used."
    ),
    
    'matches_table': (
        "Detailed list of all correlation matches found by this Wing. "
        "Each row represents one match (a group of related records across multiple Feathers)."
    ),
    
    'match_id_column': (
        "Unique identifier for this match. "
        "Used to reference this match in exports and reports."
    ),
    
    'anchor_time_column': (
        "Timestamp from the anchor Feather that triggered this match. "
        "All other Feathers are correlated within the time window around this timestamp."
    ),
    
    'score_column': (
        "Match score. For weighted scoring, this is the sum of matched Feather weights. "
        "For simple scoring, this is the count of matched Feathers."
    ),
    
    'interpretation_column': (
        "Human-readable interpretation of the match score. "
        "Based on thresholds configured in the Wing."
    ),
    
    'feathers_column': (
        "Number of Feathers that contributed to this match. "
        "Click to expand and see details for each Feather."
    ),
    
    'time_span_column': (
        "Time span between the earliest and latest records in this match. "
        "Indicates how tightly clustered the correlated events are."
    ),
}

# ============================================================================
# AUTO FEATHER GENERATION TOOLTIPS
# ============================================================================

AUTO_FEATHER_GENERATION_TOOLTIPS = {
    'progress_dialog': (
        "Automatically generating Feathers from Crow-Eye parser output. "
        "This process reads parsed artifact databases and creates normalized Feathers "
        "for correlation analysis. This may take 30-60 seconds."
    ),
    
    'cancel_button': (
        "Cancel Feather generation. "
        "⚠ Partially generated Feathers will be incomplete and may not work correctly."
    ),
}

# ============================================================================
# WINGS CREATOR TOOLTIPS
# ============================================================================

WINGS_CREATOR_TOOLTIPS = {
    'wing_name': (
        "Descriptive name for this Wing. "
        "Should clearly indicate what this Wing proves or correlates. "
        "Example: 'Execution Proof Correlation', 'User Activity Timeline'."
    ),
    
    'wing_id': (
        "Unique identifier for this Wing (auto-generated from name). "
        "Used internally to reference this Wing in configurations."
    ),
    
    'description': (
        "Detailed description of what this Wing does and what it proves. "
        "Helps other analysts understand the purpose and methodology."
    ),
    
    'author': (
        "Name of the person who created this Wing. "
        "Useful for attribution and questions about methodology."
    ),
    
    'proves': (
        "What does this Wing prove when matches are found? "
        "Example: 'Program was executed on the system', 'User actively interacted with files'."
    ),
    
    'time_window': (
        "Time tolerance (in minutes) for matching records across Feathers. "
        "Records within ±this window are considered potentially related. "
        "Typical values: 5 minutes for tight correlation, 30 minutes for loose correlation."
    ),
    
    'minimum_matches': (
        "Minimum number of Feathers that must match to create a correlation match. "
        "Higher values = stricter correlation, fewer false positives. "
        "Lower values = more permissive, may find weaker correlations."
    ),
    
    'anchor_priority': (
        "Order in which Feathers are tried as the anchor (starting point) for correlation. "
        "Drag to reorder. The first available Feather with data will be used as anchor."
    ),
    
    'target_application': (
        "Filter correlation to a specific application/file. "
        "Leave empty or use '*' to correlate all applications. "
        "Example: 'chrome.exe', 'notepad.exe', 'powershell.exe'."
    ),
    
    'target_path': (
        "Optional path filter to narrow correlation scope. "
        "Supports wildcards. Example: 'C:\\Windows\\System32\\*', 'C:\\Users\\*\\Downloads\\*'."
    ),
    
    'target_event_id': (
        "Filter to specific Event IDs (for Log artifacts). "
        "Comma-separated for multiple IDs. Example: '4688,4624,4625'."
    ),
}

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_tooltip(category: str, key: str) -> str:
    """
    Get tooltip text for a specific UI element.
    
    Args:
        category: Category name (e.g., 'weighted_scoring', 'semantic_mapping')
        key: Specific element key
        
    Returns:
        Tooltip text, or empty string if not found
    """
    tooltip_maps = {
        'weighted_scoring': WEIGHTED_SCORING_TOOLTIPS,
        'semantic_mapping': SEMANTIC_MAPPING_TOOLTIPS,
        'wing_selection': WING_SELECTION_TOOLTIPS,
        'scoring_breakdown': SCORING_BREAKDOWN_TOOLTIPS,
        'pipeline_builder': PIPELINE_BUILDER_TOOLTIPS,
        'results_viewer': RESULTS_VIEWER_TOOLTIPS,
        'auto_generation': AUTO_FEATHER_GENERATION_TOOLTIPS,
        'wings_creator': WINGS_CREATOR_TOOLTIPS,
    }
    
    tooltip_map = tooltip_maps.get(category, {})
    return tooltip_map.get(key, '')


def format_help_text(text: str, max_width: int = 80) -> str:
    """
    Format help text for display in labels or dialogs.
    
    Args:
        text: Raw help text
        max_width: Maximum line width for wrapping
        
    Returns:
        Formatted help text
    """
    import textwrap
    return '\n'.join(textwrap.wrap(text, width=max_width))


# ============================================================================
# EXAMPLE USAGE DOCUMENTATION
# ============================================================================

EXAMPLES = {
    'weighted_scoring': {
        'title': 'Weighted Scoring Example',
        'description': (
            "Weighted scoring assigns forensic strength values to each Feather:\n\n"
            "Tier 1 - Direct Execution Evidence:\n"
            "  • Prefetch (0.40) - Strongest evidence of execution\n"
            "  • ShimCache (0.25) - Strong execution indicator\n\n"
            "Tier 2 - Strong Supporting Evidence:\n"
            "  • AmCache (0.15) - Application installation/execution\n\n"
            "Tier 3 - User-Triggered Traces:\n"
            "  • LNK files (0.10) - User accessed file\n"
            "  • Jumplists (0.10) - Recent application usage\n\n"
            "If Prefetch + ShimCache + AmCache match:\n"
            "Score = 0.40 + 0.25 + 0.15 = 0.80 → 'Confirmed Execution'"
        ),
    },
    
    'semantic_mapping': {
        'title': 'Semantic Mapping Examples',
        'description': (
            "Common semantic mappings:\n\n"
            "Windows Security Events:\n"
            "  • 4624 → 'User Login'\n"
            "  • 4634 → 'User Logoff'\n"
            "  • 4688 → 'Process Creation'\n"
            "  • 4800 → 'Session Locked'\n\n"
            "System Events:\n"
            "  • 6005 → 'System Startup'\n"
            "  • 6006 → 'System Shutdown'\n"
            "  • 1074 → 'System Restart'\n\n"
            "Registry Status Codes:\n"
            "  • 0x00000000 → 'Success'\n"
            "  • 0xC0000001 → 'Unsuccessful'"
        ),
    },
}


def get_example(category: str) -> dict:
    """
    Get example documentation for a category.
    
    Args:
        category: Category name
        
    Returns:
        Dictionary with 'title' and 'description' keys
    """
    return EXAMPLES.get(category, {
        'title': 'No Example Available',
        'description': 'No example documentation available for this category.'
    })
