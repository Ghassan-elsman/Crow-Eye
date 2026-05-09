"""
Report Engine for EYE Forensic Assistant.

This module implements the ReportEngine class that manages the Living Report Workspace,
providing CRUD operations for report blocks and maintaining edit history.

"""

import threading
from typing import List, Dict, Any, Optional
from datetime import datetime
from uuid import uuid4
import logging
import base64
import os
import json
from dataclasses import fields

try:
    import markdown
except ImportError:
    markdown = None

from eye.models.report_blocks import (
    ReportBlock,
    TextBlock,
    TableBlock,
    ImageBlock,
    ReferenceBlock,
    ChatBlock,
    ChartBlock,
    TimelineBlock,
    HeatmapBlock,
    ChainOfCustodyBlock
)


from eye.services.color_manager import ColorManager


class ReportEngine:
    """
    Manages Living Report Workspace and provides CRUD operations for report blocks.
    """
    
    def __init__(self, case_directory: Optional[str] = None):
        self.case_directory = case_directory
        self.blocks: List[ReportBlock] = []
        self.edit_history: List[Dict[str, Any]] = []
        self.logger = logging.getLogger(__name__)
        self.max_history_size = 50
        
        # Initialize color manager for chart visuals
        self.color_manager = ColorManager()
        
        # Threading lock for report modifications
        self._lock = threading.RLock()
        
        # Section numbering state 
        self._section_numbering_enabled = False
        self._section_counters = []  # Stack of section counters for hierarchical numbering
        
        # Table of contents state 
        self._toc_enabled = False
        self._toc_entries = []  # List of {number, title, block_id, level}
        
        # Cover page state 
        self._cover_page_metadata = None
        
        # Page break markers 
        self._page_breaks = []  # List of block_ids after which to insert page breaks
        
        # Watermark state 
        self._watermark = None  # Dictionary with {text, opacity, position}
        
        # Logo branding state 
        self._logo = None  # Dictionary with {logo_path, position}
        
        # Colorblind preview state 
        self._colorblind_preview_enabled = False
        self._colorblind_deficiency_type = "deuteranopia"
        
        # Grayscale preview state 
        self._grayscale_preview_enabled = False 

        if case_directory:
            self.load_report()

    def set_case_directory(self, case_directory: str) -> None:
        """Update the active case directory and load existing report workspace."""
        self.case_directory = case_directory
        self.load_report()
    
    def append_section(self, title: str, markdown_content: str, author: str = "ai") -> str:
        with self._lock:
            block = TextBlock(
                title=title,
                markdown_content=markdown_content,
                metadata={
                    "author": author,
                    "timestamp": datetime.now().isoformat()
                }
            )
            self.blocks.append(block)
            self._record_edit("append", block.block_id, author, {
                "block_type": "text",
                "title": title
            })
            
            # Update section numbers if enabled
            if self._section_numbering_enabled:
                self._update_section_numbers()
            
            return block.block_id
    
    def add_data_table(
        self,
        sql_query: str,
        columns: List[str],
        rows: List[Dict[str, Any]],
        caption: str = "",
        column_widths: Optional[Dict[str, str]] = None,
        compact_spacing: bool = False,
        author: str = "ai"
    ) -> str:
        with self._lock:
            block = TableBlock(
                sql_query=sql_query,
                columns=columns,
                rows=rows,
                caption=caption,
                column_widths=column_widths or {},
                compact_spacing=compact_spacing,
                metadata={
                    "author": author,
                    "timestamp": datetime.now().isoformat()
                }
            )
            self.blocks.append(block)
            self._record_edit("append", block.block_id, author, {
                "block_type": "table",
                "row_count": len(rows),
                "column_count": len(columns)
            })
            return block.block_id

    def add_chat_transcript(self, messages: List[Dict[str, str]], author: str = "ai") -> str:
        with self._lock:
            block = ChatBlock(
                messages=messages,
                metadata={
                    "author": author,
                    "timestamp": datetime.now().isoformat()
                }
            )
            self.blocks.append(block)
            self._record_edit("append", block.block_id, author, {
                "block_type": "chat",
                "message_count": len(messages)
            })
            return block.block_id

    def add_chart(self, title: str, labels: List[str], datasets: List[Dict[str, Any]], chart_type: str = "bar", author: str = "ai") -> str:
        with self._lock:
            block = ChartBlock(
                title=title,
                labels=labels,
                datasets=datasets,
                chart_type=chart_type,
                metadata={
                    "author": author,
                    "timestamp": datetime.now().isoformat()
                }
            )
            

            try:
                from eye.services.chart_renderer import ChartRenderer
                chart_renderer = ChartRenderer()
                block.metadata["chart_config"] = chart_renderer.render_chart_config(block)
            except Exception as e:
                self.logger.warning(f"Could not render chart config for {title}: {e}")
            
            self.blocks.append(block)
            self._record_edit("append", block.block_id, author, {
                "block_type": "chart",
                "chart_type": chart_type,
                "title": title
            })
            return block.block_id
    
    def add_chart_enhanced(
        self,
        title: str,
        labels: List[str],
        datasets: List[Dict[str, Any]],
        chart_type: str = "bar",
        color_scheme: Optional[str] = None,
        custom_colors: Optional[List[str]] = None,
        gradient_config: Optional[Dict[str, Any]] = None,
        legend_position: str = "top",
        annotations: Optional[List[Dict[str, Any]]] = None,
        reference_lines: Optional[List[Dict[str, Any]]] = None,
        author: str = "ai"
    ) -> str:
        """
        Add enhanced chart with color customization and advanced features.
        
        Args:
            title: Chart title
            labels: List of X-axis labels
            datasets: List of dataset dicts {"label": "...", "data": [...]}
            chart_type: Type of chart (bar, line, pie, doughnut, radar, scatter, horizontalBar)
            color_scheme: Optional palette name (forensic, professional, high_contrast, colorblind_friendly, grayscale)
            custom_colors: Optional custom hex colors (overrides palette)
            gradient_config: Optional gradient configuration with start_color, end_color, direction
            legend_position: Legend position (top, bottom, left, right, hidden)
            annotations: Optional list of text annotations with x, y, label
            reference_lines: Optional list of reference lines with type, value, color, label
            author: Author of the block
            
        Returns:
            Block ID of created chart
            
        """
        with self._lock:
            from eye.services.chart_renderer import ChartRenderer
            
            # Create enhanced ChartBlock with all new fields
            block = ChartBlock(
                title=title,
                labels=labels,
                datasets=datasets,
                chart_type=chart_type,
                color_scheme=color_scheme,
                custom_colors=custom_colors,
                gradient_config=gradient_config,
                legend_position=legend_position,
                annotations=annotations if annotations else [],
                reference_lines=reference_lines if reference_lines else [],
                metadata={
                    "author": author,
                    "timestamp": datetime.now().isoformat()
                }
            )
            
            # Use ChartRenderer to generate Chart.js configuration
            chart_renderer = ChartRenderer()
            chart_config = chart_renderer.render_chart_config(block)
            
            # Store the rendered configuration in metadata for later use
            block.metadata["chart_config"] = chart_config
            
            # Add block to report
            self.blocks.append(block)
            
            # Record edit history
            self._record_edit("append", block.block_id, author, {
                "block_type": "chart",
                "chart_type": chart_type,
                "title": title,
                "color_scheme": color_scheme,
                "has_custom_colors": bool(custom_colors),
                "has_gradient": bool(gradient_config),
                "has_annotations": bool(annotations),
                "has_reference_lines": bool(reference_lines)
            })
            
            return block.block_id
    
    def add_timeline(
        self,
        title: str,
        events: List[Dict[str, Any]],
        color_scheme: Optional[str] = None,
        custom_colors: Optional[Dict[str, str]] = None,
        author: str = "ai"
    ) -> str:
        """
        Add timeline visualization block.
        
        Args:
            title: Timeline title
            events: List of event dicts with {timestamp, label, description, category}
            color_scheme: Optional palette name for category colors
            custom_colors: Optional category -> color mapping
            author: Author of the block
            
        Returns:
            Block ID of created timeline
            
        """
        with self._lock:
            block = TimelineBlock(
                title=title,
                events=events,
                color_scheme=color_scheme,
                custom_colors=custom_colors,
                metadata={
                    "author": author,
                    "timestamp": datetime.now().isoformat()
                }
            )
            self.blocks.append(block)
            self._record_edit("append", block.block_id, author, {
                "block_type": "timeline",
                "title": title,
                "event_count": len(events)
            })
            return block.block_id
    
    def add_heatmap(
        self,
        title: str,
        x_labels: List[str],
        y_labels: List[str],
        intensity_values: List[List[float]],
        color_scheme: str = "sequential",
        author: str = "ai"
    ) -> str:
        """
        Add heatmap visualization block.
        
        Args:
            title: Heatmap title
            x_labels: List of X-axis labels
            y_labels: List of Y-axis labels
            intensity_values: 2D array of intensity values
            color_scheme: Color scheme (sequential, diverging, thermal)
            author: Author of the block
            
        Returns:
            Block ID of created heatmap
            
        """
        with self._lock:
            block = HeatmapBlock(
                title=title,
                x_labels=x_labels,
                y_labels=y_labels,
                intensity_values=intensity_values,
                color_scheme=color_scheme,
                metadata={
                    "author": author,
                    "timestamp": datetime.now().isoformat()
                }
            )
            self.blocks.append(block)
            self._record_edit("append", block.block_id, author, {
                "block_type": "heatmap",
                "title": title,
                "dimensions": f"{len(y_labels)}x{len(x_labels)}"
            })
            return block.block_id
    
    def add_chain_of_custody(
        self,
        entries: List[Dict[str, Any]],
        author: str = "user"
    ) -> str:
        """
        Add chain of custody block with evidence tracking entries.
        
        Args:
            entries: List of custody entry dictionaries with fields:
                - evidence_id: Unique identifier for the evidence
                - acquisition_date: Date evidence was acquired
                - handler_name: Name of person handling evidence
                - action: Action performed (acquired, transferred, examined, etc.)
                - timestamp: ISO 8601 timestamp of the action
            author: Author of the block
            
        Returns:
            Block ID of created chain of custody block
            
        """
        with self._lock:
            block = ChainOfCustodyBlock(
                entries=entries,
                metadata={
                    "author": author,
                    "timestamp": datetime.now().isoformat()
                }
            )
            
            # Validate all entries
            for entry in entries:
                if not block.validate_entry(entry):
                    raise ValueError(
                        f"Invalid chain of custody entry: {entry}. "
                        "Required fields: evidence_id, handler_name, action, timestamp"
                    )
            
            self.blocks.append(block)
            self._record_edit("append", block.block_id, author, {
                "block_type": "chain_of_custody",
                "entry_count": len(entries)
            })
            return block.block_id
    
    def add_image(
        self,
        image_path: str,
        caption: str,
        author: str = "user"
    ) -> str:

        try:
            if self.case_directory:
                abs_case = os.path.abspath(self.case_directory)
                abs_img = os.path.abspath(image_path)
                if abs_img.startswith(abs_case):
                    image_path = os.path.relpath(abs_img, abs_case)
        except Exception:
            pass # Keep original path if relative conversion fails

        with self._lock:
            block = ImageBlock(
                image_path=image_path,
                caption=caption,
                metadata={
                    "author": author,
                    "timestamp": datetime.now().isoformat()
                }
            )
            self.blocks.append(block)
            self._record_edit("append", block.block_id, author, {
                "block_type": "image",
                "image_path": image_path
            })
            return block.block_id
    
    def edit_section(
        self,
        block_id: str,
        new_content: str,
        author: str = "user"
    ) -> bool:
        with self._lock:
            for block in self.blocks:
                if block.block_id == block_id:
                    if isinstance(block, TextBlock):
                        block.markdown_content = new_content
                    elif isinstance(block, TableBlock):
                        block.caption = new_content
                    elif isinstance(block, ImageBlock):
                        block.caption = new_content
                    elif isinstance(block, ReferenceBlock):
                        block.reference_text = new_content
                    elif hasattr(block, "title"):
                        setattr(block, "title", new_content)
                    else:
                        return False
                    
                    block.metadata["last_modified"] = datetime.now().isoformat()
                    block.metadata["last_modified_by"] = author
                    self._record_edit("edit", block_id, author, {"block_type": block.block_type})
                    

                    if self._section_numbering_enabled:
                        self._update_section_numbers()
                        
                    return True
            return False
    
    def delete_section(self, block_id: str, author: str = "user") -> bool:
        with self._lock:
            for i, block in enumerate(self.blocks):
                if block.block_id == block_id:
                    deleted_block = self.blocks.pop(i)
                    self._record_edit("delete", block_id, author, {"block_type": deleted_block.block_type})
                    

                    if self._section_numbering_enabled:
                        self._update_section_numbers()
                    return True
            return False
    
    def import_blocks(
        self, 
        blocks: List[ReportBlock], 
        source: str
    ) -> Dict[str, Any]:
        """
        Import report blocks from external source.
        
        Args:
            blocks: List of ReportBlock objects to import
            source: Source identifier (e.g., filename)
            
        Returns:
            Dictionary with import statistics:
            {
                "imported_count": 5,
                "skipped_count": 0,
                "source": "forensic_report_2024.html",
                "errors": []
            }
            
        """
        with self._lock:
            imported_count = 0
            skipped_count = 0
            errors = []
            

            existing_ids = {b.block_id for b in self.blocks}
            
            for block in blocks:
                try:
                    # Check for duplicate block_id collision
                    if block.block_id in existing_ids:
                        # Generate new UUID and log warning
                        old_id = block.block_id
                        block.block_id = str(uuid4())
                        self.logger.warning(
                            f"Duplicate block_id collision: {old_id} -> {block.block_id}"
                        )
                        # Add new ID to the set to prevent collisions within the same batch
                        existing_ids.add(block.block_id)
                    
                    # Validate block type
                    if not isinstance(block, (TextBlock, TableBlock, ImageBlock, ReferenceBlock, ChatBlock, ChartBlock, TimelineBlock, HeatmapBlock)):
                        self.logger.error(f"Invalid block type: {type(block)}")
                        skipped_count += 1
                        errors.append(f"Invalid block type: {type(block)}")
                        continue
                    
                    # Add source metadata
                    if not block.metadata:
                        block.metadata = {}
                    block.metadata["source"] = source
                    block.metadata["imported_at"] = datetime.now().isoformat()
                    
                    # Use existing timestamp or add current timestamp
                    if "timestamp" not in block.metadata:
                        block.metadata["timestamp"] = datetime.now().isoformat()
                    
                    # Append to blocks list
                    self.blocks.append(block)
                    imported_count += 1
                    
                except Exception as e:
                    self.logger.error(f"Error importing block {block.block_id}: {e}")
                    skipped_count += 1
                    errors.append(f"Block {block.block_id}: {str(e)}")
            
            # Record edit history
            self._record_edit(
                action="import",
                block_id=f"batch_{source}",
                author="system",
                details={
                    "source": source,
                    "imported_count": imported_count,
                    "skipped_count": skipped_count
                }
            )
            
            return {
                "imported_count": imported_count,
                "skipped_count": skipped_count,
                "source": source,
                "errors": errors
            }
    
    def get_blocks_by_source(self, source: str) -> List[ReportBlock]:
        """
        Get all blocks imported from a specific source.
        
        Args:
            source: Source identifier
            
        Returns:
            List of ReportBlock objects from that source
            
        """
        return [
            block for block in self.blocks
            if block.metadata.get("source") == source
        ]
    
    def get_block_statistics(self) -> Dict[str, int]:
        """
        Get statistics about blocks in the report.
        
        Returns:
            Dictionary with block counts by type
            
        """
        stats = {
            "total_blocks": len(self.blocks),
            "text_blocks": 0,
            "table_blocks": 0,
            "image_blocks": 0,
            "chart_blocks": 0,
            "chat_blocks": 0,
            "reference_blocks": 0,
            "timeline_blocks": 0,
            "heatmap_blocks": 0,
            "imported_blocks": 0
        }
        
        with self._lock:
            for block in self.blocks:
                b_type = block.block_type
                if b_type == "text": stats["text_blocks"] += 1
                elif b_type == "table": stats["table_blocks"] += 1
                elif b_type == "image": stats["image_blocks"] += 1
                elif b_type == "chart": stats["chart_blocks"] += 1
                elif b_type == "chat": stats["chat_blocks"] += 1
                elif b_type == "reference": stats["reference_blocks"] += 1
                elif b_type == "timeline": stats["timeline_blocks"] += 1
                elif b_type == "heatmap": stats["heatmap_blocks"] += 1
                
                # Count imported blocks
                if block.metadata.get("source"):
                    stats["imported_blocks"] += 1
        
        return stats
    
    def save_report(self) -> bool:
        """Save the current report state to the case directory."""
        if not self.case_directory:
            return False
            
        logs_dir = os.path.join(self.case_directory, "EYE_Logs")
        os.makedirs(logs_dir, exist_ok=True)
        
        report_file = os.path.join(logs_dir, "eye_report_workspace.json")
        temp_file = report_file + ".tmp"
        try:
            state = self.get_report_json()

            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
            
            # Atomic swap (os.replace is more robust on Windows than remove+rename)
            os.replace(temp_file, report_file)
            
            self.logger.info(f"Report workspace saved atomically to {report_file}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save report workspace: {e}")
            return False

    def load_report(self) -> bool:
        """Load the report state from the case directory."""
        if not self.case_directory:
            return False
            
        report_file = os.path.join(self.case_directory, "EYE_Logs", "eye_report_workspace.json")
        if not os.path.exists(report_file):
            return False
            
        try:
            with open(report_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            
            with self._lock:
                self.blocks = []
                
                # Type mapping for factory reconstruction
                type_map = {
                    "text": TextBlock,
                    "table": TableBlock,
                    "image": ImageBlock,
                    "chart": ChartBlock,
                    "chat": ChatBlock,
                    "timeline": TimelineBlock,
                    "heatmap": HeatmapBlock,
                    "chain_of_custody": ChainOfCustodyBlock,
                    "reference": ReferenceBlock
                }
                
                for block_data in state.get("blocks", []):
                    b_type = block_data.get("block_type")
                    cls = type_map.get(b_type)
                    
                    if cls:

                        # This prevents crashes if the JSON contains extra fields from newer versions.
                        valid_fields = {f.name for f in fields(cls)}
                        params = {k: v for k, v in block_data.items() if k in valid_fields}
                        
                        # Initialize block with filtered fields
                        try:
                            block = cls(**params)
                            self.blocks.append(block)
                        except Exception as e:
                            self.logger.error(f"Failed to reconstruct {b_type} block: {e}")
                
                self.edit_history = state.get("edit_history", [])
                
            self.logger.info(f"Loaded {len(self.blocks)} blocks from report workspace.")
            return True
        except Exception as e:
            self.logger.error(f"Failed to load report workspace: {e}")
            return False

    def get_report_json(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "blocks": [block.to_dict() for block in self.blocks],
                "edit_history": self.edit_history,
                "metadata": {
                    "block_count": len(self.blocks),
                    "last_modified": datetime.now().isoformat()
                }
            }
    
    def _record_edit(self, action, block_id, author, details=None):
        self.edit_history.append({
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "block_id": block_id,
            "author": author,
            "details": details or {}
        })
        if len(self.edit_history) > self.max_history_size:
            self.edit_history.pop(0)
    
    def enable_section_numbering(self, enabled: bool = True) -> None:
        """
        Enable or disable automatic section numbering.
        
        Args:
            enabled: True to enable section numbering, False to disable
            
        """
        self._section_numbering_enabled = enabled
        if enabled:
            self._update_section_numbers()
    
    def enable_colorblind_preview(
        self, 
        enabled: bool = True, 
        deficiency_type: str = "deuteranopia"
    ) -> None:
        """
        Enable or disable colorblind simulation preview mode.
        
        When enabled, all colors in the HTML output will be transformed to simulate
        how they appear to someone with the specified color vision deficiency.
        This allows users to preview reports and ensure they remain accessible
        to people with color blindness.
        
        Args:
            enabled: True to enable colorblind preview, False to disable
            deficiency_type: Type of color vision deficiency to simulate
                           - "deuteranopia": red-green colorblindness (missing green cones)
                           - "protanopia": red-green colorblindness (missing red cones)
        
        Raises:
            ValueError: If deficiency_type is not supported
            
        """
        if deficiency_type not in ("deuteranopia", "protanopia"):
            raise ValueError(
                f"Invalid deficiency_type: {deficiency_type}. "
                f"Must be 'deuteranopia' or 'protanopia'"
            )
        
        self._colorblind_preview_enabled = enabled
        self._colorblind_deficiency_type = deficiency_type
    
    def enable_grayscale_preview(self, enabled: bool = True) -> None:
        """
        Enable or disable grayscale preview mode for print simulation.
        
        When enabled, all colors in the HTML output will be converted to grayscale
        to simulate how the report will appear when printed on a black-and-white printer.
        This allows users to preview reports and ensure they remain readable and
        accessible when printed in grayscale.
        
        The grayscale conversion uses luminosity-based conversion to preserve
        perceived brightness and ensure text contrast remains at least 3:1 for readability.
        
        Args:
            enabled: True to enable grayscale preview, False to disable
            
        """
        self._grayscale_preview_enabled = enabled
    
    def _update_section_numbers(self) -> None:
        """
        Update section numbers for all titled report blocks.
        Implements sequential numbering for the Table of Contents.

        """
        with self._lock:
            self._toc_entries = []
            section_counter = 0

            for block in self.blocks:

                block_title = getattr(block, "title", None)
                # Tables use 'caption', Images use 'caption'
                if not block_title:
                    block_title = getattr(block, "caption", None)

                if block_title:
                    section_counter += 1
                    section_number = str(section_counter)

                    # Store TOC entry
                    self._toc_entries.append({
                        "number": section_number,
                        "title": block_title,
                        "block_id": block.block_id,
                        "level": 1
                    })

                    # Update block metadata with section number
                    if not block.metadata:
                        block.metadata = {}
                    block.metadata["section_number"] = section_number    
    def generate_table_of_contents(self) -> str:
        """
        Generate table of contents HTML with semantic nav element.
        
        Returns:
            HTML string for table of contents
            
        """
        if not self._toc_entries:
            return ""
        
        toc_html = ['<nav class="table-of-contents" id="toc" aria-label="Table of Contents">']
        toc_html.append('<h2 style="color: var(--accent); margin-bottom: 24px;">Table of Contents</h2>')
        
        for entry in self._toc_entries:
            number = entry["number"]
            title = self._escape_html(entry["title"])
            block_id = entry["block_id"]
            level = entry.get("level", 1)
            
            indent = (level - 1) * 24
            toc_html.append(
                f'<div style="margin-left: {indent}px; margin-bottom: 8px;">'
                f'<a href="#{block_id}" style="color: var(--tx); text-decoration: none;">'
                f'<span style="color: var(--accent); font-family: \'Space Mono\';">{number}</span> {title}'
                f'</a></div>'
            )
        
        toc_html.append('</nav>')
        
        return '\n'.join(toc_html)
    
    def set_cover_page(self, case_metadata: Dict[str, Any]) -> None:
        """
        Set cover page with case metadata.
        
        Args:
            case_metadata: Dictionary with case information:
                - case_number (required): Case identifier
                - investigator_name (required): Name of investigator
                - investigation_date: Date of investigation
                - classification_level: UNCLASSIFIED, CONFIDENTIAL, SECRET
                - case_title: Title of the case
                - organization: Organization name
                - case_description: Brief description
                
        Raises:
            ValueError: If required fields are missing
            
        """
        # Validate required fields
        required_fields = ["case_number", "investigator_name"]
        missing_fields = [f for f in required_fields if not case_metadata.get(f)]
        
        if missing_fields:
            raise ValueError(
                f"Missing required case metadata fields: {', '.join(missing_fields)}"
            )
        
        self._cover_page_metadata = case_metadata.copy()
        self.logger.info(f"Cover page set for case {case_metadata['case_number']}")
    
    def _render_cover_page(self) -> str:
        """
        Render cover page HTML with semantic header element.
        
        Returns:
            HTML string for cover page
            
        """
        if not self._cover_page_metadata:
            return ""
        
        meta = self._cover_page_metadata
        case_number = self._escape_html(meta.get("case_number", ""))
        case_title = self._escape_html(meta.get("case_title", "Forensic Investigation Report"))
        investigator = self._escape_html(meta.get("investigator_name", ""))
        date = self._escape_html(meta.get("investigation_date", datetime.now().strftime("%Y-%m-%d")))
        organization = self._escape_html(meta.get("organization", ""))
        classification = self._escape_html(meta.get("classification_level", ""))
        description = self._escape_html(meta.get("case_description", ""))
        
        cover_html = [
            '<header class="cover-page" style="min-height: 100vh; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; padding: 40px;">',
            f'<h1 style="font-family: \'Syne\', sans-serif; font-size: 48px; color: var(--accent); margin-bottom: 24px;">Case {case_number}</h1>',
        ]
        
        if case_title:
            cover_html.append(f'<h2 style="font-size: 32px; color: var(--tx); margin-bottom: 48px;">{case_title}</h2>')
        
        if description:
            cover_html.append(f'<p style="font-size: 16px; color: var(--tx2); max-width: 600px; margin-bottom: 48px;">{description}</p>')
        
        cover_html.append('<div style="margin-top: 48px; font-family: \'Space Mono\'; font-size: 14px; color: var(--tx2);">')
        cover_html.append(f'<p><strong>Investigator:</strong> {investigator}</p>')
        cover_html.append(f'<p><strong>Date:</strong> {date}</p>')
        
        if organization:
            cover_html.append(f'<p><strong>Organization:</strong> {organization}</p>')
        
        if classification:
            cover_html.append(f'<p style="margin-top: 24px; padding: 12px 24px; background: rgba(249, 115, 22, 0.1); border: 1px solid var(--accent); border-radius: 8px;"><strong>Classification:</strong> {classification}</p>')
        
        cover_html.append('</div>')
        cover_html.append('</header>')
        
        return '\n'.join(cover_html)
    
    def insert_page_break(self) -> None:
        """
        Insert explicit page break marker after the last block.
        
        """
        if self.blocks:
            last_block_id = self.blocks[-1].block_id
            if last_block_id not in self._page_breaks:
                self._page_breaks.append(last_block_id)
                self.logger.debug(f"Page break inserted after block {last_block_id}")
    
    def apply_template(
        self,
        template_name: str,
        case_metadata: Dict[str, Any]
    ) -> None:
        """
        Apply report template with case metadata.
        
        Args:
            template_name: Name of template (executive_summary, technical_analysis, timeline_report)
            case_metadata: Case metadata for cover page
            
        """
        from eye.services.template_manager import TemplateManager
        
        template_manager = TemplateManager()
        template_manager.apply_template(self, template_name, case_metadata)
    
    def _get_page_break_css(self) -> str:
        """
        Get CSS for page breaks in PDF export.
        
        Returns:
            CSS string for page breaks
            
        """
        if not self._page_breaks:
            return ""
        
        css_rules = []
        for block_id in self._page_breaks:
            css_rules.append(f"#{block_id} {{ page-break-after: always; }}")
        
        return "\n".join(css_rules)
    
    def add_watermark(
        self,
        text: str,
        opacity: float = 0.3,
        position: str = "center"
    ) -> None:
        """
        Add watermark to all pages in the report.
        
        Args:
            text: Watermark text (or preset name: draft, confidential, for_official_use_only)
            opacity: Watermark opacity (0.0 to 1.0)
            position: Watermark position (center, top, bottom, diagonal)
            
        """
        presets = {
            "draft": "DRAFT",
            "confidential": "CONFIDENTIAL",
            "for_official_use_only": "FOR OFFICIAL USE ONLY"
        }
        
        watermark_text = presets.get(text.lower(), text)
        
        # Validate opacity
        if not 0.0 <= opacity <= 1.0:
            raise ValueError(f"Opacity must be between 0.0 and 1.0, got {opacity}")
        
        # Validate position
        valid_positions = ["center", "top", "bottom", "diagonal"]
        if position not in valid_positions:
            raise ValueError(f"Position must be one of {valid_positions}, got {position}")
        
        self._watermark = {
            "text": watermark_text,
            "opacity": opacity,
            "position": position
        }
        
        self.logger.info(f"Watermark set: '{watermark_text}' at {position} with opacity {opacity}")
    
    def add_logo(
        self,
        logo_path: str,
        position: str = "header"
    ) -> None:
        """
        Add logo image to header or footer of each page.
        
        Args:
            logo_path: Path to logo image file
            position: Logo position ("header" or "footer")
            
        Raises:
            ValueError: If logo file doesn't exist or is not a valid image format
            ValueError: If position is not "header" or "footer"
            
        """
        # Validate position
        valid_positions = ["header", "footer"]
        if position not in valid_positions:
            raise ValueError(f"Position must be one of {valid_positions}, got {position}")
        
        # Validate logo file exists
        if not os.path.exists(logo_path):
            raise ValueError(f"Logo file not found: {logo_path}")
            

        try:
            if self.case_directory:
                abs_case = os.path.abspath(self.case_directory)
                abs_logo = os.path.abspath(logo_path)
                if abs_logo.startswith(abs_case):
                    logo_path = os.path.relpath(abs_logo, abs_case)
        except Exception:
            pass # Keep original path if relative conversion fails
        
        # Validate logo file is a valid image format
        valid_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.svg']
        ext = os.path.splitext(logo_path)[1].lower()
        if ext not in valid_extensions:
            raise ValueError(
                f"Invalid logo image format: {ext}. "
                f"Supported formats: {', '.join(valid_extensions)}"
            )
        
        self._logo = {
            "logo_path": logo_path,
            "position": position
        }
        
        self.logger.info(f"Logo set: '{logo_path}' at {position}")
    
    def _get_watermark_html(self) -> str:
        """
        Generate watermark HTML overlay.
        
        Returns:
            HTML string for watermark overlay
            
        """
        if not self._watermark:
            return ""
        
        text = self._escape_html(self._watermark["text"])
        opacity = self._watermark["opacity"]
        position = self._watermark["position"]
        
        # Position-specific styles
        position_styles = {
            "center": "top: 50%; left: 50%; transform: translate(-50%, -50%);",
            "top": "top: 10%; left: 50%; transform: translateX(-50%);",
            "bottom": "bottom: 10%; left: 50%; transform: translateX(-50%);",
            "diagonal": "top: 50%; left: 50%; transform: translate(-50%, -50%) rotate(-45deg);"
        }
        
        position_style = position_styles.get(position, position_styles["center"])
        
        return f"""
        <div class="watermark-overlay" style="
            position: fixed;
            {position_style}
            font-family: 'Syne', sans-serif;
            font-size: 120px;
            font-weight: 800;
            color: var(--accent);
            opacity: {opacity};
            pointer-events: none;
            z-index: 9999;
            user-select: none;
            white-space: nowrap;
        ">{text}</div>
        """
    
    def _get_logo_html(self) -> str:
        """
        Generate logo HTML for header or footer.
        
        Returns:
            HTML string for logo
            
        """
        if not self._logo:
            return ""
        
        logo_path = self._logo["logo_path"]
        position = self._logo["position"]
        

        final_path = logo_path
        if not os.path.isabs(logo_path) and self.case_directory:
            final_path = os.path.join(self.case_directory, logo_path)

        try:
            with open(final_path, 'rb') as f:
                image_data = f.read()
                ext = os.path.splitext(logo_path)[1].lower()
                mime_types = {
                    '.png': 'image/png',
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.gif': 'image/gif',
                    '.svg': 'image/svg+xml'
                }
                mime_type = mime_types.get(ext, 'image/png')
                encoded = base64.b64encode(image_data).decode('utf-8')
                
                # Position-specific styles
                if position == "header":
                    position_style = "top: 20px; left: 50%; transform: translateX(-50%);"
                else:  # footer
                    position_style = "bottom: 20px; left: 50%; transform: translateX(-50%);"
                
                return f"""
        <div class="logo-overlay" style="
            position: fixed;
            {position_style}
            max-width: 200px;
            max-height: 80px;
            pointer-events: none;
            z-index: 9998;
        ">
            <img src="data:{mime_type};base64,{encoded}" alt="Logo" style="max-width: 100%; max-height: 100%; object-fit: contain;">
        </div>
        """
        except Exception as e:
            self.logger.error(f"Error embedding logo: {e}")
            return ""
    
    def _get_watermark_css(self) -> str:
        """
        Generate watermark CSS for PDF export.
        
        Returns:
            CSS string for watermark in PDF
            
        """
        if not self._watermark:
            return ""
        
        text = self._watermark["text"]
        opacity = self._watermark["opacity"]
        position = self._watermark["position"]
        
        # Position-specific styles for PDF
        position_styles = {
            "center": "top: 50%; left: 50%; transform: translate(-50%, -50%);",
            "top": "top: 10%; left: 50%; transform: translateX(-50%);",
            "bottom": "bottom: 10%; left: 50%; transform: translateX(-50%);",
            "diagonal": "top: 50%; left: 50%; transform: translate(-50%, -50%) rotate(-45deg);"
        }
        
        position_style = position_styles.get(position, position_styles["center"])
        
        return f"""
        @page {{
            @top-center {{
                content: "";
            }}
        }}
        .watermark-overlay {{
            position: fixed;
            {position_style}
            font-family: 'Syne', sans-serif;
            font-size: 120px;
            font-weight: 800;
            color: #f97316;
            opacity: {opacity};
            pointer-events: none;
            z-index: 9999;
            user-select: none;
            white-space: nowrap;
        }}
        """
    
    def _get_logo_css(self) -> str:
        """
        Generate logo CSS for PDF export.
        
        Returns:
            CSS string for logo in PDF
            
        """
        if not self._logo:
            return ""
        
        logo_path = self._logo["logo_path"]
        position = self._logo["position"]
        
        # Read and encode logo image
        try:
            with open(logo_path, 'rb') as f:
                image_data = f.read()
                ext = os.path.splitext(logo_path)[1].lower()
                mime_types = {
                    '.png': 'image/png',
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.gif': 'image/gif',
                    '.svg': 'image/svg+xml'
                }
                mime_type = mime_types.get(ext, 'image/png')
                encoded = base64.b64encode(image_data).decode('utf-8')
                
                # Position-specific styles for PDF
                if position == "header":
                    position_style = "top: 20px; left: 50%; transform: translateX(-50%);"
                else:  # footer
                    position_style = "bottom: 20px; left: 50%; transform: translateX(-50%);"
                
                return f"""
        .logo-overlay {{
            position: fixed;
            {position_style}
            max-width: 200px;
            max-height: 80px;
            pointer-events: none;
            z-index: 9998;
        }}
        .logo-overlay img {{
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
        }}
        """
        except Exception as e:
            self.logger.error(f"Error generating logo CSS: {e}")
            return ""

    def render_html(self, title: str = "Forensic Investigation Report") -> str:
        """
        Render report as HTML with semantic HTML5 structure.
        
        Uses proper semantic elements for accessibility:
        - <header> for cover page and report header
        - <nav> for table of contents
        - <main> for main report content
        - <section> for report blocks
        - <footer> for report footer
        
        """
        # Update section numbers if enabled
        if self._section_numbering_enabled:
            self._update_section_numbers()
        
        # Render cover page if set
        cover_page_html = self._render_cover_page()
        
        # Render table of contents if enabled
        toc_html = ""
        if self._toc_enabled and self._toc_entries:
            toc_html = self.generate_table_of_contents()
        
        watermark_html = self._get_watermark_html()
        
        logo_html = self._get_logo_html()
        
        # Render blocks
        blocks_html = [self._render_block_html(b) for b in self.blocks]
        
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{self._escape_html(title)}</title>
    <style>{self._get_embedded_css()}{self._get_page_break_css()}{self._get_watermark_css()}{self._get_logo_css()}</style>
    {self._get_embedded_js()}
</head>
<body>
    {watermark_html}
    {logo_html}
    <div class="report-container">
        {cover_page_html}
        
        {toc_html}
        
        <header class="report-header">
            <h1>{self._escape_html(title)}</h1>
            <p class="report-meta">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </header>
        
        <section class="arch-description">
            <h3>Windows Boot Disk Explorer</h3>
            <p>NTFS structure access, MFT/USN Journal mapping, and granular file lifecycle tracking.</p>
        </section>

        <section class="arch-description">
            <h3>EYE Intelligence Chat Interface</h3>
            <p>RAG-driven forensic synthesis with real-time database correlation.</p>
        </section>

        <main class="report-content">
{''.join(blocks_html)}
        </main>
        
        <footer class="report-footer">
            <p>EYE Forensic Assistant Report - {len(self.blocks)} blocks</p>
        </footer>
    </div>
</body>
</html>"""
        
        if self._colorblind_preview_enabled:
            from eye.services.color_manager import ColorManager
            color_manager = ColorManager()
            html = color_manager.apply_colorblind_simulation_to_html(
                html, 
                self._colorblind_deficiency_type
            )
        
        if self._grayscale_preview_enabled:
            from eye.services.color_manager import ColorManager
            color_manager = ColorManager()
            html = color_manager.apply_grayscale_conversion_to_html(html)
        
        return html
    
    def _render_block_html(self, block: ReportBlock) -> str:
        if isinstance(block, TextBlock): return self._render_text_block(block)
        if isinstance(block, TableBlock): return self._render_table_block(block)
        if isinstance(block, ImageBlock): return self._render_image_block(block)
        if isinstance(block, ReferenceBlock): return self._render_reference_block(block)
        if block.block_type == "chat": return self._render_chat_block(block)
        if block.block_type == "chart": return self._render_chart_block(block)
        if block.block_type == "timeline": return self._render_timeline_block(block)
        if block.block_type == "heatmap": return self._render_heatmap_block(block)
        if block.block_type == "chain_of_custody": return self._render_chain_of_custody_block(block)
        return ""

    def _render_chart_block(self, block: Any) -> str:
        """
        Render chart block with Chart.js and accessibility features.
        
        """
        chart_id = f"chart_{block.block_id.replace('-', '')}"
        

        # This ensures add_chart_enhanced features (gradients, schemes) are preserved.
        config = block.metadata.get("chart_config")
        
        if not config:
            # Fallback for simple ChartBlocks
            colors = ['#f97316', '#06b6d4', '#ec4899', '#10b981', '#ff4d6a']
            config = {
                "type": block.chart_type,
                "data": { "labels": block.labels, "datasets": block.datasets },
                "options": {
                    "responsive": True,
                    "maintainAspectRatio": False,
                    "plugins": {
                        "legend": { "labels": { "color": "#e8edf5", "font": { "family": "Space Mono" } } },
                        "title": { "display": True, "text": block.title, "color": "#f97316", "font": { "size": 18, "family": "Syne" } }
                    },
                    "scales": {
                        "y": { "ticks": { "color": "#8899aa" }, "grid": { "color": "#1e2a3a" } },
                        "x": { "ticks": { "color": "#8899aa" }, "grid": { "color": "#1e2a3a" } }
                    }
                }
            }
            
            # Hide scales for circular charts
            if block.chart_type in ["pie", "doughnut", "radar"]:
                config["options"].pop("scales", None)


            for idx, ds in enumerate(config["data"]["datasets"]):
                if "backgroundColor" not in ds:
                    if block.chart_type in ["pie", "doughnut"]:
                        # Single dataset, multiple slices (one color per label)
                        ds["backgroundColor"] = [colors[i % len(colors)] for i in range(len(block.labels))]
                    else:
                        # Multiple datasets (one color per dataset)
                        ds["backgroundColor"] = colors[idx % len(colors)]
                        if block.chart_type == "line":
                             ds["borderColor"] = colors[idx % len(colors)]
        
        alt_text = self._generate_chart_alt_text(block.chart_type, block.title)
        escaped_alt_text = self._escape_html(alt_text)
        
        return f"""
        <section class="report-block chart-block" id="{block.block_id}">
            <div style="height: 400px; width: 100%;"><canvas id="{chart_id}" role="img" aria-label="{escaped_alt_text}"></canvas></div>
            <script>new Chart(document.getElementById('{chart_id}'), {json.dumps(config)});</script>
        </section>"""
    
    def _generate_chart_alt_text(self, chart_type: str, title: str) -> str:
        """
        Generate descriptive alt text for chart accessibility.
        
        Args:
            chart_type: Type of chart (bar, line, pie, etc.)
            title: Chart title
            
        Returns:
            Alt text string describing chart type and title
            
        """
        # Capitalize chart type for readability
        chart_type_display = chart_type.capitalize()
        
        # Handle special chart type names
        if chart_type == "horizontalBar":
            chart_type_display = "Horizontal bar"
        elif chart_type == "doughnut":
            chart_type_display = "Doughnut"
        
        # Format: "{Chart Type} chart: {Title}"
        if title:
            return f"{chart_type_display} chart: {title}"
        else:
            return f"{chart_type_display} chart"

    def _render_chat_block(self, block: Any) -> str:
        messages_html = []
        for msg in block.messages:
            role = msg.get("role", "ai"); content = self._escape_html(msg.get("content", "")).replace("\n", "<br>")
            cls = "ai-message" if role in ["ai", "assistant"] else "user-message"
            messages_html.append(f'<div class="chat-message {cls}">{content}</div>')
        return f'<section class="report-block chat-block" id="{block.block_id}">{"".join(messages_html)}</section>'
    
    def _render_text_block(self, block: TextBlock) -> str:
        content_html = markdown.markdown(block.markdown_content, extensions=['extra', 'codehilite', 'tables']) if markdown else f"<p>{self._escape_html(block.markdown_content)}</p>"
        
        # Add section number if enabled
        title_html = self._escape_html(block.title)
        if self._section_numbering_enabled and block.metadata.get("section_number"):
            section_number = block.metadata["section_number"]
            title_html = f'<span style="color: var(--accent); font-family: \'Space Mono\'; margin-right: 12px;">{section_number}</span>{title_html}'
        
        return f'<section class="report-block text-block" id="{block.block_id}"><h2>{title_html}</h2><div class="text-content">{content_html}</div></section>'
    
    def _render_table_block(self, block: TableBlock) -> str:
        """
        Render TableBlock with enhanced styling and conditional formatting.
        
        """
        # Pass block to _render_datatable for enhanced rendering
        table_html = self._render_datatable_enhanced(block)
        caption = f"<p class='table-caption'>{self._escape_html(block.caption)}</p>" if block.caption else ""
        return f'<section class="report-block table-block" id="{block.block_id}">{caption}{table_html}<details class="sql-query"><summary>View SQL</summary><pre><code>{self._escape_html(block.sql_query)}</code></pre></details></section>'


    def _render_image_block(self, block: ImageBlock) -> str:
        """Render ImageBlock with embedded image data."""

        final_path = block.image_path
        if not os.path.isabs(final_path) and self.case_directory:
            final_path = os.path.join(self.case_directory, final_path)
            
        image_html = ""
        if os.path.exists(final_path):
            try:
                with open(final_path, 'rb') as f:
                    image_data = f.read()
                    ext = os.path.splitext(final_path)[1].lower()
                    mime_types = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.svg': 'image/svg+xml'}
                    mime_type = mime_types.get(ext, 'image/png')
                    encoded = base64.b64encode(image_data).decode('utf-8')
                    image_html = f'<img src="data:{mime_type};base64,{encoded}" alt="{self._escape_html(block.caption)}" style="max-width:100%; border-radius:12px; border:1px solid var(--border);">'
            except Exception as e:
                image_html = f'<p class="image-error">Error embedding image: {e}</p>'
        else:
            image_html = f'<p class="image-error">Image not found: {self._escape_html(block.image_path)}</p>'
        
        return f"""
        <section class="report-block image-block" id="{block.block_id}">
            <figure style="text-align:center;">
                {image_html}
                <figcaption style="margin-top:12px; font-family:\'Space Mono\'; font-size:12px; color:var(--tx2); font-style:italic;">{self._escape_html(block.caption)}</figcaption>
            </figure>
        </section>
"""

    def _render_reference_block(self, block: ReferenceBlock) -> str:
        return f'<section class="report-block reference-block" id="{block.block_id}"><details><summary>{self._escape_html(block.reference_text)}</summary>Source: {block.source_link}</details></section>'

    def _render_timeline_block(self, block: Any) -> str:
        """Render TimelineBlock with chronological event display."""
        from eye.services.timeline_renderer import TimelineRenderer
        
        renderer = TimelineRenderer()
        timeline_data = renderer.render_timeline(
            title=block.title,
            events=block.events,
            color_scheme=block.color_scheme,
            custom_colors=block.custom_colors
        )
        
        # Generate timeline HTML
        title = timeline_data.get("title", "Timeline")
        events = timeline_data.get("events", [])
        category_colors = timeline_data.get("category_colors", {})
        
        # Build timeline HTML
        events_html = []
        for event in events:
            category = event.get("category", "default")
            color = category_colors.get(category, "#8899aa")
            label = event.get("label", "Event")
            description = event.get("description", "")
            timestamp = event.get("timestamp", "")
            
            event_html = f"""
            <div class="timeline-event" style="border-left: 3px solid {color}; padding-left: 16px; margin-bottom: 24px;">
                <div class="timeline-event-header" style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                    <span class="timeline-event-label" style="font-weight: bold; color: var(--tx);">{self._escape_html(label)}</span>
                    <span class="timeline-event-time" style="color: var(--tx2); font-family: 'Space Mono'; font-size: 12px;">{self._escape_html(str(timestamp))}</span>
                </div>
                <div class="timeline-event-description" style="color: var(--tx2); margin-bottom: 8px;">{self._escape_html(description)}</div>
                <div class="timeline-event-category" style="color: {color}; font-size: 11px; text-transform: uppercase; letter-spacing: 1px;">{self._escape_html(category)}</div>
            </div>
            """
            events_html.append(event_html)
        
        return f"""
        <section class="report-block timeline-block" id="{block.block_id}">
            <h2 style="color: var(--accent); margin-bottom: 24px;">{self._escape_html(title)}</h2>
            <div class="timeline-events">
                {''.join(events_html)}
            </div>
        </section>
        """
    
    def _render_heatmap_block(self, block: Any) -> str:
        """Render HeatmapBlock with intensity gradient visualization."""
        from eye.services.heatmap_renderer import HeatmapRenderer
        
        renderer = HeatmapRenderer()
        heatmap_data = renderer.render_heatmap(
            title=block.title,
            x_labels=block.x_labels,
            y_labels=block.y_labels,
            intensity_values=block.intensity_values,
            color_scheme=block.color_scheme
        )
        
        # Generate heatmap HTML
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
        header_row = '<div style="display: flex;"><div style="width: 100px; padding: 8px; font-weight: bold;"></div>'
        for x_label in x_labels:
            header_row += f'<div style="width: 80px; padding: 8px; text-align: center; font-weight: bold; color: var(--accent); font-size: 11px;">{self._escape_html(x_label)}</div>'
        header_row += '</div>'
        grid_html.append(header_row)
        
        # Add data rows
        for i, y_label in enumerate(y_labels):
            row_html = f'<div style="display: flex;"><div style="width: 100px; padding: 8px; font-weight: bold; color: var(--accent); font-size: 11px;">{self._escape_html(y_label)}</div>'
            
            if i < len(intensity_values):
                for j, intensity in enumerate(intensity_values[i]):
                    color = renderer.map_intensity_to_color(
                        intensity,
                        min_intensity,
                        max_intensity,
                        color_scheme
                    )
                    row_html += f'<div style="width: 80px; padding: 8px; text-align: center; background-color: {color}; border: 1px solid var(--border); font-family: \'Space Mono\'; font-size: 11px; color: var(--tx);" title="{intensity}">{intensity:.2f}</div>'
            
            row_html += '</div>'
            grid_html.append(row_html)
        
        return f"""
        <section class="report-block heatmap-block" id="{block.block_id}">
            <h2 style="color: var(--accent); margin-bottom: 16px;">{self._escape_html(title)}</h2>
            <div class="heatmap-grid" style="margin-bottom: 16px;">
                {''.join(grid_html)}
            </div>
            <div class="heatmap-legend" style="display: flex; gap: 16px; font-family: 'Space Mono'; font-size: 11px; color: var(--tx2);">
                <span>Min: {min_intensity:.2f}</span>
                <span>Max: {max_intensity:.2f}</span>
                <span>Scheme: {color_scheme}</span>
            </div>
        </section>
        """

    def _render_chain_of_custody_block(self, block: Any) -> str:
        """
        Render ChainOfCustodyBlock with chronological ordering and distinct visual style.
        
        """
        from eye.models.report_blocks import ChainOfCustodyBlock
        
        sorted_entries = sorted(
            block.entries,
            key=lambda e: e.get("timestamp", "")
        )
        
        # Build entries HTML
        entries_html = []
        for entry in sorted_entries:
            evidence_id = entry.get("evidence_id", "N/A")
            acquisition_date = entry.get("acquisition_date", "N/A")
            handler_name = entry.get("handler_name", "N/A")
            action = entry.get("action", "N/A")
            timestamp = entry.get("timestamp", "N/A")
            
            entry_html = f"""
            <div class="custody-entry" style="
                background: rgba(249, 115, 22, 0.05);
                border: 2px solid var(--accent);
                border-radius: 12px;
                padding: 20px;
                margin-bottom: 16px;
                box-shadow: 0 2px 8px rgba(249, 115, 22, 0.1);
            ">
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 12px;">
                    <div>
                        <span style="color: var(--accent); font-weight: bold; font-size: 11px; text-transform: uppercase; letter-spacing: 1px;">Evidence ID</span>
                        <div style="color: var(--tx); font-family: 'Space Mono'; font-size: 14px; margin-top: 4px;">{self._escape_html(str(evidence_id))}</div>
                    </div>
                    <div>
                        <span style="color: var(--accent); font-weight: bold; font-size: 11px; text-transform: uppercase; letter-spacing: 1px;">Acquisition Date</span>
                        <div style="color: var(--tx); font-family: 'Space Mono'; font-size: 14px; margin-top: 4px;">{self._escape_html(str(acquisition_date))}</div>
                    </div>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 12px;">
                    <div>
                        <span style="color: var(--accent); font-weight: bold; font-size: 11px; text-transform: uppercase; letter-spacing: 1px;">Handler</span>
                        <div style="color: var(--tx); font-family: 'Space Mono'; font-size: 14px; margin-top: 4px;">{self._escape_html(str(handler_name))}</div>
                    </div>
                    <div>
                        <span style="color: var(--accent); font-weight: bold; font-size: 11px; text-transform: uppercase; letter-spacing: 1px;">Action</span>
                        <div style="color: var(--tx); font-family: 'Space Mono'; font-size: 14px; margin-top: 4px;">{self._escape_html(str(action))}</div>
                    </div>
                </div>
                <div>
                    <span style="color: var(--accent); font-weight: bold; font-size: 11px; text-transform: uppercase; letter-spacing: 1px;">Timestamp</span>
                    <div style="color: var(--tx); font-family: 'Space Mono'; font-size: 14px; margin-top: 4px;">{self._escape_html(str(timestamp))}</div>
                </div>
            </div>
            """
            entries_html.append(entry_html)
        
        return f"""
        <section class="report-block chain-of-custody-block" id="{block.block_id}" style="
            background: linear-gradient(135deg, rgba(249, 115, 22, 0.03) 0%, rgba(6, 182, 212, 0.03) 100%);
            border: 2px solid var(--accent);
            border-radius: 24px;
            padding: 40px;
            margin-bottom: 48px;
        ">
            <div style="display: flex; align-items: center; gap: 16px; margin-bottom: 24px;">
                <div style="
                    background: var(--accent);
                    color: var(--bg);
                    padding: 8px 16px;
                    border-radius: 8px;
                    font-weight: bold;
                    font-size: 12px;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                ">⚖️ Legal Document</div>
                <h2 style="color: var(--accent); margin: 0; font-size: 24px;">Chain of Custody</h2>
            </div>
            <div class="custody-entries">
                {''.join(entries_html) if entries_html else '<p style="color: var(--tx2); font-style: italic;">No custody entries recorded.</p>'}
            </div>
        </section>
        """

    def _render_datatable(self, columns, rows) -> str:
        if not columns or not rows: return "<p>No data</p>"

        import hashlib
        content_hash = hashlib.md5(str(rows[:100]).encode()).hexdigest()[:8]
        table_id = f"dt_{content_hash}"
        header = "<tr>" + "".join(f"<th>{self._escape_html(c)}</th>" for c in columns) + "</tr>"
        body = "".join("<tr>" + "".join(f"<td>{self._escape_html(str(r.get(c, '')))}</td>" for c in columns) + "</tr>" for r in rows)
        return f'<table id="{table_id}" class="forensic-table"><thead>{header}</thead><tbody>{body}</tbody></table><script>$(document).ready(function(){{$("#{table_id}").DataTable();}});</script>'

    def _render_datatable_enhanced(self, block: TableBlock) -> str:
        """
        Render enhanced datatable with styling options and conditional formatting.
        
        """
        if not block.columns or not block.rows:
            return "<p>No data</p>"
        

        table_id = f"dt_{block.block_id.replace('-', '_')}"
        
        # Build table styles
        table_styles = []
        if block.compact_spacing:
            table_styles.append("padding: 6px;")
        
        header_cells = []
        for col in block.columns:
            width_style = f"width: {block.column_widths[col]};" if col in block.column_widths else ""
            header_cells.append(f'<th scope="col" style="{width_style}">{self._escape_html(col)}</th>')
        header = "<tr>" + "".join(header_cells) + "</tr>"
        
        # Build body rows with conditional formatting
        body_rows = []
        for row_idx, row in enumerate(block.rows):
            row_class = "striped-row" if block.striped_rows and row_idx % 2 == 1 else ""
            
            cells = []
            for col in block.columns:
                cell_value = row.get(col, '')
                cell_style_parts = []
                
                if col in block.cell_alignment:
                    alignment = block.cell_alignment[col]
                    cell_style_parts.append(f"text-align: {alignment};")
                
                cell_bg_color = None
                for rule in block.conditional_formatting:
                    if rule.get("column") == col:
                        if self._evaluate_condition(cell_value, rule.get("operator"), rule.get("value")):
                            cell_bg_color = rule.get("color", "#ff0000")
                            break
                
                if cell_bg_color:
                    cell_style_parts.append(f"background-color: {cell_bg_color};")
                
                if block.compact_spacing:
                    cell_style_parts.append("padding: 6px;")
                
                cell_style = " ".join(cell_style_parts)
                cells.append(f'<td style="{cell_style}">{self._escape_html(str(cell_value))}</td>')
            
            body_rows.append(f'<tr class="{row_class}">' + "".join(cells) + '</tr>')
        
        body = "".join(body_rows)
        
        table_class = "forensic-table"
        if block.bordered_cells:
            table_class += " bordered-cells"
        
        datatable_options = {}
        if len(block.rows) > 20:
            datatable_options["paging"] = True
            datatable_options["pageLength"] = 20
        else:
            datatable_options["paging"] = False
        
        datatable_config = json.dumps(datatable_options)
        
        return f'''<table id="{table_id}" class="{table_class}"><thead>{header}</thead><tbody>{body}</tbody></table>
<script>$(document).ready(function(){{$("#{table_id}").DataTable({datatable_config});}});</script>'''

    def _evaluate_condition(self, value: Any, operator: str, threshold: Any) -> bool:
        """
        Evaluate conditional formatting rule.
        
        Args:
            value: Cell value to evaluate
            operator: Comparison operator (>, <, >=, <=, ==, !=)
            threshold: Threshold value to compare against
            
        Returns:
            True if condition is met, False otherwise
            
        """
        try:
            # Try numeric comparison first
            num_value = float(value)
            num_threshold = float(threshold)
            
            if operator == ">":
                return num_value > num_threshold
            elif operator == "<":
                return num_value < num_threshold
            elif operator == ">=":
                return num_value >= num_threshold
            elif operator == "<=":
                return num_value <= num_threshold
            elif operator == "==":
                return num_value == num_threshold
            elif operator == "!=":
                return num_value != num_threshold
        except (ValueError, TypeError):
            # Fall back to string comparison
            if operator == "==":
                return str(value) == str(threshold)
            elif operator == "!=":
                return str(value) != str(threshold)
        
        return False


    def _get_embedded_css(self) -> str:
        return """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700&family=Space+Mono:wght@400;700&family=Syne:wght@800&display=swap');
:root { --bg: #0a0c10; --bg1: #0f1218; --bg2: #151a22; --border: #1e2a3a; --tx: #e8edf5; --tx2: #8899aa; --accent: #f97316; --identity: #06b6d4; }
body { background: var(--bg); color: var(--tx); font-family: 'Inter', sans-serif; padding: 40px 24px; }
.report-header h1 { font-family: 'Syne', sans-serif; font-size: 40px; color: #fff; }
.report-block { background: var(--bg1); border: 1px solid var(--border); border-radius: 24px; padding: 40px; margin-bottom: 48px; }

.forensic-table { 
    width: 100%; 
    border-collapse: collapse; 
    font-family: 'Space Mono', monospace; 
    font-size: 12px;
    /* Ensure table structure is preserved in PDF */
    page-break-inside: auto;
}

.forensic-table th { 
    color: var(--accent); 
    text-align: left; 
    padding: 12px; 
    border-bottom: 1px solid var(--border);
    font-weight: bold;
    background: var(--bg2);
    /* Prevent header from breaking across pages */
    page-break-inside: avoid;
    page-break-after: avoid;
}

.forensic-table td { 
    color: var(--tx2); 
    padding: 12px; 
    border-bottom: 1px solid var(--border);
    /* Prevent cell content from breaking awkwardly */
    page-break-inside: avoid;
}

/* Bordered cells styling - explicit borders for PDF rendering */
.forensic-table.bordered-cells td, 
.forensic-table.bordered-cells th { 
    border: 1px solid var(--border);
    /* Ensure borders are visible in PDF */
    border-style: solid;
    border-width: 1px;
}

/* Striped rows - explicit background color for PDF */
.forensic-table tr.striped-row { 
    background: rgba(249, 115, 22, 0.05);
    background-color: rgba(249, 115, 22, 0.05);
    /* Ensure striped background is preserved in PDF */
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
    color-adjust: exact;
}

/* Table structure preservation for PDF */
.forensic-table thead { 
    display: table-header-group;
    /* Repeat header on each page in PDF */
    page-break-inside: avoid;
}

.forensic-table tbody { 
    display: table-row-group;
}

.forensic-table tr {
    /* Prevent rows from breaking across pages when possible */
    page-break-inside: avoid;
}

/* Cell alignment preservation - ensure inline styles work in PDF */
.forensic-table td[style*="text-align"],
.forensic-table th[style*="text-align"] {
    /* Alignment is handled via inline styles in _render_datatable_enhanced */
}

/* Conditional formatting preservation - ensure background colors render in PDF */
.forensic-table td[style*="background-color"],
.forensic-table td[style*="background"] {
    /* Background colors from conditional formatting */
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
    color-adjust: exact;
}

.ai-message { background: rgba(249, 115, 22, 0.1); border-left: 3px solid var(--accent); padding: 16px; border-radius: 8px; }

/* Timeline styling */
.timeline-event { position: relative; padding: 24px; border-left: 2px solid var(--border); margin-left: 20px; }
.timeline-event::before { content: ""; position: absolute; left: -11px; top: 28px; width: 20px; height: 20px; border-radius: 50%; background: var(--bg); border: 2px solid var(--accent); }
.timeline-event-time { color: var(--accent); font-family: 'Space Mono', monospace; font-size: 14px; font-weight: bold; }
.timeline-event-label { color: #fff; font-weight: 700; margin-left: 12px; }
.timeline-event-description { color: var(--tx2); margin-top: 8px; line-height: 1.6; }
.timeline-event-category { display: inline-block; padding: 2px 10px; border-radius: 12px; background: var(--bg2); color: var(--tx2); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 8px; }

/* Heatmap styling */
.heatmap-container { display: flex; flex-direction: column; gap: 4px; }
.heatmap-row { display: flex; gap: 4px; align-items: center; }
.heatmap-cell { width: 32px; height: 32px; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 10px; color: rgba(255,255,255,0.5); }
.heatmap-label { width: 120px; font-size: 12px; color: var(--tx2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Chat Transcript styling */
.chat-transcript { display: flex; flex-direction: column; gap: 16px; }
.chat-message { padding: 16px; border-radius: 12px; max-width: 85%; }
.user-message { align-self: flex-end; background: var(--bg2); border: 1px solid var(--border); color: var(--tx); }
.assistant-message { align-self: flex-start; background: rgba(249, 115, 22, 0.08); border: 1px solid rgba(249, 115, 22, 0.2); color: var(--tx); border-left: 3px solid var(--accent); }

/* Print and PDF-specific styles */
@media print {
    .forensic-table thead { 
        display: table-header-group;
        /* Ensure headers repeat on each page */
    }
    .forensic-table tbody { 
        display: table-row-group;
    }
    
    /* Preserve all colors in print/PDF */
    .forensic-table tr.striped-row,
    .forensic-table td[style*="background"],
    .forensic-table th {
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
        color-adjust: exact;
    }
    
    /* Ensure borders are visible in print */
    .forensic-table.bordered-cells td,
    .forensic-table.bordered-cells th {
        border: 1px solid var(--border) !important;
    }
}

/* Weasyprint-specific optimizations for PDF export */
@page {
    /* Ensure proper page margins for tables */
    margin: 2cm;
}
"""

    def _get_embedded_js(self) -> str:
        return """
<script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
<script src="https://cdn.datatables.net/1.13.7/js/jquery.dataTables.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
"""

    def _escape_html(self, text: str) -> str:
        return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#x27;")

    def export_markdown(self) -> str:
        """
        Export report as Markdown with comprehensive block coverage and chart fallback.
        
        """
        md_parts = []
        for block in self.blocks:
            if isinstance(block, TextBlock):
                md_parts.append(f"## {block.title}\n\n{block.markdown_content}")
                
            elif isinstance(block, TableBlock):
                if not block.columns or not block.rows: 
                    md_parts.append(f"### {block.caption or 'Data Table'}\n_No data available_")
                else:
                    header = "| " + " | ".join(block.columns) + " |"
                    sep = "| " + " | ".join(["---"] * len(block.columns)) + " |"
                    rows = ["| " + " | ".join([str(r.get(c, "")).replace("|", "\\|") for c in block.columns]) + " |" for r in block.rows]
                    title = f"### {block.caption}\n\n" if block.caption else ""
                    md_parts.append(f"{title}{header}\n{sep}\n" + "\n".join(rows))
                    
            elif block.block_type == "chart":
                md_parts.append(self._render_chart_markdown_fallback(block))
                
            elif block.block_type == "chat":
                chat_md = ["## Forensic Synthesis Transcript\n"]
                for msg in block.messages:
                    role = msg.get('role', 'ai').upper()
                    content = msg.get('content', '')
                    chat_md.append(f"> **{role}**: {content}\n")
                md_parts.append("\n".join(chat_md))
                
            elif block.block_type == "timeline":
                tl_md = [f"## {block.title or 'Timeline'}\n"]
                for event in block.events:
                    ts = event.get("timestamp", "N/A")
                    lbl = event.get("label", "Event")
                    desc = event.get("description", "")
                    cat = event.get("category", "General")
                    tl_md.append(f"- **{ts}** | [{cat}] **{lbl}**: {desc}")
                md_parts.append("\n".join(tl_md))
                
            elif block.block_type == "heatmap":
                hm_md = [f"## {block.title or 'Activity Heatmap'}\n", "Grid mapping intensity values by category.\n"]
                # Create a markdown table for the heatmap
                if block.x_labels and block.y_labels and block.intensity_values:
                    header = "| | " + " | ".join(block.x_labels) + " |"
                    sep = "| --- | " + " | ".join(["---"] * len(block.x_labels)) + " |"
                    hm_md.append(header)
                    hm_md.append(sep)
                    for i, y_label in enumerate(block.y_labels):
                        if i < len(block.intensity_values):
                            row = [f"**{y_label}**"] + [f"{v:.2f}" for v in block.intensity_values[i]]
                            hm_md.append("| " + " | ".join(row) + " |")
                md_parts.append("\n".join(hm_md))
                
            elif block.block_type == "chain_of_custody":
                coc_md = ["## Chain of Custody\n", "| Timestamp | Action | Handler | Evidence ID |", "| --- | --- | --- | --- |"]
                sorted_entries = sorted(block.entries, key=lambda e: e.get("timestamp", ""))
                for entry in sorted_entries:
                    ts = entry.get("timestamp", "N/A")
                    act = entry.get("action", "N/A")
                    hdl = entry.get("handler_name", "N/A")
                    eid = entry.get("evidence_id", "N/A")
                    coc_md.append(f"| {ts} | {act} | {hdl} | {eid} |")
                md_parts.append("\n".join(coc_md))
                
            elif block.block_type == "image":
                md_parts.append(f"## {block.caption}\n\n![{block.caption}]({block.image_path})")

        return "\n\n".join(md_parts)
    
    def _render_chart_markdown_fallback(self, block: Any) -> str:
        """
        Render chart as Markdown with text description and data table fallback.
        
        Args:
            block: ChartBlock to render
            
        Returns:
            Markdown string with chart description and data table
            
        """
        md_parts = []
        
        # Chart description
        chart_type_display = block.chart_type.replace("_", " ").title()
        md_parts.append(f"## {block.title}")
        md_parts.append(f"*Chart Type: {chart_type_display}*")
        md_parts.append("")
        
        # Generate data table from chart data
        if not block.labels or not block.datasets:
            md_parts.append("_No chart data available_")
            return "\n".join(md_parts)
        
        # Build table header with labels column + dataset columns
        columns = ["Label"] + [ds.get("label", f"Dataset {i+1}") for i, ds in enumerate(block.datasets)]
        header = "| " + " | ".join(columns) + " |"
        separator = "| " + " | ".join(["---"] * len(columns)) + " |"
        
        md_parts.append(header)
        md_parts.append(separator)
        
        # Build table rows
        for i, label in enumerate(block.labels):
            row_values = [str(label).replace("|", "\\|")]
            
            for dataset in block.datasets:
                data = dataset.get("data", [])
                if i < len(data):
                    value = data[i]
                    # Format numeric values
                    if isinstance(value, (int, float)):
                        row_values.append(f"{value:.2f}" if isinstance(value, float) else str(value))
                    else:
                        row_values.append(str(value).replace("|", "\\|"))
                else:
                    row_values.append("N/A")
            
            md_parts.append("| " + " | ".join(row_values) + " |")
        
        return "\n".join(md_parts)

    def export_markdown_file(self, output_path: str, title: str = "Forensic Investigation Report") -> None:
        """
        Export report as a Markdown file with automatic organization and indexing.
        """
        md_content = self.export_markdown()
        
        # Determine final output path
        final_output_path = output_path
        if self.case_directory:
            from eye.services.case_directory_manager import CaseDirectoryManager
            case_manager = CaseDirectoryManager(self.case_directory)
            case_manager.ensure_reports_directory()
            
            case_number = self._cover_page_metadata.get("case_number", "UNKNOWN") if self._cover_page_metadata else "UNKNOWN"

            # but strip redundant extensions/timestamps if possible
            report_type = output_path
            if output_path.endswith('.md'):
                report_type = os.path.splitext(os.path.basename(output_path))[0]
            
            final_output_path = case_manager.get_report_path(case_number, report_type, "md")
            
            with open(final_output_path, 'w', encoding='utf-8') as f:
                f.write(md_content)
                
            # Update report index
            report_metadata = {
                "filename": os.path.basename(final_output_path),
                "case_number": case_number,
                "report_type": report_type,
                "timestamp": datetime.now().isoformat(),
                "format": "md",
                "file_size": os.path.getsize(final_output_path) if os.path.exists(final_output_path) else 0
            }
            case_manager.update_report_index(report_metadata)
            self.logger.info(f"Markdown exported to case directory: {final_output_path}")
        else:
            with open(final_output_path, 'w', encoding='utf-8') as f:
                f.write(md_content)
            self.logger.info(f"Markdown exported to: {final_output_path}")

    def export_pdf(self, output_path: str, config: Optional[Dict[str, Any]] = None) -> None:
        """
        Export report as PDF using PDFExporter with enhanced quality settings.
        
        When case_directory is provided, exports to {case_directory}/Reports/ using
        CaseDirectoryManager for automatic organization and indexing. When case_directory
        is None, exports to the specified output_path (current working directory fallback).
        
        Args:
            output_path: Path to output PDF file (used when case_directory is None)
                        or report_type identifier (used when case_directory is provided)
            config: Optional export configuration dictionary with keys:
                - dpi: int (default 300)
                - color_space: str "RGB" or "CMYK" (default "RGB")
                - embed_fonts: bool (default True)
                - print_optimized: bool (default False)
                
        Raises:
            ImportError: If weasyprint is not installed
            
        """
        from eye.services.pdf_exporter import PDFExporter, ExportConfig
        
        # Build export configuration from parameters and report state
        export_config = config.copy() if config else {}
        
        if self._watermark:
            export_config["watermark"] = self._watermark
        
        if self._logo:
            export_config["logo"] = self._logo
        
        # Create PDFExporter with configuration
        exporter = PDFExporter(export_config)
        
        # Render HTML content
        html_content = self.render_html()
        
        # Extract metadata from cover page if available
        metadata = None
        if self._cover_page_metadata:
            metadata = {
                "title": self._cover_page_metadata.get("case_title", "Forensic Investigation Report"),
                "author": self._cover_page_metadata.get("investigator_name", ""),
                "subject": f"Case {self._cover_page_metadata.get('case_number', '')}",
                "keywords": "forensic, investigation, report"
            }
        
        # Determine final output path using CaseDirectoryManager if case_directory is provided
        final_output_path = output_path
        if self.case_directory:
            from eye.services.case_directory_manager import CaseDirectoryManager
            
            case_manager = CaseDirectoryManager(self.case_directory)
            case_manager.ensure_reports_directory()
            
            # Extract case_number and report_type from metadata or use defaults
            case_number = self._cover_page_metadata.get("case_number", "UNKNOWN") if self._cover_page_metadata else "UNKNOWN"
            # Use output_path as report_type identifier when case_directory is provided
            report_type = output_path if not output_path.endswith('.pdf') else os.path.splitext(os.path.basename(output_path))[0]
            
            # Generate standardized filename and path
            final_output_path = case_manager.get_report_path(case_number, report_type, "pdf")
            
            # Export to PDF using PDFExporter
            exporter.export(html_content, final_output_path, metadata)
            
            # Update report index with metadata
            report_metadata = {
                "filename": os.path.basename(final_output_path),
                "case_number": case_number,
                "report_type": report_type,
                "timestamp": datetime.now().isoformat(),
                "format": "pdf",
                "file_size": os.path.getsize(final_output_path) if os.path.exists(final_output_path) else 0
            }
            
            # Add investigator if available
            if self._cover_page_metadata and "investigator_name" in self._cover_page_metadata:
                report_metadata["investigator"] = self._cover_page_metadata["investigator_name"]
            
            case_manager.update_report_index(report_metadata)
            
            self.logger.info(f"PDF exported to case directory: {final_output_path}")
        else:
            # Fall back to current working directory when case_directory is None
            exporter.export(html_content, final_output_path, metadata)
            self.logger.info(f"PDF exported to: {final_output_path}")
    
    def export_html(self, output_path: str, title: str = "Forensic Investigation Report") -> None:
        """
        Export report as HTML file.
        
        When case_directory is provided, exports to {case_directory}/Reports/ using
        CaseDirectoryManager for automatic organization and indexing. When case_directory
        is None, exports to the specified output_path (current working directory fallback).
        
        Args:
            output_path: Path to output HTML file (used when case_directory is None)
                        or report_type identifier (used when case_directory is provided)
            title: Report title for HTML document
            
        """
        # Render HTML content
        html_content = self.render_html(title)
        
        # Determine final output path using CaseDirectoryManager if case_directory is provided
        final_output_path = output_path
        if self.case_directory:
            from eye.services.case_directory_manager import CaseDirectoryManager
            
            case_manager = CaseDirectoryManager(self.case_directory)
            case_manager.ensure_reports_directory()
            
            # Extract case_number and report_type from metadata or use defaults
            case_number = self._cover_page_metadata.get("case_number", "UNKNOWN") if self._cover_page_metadata else "UNKNOWN"
            # Use output_path as report_type identifier when case_directory is provided
            report_type = output_path if not output_path.endswith('.html') else os.path.splitext(os.path.basename(output_path))[0]
            
            # Generate standardized filename and path
            final_output_path = case_manager.get_report_path(case_number, report_type, "html")
            
            # Write HTML to file
            with open(final_output_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            # Update report index with metadata
            report_metadata = {
                "filename": os.path.basename(final_output_path),
                "case_number": case_number,
                "report_type": report_type,
                "timestamp": datetime.now().isoformat(),
                "format": "html",
                "file_size": os.path.getsize(final_output_path) if os.path.exists(final_output_path) else 0
            }
            
            # Add investigator if available
            if self._cover_page_metadata and "investigator_name" in self._cover_page_metadata:
                report_metadata["investigator"] = self._cover_page_metadata["investigator_name"]
            
            case_manager.update_report_index(report_metadata)
            
            self.logger.info(f"HTML exported to case directory: {final_output_path}")
        else:
            # Fall back to current working directory when case_directory is None
            with open(final_output_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            self.logger.info(f"HTML exported to: {final_output_path}")
