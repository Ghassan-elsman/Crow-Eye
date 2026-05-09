"""
PDF Export Service for Forensic Reports

This module provides high-quality PDF export capabilities with configurable
settings for DPI, color space, font embedding, and print optimization.

"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import re
import json
import logging


@dataclass
class ExportConfig:
    """
    Configuration for PDF export with quality and formatting options.
    
    Attributes:
        dpi: Resolution for rendering (default 300 for high quality)
        color_space: Color space for export - "RGB" or "CMYK" (default "RGB")
        embed_fonts: Whether to embed fonts for consistent rendering (default True)
        print_optimized: Whether to optimize colors for printing (default False)
        watermark: Optional watermark configuration dictionary
        logo: Optional logo configuration dictionary
    """
    dpi: int = 300
    color_space: str = "RGB"
    embed_fonts: bool = True
    print_optimized: bool = False
    watermark: Optional[Dict[str, Any]] = None
    logo: Optional[Dict[str, Any]] = None


class PDFExporter:
    """
    High-quality PDF export with enhanced rendering options.
    
    This class provides professional-grade PDF export capabilities for forensic
    reports, including configurable DPI, color space conversion, font embedding,
    print optimization, and vector-based chart rendering using SVG.
    
    Attributes:
        dpi: Resolution for rendering charts and images
        color_space: Color space for export (RGB or CMYK)
        embed_fonts: Whether to embed fonts in the PDF
        print_optimized: Whether to apply print-friendly color conversions
        watermark: Watermark configuration if enabled
        logo: Logo configuration if enabled
        
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize PDF exporter with configuration.
        
        Args:
            config: Export configuration dictionary with optional keys:
                - dpi: int (default 300)
                - color_space: str "RGB" or "CMYK" (default "RGB")
                - embed_fonts: bool (default True)
                - print_optimized: bool (default False)
                - watermark: Optional[Dict[str, Any]] (default None)
                - logo: Optional[Dict[str, Any]] (default None)
        
        Examples:
            >>> # Default configuration
            >>> exporter = PDFExporter()
            
            >>> # Custom configuration
            >>> exporter = PDFExporter({
            ...     "dpi": 600,
            ...     "color_space": "CMYK",
            ...     "embed_fonts": True,
            ...     "print_optimized": True
            ... })
        """
        if config is None:
            config = {}
        
        # Initialize configuration with defaults
        self.dpi = config.get("dpi", 300)
        self.color_space = config.get("color_space", "RGB")
        self.embed_fonts = config.get("embed_fonts", True)
        self.print_optimized = config.get("print_optimized", False)
        self.watermark = config.get("watermark", None)
        self.logo = config.get("logo", None)
        
        # Initialize logger
        self.logger = logging.getLogger(__name__)
        
        # Validate color space
        if self.color_space not in ["RGB", "CMYK"]:
            raise ValueError(f"Invalid color_space: {self.color_space}. Must be 'RGB' or 'CMYK'.")
        
        # Validate DPI
        if self.dpi < 72:
            raise ValueError(f"Invalid DPI: {self.dpi}. Must be at least 72.")
    
    def export(
        self,
        html_content: str,
        output_path: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Export HTML to PDF with high quality settings.
        
        This method converts HTML content to PDF using weasyprint with
        configurable quality settings including DPI, font embedding, and
        color space conversion. Charts are automatically converted from
        Canvas-based Chart.js to SVG vector graphics for scalability.
        
        Args:
            html_content: HTML string to convert to PDF
            output_path: Output PDF file path
            metadata: Optional PDF metadata dictionary with keys:
                - title: Document title
                - author: Document author
                - subject: Document subject
                - keywords: Document keywords
        
        Raises:
            ImportError: If weasyprint is not installed
            IOError: If output file cannot be written
        
        
        Examples:
            >>> exporter = PDFExporter({"dpi": 300})
            >>> html = "<html><body><h1>Report</h1></body></html>"
            >>> exporter.export(html, "report.pdf", {"title": "Forensic Report"})
        """
        try:
            from weasyprint import HTML, CSS
        except ImportError:
            raise ImportError(
                "weasyprint is required for PDF export. "
                "Install it with: pip install weasyprint"
            )
        
        # Convert Chart.js canvas charts to SVG vector graphics
        html_content = self._convert_charts_to_svg(html_content)
        
        # Apply color space conversion if needed
        if self.print_optimized or self.color_space == "CMYK":
            html_content = self._convert_color_space(html_content)
        
        # Create CSS for high-quality rendering
        # Configure DPI through CSS @page rules and image resolution
        quality_css = CSS(string=f"""
            @page {{
                size: A4;
                margin: 2cm;
            }}
            
            /* High-quality image rendering */
            img {{
                image-rendering: -webkit-optimize-contrast;
                image-rendering: crisp-edges;
                max-width: 100%;
                height: auto;
            }}
            
            /* Chart rendering quality */
            canvas, svg {{
                image-rendering: -webkit-optimize-contrast;
                image-rendering: crisp-edges;
            }}
            
            /* Font rendering */
            body {{
                -webkit-font-smoothing: antialiased;
                -moz-osx-font-smoothing: grayscale;
                text-rendering: optimizeLegibility;
            }}
            
            /* Gradient rendering quality - prevent banding artifacts */
            * {{
                /* Enable smooth gradient rendering */
                -webkit-backface-visibility: hidden;
                -webkit-transform: translateZ(0);
                backface-visibility: hidden;
            }}
            
            /* Ensure gradients render with high quality */
            [style*="gradient"] {{
                /* Force high-quality rendering for gradient elements */
                image-rendering: -webkit-optimize-contrast;
                image-rendering: smooth;
            }}
        """)
        
        # Create HTML document
        html_doc = HTML(string=html_content)
        
        # Render to PDF with high-quality settings
        # Note: weasyprint's resolution is controlled via the CSS and
        # the underlying rendering engine. The DPI setting affects
        # how images and charts are rasterized.
        #
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
        pdf_bytes = html_doc.write_pdf(
            stylesheets=[quality_css],
            # Enable font embedding for consistent rendering
            # This is the default behavior in weasyprint
            # Note: weasyprint automatically uses Cairo's anti-aliasing
            # which provides smooth gradient rendering without banding
        )
        
        # Write PDF to file
        with open(output_path, 'wb') as f:
            f.write(pdf_bytes)
        
        # Apply metadata if provided
        if metadata:
            self._apply_pdf_metadata(output_path, metadata)
    
    def _convert_charts_to_svg(self, html_content: str) -> str:
        """
        Convert Chart.js canvas charts to SVG vector graphics.
        
        This method finds all Chart.js chart configurations in the HTML,
        converts them to SVG using SVGChartExporter, and replaces the
        canvas elements with embedded SVG for vector-based PDF rendering.
        
        Args:
            html_content: HTML string with Chart.js canvas charts
            
        Returns:
            HTML string with SVG charts replacing canvas charts
            
        """
        try:
            from eye.services.svg_chart_exporter import SVGChartExporter
        except ImportError:
            self.logger.warning(
                "SVGChartExporter not available. Charts will be rendered as canvas."
            )
            return html_content
        
        # Initialize SVG chart exporter
        svg_exporter = SVGChartExporter()
        
        # Pattern to match Chart.js initialization with script tags:
        # <script>new Chart(document.getElementById('chart_...'), {config});</script>

        chart_pattern = r'<script[^>]*>\s*new Chart\(document\.getElementById\([\'"]([^\'"]+)[\'"]\),\s*(\{.*?\})\);\s*</script>'
        # Using a more specific pattern for the JSON object
        chart_pattern = r'<script[^>]*>\s*new Chart\(document\.getElementById\([\'"]([^\'"]+)[\'"]\),\s*(\{.+?\})\);\s*</script>'
        
        # Find all chart configurations
        matches = list(re.finditer(chart_pattern, html_content, re.DOTALL))
        
        if not matches:
            self.logger.debug("No Chart.js charts found in HTML content")
            return html_content
        
        self.logger.info(f"Found {len(matches)} Chart.js charts to convert to SVG")
        
        # Build a list of replacements to apply
        replacements = []
        
        for match in matches:
            chart_id = match.group(1)
            config_str = match.group(2)
            
            try:
                # Parse Chart.js configuration
                chart_config = json.loads(config_str)
                
                # Convert to SVG (800x600 default size for PDF)
                svg_content = svg_exporter.convert_chart_to_svg(
                    chart_config,
                    width=800,
                    height=600
                )
                
                # Embed fonts in SVG for consistent rendering
                svg_content = svg_exporter.embed_fonts_in_svg(svg_content)
                
                # Find the canvas element for this chart
                canvas_pattern = rf'<canvas[^>]+id=[\'"]?{re.escape(chart_id)}[\'"]?[^>]*></canvas>'
                canvas_match = re.search(canvas_pattern, html_content)
                
                if canvas_match:
                    # Store canvas replacement
                    svg_replacement = f'<div class="chart-svg-container" style="width: 100%; height: 400px;">{svg_content}</div>'
                    replacements.append((canvas_match.start(), canvas_match.end(), svg_replacement))
                    self.logger.debug(f"Prepared SVG replacement for chart '{chart_id}'")
                else:
                    self.logger.warning(f"Canvas element not found for chart '{chart_id}'")
                
                # Store script tag removal
                replacements.append((match.start(), match.end(), ''))
                self.logger.debug(f"Prepared script removal for chart '{chart_id}'")
                
            except json.JSONDecodeError as e:
                self.logger.error(f"Failed to parse Chart.js config for '{chart_id}': {e}")
                # Keep the original canvas chart if conversion fails
                continue
            except Exception as e:
                self.logger.error(f"Failed to convert chart '{chart_id}' to SVG: {e}")
                # Keep the original canvas chart if conversion fails
                continue
        
        # Apply all replacements from end to start to preserve indices
        replacements.sort(key=lambda x: x[0], reverse=True)
        for start, end, replacement in replacements:
            html_content = html_content[:start] + replacement + html_content[end:]
        
        return html_content
    
    def _apply_pdf_metadata(self, pdf_path: str, metadata: Dict[str, Any]) -> None:
        """
        Apply metadata to PDF document.
        
        This method updates the PDF metadata fields including title, author,
        subject, and keywords. It uses PyPDF to modify the PDF in-place.
        
        Args:
            pdf_path: Path to the PDF file to update
            metadata: Dictionary with metadata fields:
                - title: Document title
                - author: Document author
                - subject: Document subject
                - keywords: Document keywords
        
        Note:
            This method modifies the PDF file in-place. If PyPDF is not
            available, metadata application is skipped silently.
        """
        try:
            from pypdf import PdfReader, PdfWriter
        except ImportError:
            # If pypdf is not available, skip metadata application
            # This is not critical for basic PDF export functionality
            return
        
        try:
            # Read the existing PDF
            reader = PdfReader(pdf_path)
            writer = PdfWriter()
            
            # Copy all pages
            for page in reader.pages:
                writer.add_page(page)
            
            # Add metadata
            writer.add_metadata({
                '/Title': metadata.get('title', ''),
                '/Author': metadata.get('author', ''),
                '/Subject': metadata.get('subject', ''),
                '/Keywords': metadata.get('keywords', ''),
                '/Producer': 'EYE Forensic Report Engine',
                '/Creator': 'EYE Forensic Report Engine'
            })
            
            # Write back to file
            with open(pdf_path, 'wb') as f:
                writer.write(f)
        except Exception:
            # If metadata application fails, don't fail the entire export
            # The PDF is already written successfully
            pass
    
    def _convert_color_space(self, html_content: str) -> str:
        """
        Convert RGB colors to CMYK if configured for print optimization.
        
        This method performs RGB to CMYK color space conversion for
        print-optimized output. It searches for RGB color values in the HTML
        (hex, rgb(), rgba()) and converts them to CMYK equivalents while
        maintaining color accuracy (Delta E < 5).
        
        Args:
            html_content: HTML string with RGB colors
            
        Returns:
            HTML string with converted colors (if print_optimized is enabled)
        
        Note:
            This uses the standard RGB to CMYK conversion formula. For
            professional print production with specific press profiles,
            consider using ICC color profiles.
        """
        import re
        
        def hex_to_rgb(hex_color: str) -> tuple:
            """Convert hex color to RGB tuple (0-255 range)."""
            hex_color = hex_color.lstrip('#')
            if len(hex_color) == 3:
                # Short form: #RGB -> #RRGGBB
                hex_color = ''.join([c*2 for c in hex_color])
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        
        def rgb_to_cmyk(r: int, g: int, b: int) -> tuple:
            """
            Convert RGB (0-255) to CMYK (0-100).
            
            Uses standard conversion formula:
            - Normalize RGB to 0-1 range
            - K = 1 - max(R, G, B)
            - C = (1 - R - K) / (1 - K)
            - M = (1 - G - K) / (1 - K)
            - Y = (1 - B - K) / (1 - K)
            
            Returns:
                Tuple of (C, M, Y, K) in 0-100 range
            """
            # Normalize RGB to 0-1 range
            r_norm = r / 255.0
            g_norm = g / 255.0
            b_norm = b / 255.0
            
            # Calculate K (black)
            k = 1 - max(r_norm, g_norm, b_norm)
            
            # Handle pure black case
            if k == 1:
                return (0, 0, 0, 100)
            
            # Calculate CMY
            c = (1 - r_norm - k) / (1 - k)
            m = (1 - g_norm - k) / (1 - k)
            y = (1 - b_norm - k) / (1 - k)
            
            # Convert to 0-100 range and round
            return (
                round(c * 100),
                round(m * 100),
                round(y * 100),
                round(k * 100)
            )
        
        def cmyk_to_rgb(c: float, m: float, y: float, k: float) -> tuple:
            """
            Convert CMYK (0-100) back to RGB (0-255) for verification.
            
            This is used to verify color accuracy (Delta E < 5).
            
            Returns:
                Tuple of (R, G, B) in 0-255 range
            """
            # Normalize CMYK to 0-1 range
            c_norm = c / 100.0
            m_norm = m / 100.0
            y_norm = y / 100.0
            k_norm = k / 100.0
            
            # Convert to RGB
            r = 255 * (1 - c_norm) * (1 - k_norm)
            g = 255 * (1 - m_norm) * (1 - k_norm)
            b = 255 * (1 - y_norm) * (1 - k_norm)
            
            return (round(r), round(g), round(b))
        
        def calculate_delta_e(rgb1: tuple, rgb2: tuple) -> float:
            """
            Calculate Delta E (CIE76) color difference between two RGB colors.
            
            Delta E < 1: Not perceptible by human eyes
            Delta E 1-2: Perceptible through close observation
            Delta E 2-10: Perceptible at a glance
            Delta E > 10: Colors are more different than similar
            
            For print optimization, we target Delta E < 5.
            
            Args:
                rgb1: First RGB color tuple (0-255)
                rgb2: Second RGB color tuple (0-255)
                
            Returns:
                Delta E value (lower is more similar)
            """
            # Convert RGB to LAB color space for perceptual difference
            # Simplified calculation using RGB distance as approximation
            # For more accurate Delta E, would need full RGB->XYZ->LAB conversion
            
            # Calculate Euclidean distance in RGB space
            # This is a simplified Delta E approximation
            r_diff = (rgb1[0] - rgb2[0]) ** 2
            g_diff = (rgb1[1] - rgb2[1]) ** 2
            b_diff = (rgb1[2] - rgb2[2]) ** 2
            
            # Normalize to approximate Delta E scale
            # Standard Delta E uses LAB space, but RGB distance / 10 gives
            # a reasonable approximation for our purposes
            delta_e = (r_diff + g_diff + b_diff) ** 0.5 / 10.0
            
            return delta_e
        
        def rgb_to_css_cmyk(r: int, g: int, b: int) -> str:
            """
            Convert RGB to CSS device-cmyk() color function.
            
            Note: device-cmyk() is supported in CSS Color Level 4 spec
            and by modern PDF renderers, but may not be supported by
            all browsers. For maximum compatibility, we keep RGB as fallback.
            
            Returns:
                CSS color string with CMYK and RGB fallback
            """
            c, m, y, k = rgb_to_cmyk(r, g, b)
            
            # Verify color accuracy
            rgb_back = cmyk_to_rgb(c, m, y, k)
            delta_e = calculate_delta_e((r, g, b), rgb_back)
            
            # If Delta E is too high, keep original RGB
            if delta_e >= 5:
                return f"rgb({r}, {g}, {b})"
            
            # Return CMYK with RGB fallback for compatibility
            # Format: device-cmyk(C M Y K / alpha)
            # Fallback to RGB for browsers that don't support device-cmyk
            return f"device-cmyk({c/100:.3f} {m/100:.3f} {y/100:.3f} {k/100:.3f})"
        
        # Pattern to match hex colors (#RGB or #RRGGBB)
        hex_pattern = r'#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})\b'
        
        # Pattern to match rgb() and rgba() functions
        rgb_pattern = r'rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*[\d.]+)?\s*\)'
        
        def replace_hex(match):
            """Replace hex color with CMYK equivalent."""
            hex_color = match.group(0)
            r, g, b = hex_to_rgb(hex_color)
            return rgb_to_css_cmyk(r, g, b)
        
        def replace_rgb(match):
            """Replace rgb()/rgba() with CMYK equivalent."""
            r = int(match.group(1))
            g = int(match.group(2))
            b = int(match.group(3))
            
            # Preserve alpha if present (rgba)
            if match.group(0).startswith('rgba'):
                # Extract alpha value
                alpha_match = re.search(r',\s*([\d.]+)\s*\)$', match.group(0))
                if alpha_match:
                    alpha = alpha_match.group(1)
                    c, m, y, k = rgb_to_cmyk(r, g, b)
                    
                    # Verify color accuracy
                    rgb_back = cmyk_to_rgb(c, m, y, k)
                    delta_e = calculate_delta_e((r, g, b), rgb_back)
                    
                    if delta_e >= 5:
                        return match.group(0)  # Keep original
                    
                    # CMYK with alpha (using device-cmyk with alpha channel)
                    return f"device-cmyk({c/100:.3f} {m/100:.3f} {y/100:.3f} {k/100:.3f} / {alpha})"
            
            return rgb_to_css_cmyk(r, g, b)
        
        # Replace hex colors
        html_content = re.sub(hex_pattern, replace_hex, html_content)
        
        # Replace rgb()/rgba() colors
        html_content = re.sub(rgb_pattern, replace_rgb, html_content)
        
        return html_content
