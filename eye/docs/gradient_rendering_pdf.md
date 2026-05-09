# PDF Gradient Rendering Implementation

## Overview




## Implementation

### Background

Gradient banding (also called posterization) occurs when there aren't enough color steps in a gradient, causing visible "bands" or steps instead of a smooth transition. This is particularly noticeable in:
- Black-to-white gradients
- Subtle color transitions
- Large gradient areas
- Low-resolution outputs

### Solution Components

The implementation ensures smooth gradient rendering through multiple mechanisms:

#### 1. High DPI Configuration

**File**: `eye/services/pdf_exporter.py`

The PDFExporter is configured with a default DPI of 300, which provides sufficient resolution for smooth gradient rendering:

```python
self.dpi = config.get("dpi", 300)
```

Higher DPI values (300+) provide more pixels for color transitions, reducing the visibility of banding artifacts.

#### 2. CSS Gradient Quality Settings

Enhanced CSS rules ensure gradients are rendered with high quality:

```css
/* Gradient rendering quality - prevent banding artifacts */
* {
    /* Enable smooth gradient rendering */
    -webkit-backface-visibility: hidden;
    -webkit-transform: translateZ(0);
    backface-visibility: hidden;
}

/* Ensure gradients render with high quality */
[style*="gradient"] {
    /* Force high-quality rendering for gradient elements */
    image-rendering: -webkit-optimize-contrast;
    image-rendering: smooth;
}
```

These CSS properties:
- Enable hardware acceleration for smoother rendering
- Force high-quality image rendering for gradient elements
- Prevent visual artifacts during rendering

#### 3. Weasyprint + Cairo Rendering

**Rendering Engine**: Weasyprint uses Cairo as its rendering backend.

Cairo provides:
- **Anti-aliasing**: Automatically enabled for smooth edges and transitions
- **Dithering**: Applies dithering to gradients to create the illusion of more colors
- **High-quality interpolation**: Smooth color transitions between gradient stops

From the code comments:

```python
# Gradient rendering quality:
# Weasyprint uses Cairo for rendering, which supports smooth gradients.
# The quality is controlled by:
# 1. CSS gradient definitions (linear-gradient, radial-gradient)
# 2. Cairo's anti-aliasing settings (enabled by default)
# 3. PDF resolution (controlled by DPI)
#
# To prevent banding artifacts in gradients:
# - Use sufficient color stops in gradient definitions
# - Ensure high DPI (300+ recommended)
# - Cairo automatically applies dithering for smooth transitions
```

#### 4. Gradient Definition Best Practices

For optimal results, gradients should be defined with:

**Simple gradients** (2 color stops):
```css
background: linear-gradient(135deg, #f97316 0%, #06b6d4 100%);
```

**Complex gradients** (multiple color stops for very smooth transitions):
```css
background: linear-gradient(to right, 
    #ff0000 0%, 
    #ff4400 20%, 
    #ff8800 40%, 
    #ffcc00 60%, 
    #ffff00 80%, 
    #ffffff 100%);
```

More color stops provide smoother transitions, especially for long gradients or subtle color changes.

## Testing

### Unit Tests

**File**: `eye/services/test_pdf_gradient_rendering.py`

The test suite includes:

1. **Basic gradient rendering**: Verifies gradients are included in PDF output
2. **High DPI rendering**: Tests that high DPI improves gradient quality
3. **Multiple gradients**: Tests reports with multiple gradient elements
4. **Transparent gradients**: Tests rgba gradients with transparency
5. **Visual quality test**: Manual inspection test for gradient smoothness

### Running Tests

```bash
# Run all gradient rendering tests
pytest eye/services/test_pdf_gradient_rendering.py -v

# Run visual quality test (requires manual inspection)
RUN_VISUAL_TESTS=1 pytest eye/services/test_pdf_gradient_rendering.py::TestPDFGradientRendering::test_gradient_visual_quality
```

**Note**: Tests require weasyprint and its dependencies (GTK libraries) to be properly installed. On systems where weasyprint is not available, tests will skip gracefully.

## Usage Examples

### Creating Reports with Gradients

```python
from eye.services.report_engine import ReportEngine
from eye.services.color_manager import ColorManager

# Initialize services
report_engine = ReportEngine()
color_manager = ColorManager()

# Create gradient configuration
gradient = color_manager.create_gradient(
    start_color="#f97316",  # Orange
    end_color="#06b6d4",    # Cyan
    direction="vertical"
)

# Add chart with gradient
report_engine.add_chart_enhanced(
    title="Evidence Timeline",
    labels=["Jan", "Feb", "Mar"],
    datasets=[{"label": "Events", "data": [10, 20, 15]}],
    gradient_config=gradient
)

# Export to PDF with high quality
report_engine.export_pdf("report.pdf")
```

### Custom Gradient in HTML

For custom HTML blocks with gradients:

```python
html_content = """
<div style="
    background: linear-gradient(135deg, 
        rgba(249, 115, 22, 0.1) 0%, 
        rgba(6, 182, 212, 0.1) 100%);
    padding: 20px;
    border-radius: 8px;
">
    <h2>Section with Gradient Background</h2>
    <p>Content here...</p>
</div>
"""

report_engine.add_html(html_content)
```

## Technical Details

### Color Space Considerations

When using print-optimized mode or CMYK color space:

```python
exporter = PDFExporter({
    "dpi": 300,
    "color_space": "CMYK",
    "print_optimized": True
})
```

The exporter:
1. Converts RGB gradients to CMYK
2. Verifies color accuracy (Delta E < 5)
3. Maintains smooth transitions in the converted color space

### DPI Recommendations

| DPI | Use Case | Gradient Quality |
|-----|----------|------------------|
| 72  | Screen viewing only | Acceptable for simple gradients |
| 150 | Draft printing | Noticeable banding in subtle gradients |
| 300 | Professional printing | Smooth gradients, recommended minimum |
| 600 | High-quality printing | Excellent gradient quality |

**Recommendation**: Use 300 DPI or higher for professional forensic reports.

### Gradient Types Supported

1. **Linear gradients**: `linear-gradient(direction, color1, color2, ...)`
2. **Radial gradients**: `radial-gradient(shape, color1, color2, ...)`
3. **Transparent gradients**: Using `rgba()` colors with alpha channel
4. **Multi-stop gradients**: Multiple color stops for complex transitions

## Troubleshooting

### Visible Banding in Gradients

If you observe banding artifacts:

1. **Increase DPI**: Use 600 DPI for critical reports
   ```python
   exporter = PDFExporter({"dpi": 600})
   ```

2. **Add more color stops**: For long gradients, add intermediate colors
   ```css
   /* Instead of: */
   background: linear-gradient(to right, #000000 0%, #ffffff 100%);
   
   /* Use: */
   background: linear-gradient(to right, 
       #000000 0%, 
       #404040 25%, 
       #808080 50%, 
       #c0c0c0 75%, 
       #ffffff 100%);
   ```

3. **Check color space**: Ensure RGB mode for screen viewing
   ```python
   exporter = PDFExporter({"color_space": "RGB"})
   ```

### Weasyprint Installation Issues

On Windows, weasyprint requires GTK libraries. If you encounter import errors:

1. Follow the official installation guide: https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation
2. Install GTK for Windows: https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer
3. Verify installation:
   ```python
   from weasyprint import HTML
   print("Weasyprint is working!")
   ```

## References

- **Design Document**: Section 6 - PDFExporter
- **Cairo Graphics**: https://www.cairographics.org/
- **Weasyprint Documentation**: https://doc.courtbouillon.org/weasyprint/

## Changelog

- **2024**: Initial implementation of gradient rendering for PDF export
  - Added CSS quality settings for smooth gradients
  - Configured weasyprint with Cairo anti-aliasing
  - Created comprehensive test suite
  - Documented gradient rendering best practices
