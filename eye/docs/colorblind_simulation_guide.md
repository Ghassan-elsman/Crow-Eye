# Colorblind Simulation Guide

## Overview

The colorblind simulation feature allows forensic investigators to preview how their reports will appear to people with color vision deficiency. This ensures that reports remain accessible and that critical information is not conveyed solely through color.


## Supported Color Vision Deficiencies

The system supports simulation of two types of red-green colorblindness:

### Deuteranopia
- **Description**: Missing or non-functional green cones (M-cones)
- **Prevalence**: Affects approximately 1% of males
- **Impact**: Difficulty distinguishing red from green; colors shift toward yellow and blue

### Protanopia
- **Description**: Missing or non-functional red cones (L-cones)
- **Prevalence**: Affects approximately 1% of males
- **Impact**: Difficulty distinguishing red from green; reduced brightness perception of red

## How It Works

The colorblind simulation uses scientifically validated color transformation matrices based on research by Brettel, Viénot, and Mollon (1997, 1999). These matrices accurately simulate how colors appear to people with specific types of color vision deficiency.

### Transformation Process

1. **Color Extraction**: All hex color codes in the HTML are identified
2. **RGB Conversion**: Colors are converted from hex to RGB (0-1 range)
3. **Matrix Application**: A transformation matrix is applied based on the deficiency type
4. **Clamping**: Values are clamped to valid range (0-1)
5. **Hex Conversion**: Transformed colors are converted back to hex format

## Usage

### Basic Usage with ReportEngine

```python
from eye.services.report_engine import ReportEngine

# Create a report
engine = ReportEngine()

# Add content (charts, tables, etc.)
engine.add_chart(
    title="Evidence Analysis",
    labels=["Files", "Registry", "Network"],
    datasets=[
        {"label": "Suspicious", "data": [45, 23, 12]},
        {"label": "Malicious", "data": [12, 8, 5]}
    ],
    chart_type="bar"
)

# Enable colorblind preview for deuteranopia
engine.enable_colorblind_preview(True, "deuteranopia")

# Render HTML with simulated colors
html = engine.render_html("Report - Deuteranopia Preview")

# Save for review
with open("report_deuteranopia.html", "w") as f:
    f.write(html)

# Switch to protanopia simulation
engine.enable_colorblind_preview(True, "protanopia")
html = engine.render_html("Report - Protanopia Preview")

# Disable simulation for normal view
engine.enable_colorblind_preview(False)
html = engine.render_html("Report - Normal View")
```

### Direct Color Transformation

```python
from eye.services.color_manager import ColorManager

cm = ColorManager()

# Simulate a single color
original = "#ff0000"  # Red
deuteranopia = cm.simulate_colorblind(original, "deuteranopia")
protanopia = cm.simulate_colorblind(original, "protanopia")

print(f"Original: {original}")
print(f"Deuteranopia: {deuteranopia}")
print(f"Protanopia: {protanopia}")
```

### Batch HTML Transformation

```python
from eye.services.color_manager import ColorManager

cm = ColorManager()

# Transform all colors in HTML content
html_content = """
<div style="color: #ff0000; background: #00ff00;">
    <p>Important evidence</p>
</div>
"""

simulated_html = cm.apply_colorblind_simulation_to_html(
    html_content, 
    "deuteranopia"
)
```

## Best Practices

### 1. Preview Before Finalizing

Always preview reports with colorblind simulation before finalizing them for distribution:

```python
# Generate all three versions
engine.enable_colorblind_preview(False)
normal = engine.render_html()

engine.enable_colorblind_preview(True, "deuteranopia")
deut = engine.render_html()

engine.enable_colorblind_preview(True, "protanopia")
prot = engine.render_html()

# Review all three versions to ensure accessibility
```

### 2. Use Colorblind-Friendly Palette

The `colorblind_friendly` palette is specifically designed to remain distinguishable with color vision deficiency:

```python
from eye.services.color_manager import ColorManager

cm = ColorManager()

# Use colorblind-friendly palette for charts
engine.add_chart(
    title="Analysis Results",
    labels=["A", "B", "C"],
    datasets=[{"label": "Data", "data": [10, 20, 30]}],
    color_scheme="colorblind_friendly"
)
```

### 3. Don't Rely Solely on Color

Ensure critical information is not conveyed through color alone:

- **Use patterns**: Add patterns or textures to chart elements
- **Use labels**: Include text labels on data points
- **Use shapes**: Use different shapes for different categories
- **Use contrast**: Ensure sufficient contrast between elements

### 4. Test with Multiple Deficiency Types

Different types of colorblindness affect colors differently. Test with both:

```python
# Test deuteranopia
engine.enable_colorblind_preview(True, "deuteranopia")
deut_html = engine.render_html()

# Test protanopia
engine.enable_colorblind_preview(True, "protanopia")
prot_html = engine.render_html()

# Verify both versions are readable
```

## Color Transformation Examples

### Forensic Palette

| Original | Color Name | Deuteranopia | Protanopia |
|----------|------------|--------------|------------|
| #f97316 | Orange | #c7d132 | #bfbe2d |
| #06b6d4 | Cyan | #483bcb | #5254cd |
| #ec4899 | Pink | #aebb81 | #a5a485 |
| #10b981 | Green | #4f4392 | #595b8f |

### Professional Palette

| Original | Color Name | Deuteranopia | Protanopia |
|----------|------------|--------------|------------|
| #1e40af | Deep Blue | #2b288e | #2d2d94 |
| #475569 | Slate Gray | #4c4b63 | #4d4d64 |
| #0891b2 | Cyan Blue | #3b31a8 | #4345aa |

### Colorblind-Friendly Palette

| Original | Color Name | Deuteranopia | Protanopia |
|----------|------------|--------------|------------|
| #0173b2 | Blue | #2c239f | #3233a3 |
| #de8f05 | Orange | #c0c62e | #bcbb26 |
| #029e73 | Green | #3d3180 | #46477d |

## API Reference

### ColorManager.simulate_colorblind()

```python
def simulate_colorblind(
    self, 
    color: str, 
    deficiency_type: str = "deuteranopia"
) -> str:
    """
    Simulate how a color appears with color vision deficiency.
    
    Args:
        color: Hex color code (e.g., "#FF5733")
        deficiency_type: "deuteranopia" or "protanopia"
    
    Returns:
        Hex color code showing simulated appearance
    
    Raises:
        ValueError: If color is invalid or deficiency_type not supported
    """
```

### ColorManager.apply_colorblind_simulation_to_html()

```python
def apply_colorblind_simulation_to_html(
    self, 
    html_content: str, 
    deficiency_type: str = "deuteranopia"
) -> str:
    """
    Apply colorblind simulation to all colors in HTML.
    
    Args:
        html_content: HTML string containing color codes
        deficiency_type: "deuteranopia" or "protanopia"
    
    Returns:
        HTML with all colors transformed
    
    Raises:
        ValueError: If deficiency_type not supported
    """
```

### ReportEngine.enable_colorblind_preview()

```python
def enable_colorblind_preview(
    self, 
    enabled: bool = True, 
    deficiency_type: str = "deuteranopia"
) -> None:
    """
    Enable or disable colorblind simulation preview mode.
    
    Args:
        enabled: True to enable, False to disable
        deficiency_type: "deuteranopia" or "protanopia"
    
    Raises:
        ValueError: If deficiency_type not supported
    """
```

## Technical Details

### Transformation Matrices

#### Deuteranopia (Missing Green Cones)
```
R' = 0.625*R + 0.375*G + 0.0*B
G' = 0.7*R + 0.3*G + 0.0*B
B' = 0.0*R + 0.3*G + 0.7*B
```

#### Protanopia (Missing Red Cones)
```
R' = 0.567*R + 0.433*G + 0.0*B
G' = 0.558*R + 0.442*G + 0.0*B
B' = 0.0*R + 0.242*G + 0.758*B
```

### Color Space

- **Input**: sRGB color space (hex format)
- **Processing**: Linear RGB (gamma-corrected)
- **Output**: sRGB color space (hex format)

### Accuracy

The transformation matrices are based on peer-reviewed research and provide scientifically accurate simulations of color vision deficiency. However, individual experiences may vary.

## Limitations

1. **Simulation Only**: This feature simulates how colors appear; it does not guarantee perfect accuracy for all individuals
2. **Red-Green Only**: Currently supports only deuteranopia and protanopia (red-green colorblindness)
3. **Static Preview**: Simulation is applied to static HTML; interactive elements may behave differently
4. **No Tritanopia**: Blue-yellow colorblindness (tritanopia) is not currently supported

## Future Enhancements

Potential future additions:
- Tritanopia simulation (blue-yellow colorblindness)
- Achromatopsia simulation (complete colorblindness)
- Interactive preview mode with real-time switching
- Automated accessibility scoring
- Suggested color adjustments for better accessibility

## References

- Brettel, H., Viénot, F., & Mollon, J. D. (1997). Computerized simulation of color appearance for dichromats. *Journal of the Optical Society of America A*, 14(10), 2647-2655.
- Viénot, F., Brettel, H., & Mollon, J. D. (1999). Digital video colourmaps for checking the legibility of displays by dichromats. *Color Research & Application*, 24(4), 243-252.

## Support

For questions or issues with the colorblind simulation feature, please refer to:
- Main documentation: `eye/docs/eye_deep_analysis.md`
- Test examples: `eye/services/test_colorblind_simulation.py`
- Demo script: `eye/services/demo_colorblind_simulation.py`
