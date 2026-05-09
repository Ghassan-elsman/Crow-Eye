"""
Heatmap Renderer for EYE Forensic Assistant.

This module implements the HeatmapRenderer class that renders heatmap visualizations
for intensity/frequency data in forensic reports.

"""

from typing import Dict, Any, List, Tuple
import json


class HeatmapRenderer:
    """
    Renders heatmap visualizations with intensity gradient mapping.
    """
    
    # Color schemes for heatmaps
    COLOR_SCHEMES = {
        "sequential": {
            "start": "#0a0c10",  # Dark
            "end": "#f97316"     # Orange
        },
        "diverging": {
            "start": "#06b6d4",  # Cyan
            "middle": "#0a0c10", # Dark
            "end": "#f97316"     # Orange
        },
        "thermal": {
            "start": "#ff0000",  # Red
            "middle": "#ffff00", # Yellow
            "end": "#ffffff"     # White
        }
    }
    
    def __init__(self):
        """Initialize HeatmapRenderer."""
        pass
    
    def render_heatmap(
        self,
        title: str,
        x_labels: List[str],
        y_labels: List[str],
        intensity_values: List[List[float]],
        color_scheme: str = "sequential"
    ) -> Dict[str, Any]:
        """
        Render heatmap visualization configuration.
        
        Args:
            title: Heatmap title
            x_labels: List of X-axis labels
            y_labels: List of Y-axis labels
            intensity_values: 2D array of intensity values
            color_scheme: Color scheme (sequential, diverging, thermal)
            
        Returns:
            Heatmap configuration dictionary for rendering
            
        """
        # Validate color scheme
        if color_scheme not in self.COLOR_SCHEMES:
            color_scheme = "sequential"
        
        # Calculate min and max intensity values
        flat_values = [val for row in intensity_values for val in row]
        min_intensity = min(flat_values) if flat_values else 0
        max_intensity = max(flat_values) if flat_values else 1
        
        # Build heatmap data structure
        heatmap_data = {
            "title": title,
            "x_labels": x_labels,
            "y_labels": y_labels,
            "intensity_values": intensity_values,
            "color_scheme": color_scheme,
            "min_intensity": min_intensity,
            "max_intensity": max_intensity,
            "colors": self.COLOR_SCHEMES[color_scheme]
        }
        
        return heatmap_data
    
    def map_intensity_to_color(
        self,
        intensity: float,
        min_intensity: float,
        max_intensity: float,
        color_scheme: str = "sequential"
    ) -> str:
        """
        Map intensity value to color using gradient interpolation.
        
        Args:
            intensity: Intensity value to map
            min_intensity: Minimum intensity in dataset
            max_intensity: Maximum intensity in dataset
            color_scheme: Color scheme to use
            
        Returns:
            Hex color code
            
        """
        # Normalize intensity to 0-1 range
        if max_intensity == min_intensity:
            normalized = 0.5
        else:
            normalized = (intensity - min_intensity) / (max_intensity - min_intensity)
        
        # Clamp normalized value to 0-1 range to handle out-of-bounds values
        normalized = max(0.0, min(1.0, normalized))
        
        # Get color scheme
        scheme = self.COLOR_SCHEMES.get(color_scheme, self.COLOR_SCHEMES["sequential"])
        
        # Interpolate color based on scheme type
        if "middle" in scheme:
            # Diverging or thermal scheme (3 colors)
            if normalized < 0.5:
                # Interpolate between start and middle
                return self._interpolate_color(
                    scheme["start"],
                    scheme["middle"],
                    normalized * 2
                )
            else:
                # Interpolate between middle and end
                return self._interpolate_color(
                    scheme["middle"],
                    scheme["end"],
                    (normalized - 0.5) * 2
                )
        else:
            # Sequential scheme (2 colors)
            return self._interpolate_color(
                scheme["start"],
                scheme["end"],
                normalized
            )
    
    def _interpolate_color(
        self,
        start_color: str,
        end_color: str,
        ratio: float
    ) -> str:
        """
        Interpolate between two hex colors.
        
        Args:
            start_color: Starting hex color
            end_color: Ending hex color
            ratio: Interpolation ratio (0-1)
            
        Returns:
            Interpolated hex color
        """
        # Clamp ratio to 0-1 range
        ratio = max(0.0, min(1.0, ratio))
        
        # Parse hex colors
        start_rgb = self._hex_to_rgb(start_color)
        end_rgb = self._hex_to_rgb(end_color)
        
        # Interpolate each channel
        r = int(start_rgb[0] + (end_rgb[0] - start_rgb[0]) * ratio)
        g = int(start_rgb[1] + (end_rgb[1] - start_rgb[1]) * ratio)
        b = int(start_rgb[2] + (end_rgb[2] - start_rgb[2]) * ratio)
        
        # Clamp RGB values to valid range
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))
        
        # Convert back to hex
        return f"#{r:02x}{g:02x}{b:02x}"
    
    def _hex_to_rgb(self, hex_color: str) -> Tuple[int, int, int]:
        """
        Convert hex color to RGB tuple.
        
        Args:
            hex_color: Hex color string (e.g., "#ff5733")
            
        Returns:
            RGB tuple (r, g, b)
        """
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    def generate_html(self, heatmap_data: Dict[str, Any]) -> str:
        """
        Generate HTML representation of heatmap.
        
        Args:
            heatmap_data: Heatmap configuration from render_heatmap
            
        Returns:
            HTML string for heatmap visualization
        """
        title = heatmap_data.get("title", "Heatmap")
        x_labels = heatmap_data.get("x_labels", [])
        y_labels = heatmap_data.get("y_labels", [])
        intensity_values = heatmap_data.get("intensity_values", [])
        color_scheme = heatmap_data.get("color_scheme", "sequential")
        min_intensity = heatmap_data.get("min_intensity", 0)
        max_intensity = heatmap_data.get("max_intensity", 1)
        
        # Build heatmap grid HTML
        grid_html = []
        
        # Add header row with x-labels
        header_row = '<div class="heatmap-row"><div class="heatmap-cell heatmap-header"></div>'
        for x_label in x_labels:
            header_row += f'<div class="heatmap-cell heatmap-header">{self._escape_html(x_label)}</div>'
        header_row += '</div>'
        grid_html.append(header_row)
        
        # Add data rows
        for i, y_label in enumerate(y_labels):
            row_html = f'<div class="heatmap-row"><div class="heatmap-cell heatmap-header">{self._escape_html(y_label)}</div>'
            
            if i < len(intensity_values):
                for j, intensity in enumerate(intensity_values[i]):
                    color = self.map_intensity_to_color(
                        intensity,
                        min_intensity,
                        max_intensity,
                        color_scheme
                    )
                    row_html += f'<div class="heatmap-cell heatmap-data" style="background-color: {color};" title="{intensity}">{intensity:.2f}</div>'
            
            row_html += '</div>'
            grid_html.append(row_html)
        
        html = f"""
        <div class="heatmap-container">
            <h3 class="heatmap-title">{self._escape_html(title)}</h3>
            <div class="heatmap-grid">
                {''.join(grid_html)}
            </div>
            <div class="heatmap-legend">
                <span>Min: {min_intensity:.2f}</span>
                <span>Max: {max_intensity:.2f}</span>
                <span>Scheme: {color_scheme}</span>
            </div>
        </div>
        """
        
        return html
    
    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#x27;")
