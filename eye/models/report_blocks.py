"""
Report Block Data Models for EYE Forensic Assistant.

This module defines the dataclass structures for different types of report blocks
that can be added to forensic reports. All blocks are JSON-serializable and support
metadata tracking for timestamps, authors, and modifications.

"""

from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional
from uuid import uuid4
from datetime import datetime


@dataclass
class CaseMetadata:
    """
    Case metadata for cover page and document properties.
    
    Attributes:
        case_number: Unique case identifier (required)
        investigator_name: Name of the investigator (required)
        investigation_date: Date of investigation
        classification_level: UNCLASSIFIED, CONFIDENTIAL, SECRET
        case_title: Title of the case
        organization: Organization name
        case_description: Brief description of the case
    
    """
    case_number: str
    investigator_name: str
    investigation_date: Optional[str] = None
    classification_level: Optional[str] = None
    case_title: Optional[str] = None
    organization: Optional[str] = None
    case_description: Optional[str] = None


@dataclass
class ReportBlock:
    """
    Base class for all report blocks.
    
    Attributes:
        block_id: Unique identifier for the block (auto-generated UUID)
        block_type: Type of block (text/table/image/reference)
        metadata: Dictionary containing timestamps, author, and other metadata
    
    """
    block_id: str = field(default_factory=lambda: str(uuid4()))
    block_type: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Initialize metadata with timestamp if not present."""
        if not self.metadata.get("timestamp"):
            self.metadata["timestamp"] = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert block to dictionary for JSON serialization.
        
        Returns:
            Dictionary representation of the block
        
        """
        return asdict(self)


@dataclass
class TextBlock(ReportBlock):
    """
    Text block containing markdown content.
    
    Attributes:
        title: Title of the text section
        markdown_content: Markdown-formatted text content
        block_type: Set to "text"
    
    """
    title: str = ""
    markdown_content: str = ""
    block_type: str = "text"


@dataclass
class TableBlock(ReportBlock):
    """
    Interactive table block containing SQL query results with enhanced formatting.
    
    Attributes:
        sql_query: SQL query that generated the table data
        columns: List of column names
        rows: List of dictionaries representing table rows
        caption: Optional caption for the table
        striped_rows: Enable alternating row colors
        bordered_cells: Enable cell borders
        compact_spacing: Use compact padding
        column_widths: Dict mapping column names to width values (e.g., {"col1": "20%"})
        cell_alignment: Dict mapping column names to alignment (left/center/right/justify)
        conditional_formatting: List of formatting rules
        block_type: Set to "table"
    
    """
    sql_query: str = ""
    columns: List[str] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    caption: str = ""
    
    # Enhanced styling options 
    striped_rows: bool = True
    bordered_cells: bool = True
    compact_spacing: bool = False
    column_widths: Dict[str, str] = field(default_factory=dict)  # {"column_name": "20%"}
    cell_alignment: Dict[str, str] = field(default_factory=dict)  # {"column_name": "left"}
    
    # Conditional formatting 
    conditional_formatting: List[Dict[str, Any]] = field(default_factory=list)
    # Format: [{"column": "col_name", "operator": ">", "value": 100, "color": "#ff0000"}]
    
    block_type: str = "table"


@dataclass
class ImageBlock(ReportBlock):
    """
    Image block with embedded image and caption.
    
    Attributes:
        image_path: File path to the image
        caption: Caption describing the image
        block_type: Set to "image"
    
    """
    image_path: str = ""
    caption: str = ""
    block_type: str = "image"


@dataclass
class ReferenceBlock(ReportBlock):
    """
    Expandable evidence reference block with database row references.
    
    Attributes:
        reference_text: Summary or description of the reference
        source_link: Link to the source (database query, file path, etc.)
        block_type: Set to "reference"
    
    """
    reference_text: str = ""
    source_link: str = ""
    block_type: str = "reference"


@dataclass
class ChatBlock(ReportBlock):
    """
    Chat transcript block for forensic synthesis.
    
    Attributes:
        messages: List of message dicts {"role": "ai/user", "content": "..."}
        block_type: Set to "chat"
    """
    messages: List[Dict[str, str]] = field(default_factory=list)
    block_type: str = "chat"


@dataclass
class ChartBlock(ReportBlock):
    """
    Data visualization block (Bar, Line, Pie charts).
    
    Attributes:
        chart_type: Type of chart (bar/line/pie/doughnut/radar/scatter/horizontalBar)
        title: Title of the chart
        labels: List of X-axis labels
        datasets: List of dataset dicts {"label": "...", "data": [...]}
        color_scheme: Optional palette name (forensic, professional, etc.)
        custom_colors: Optional custom hex colors (overrides palette)
        gradient_config: Optional gradient configuration
        legend_position: Legend position (top, bottom, left, right, hidden)
        annotations: List of text annotations with coordinates
        reference_lines: List of reference lines (horizontal or vertical)
        block_type: Set to "chart"
    
    """
    chart_type: str = "bar"
    title: str = ""
    labels: List[str] = field(default_factory=list)
    datasets: List[Dict[str, Any]] = field(default_factory=list)
    
    # New fields for enhancement
    color_scheme: str = None  # Palette name (forensic, professional, etc.)
    custom_colors: List[str] = None  # Custom hex colors
    gradient_config: Dict[str, Any] = None  # Gradient configuration
    legend_position: str = "top"  # top, bottom, left, right, hidden
    annotations: List[Dict[str, Any]] = field(default_factory=list)  # Text annotations
    reference_lines: List[Dict[str, Any]] = field(default_factory=list)  # Reference lines
    
    block_type: str = "chart"


@dataclass
class TimelineBlock(ReportBlock):
    """
    Timeline visualization block for chronological event display.
    
    Attributes:
        title: Title of the timeline
        events: List of event dicts {timestamp, label, description, category}
        color_scheme: Optional palette name for category colors
        custom_colors: Optional category -> color mapping (overrides palette)
        block_type: Set to "timeline"
    
    """
    title: str = ""
    events: List[Dict[str, Any]] = field(default_factory=list)
    color_scheme: str = None
    custom_colors: Dict[str, str] = None  # Category -> color mapping
    block_type: str = "timeline"


@dataclass
class HeatmapBlock(ReportBlock):
    """
    Heatmap visualization block for intensity/frequency data.
    
    Attributes:
        title: Title of the heatmap
        x_labels: List of X-axis labels
        y_labels: List of Y-axis labels
        intensity_values: 2D array of intensity values
        color_scheme: Color scheme (sequential, diverging, thermal)
        block_type: Set to "heatmap"
    
    """
    title: str = ""
    x_labels: List[str] = field(default_factory=list)
    y_labels: List[str] = field(default_factory=list)
    intensity_values: List[List[float]] = field(default_factory=list)
    color_scheme: str = "sequential"  # sequential, diverging, thermal
    block_type: str = "heatmap"


@dataclass
class ChainOfCustodyBlock(ReportBlock):
    """
    Chain of custody documentation block for evidence tracking.
    
    Attributes:
        entries: List of custody entry dictionaries
        block_type: Set to "chain_of_custody"
    
    Entry structure:
        evidence_id: Unique identifier for the evidence
        acquisition_date: Date evidence was acquired
        handler_name: Name of person handling evidence
        action: Action performed (acquired, transferred, examined, etc.)
        timestamp: ISO 8601 timestamp of the action
    
    """
    entries: List[Dict[str, Any]] = field(default_factory=list)
    block_type: str = "chain_of_custody"
    
    def validate_entry(self, entry: Dict[str, Any]) -> bool:
        """
        Validate that entry has all required fields.
        
        Args:
            entry: Dictionary containing custody entry data
            
        Returns:
            True if entry is valid, False otherwise
            
        """
        required_fields = ["evidence_id", "handler_name", "action", "timestamp"]
        return all(field in entry and entry[field] for field in required_fields)
