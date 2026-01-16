# Semantic Rules Configuration

This directory contains JSON configuration files for semantic mapping rules used by the Crow-Eye Correlation Engine.

## Overview

Semantic rules map technical forensic values (like Event IDs, file names, registry keys) to human-readable meanings. This helps investigators quickly understand the significance of correlation matches.

## File Structure

- **semantic_rules_default.json** - Default forensic rules provided by the system (20+ rules)
- **semantic_rules_custom.json** - Your custom rules that extend or override defaults
- **semantic_rules_schema.json** - JSON schema for validation
- **semantic_rules_example.json** - Annotated examples showing rule syntax
- **README.md** - This documentation file

## Rule Format

Each rule is a JSON object with the following structure:

```json
{
  "rule_id": "unique_identifier",
  "name": "Human Readable Name",
  "semantic_value": "What this rule means",
  "conditions": [
    {
      "feather_id": "ArtifactSource",
      "field_name": "FieldToMatch",
      "value": "ValueToMatch",
      "operator": "equals|contains|regex|wildcard"
    }
  ],
  "logic_operator": "AND|OR",
  "scope": "global|wing|pipeline",
  "category": "Category",
  "severity": "info|low|medium|high|critical",
  "confidence": 0.85,
  "description": "Detailed description"
}
```

### Required Fields

- **rule_id**: Unique identifier for the rule (string)
- **name**: Human-readable name (string)
- **semantic_value**: The semantic meaning when this rule matches (string)
- **conditions**: Array of conditions to evaluate (array, minimum 1 condition)
- **logic_operator**: How to combine conditions - "AND" or "OR" (string)

### Optional Fields

- **scope**: Where the rule applies - "global", "wing", or "pipeline" (default: "global")
- **category**: Classification category (string)
- **severity**: Importance level - "info", "low", "medium", "high", or "critical" (default: "info")
- **confidence**: Confidence score from 0.0 to 1.0 (default: 1.0)
- **description**: Detailed explanation of the rule (string)
- **wing_id**: Wing ID if scope is "wing" (string)
- **pipeline_id**: Pipeline ID if scope is "pipeline" (string)

### Condition Fields

Each condition must have:

- **feather_id**: The artifact source (e.g., "SecurityLogs", "Prefetch", "Registry")
- **field_name**: The field to match (e.g., "EventID", "executable_name", "KeyPath")
- **value**: The value to match, or "*" for wildcard
- **operator**: Match operator:
  - **equals**: Exact match (case-insensitive)
  - **contains**: Substring match (case-insensitive)
  - **regex**: Regular expression match
  - **wildcard**: Match any non-empty value (use value: "*")

## Logic Operators

- **AND**: All conditions must match
- **OR**: At least one condition must match

## Examples

### Simple Rule (Single Condition)

```json
{
  "rule_id": "user_login",
  "name": "User Login",
  "semantic_value": "User Login",
  "conditions": [
    {
      "feather_id": "SecurityLogs",
      "field_name": "EventID",
      "value": "4624",
      "operator": "equals"
    }
  ],
  "logic_operator": "AND",
  "severity": "info",
  "confidence": 1.0
}
```

### Complex Rule (Multiple Conditions with AND)

```json
{
  "rule_id": "suspicious_powershell",
  "name": "Suspicious PowerShell Execution",
  "semantic_value": "Potential malicious PowerShell activity",
  "conditions": [
    {
      "feather_id": "SecurityLogs",
      "field_name": "EventID",
      "value": "4688",
      "operator": "equals"
    },
    {
      "feather_id": "SecurityLogs",
      "field_name": "CommandLine",
      "value": ".*-encodedcommand.*",
      "operator": "regex"
    }
  ],
  "logic_operator": "AND",
  "category": "Execution",
  "severity": "high",
  "confidence": 0.85,
  "description": "Detects PowerShell with encoded commands"
}
```

### Wildcard Rule

```json
{
  "rule_id": "registry_modification",
  "name": "Registry Modification",
  "semantic_value": "Registry Change",
  "conditions": [
    {
      "feather_id": "Registry",
      "field_name": "KeyPath",
      "value": ".*\\\\Run.*",
      "operator": "regex"
    },
    {
      "feather_id": "Registry",
      "field_name": "ValueName",
      "value": "*",
      "operator": "wildcard"
    }
  ],
  "logic_operator": "AND",
  "severity": "medium",
  "confidence": 0.9
}
```

## Creating Custom Rules

1. **Create or edit** `semantic_rules_custom.json`
2. **Add your rules** following the format above
3. **Validate** using the Settings Dialog → Semantic Mapping → "Validate Rule Files" button
4. **Reload** rules using the "Reload Rules" button (no restart needed)

### Custom Rule Priority

- Custom rules **override** default rules with the same `rule_id`
- Custom rules with unique `rule_id` values are **added** to the rule set
- Load order: Default rules first, then custom rules

## Validation

The system validates all rules before loading:

- **JSON syntax**: Must be valid JSON
- **Required fields**: All required fields must be present
- **Field types**: Fields must have correct types (string, number, array)
- **Enum values**: logic_operator, severity, operator must use valid values
- **Confidence range**: Must be between 0.0 and 1.0
- **Regex patterns**: Must be valid regular expressions

### Validation Errors

If validation fails, you'll see detailed error messages:

```
[ERROR] Rule 'my_rule' - logic_operator: Invalid value 'XOR'. Must be 'AND' or 'OR'.
  Suggestion: Change logic_operator to either 'AND' or 'OR'.
```

## Fallback Behavior

If JSON files are missing or corrupted:

- **Missing default file**: System creates it from built-in rules
- **Corrupted default file**: System uses built-in rules and logs warning
- **Missing custom file**: System uses only default rules
- **Corrupted custom file**: System skips custom rules and uses defaults

The system **never crashes** due to configuration errors.

## Performance

- Rules are loaded once at startup
- Cached in memory for fast access
- Regex patterns are compiled once
- Expected performance: < 500ms for 100 rules

## GUI Management

Use the Settings Dialog (Semantic Mapping tab) to:

- **Validate** rule files for errors
- **Export** default rules to JSON
- **Reload** rules without restarting
- **Add/Edit** rules through the GUI

## Troubleshooting

### Rules not loading

1. Check file exists: `Crow-Eye/configs/semantic_rules_default.json`
2. Validate JSON syntax using online validator or Settings Dialog
3. Check console logs for error messages
4. Use "Export Default Rules" to create fresh default file

### Rules not matching

1. Verify `feather_id` matches your artifact source name
2. Check `field_name` matches actual field names in data
3. Test regex patterns using online regex tester
4. Check `logic_operator` is correct (AND vs OR)
5. Verify `confidence` threshold in correlation settings

### Duplicate rule_id warning

- Each `rule_id` should be unique
- System uses last occurrence if duplicates found
- Remove duplicate or rename one of the rules

## Best Practices

1. **Use descriptive rule_id values**: `user_login_success` not `rule1`
2. **Set appropriate severity**: Match severity to actual threat level
3. **Add descriptions**: Help future users understand the rule
4. **Test regex patterns**: Verify patterns match expected values
5. **Use wildcards sparingly**: Specific matches are more reliable
6. **Document custom rules**: Add comments in separate documentation
7. **Backup before editing**: Keep copies of working configurations
8. **Validate after changes**: Always validate before deploying

## Support

For issues or questions:

1. Check this README
2. Review `semantic_rules_example.json` for examples
3. Use Settings Dialog validation for error details
4. Check console logs for detailed error messages
5. Consult Crow-Eye technical documentation

## Version

Configuration format version: 1.0
Compatible with: Crow-Eye Correlation Engine v2.0+
