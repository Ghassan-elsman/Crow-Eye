# Migration Guide: Forensic Report Enhancement

## Overview

This guide helps you migrate from the original EYE report API to the enhanced forensic report system. The good news: **all existing code continues to work without modification**. This guide shows you how to adopt new features when you're ready.

## Backward Compatibility Guarantee

The enhanced report system maintains 100% backward compatibility:

- ✅ All existing `add_chart()` calls work identically
- ✅ Existing report JSON files load without modification
- ✅ Default behavior matches the original 5-color palette
- ✅ All existing block types (text, table, image, chart, chat, reference) work unchanged
- ✅ HTML, Markdown, and PDF exports produce the same output for existing reports

**You don't need to change anything unless you want to use new features.**

---

## What's New

The enhanced system adds:

1. **Expanded Color Palettes** - 4 built-in palettes with 12+ colors each
2. **New Chart Types** - Doughnut, radar, scatter, horizontal bar, timeline, heatmap
3. **Per-Chart Color Customization** - Custom colors and gradients
4. **Report Templates** - Executive summary, technical analysis, timeline report
5. **Section Numbering & Table of Contents** - Automatic hierarchical numbering
6. **Cover Pages** - Professional case metadata display
7. **Chain of Custody Blocks** - Legal evidence tracking
8. **Enhanced Table Formatting** - Striped rows, borders, conditional formatting
9. **Watermarks & Branding** - Logo and watermark support
10. **Accessibility Features** - Colorblind simulation, grayscale preview, WCAG compliance
11. **Vector-Based PDF Export** - High-quality scalable charts

---

## Migration Path

### 1. Basic Charts (No Changes Required)

**Old API (still works):**

```python
from eye.services.report_engine import ReportEngine

report = ReportEngine()

# This continues to work exactly as before
report.add_chart(
    title="Evidence Timeline",
    labels=["Jan", "Feb", "Mar"],
    datasets=[{
        "label": "Events",
        "data": [10, 20, 15]
    }],
    chart_type="bar"
)
```

**Default Values for New Fields:**

When you use the old API, these defaults are applied automatically:

| Field | Default Value | Behavior |
|-------|--------------|----------|
| `color_scheme` | `None` (uses "forensic" palette) | Original 5-color palette |
| `custom_colors` | `None` | No custom colors |
| `gradient_config` | `None` | No gradients |
| `legend_position` | `"top"` | Legend at top |
| `annotations` | `[]` | No annotations |
| `reference_lines` | `[]` | No reference lines |

---

### 2. Using New Color Palettes

**Adopt when:** You need more than 5 colors or want professional/accessible color schemes

**Old code:**
```python
# Limited to 5 colors, cycles after that
report.add_chart(
    title="File Types Distribution",
    labels=["PDF", "DOCX", "XLSX", "JPG", "PNG", "TXT", "CSV", "ZIP"],
    datasets=[{"label": "Count", "data": [45, 32, 28, 67, 54, 23, 19, 31]}]
)
```

**New code with color palette:**
```python
# Use professional palette with 12 distinct colors
report.add_chart(
    title="File Types Distribution",
    labels=["PDF", "DOCX", "XLSX", "JPG", "PNG", "TXT", "CSV", "ZIP"],
    datasets=[{"label": "Count", "data": [45, 32, 28, 67, 54, 23, 19, 31]}],
    color_scheme="professional"  # NEW: Choose from forensic, professional, high_contrast, colorblind_friendly, grayscale
)
```

**Available Palettes:**

| Palette Name | Use Case | Colors |
|--------------|----------|--------|
| `forensic` | Default, original theme | 12 colors (orange-cyan theme) |
| `professional` | Business reports | 12 colors (blues and grays) |
| `high_contrast` | Maximum differentiation | 12 colors (pure colors) |
| `colorblind_friendly` | Accessible to colorblind users | 12 colors (deuteranopia/protanopia safe) |
| `grayscale` | Black & white printing | 12 shades of gray |

---

### 3. Custom Colors for Specific Charts

**Adopt when:** You need specific colors for branding or highlighting

**Old code:**
```python
# Colors assigned automatically from palette
report.add_chart(
    title="Alert Severity",
    labels=["Critical", "High", "Medium", "Low"],
    datasets=[{"label": "Count", "data": [5, 12, 34, 89]}]
)
```

**New code with custom colors:**
```python
# Specify exact colors for each dataset
report.add_chart(
    title="Alert Severity",
    labels=["Critical", "High", "Medium", "Low"],
    datasets=[{"label": "Count", "data": [5, 12, 34, 89]}],
    custom_colors=["#dc2626", "#f97316", "#fbbf24", "#10b981"]  # NEW: Red, orange, yellow, green
)
```

**Note:** Custom colors override the color palette. Colors cycle if you have more datasets than colors.

---

### 4. New Chart Types

**Adopt when:** You need specialized visualizations

#### Doughnut Charts

**Old code:**
```python
# Only pie charts available
report.add_chart(
    title="Evidence Sources",
    labels=["Hard Drive", "USB", "Cloud", "Email"],
    datasets=[{"label": "Files", "data": [450, 120, 89, 234]}],
    chart_type="pie"
)
```

**New code with doughnut:**
```python
# Doughnut chart with hollow center
report.add_chart(
    title="Evidence Sources",
    labels=["Hard Drive", "USB", "Cloud", "Email"],
    datasets=[{"label": "Files", "data": [450, 120, 89, 234]}],
    chart_type="doughnut"  # NEW: Doughnut chart type
)
```

#### Timeline Visualizations

**Old code:**
```python
# Manual text-based timeline
report.append_section(
    title="Event Timeline",
    markdown_content="""
    - 2024-01-15 10:30: User login
    - 2024-01-15 10:45: File accessed
    - 2024-01-15 11:00: File modified
    """
)
```

**New code with timeline block:**
```python
# Visual timeline with categories and colors
report.add_timeline(
    title="Event Timeline",
    events=[
        {
            "timestamp": "2024-01-15T10:30:00",
            "label": "User login",
            "description": "User jdoe logged in from 192.168.1.100",
            "category": "authentication"
        },
        {
            "timestamp": "2024-01-15T10:45:00",
            "label": "File accessed",
            "description": "Opened confidential.docx",
            "category": "file_access"
        },
        {
            "timestamp": "2024-01-15T11:00:00",
            "label": "File modified",
            "description": "Modified confidential.docx",
            "category": "file_modification"
        }
    ],
    color_scheme="colorblind_friendly"  # NEW: Timeline visualization
)
```

#### Heatmaps

**Old code:**
```python
# Manual table for temporal patterns
report.add_data_table(
    sql_query="SELECT hour, day, count FROM activity",
    columns=["Hour", "Monday", "Tuesday", "Wednesday"],
    rows=[
        {"Hour": "09:00", "Monday": 45, "Tuesday": 52, "Wednesday": 38},
        {"Hour": "10:00", "Monday": 67, "Tuesday": 71, "Wednesday": 59}
    ]
)
```

**New code with heatmap:**
```python
# Visual heatmap with color intensity
report.add_heatmap(
    title="Activity Heatmap",
    x_labels=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
    y_labels=["09:00", "10:00", "11:00", "12:00", "13:00"],
    intensity_values=[
        [45, 52, 38, 41, 35],
        [67, 71, 59, 63, 58],
        [89, 92, 85, 88, 82],
        [34, 38, 29, 31, 27],
        [56, 61, 54, 57, 52]
    ],
    color_scheme="thermal"  # NEW: Heatmap visualization (sequential, diverging, thermal)
)
```

---

### 5. Report Templates

**Adopt when:** You want standardized report structures

**Old code:**
```python
# Manual section creation
report = ReportEngine()
report.append_section("Case Overview", "...")
report.append_section("Key Findings", "...")
report.append_section("Conclusions", "...")
```

**New code with template:**
```python
# Template creates structure automatically
report = ReportEngine()
report.apply_template(
    template_name="executive_summary",  # NEW: executive_summary, technical_analysis, timeline_report
    case_metadata={
        "case_number": "CASE-2024-001",
        "investigator_name": "Jane Smith",
        "investigation_date": "2024-01-15",
        "case_title": "Data Breach Investigation",
        "classification_level": "CONFIDENTIAL"
    }
)

# Template creates these sections automatically:
# - Cover page with case metadata
# - Table of contents
# - Case Overview (empty, ready for content)
# - Key Findings (empty, ready for content)
# - Conclusions (empty, ready for content)
# - Recommendations (empty, ready for content)
```

**Available Templates:**

| Template | Sections | Use Case |
|----------|----------|----------|
| `executive_summary` | Case Overview, Key Findings, Conclusions, Recommendations | High-level reports for management |
| `technical_analysis` | Methodology, Detailed Findings, Evidence References, Technical Appendices | Detailed technical reports |
| `timeline_report` | Event Timeline, Chronological Event Listing | Timeline-focused investigations |

---

### 6. Section Numbering & Table of Contents

**Adopt when:** You have long reports that need navigation

**Old code:**
```python
# Manual numbering in titles
report.append_section("1. Introduction", "...")
report.append_section("2. Findings", "...")
report.append_section("2.1 Network Activity", "...")
```

**New code with automatic numbering:**
```python
# Enable automatic section numbering
report.enable_section_numbering(True)  # NEW: Automatic hierarchical numbering

# Just use plain titles
report.append_section("Introduction", "...")
report.append_section("Findings", "...")
report.append_section("Network Activity", "...")

# Renders as:
# 1 Introduction
# 2 Findings
# 3 Network Activity

# Table of contents is generated automatically in HTML export
```

---

### 7. Cover Pages

**Adopt when:** You need professional case identification

**Old code:**
```python
# Manual cover page as first section
report.append_section(
    "Cover Page",
    """
    # Case CASE-2024-001
    Investigator: Jane Smith
    Date: 2024-01-15
    """
)
```

**New code with cover page:**
```python
# Professional cover page with metadata
report.set_cover_page({
    "case_number": "CASE-2024-001",  # Required
    "investigator_name": "Jane Smith",  # Required
    "investigation_date": "2024-01-15",
    "case_title": "Data Breach Investigation",
    "organization": "Acme Security",
    "classification_level": "CONFIDENTIAL",  # Shows banner on every page
    "case_description": "Investigation of unauthorized data access"
})

# Cover page renders automatically before table of contents
```

---

### 8. Chain of Custody

**Adopt when:** You need legal evidence tracking

**Old code:**
```python
# Manual table for chain of custody
report.add_data_table(
    sql_query="",
    columns=["Evidence ID", "Handler", "Action", "Timestamp"],
    rows=[
        {"Evidence ID": "HDD-001", "Handler": "J. Smith", "Action": "Acquired", "Timestamp": "2024-01-15T09:00:00"}
    ]
)
```

**New code with chain of custody block:**
```python
# Specialized chain of custody block with validation
report.add_chain_of_custody(
    entries=[
        {
            "evidence_id": "HDD-001",
            "acquisition_date": "2024-01-15",
            "handler_name": "Jane Smith",
            "action": "Acquired from suspect's office",
            "timestamp": "2024-01-15T09:00:00"
        },
        {
            "evidence_id": "HDD-001",
            "acquisition_date": "2024-01-15",
            "handler_name": "John Doe",
            "action": "Transferred to forensic lab",
            "timestamp": "2024-01-15T10:30:00"
        },
        {
            "evidence_id": "HDD-001",
            "acquisition_date": "2024-01-15",
            "handler_name": "Jane Smith",
            "action": "Forensic imaging completed",
            "timestamp": "2024-01-15T14:00:00"
        }
    ]
)

# Renders with:
# - Distinct legal document styling
# - Chronological ordering
# - Validation of required fields
# - Visual emphasis for legal significance
```

---

### 9. Enhanced Table Formatting

**Adopt when:** You need better table readability

**Old code:**
```python
# Basic table
report.add_data_table(
    sql_query="SELECT * FROM files",
    columns=["Filename", "Size", "Modified"],
    rows=[
        {"Filename": "doc1.pdf", "Size": 1024, "Modified": "2024-01-15"},
        {"Filename": "doc2.pdf", "Size": 2048, "Modified": "2024-01-16"}
    ]
)
```

**New code with enhanced formatting:**
```python
from eye.models.report_blocks import TableBlock

# Create table block with enhanced options
table_block = TableBlock(
    sql_query="SELECT * FROM files",
    columns=["Filename", "Size", "Modified"],
    rows=[
        {"Filename": "doc1.pdf", "Size": 1024, "Modified": "2024-01-15"},
        {"Filename": "doc2.pdf", "Size": 2048, "Modified": "2024-01-16"},
        {"Filename": "doc3.pdf", "Size": 5120, "Modified": "2024-01-17"}
    ],
    caption="Evidence Files",
    # NEW: Enhanced formatting options
    striped_rows=True,  # Alternating row colors
    bordered_cells=True,  # Cell borders
    compact_spacing=False,  # Normal padding
    column_widths={"Filename": "50%", "Size": "25%", "Modified": "25%"},
    cell_alignment={"Size": "right", "Modified": "center"},
    conditional_formatting=[
        {
            "column": "Size",
            "operator": ">",
            "value": 3000,
            "color": "#fbbf24"  # Highlight large files in yellow
        }
    ]
)

report.blocks.append(table_block)
```

---

### 10. Watermarks & Branding

**Adopt when:** You need document protection or branding

**Old code:**
```python
# No watermark support
report = ReportEngine()
```

**New code with watermark:**
```python
# Add watermark to all pages
report = ReportEngine()

# Use preset watermark
report.add_watermark(
    text="draft",  # NEW: Presets: draft, confidential, for_official_use_only
    opacity=0.3,
    position="diagonal"  # center, top, bottom, diagonal
)

# Or custom watermark text
report.add_watermark(
    text="ATTORNEY-CLIENT PRIVILEGED",
    opacity=0.2,
    position="center"
)

# Add logo to header or footer
report.add_logo(
    logo_path="path/to/logo.png",
    position="header"  # header or footer
)
```

---

### 11. Accessibility Features

**Adopt when:** You need accessible reports

#### Colorblind Simulation

**Old code:**
```python
# No preview capability
html = report.render_html()
```

**New code with colorblind preview:**
```python
# Preview how report looks to colorblind users
report.enable_colorblind_preview(
    enabled=True,
    deficiency_type="deuteranopia"  # deuteranopia or protanopia
)

html = report.render_html()  # Colors transformed for simulation
```

#### Grayscale Preview

**Old code:**
```python
# No print preview
html = report.render_html()
```

**New code with grayscale preview:**
```python
# Preview how report looks when printed in black & white
report.enable_grayscale_preview(True)

html = report.render_html()  # Colors converted to grayscale
```

#### Use Colorblind-Friendly Palette by Default

**Best practice for accessibility:**
```python
# Use colorblind-friendly palette for all charts
report.add_chart(
    title="Evidence Distribution",
    labels=["Type A", "Type B", "Type C"],
    datasets=[{"label": "Count", "data": [45, 67, 32]}],
    color_scheme="colorblind_friendly"  # Accessible to all users
)
```

---

## Complete Migration Example

### Before (Original API)

```python
from eye.services.report_engine import ReportEngine

# Create report
report = ReportEngine()

# Add sections
report.append_section("Introduction", "This is the investigation report...")
report.append_section("Findings", "We discovered the following...")

# Add chart
report.add_chart(
    title="File Types",
    labels=["PDF", "DOCX", "XLSX"],
    datasets=[{"label": "Count", "data": [45, 32, 28]}],
    chart_type="bar"
)

# Add table
report.add_data_table(
    sql_query="SELECT * FROM evidence",
    columns=["ID", "Type", "Date"],
    rows=[
        {"ID": "E001", "Type": "Document", "Date": "2024-01-15"},
        {"ID": "E002", "Type": "Image", "Date": "2024-01-16"}
    ]
)

# Export
html = report.render_html("Investigation Report")
```

### After (Enhanced API)

```python
from eye.services.report_engine import ReportEngine

# Create report with case directory
report = ReportEngine(case_directory="/cases/CASE-2024-001")

# Set cover page
report.set_cover_page({
    "case_number": "CASE-2024-001",
    "investigator_name": "Jane Smith",
    "investigation_date": "2024-01-15",
    "case_title": "Data Breach Investigation",
    "classification_level": "CONFIDENTIAL"
})

# Apply template
report.apply_template(
    template_name="technical_analysis",
    case_metadata={
        "case_number": "CASE-2024-001",
        "investigator_name": "Jane Smith",
        "investigation_date": "2024-01-15"
    }
)

# Enable section numbering
report.enable_section_numbering(True)

# Add watermark
report.add_watermark(text="confidential", opacity=0.3, position="diagonal")

# Add sections (template created structure, now add content)
report.append_section("Introduction", "This is the investigation report...")
report.append_section("Findings", "We discovered the following...")

# Add chart with professional palette
report.add_chart(
    title="File Types",
    labels=["PDF", "DOCX", "XLSX"],
    datasets=[{"label": "Count", "data": [45, 32, 28]}],
    chart_type="bar",
    color_scheme="professional",  # NEW
    legend_position="bottom"  # NEW
)

# Add timeline
report.add_timeline(
    title="Investigation Timeline",
    events=[
        {
            "timestamp": "2024-01-15T09:00:00",
            "label": "Evidence acquired",
            "description": "Hard drive seized from suspect's office",
            "category": "evidence"
        },
        {
            "timestamp": "2024-01-15T14:00:00",
            "label": "Forensic imaging completed",
            "description": "Created bit-by-bit image of HDD-001",
            "category": "analysis"
        }
    ],
    color_scheme="colorblind_friendly"  # NEW
)

# Add enhanced table
from eye.models.report_blocks import TableBlock
table_block = TableBlock(
    sql_query="SELECT * FROM evidence",
    columns=["ID", "Type", "Date"],
    rows=[
        {"ID": "E001", "Type": "Document", "Date": "2024-01-15"},
        {"ID": "E002", "Type": "Image", "Date": "2024-01-16"}
    ],
    striped_rows=True,  # NEW
    bordered_cells=True,  # NEW
    cell_alignment={"Date": "center"}  # NEW
)
report.blocks.append(table_block)

# Add chain of custody
report.add_chain_of_custody(
    entries=[
        {
            "evidence_id": "HDD-001",
            "acquisition_date": "2024-01-15",
            "handler_name": "Jane Smith",
            "action": "Acquired from suspect's office",
            "timestamp": "2024-01-15T09:00:00"
        }
    ]
)

# Export with automatic case directory organization
html = report.render_html("Investigation Report")
```

---

## Default Values Reference

When using the original API, these defaults ensure backward compatibility:

### ReportEngine Defaults

| Setting | Default | Behavior |
|---------|---------|----------|
| `case_directory` | `None` | No automatic case directory export |
| Section numbering | `False` | No automatic numbering |
| Table of contents | `False` | No TOC generated |
| Cover page | `None` | No cover page |
| Watermark | `None` | No watermark |
| Logo | `None` | No logo |
| Colorblind preview | `False` | Normal colors |
| Grayscale preview | `False` | Normal colors |

### Chart Defaults

| Field | Default | Behavior |
|-------|---------|----------|
| `chart_type` | `"bar"` | Bar chart |
| `color_scheme` | `None` | Uses "forensic" palette (original 5 colors) |
| `custom_colors` | `None` | No custom colors |
| `gradient_config` | `None` | No gradients |
| `legend_position` | `"top"` | Legend at top |
| `annotations` | `[]` | No annotations |
| `reference_lines` | `[]` | No reference lines |

### Table Defaults

| Field | Default | Behavior |
|-------|---------|----------|
| `striped_rows` | `False` | No alternating colors |
| `bordered_cells` | `False` | No cell borders |
| `compact_spacing` | `False` | Normal padding |
| `column_widths` | `{}` | Auto width |
| `cell_alignment` | `{}` | Left aligned |
| `conditional_formatting` | `[]` | No highlighting |

---

## Migration Checklist

Use this checklist when migrating to the enhanced API:

### Phase 1: Verify Compatibility (No Code Changes)
- [ ] Run existing code with enhanced system
- [ ] Verify reports render identically
- [ ] Confirm all exports (HTML, PDF, Markdown) work
- [ ] Test loading existing report JSON files

### Phase 2: Adopt Color Enhancements (Optional)
- [ ] Identify charts with >5 datasets
- [ ] Choose appropriate color palette (professional, colorblind_friendly, etc.)
- [ ] Update `add_chart()` calls with `color_scheme` parameter
- [ ] Test colorblind preview mode

### Phase 3: Adopt New Chart Types (Optional)
- [ ] Identify opportunities for timeline visualizations
- [ ] Replace manual timelines with `add_timeline()`
- [ ] Identify opportunities for heatmaps
- [ ] Replace tables with `add_heatmap()` where appropriate

### Phase 4: Adopt Templates (Optional)
- [ ] Choose appropriate template (executive_summary, technical_analysis, timeline_report)
- [ ] Prepare case metadata
- [ ] Update report creation to use `apply_template()`
- [ ] Enable section numbering if desired

### Phase 5: Adopt Enhanced Features (Optional)
- [ ] Add cover page with `set_cover_page()`
- [ ] Add watermark with `add_watermark()`
- [ ] Add logo with `add_logo()`
- [ ] Add chain of custody blocks where appropriate
- [ ] Enhance tables with formatting options

### Phase 6: Accessibility (Recommended)
- [ ] Use `colorblind_friendly` palette by default
- [ ] Test with colorblind preview mode
- [ ] Test with grayscale preview mode
- [ ] Verify WCAG AA compliance

---

## Troubleshooting

### Issue: Colors look different after upgrade

**Cause:** You're using a chart with >5 datasets, and the color cycling now uses 12 colors instead of 5.

**Solution:** Explicitly set `color_scheme="forensic"` to use the original palette, or embrace the expanded palette.

```python
# Force original 5-color behavior
report.add_chart(
    title="My Chart",
    labels=[...],
    datasets=[...],
    color_scheme="forensic"  # Explicitly use forensic palette
)
```

### Issue: Template creates sections I don't need

**Cause:** Templates create predefined section structures.

**Solution:** Don't use templates, or delete unwanted sections after template application.

```python
# Option 1: Don't use template
report = ReportEngine()
report.append_section("My Section", "...")

# Option 2: Use template and remove sections
report.apply_template("executive_summary", case_metadata)
# Remove unwanted sections by block_id
report.delete_section(block_id="...")
```

### Issue: Chain of custody validation fails

**Cause:** Missing required fields (evidence_id, handler_name, action, timestamp).

**Solution:** Ensure all required fields are present.

```python
# ❌ Missing required fields
report.add_chain_of_custody(
    entries=[{"evidence_id": "HDD-001"}]  # Missing handler_name, action, timestamp
)

# ✅ All required fields present
report.add_chain_of_custody(
    entries=[{
        "evidence_id": "HDD-001",
        "acquisition_date": "2024-01-15",
        "handler_name": "Jane Smith",  # Required
        "action": "Acquired",  # Required
        "timestamp": "2024-01-15T09:00:00"  # Required
    }]
)
```

### Issue: Watermark doesn't appear in PDF

**Cause:** Watermark is added after HTML rendering.

**Solution:** Add watermark before calling `render_html()`.

```python
# ❌ Wrong order
html = report.render_html()
report.add_watermark("DRAFT")  # Too late

# ✅ Correct order
report.add_watermark("DRAFT")
html = report.render_html()  # Watermark included
```

---

## Getting Help

- **Documentation:** See `eye/docs/` for detailed documentation
- **Examples:** See `eye/tests/` for usage examples
- **API Reference:** See `eye/services/report_engine.py` for complete API

---

## Summary

The enhanced forensic report system is **100% backward compatible**. You can:

1. **Keep using the old API** - Everything works as before
2. **Adopt new features gradually** - Add color palettes, templates, etc. when ready
3. **Mix old and new** - Use new features for some charts, old API for others

**Key principle:** Existing code works unchanged. New features are opt-in through new parameters and methods.

**Recommended migration path:**
1. Verify compatibility (no changes)
2. Adopt colorblind-friendly palette for accessibility
3. Add templates for standardized reports
4. Enhance specific charts/tables as needed
5. Add cover pages and watermarks for professional appearance

---

**Document Version:** 1.0  
**Last Updated:** 2024  
