"""
Chart Renderer for EYE Forensic Report Enhancement.

This module implements the ChartRenderer class that generates Chart.js configurations
for various chart types with color customization, annotations, and reference lines.

"""

from typing import Dict, Any, List, Optional
import logging
from eye.services.color_manager import ColorManager
from eye.models.report_blocks import ChartBlock


class ChartRenderer:
    """
    Renders Chart.js configurations for various chart types with color customization.
    
    Supports chart types: bar, line, pie, doughnut, radar, scatter, horizontalBar
    """
    
    SUPPORTED_CHART_TYPES = [
        "bar", "line", "pie", "doughnut", "radar", "scatter", "horizontalBar"
    ]
    
    def __init__(self, color_manager: Optional[ColorManager] = None):
        """
        Initialize ChartRenderer with a ColorManager.
        
        Args:
            color_manager: Optional ColorManager instance. If None, creates a new one.
        """
        self.logger = logging.getLogger(__name__)
        self.color_manager = color_manager if color_manager else ColorManager()
    
    def render_chart_config(self, chart_block: ChartBlock) -> Dict[str, Any]:
        """
        Render Chart.js configuration from a ChartBlock.
        
        Args:
            chart_block: ChartBlock instance with chart data and configuration
            
        Returns:
            Dictionary containing Chart.js configuration
            
        Raises:
            ValueError: If chart_type is not supported
        
        """
        # Validate chart type
        if chart_block.chart_type not in self.SUPPORTED_CHART_TYPES:
            raise ValueError(
                f"Unsupported chart type: '{chart_block.chart_type}'. "
                f"Supported types: {', '.join(self.SUPPORTED_CHART_TYPES)}"
            )
        
        # Build base configuration
        config = {
            "type": chart_block.chart_type,
            "data": {
                "labels": chart_block.labels,
                "datasets": self._render_datasets(chart_block)
            },
            "options": self._render_options(chart_block)
        }
        
        return config
    
    def _render_datasets(self, chart_block: ChartBlock) -> List[Dict[str, Any]]:
        """
        Render datasets with color assignments.
        
        Args:
            chart_block: ChartBlock instance
            
        Returns:
            List of dataset dictionaries with colors applied
        """
        rendered_datasets = []
        
        for idx, dataset in enumerate(chart_block.datasets):
            rendered_dataset = dataset.copy()
            
            # Apply colors
            color = self._get_dataset_color(idx, chart_block)
            
            # Apply color based on chart type
            if chart_block.chart_type in ["line", "radar"]:
                rendered_dataset["borderColor"] = color
                rendered_dataset["backgroundColor"] = self._add_transparency(color, 0.2)
            elif chart_block.chart_type in ["bar", "horizontalBar"]:
                rendered_dataset["backgroundColor"] = color
                rendered_dataset["borderColor"] = color
            elif chart_block.chart_type in ["pie", "doughnut"]:
                # For pie/doughnut, each data point gets a different color
                if "backgroundColor" not in rendered_dataset:
                    rendered_dataset["backgroundColor"] = [
                        self._get_dataset_color(i, chart_block) 
                        for i in range(len(dataset.get("data", [])))
                    ]
            elif chart_block.chart_type == "scatter":
                rendered_dataset["backgroundColor"] = color
                rendered_dataset["borderColor"] = color
            
            # Apply gradient if configured
            if chart_block.gradient_config:
                rendered_dataset["backgroundColor"] = self._apply_gradient(
                    chart_block.gradient_config
                )
            
            rendered_datasets.append(rendered_dataset)
        
        return rendered_datasets
    
    def _get_dataset_color(self, dataset_index: int, chart_block: ChartBlock) -> str:
        """
        Get color for a dataset based on chart configuration.
        
        Args:
            dataset_index: Index of the dataset
            chart_block: ChartBlock instance
            
        Returns:
            Hex color code
        """
        # Use custom colors if provided (overrides palette)
        if chart_block.custom_colors:
            return self.color_manager.get_color_for_dataset(
                dataset_index=dataset_index,
                custom_colors=chart_block.custom_colors
            )
        
        # Use color scheme (palette)
        palette_name = chart_block.color_scheme or "forensic"
        return self.color_manager.get_color_for_dataset(
            dataset_index=dataset_index,
            palette_name=palette_name
        )
    
    def _render_options(self, chart_block: ChartBlock) -> Dict[str, Any]:
        """
        Render Chart.js options including legend, annotations, and reference lines.
        
        Args:
            chart_block: ChartBlock instance
            
        Returns:
            Options dictionary for Chart.js
        """
        options = {
            "responsive": True,
            "maintainAspectRatio": True,
            "plugins": {
                "title": {
                    "display": bool(chart_block.title),
                    "text": chart_block.title
                },
                "legend": self._render_legend(chart_block)
            }
        }
        
        # Add annotations if present
        if chart_block.annotations:
            options["plugins"]["annotation"] = {
                "annotations": self._render_annotations(chart_block.annotations)
            }
        
        # Add reference lines if present
        if chart_block.reference_lines:
            if "annotation" not in options["plugins"]:
                options["plugins"]["annotation"] = {"annotations": {}}
            
            ref_line_annotations = self._render_reference_lines(chart_block.reference_lines)
            options["plugins"]["annotation"]["annotations"].update(ref_line_annotations)
        
        return options
    
    def _render_legend(self, chart_block: ChartBlock) -> Dict[str, Any]:
        """
        Render legend configuration.
        
        Args:
            chart_block: ChartBlock instance
            
        Returns:
            Legend configuration dictionary
        
        """
        legend_config = {
            "display": chart_block.legend_position != "hidden",
            "position": chart_block.legend_position if chart_block.legend_position != "hidden" else "top"
        }
        
        # Enable scrolling for large datasets (more than 10 datasets)
        if len(chart_block.datasets) > 10:
            legend_config["labels"] = {
                "boxWidth": 12,
                "padding": 8
            }
        
        return legend_config
    
    def _render_annotations(self, annotations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Render text annotations for Chart.js annotation plugin.
        
        Args:
            annotations: List of annotation dictionaries
            
        Returns:
            Annotations configuration dictionary
        
        """
        annotation_configs = {}
        
        for idx, annotation in enumerate(annotations):
            annotation_configs[f"annotation_{idx}"] = {
                "type": "label",
                "xValue": annotation.get("x", 0),
                "yValue": annotation.get("y", 0),
                "content": annotation.get("label", ""),
                "font": {
                    "size": annotation.get("font_size", 12)
                },
                "color": annotation.get("color", "#000000")
            }
        
        return annotation_configs
    
    def _render_reference_lines(self, reference_lines: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Render reference lines for Chart.js annotation plugin.
        
        Args:
            reference_lines: List of reference line dictionaries
            
        Returns:
            Reference line configuration dictionary
        
        """
        line_configs = {}
        
        for idx, ref_line in enumerate(reference_lines):
            line_type = ref_line.get("type", "horizontal")  # horizontal or vertical
            
            line_config = {
                "type": "line",
                "borderColor": ref_line.get("color", "#999999"),
                "borderWidth": ref_line.get("width", 2),
                "borderDash": ref_line.get("dash", [5, 5]),
                "label": {
                    "content": ref_line.get("label", ""),
                    "enabled": bool(ref_line.get("label")),
                    "position": "end"
                }
            }
            
            if line_type == "horizontal":
                line_config["yMin"] = ref_line.get("value", 0)
                line_config["yMax"] = ref_line.get("value", 0)
            else:  # vertical
                line_config["xMin"] = ref_line.get("value", 0)
                line_config["xMax"] = ref_line.get("value", 0)
            
            line_configs[f"ref_line_{idx}"] = line_config
        
        return line_configs
    
    def _apply_gradient(self, gradient_config: Dict[str, Any]) -> str:
        """
        Apply gradient configuration (placeholder for Chart.js gradient).
        
        Note: Actual gradient rendering requires canvas context in Chart.js.
        This returns a gradient identifier that will be processed by the frontend.
        
        Args:
            gradient_config: Gradient configuration dictionary
            
        Returns:
            Gradient identifier string
        """
        # In a real implementation, this would create a CanvasGradient object
        # For now, return a gradient identifier that the frontend can process
        return f"gradient({gradient_config.get('start_color', '#000000')},{gradient_config.get('end_color', '#ffffff')},{gradient_config.get('direction', 'vertical')})"
    
    def _add_transparency(self, hex_color: str, alpha: float) -> str:
        """
        Add transparency to a hex color by converting to rgba.
        
        Args:
            hex_color: Hex color code
            alpha: Alpha value (0.0 to 1.0)
            
        Returns:
            RGBA color string
        """
        # Remove # if present
        hex_color = hex_color.lstrip('#')
        
        # Convert to RGB
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        
        return f"rgba({r}, {g}, {b}, {alpha})"
