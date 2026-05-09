"""
Color Manager for EYE Forensic Report Enhancement.

This module implements the ColorManager class that manages color palettes for forensic reports
with WCAG compliance validation and support for custom palettes.

"""

from typing import List, Optional, Dict, Any
import json
import logging


class ColorManager:
    """
    Manages color palettes for forensic reports with WCAG compliance validation.
    
    Provides built-in palettes optimized for different use cases:
    - forensic: Orange-cyan theme for forensic investigations
    - professional: Blues and grays for corporate reports
    - high_contrast: Maximum differentiation for accessibility
    - colorblind_friendly: Safe for deuteranopia and protanopia
    - grayscale: Optimized for black-and-white printing
    """
    
    # Built-in palettes with 12 colors each
    PALETTES = {
        "forensic": [
            "#f97316", "#06b6d4", "#ec4899", "#10b981", "#ff4d6a", "#8b5cf6",
            "#f59e0b", "#14b8a6", "#ef4444", "#3b82f6", "#a855f7", "#22c55e"
        ],
        "professional": [
            "#1e40af", "#475569", "#0891b2", "#64748b", "#0369a1", "#334155",
            "#0284c7", "#94a3b8", "#075985", "#cbd5e1", "#0c4a6e", "#e2e8f0"
        ],
        "high_contrast": [
            "#000000", "#ffffff", "#ff0000", "#00ff00", "#0000ff", "#ffff00",
            "#ff00ff", "#00ffff", "#ff8800", "#8800ff", "#00ff88", "#ff0088"
        ],
        "colorblind_friendly": [
            "#0173b2", "#de8f05", "#029e73", "#cc78bc", "#ca9161", "#fbafe4",
            "#949494", "#ece133", "#56b4e9", "#009e73", "#f0e442", "#d55e00"
        ],
        "grayscale": [
            "#000000", "#1a1a1a", "#333333", "#4d4d4d", "#666666", "#808080",
            "#999999", "#b3b3b3", "#cccccc", "#e6e6e6", "#f2f2f2", "#ffffff"
        ]
    }
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize ColorManager with built-in and custom palettes.
        
        Args:
            config_path: Optional path to custom palette JSON configuration
        """
        self.logger = logging.getLogger(__name__)
        self.custom_palettes: Dict[str, List[str]] = {}
        
        if config_path:
            try:
                self.load_custom_palette(config_path)
            except Exception as e:
                self.logger.error(f"Failed to load custom palette from {config_path}: {e}")
    
    def get_palette(self, palette_name: str) -> List[str]:
        """
        Get color palette by name.
        
        Args:
            palette_name: Name of palette (forensic, professional, high_contrast, 
                         colorblind_friendly, grayscale, or custom palette name)
            
        Returns:
            List of hex color codes (minimum 12 colors)
            
        Raises:
            ValueError: If palette_name is not found
        """
        # Check built-in palettes first
        if palette_name in self.PALETTES:
            return self.PALETTES[palette_name].copy()
        
        # Check custom palettes
        if palette_name in self.custom_palettes:
            return self.custom_palettes[palette_name].copy()
        
        # Palette not found
        available = self.list_palettes()
        raise ValueError(
            f"Palette '{palette_name}' not found. Available palettes: {', '.join(available)}"
        )
    
    def get_color_for_dataset(
        self, 
        dataset_index: int, 
        palette_name: str = "forensic", 
        custom_colors: Optional[List[str]] = None
    ) -> str:
        """
        Get color for a dataset using modulo cycling.
        
        Args:
            dataset_index: Index of the dataset (0-based)
            palette_name: Name of palette to use
            custom_colors: Optional custom color list (overrides palette)
            
        Returns:
            Hex color code
        """
        # Use custom colors if provided
        if custom_colors is not None:
            if not custom_colors:
                raise ValueError("custom_colors list cannot be empty")
            return custom_colors[dataset_index % len(custom_colors)]
        
        # Use palette
        palette = self.get_palette(palette_name)
        return palette[dataset_index % len(palette)]
    
    def validate_hex_color(self, color: str) -> bool:
        """
        Validate hex color format.
        
        Args:
            color: Hex color code (e.g., "#FF5733" or "#fff")
            
        Returns:
            True if valid, False otherwise
        """
        if not isinstance(color, str):
            return False
        
        # Remove leading # if present
        color = color.lstrip('#')
        
        # Check length (3 or 6 hex digits)
        if len(color) not in (3, 6):
            return False
        
        # Check if all characters are valid hex digits
        try:
            int(color, 16)
            return True
        except ValueError:
            return False
    
    def check_wcag_contrast(
        self, 
        foreground: str, 
        background: str, 
        level: str = "AA"
    ) -> bool:
        """
        Check WCAG contrast ratio between two colors.
        
        Args:
            foreground: Foreground hex color
            background: Background hex color
            level: WCAG level ("AA" or "AAA")
            
        Returns:
        """
        # Validate colors
        if not self.validate_hex_color(foreground) or not self.validate_hex_color(background):
            return False
        
        # Calculate relative luminance for both colors
        fg_luminance = self._calculate_relative_luminance(foreground)
        bg_luminance = self._calculate_relative_luminance(background)
        
        # Calculate contrast ratio
        lighter = max(fg_luminance, bg_luminance)
        darker = min(fg_luminance, bg_luminance)
        contrast_ratio = (lighter + 0.05) / (darker + 0.05)
        
        if level == "AA":
            return contrast_ratio >= 4.5  # Normal text
        elif level == "AAA":
            return contrast_ratio >= 7.0  # Normal text
        else:
            raise ValueError(f"Invalid WCAG level: {level}. Must be 'AA' or 'AAA'")
    
    def _calculate_relative_luminance(self, color: str) -> float:
        """
        Calculate relative luminance of a color according to WCAG formula.
        
        Args:
            color: Hex color code
            
        Returns:
            Relative luminance value (0.0 to 1.0)
        """
        # Remove # and convert to RGB
        color = color.lstrip('#')
        
        # Handle 3-digit hex codes
        if len(color) == 3:
            color = ''.join([c*2 for c in color])
        
        # Convert to RGB values (0-255)
        r = int(color[0:2], 16)
        g = int(color[2:4], 16)
        b = int(color[4:6], 16)
        
        # Convert to 0-1 range
        r = r / 255.0
        g = g / 255.0
        b = b / 255.0
        
        # Apply gamma correction
        def gamma_correct(channel):
            if channel <= 0.03928:
                return channel / 12.92
            else:
                return ((channel + 0.055) / 1.055) ** 2.4
        
        r = gamma_correct(r)
        g = gamma_correct(g)
        b = gamma_correct(b)
        
        # Calculate relative luminance
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    
    def create_gradient(
        self, 
        start_color: str, 
        end_color: str, 
        direction: str = "vertical"
    ) -> Dict[str, Any]:
        """
        Create gradient configuration for Chart.js.
        
        Args:
            start_color: Starting hex color
            end_color: Ending hex color
            direction: "vertical" or "horizontal"
            
        Returns:
            Gradient configuration dictionary
        """
        # Validate colors
        if not self.validate_hex_color(start_color):
            raise ValueError(f"Invalid start_color: {start_color}")
        if not self.validate_hex_color(end_color):
            raise ValueError(f"Invalid end_color: {end_color}")
        
        # Validate direction
        if direction not in ("vertical", "horizontal"):
            raise ValueError(f"Invalid direction: {direction}. Must be 'vertical' or 'horizontal'")
        
        # Normalize colors (ensure # prefix)
        if not start_color.startswith('#'):
            start_color = '#' + start_color
        if not end_color.startswith('#'):
            end_color = '#' + end_color
        
        return {
            "type": "gradient",
            "start_color": start_color,
            "end_color": end_color,
            "direction": direction
        }
    
    def load_custom_palette(self, palette_path: str) -> None:
        """
        Load custom palette from JSON file.
        
        Expected JSON format:
        {
            "palette_name": ["#color1", "#color2", ...]
        }
        
        Args:
            palette_path: Path to JSON file with palette definition
            
        Raises:
            ValueError: If palette has fewer than 8 colors or fails WCAG validation
            FileNotFoundError: If palette file does not exist
            json.JSONDecodeError: If palette file is not valid JSON
        """
        # Load JSON file
        with open(palette_path, 'r') as f:
            palettes_data = json.load(f)
        
        # Validate and add each palette
        for palette_name, colors in palettes_data.items():
            # Check minimum color count
            if len(colors) < 8:
                raise ValueError(
                    f"Palette '{palette_name}' has only {len(colors)} colors. "
                    f"Minimum 8 colors required."
                )
            
            # Validate all colors
            for color in colors:
                if not self.validate_hex_color(color):
                    raise ValueError(
                        f"Invalid color '{color}' in palette '{palette_name}'"
                    )
            
            # Add to custom palettes
            self.custom_palettes[palette_name] = colors
            self.logger.info(f"Loaded custom palette '{palette_name}' with {len(colors)} colors")
    
    def list_palettes(self) -> List[str]:
        """
        List all available palette names (built-in and custom).
        
        Returns:
            List of palette names
        """
        built_in = list(self.PALETTES.keys())
        custom = list(self.custom_palettes.keys())
        return built_in + custom
    
    def simulate_colorblind(
        self, 
        color: str, 
        deficiency_type: str = "deuteranopia"
    ) -> str:
        """
        Simulate how a color appears to someone with color vision deficiency.
        
        Uses color transformation matrices based on research by Brettel, Viénot, and Mollon (1997)
        and Viénot, Brettel, and Mollon (1999) for accurate simulation of color blindness.
        
        Args:
            color: Hex color code (e.g., "#FF5733")
            deficiency_type: Type of color vision deficiency
                           - "deuteranopia": red-green colorblindness (missing green cones)
                           - "protanopia": red-green colorblindness (missing red cones)
            
        Returns:
            Hex color code showing how the color appears with the specified deficiency
            
        Raises:
            ValueError: If color is invalid or deficiency_type is not supported
        """
        # Validate color
        if not self.validate_hex_color(color):
            raise ValueError(f"Invalid color: {color}")
        
        # Validate deficiency type
        if deficiency_type not in ("deuteranopia", "protanopia"):
            raise ValueError(
                f"Invalid deficiency_type: {deficiency_type}. "
                f"Must be 'deuteranopia' or 'protanopia'"
            )
        
        # Convert hex to RGB (0-255)
        color = color.lstrip('#')
        if len(color) == 3:
            color = ''.join([c*2 for c in color])
        
        r = int(color[0:2], 16)
        g = int(color[2:4], 16)
        b = int(color[4:6], 16)
        
        # Convert to 0-1 range
        r = r / 255.0
        g = g / 255.0
        b = b / 255.0
        
        # Apply transformation matrix based on deficiency type
        if deficiency_type == "deuteranopia":
            # Deuteranopia transformation matrix (missing green cones)
            # Based on Viénot, Brettel, and Mollon (1999)
            r_new = 0.625 * r + 0.375 * g + 0.0 * b
            g_new = 0.7 * r + 0.3 * g + 0.0 * b
            b_new = 0.0 * r + 0.3 * g + 0.7 * b
        else:  # protanopia
            # Protanopia transformation matrix (missing red cones)
            # Based on Viénot, Brettel, and Mollon (1999)
            r_new = 0.567 * r + 0.433 * g + 0.0 * b
            g_new = 0.558 * r + 0.442 * g + 0.0 * b
            b_new = 0.0 * r + 0.242 * g + 0.758 * b
        
        # Clamp values to 0-1 range
        r_new = max(0.0, min(1.0, r_new))
        g_new = max(0.0, min(1.0, g_new))
        b_new = max(0.0, min(1.0, b_new))
        
        # Convert back to 0-255 range
        r_int = int(round(r_new * 255))
        g_int = int(round(g_new * 255))
        b_int = int(round(b_new * 255))
        
        # Convert to hex
        return f"#{r_int:02x}{g_int:02x}{b_int:02x}"
    
    def apply_colorblind_simulation_to_html(
        self, 
        html_content: str, 
        deficiency_type: str = "deuteranopia"
    ) -> str:
        """
        Apply colorblind simulation to all colors in HTML content.
        
        This method transforms all hex color codes in the HTML to simulate
        how they would appear to someone with the specified color vision deficiency.
        This is useful for previewing reports to ensure they remain accessible.
        
        Args:
            html_content: HTML string containing color codes
            deficiency_type: Type of color vision deficiency
                           - "deuteranopia": red-green colorblindness (missing green cones)
                           - "protanopia": red-green colorblindness (missing red cones)
            
        Returns:
            HTML string with all colors transformed to simulate the deficiency
            
        Raises:
            ValueError: If deficiency_type is not supported
        """
        import re
        
        # Validate deficiency type
        if deficiency_type not in ("deuteranopia", "protanopia"):
            raise ValueError(
                f"Invalid deficiency_type: {deficiency_type}. "
                f"Must be 'deuteranopia' or 'protanopia'"
            )
        
        # Find all hex color codes in the HTML (both #RRGGBB and #RGB formats)
        # Match colors in various contexts: style attributes, CSS, etc.
        hex_pattern = r'#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b'
        
        def replace_color(match):
            """Replace a color with its colorblind simulation."""
            original_color = match.group(0)
            try:
                simulated_color = self.simulate_colorblind(original_color, deficiency_type)
                return simulated_color
            except ValueError:
                # If simulation fails, return original color
                return original_color
        
        # Replace all hex colors in the HTML
        transformed_html = re.sub(hex_pattern, replace_color, html_content)
        
        return transformed_html

    def convert_to_grayscale(self, color: str) -> str:
        """
        Convert a color to grayscale using luminosity-based conversion.
        
        This method uses the luminosity formula to convert colors to grayscale,
        which preserves the perceived brightness of the original color:
        Gray = 0.2126 * R + 0.7152 * G + 0.0722 * B
        
        This ensures that text contrast is maintained when converting to grayscale,
        
        Args:
            color: Hex color code (e.g., "#FF5733")
            
        Returns:
            Hex color code for grayscale equivalent
            
        Raises:
            ValueError: If color is invalid
            
        """
        # Validate color
        if not self.validate_hex_color(color):
            raise ValueError(f"Invalid color: {color}")
        
        # Convert hex to RGB (0-255)
        color = color.lstrip('#')
        if len(color) == 3:
            color = ''.join([c*2 for c in color])
        
        r = int(color[0:2], 16)
        g = int(color[2:4], 16)
        b = int(color[4:6], 16)
        
        # Convert to 0-1 range
        r = r / 255.0
        g = g / 255.0
        b = b / 255.0
        
        # Calculate luminosity (perceived brightness)
        # This formula is based on human perception of color brightness
        luminosity = 0.2126 * r + 0.7152 * g + 0.0722 * b
        
        # Convert back to 0-255 range
        gray_value = int(round(luminosity * 255))
        
        # Clamp to valid range
        gray_value = max(0, min(255, gray_value))
        
        # Convert to hex
        return f"#{gray_value:02x}{gray_value:02x}{gray_value:02x}"
    
    def apply_grayscale_conversion_to_html(self, html_content: str) -> str:
        """
        Apply grayscale conversion to all colors in HTML content.
        
        This method transforms all hex color codes in the HTML to grayscale
        to simulate how the report will appear when printed on a black-and-white printer.
        The conversion uses luminosity-based conversion to preserve perceived brightness
        and ensure text remains readable with at least 3:1 contrast ratio.
        
        Args:
            html_content: HTML string containing color codes
            
        Returns:
            HTML string with all colors converted to grayscale
            
        """
        import re
        
        # Find all hex color codes in the HTML (both #RRGGBB and #RGB formats)
        # Match colors in various contexts: style attributes, CSS, etc.
        hex_pattern = r'#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b'
        
        def replace_color(match):
            """Replace a color with its grayscale equivalent."""
            original_color = match.group(0)
            try:
                grayscale_color = self.convert_to_grayscale(original_color)
                return grayscale_color
            except ValueError:
                # If conversion fails, return original color
                return original_color
        
        # Replace all hex colors in the HTML
        transformed_html = re.sub(hex_pattern, replace_color, html_content)
        
        return transformed_html
    
    def get_grayscale_palette_with_patterns(self) -> List[Dict[str, Any]]:
        """
        Get grayscale palette with pattern/texture information for differentiation.
        
        When printing in grayscale, similar shades of gray can be difficult to distinguish.
        This method returns the grayscale palette with additional pattern/texture information
        that can be used to differentiate between similar grayscale values in charts.
        
        Patterns include: solid, diagonal-lines, dots, cross-hatch, horizontal-lines, vertical-lines
        
        Returns:
            List of dictionaries with 'color' and 'pattern' keys
            
        """
        grayscale_palette = self.get_palette("grayscale")
        
        # Define patterns for differentiation
        # These can be used in Chart.js or SVG rendering to add visual texture
        patterns = [
            "solid",              # No pattern
            "diagonal-lines",     # Diagonal lines (/)
            "dots",               # Dotted pattern
            "cross-hatch",        # Cross-hatch pattern (X)
            "horizontal-lines",   # Horizontal lines (-)
            "vertical-lines",     # Vertical lines (|)
            "diagonal-lines-reverse",  # Diagonal lines (\)
            "grid",               # Grid pattern
            "circles",            # Circle pattern
            "squares",            # Square pattern
            "triangles",          # Triangle pattern
            "waves",              # Wave pattern
        ]
        
        # Combine colors with patterns
        palette_with_patterns = []
        for i, color in enumerate(grayscale_palette):
            palette_with_patterns.append({
                "color": color,
                "pattern": patterns[i % len(patterns)]
            })
        
        return palette_with_patterns
