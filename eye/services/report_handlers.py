"""
Report Tool Handlers for EYE AI Assistant.

This module handles all interactions with the Report Engine:
- Appending markdown sections
- Adding interactive data tables
- Including forensic images/screenshots
- Editing and deleting report blocks
"""

import os
import logging
from typing import Dict, Any

class ReportHandlers:
    """
    Implementation of reporting and documentation tools.
    """
    
    def __init__(self, context_manager):
        self.cm = context_manager
        self.logger = logging.getLogger(__name__)

    def handle_report_append_section(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a markdown text section to the forensic report."""
        title = params.get("title", "New Section")
        content = params.get("markdown_content") or params.get("content", "")
        
        if not content:
            return {"success": False, "error": "No content provided for report section."}
            
        # Provenance (source_query + timestamp) is stamped centrally by
        # ReportEngine._stamp_and_append for every block type.
        block_id = self.cm.report_engine.append_section(title, content, author="ai")
        self.cm.report_engine.save_report() # Auto-save
        return {"success": True, "block_id": block_id, "message": f"Section '{title}' added to report."}

    def handle_report_add_data_table(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add an interactive data table to the report."""
        db_name = params.get("database_name")
        sql_query = params.get("sql_query", "")
        columns = params.get("columns", [])
        data = params.get("rows", []) # AI can now provide data directly
        caption = params.get("caption", "")
        
        # INCREASED ROW LIMIT: Matches ReportEngine's internal cap for forensic rigor.
        ROW_LIMIT = 1000
        
        # IMPROVEMENT: If we have a query and database, ALWAYS fetch the FULL data
        # from the database, even if 'rows' were provided. This ensures the report
        # gets the complete evidence, not just the AI's context sample (TOON).
        if db_name and sql_query:
            self.logger.info(f"Fetching full data for report table from {db_name} using query.")
            res = self.cm.database_service.execute_query(db_name, sql_query)
            if res.get("success"):
                data = res.get("data", []) or res.get("rows", [])
            elif not data:
                # Only return error if we didn't have fallback rows
                return {"success": False, "error": f"Failed to retrieve data for table: {res.get('error')}"}
                
        original_count = len(data)
        if original_count > ROW_LIMIT:
            data = data[:ROW_LIMIT]
            self.logger.warning(f"Truncated report table from {original_count} to {ROW_LIMIT} rows.")

        # If columns weren't provided, try to extract from data
        if not columns and data:
            columns = list(data[0].keys())
            
        # Determine caption if not provided
        if not caption and original_count > ROW_LIMIT:
            caption = f"Showing top {len(data)} results"

        block_id = self.cm.report_engine.add_data_table(
            sql_query, columns, data,
            caption=caption,
            author="ai"
        )
        # Provenance stamped centrally in ReportEngine._stamp_and_append.
        self.cm.report_engine.save_report() # Auto-save
        
        message = f"Data table with {len(data)} rows added to report (ID: {block_id})."
        if original_count > ROW_LIMIT:
            message += f" Note: Result set was truncated from {original_count} rows for performance."

        return {
            "success": True, 
            "block_id": block_id, 
            "message": message
        }

    def handle_report_add_evidence(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add an expandable evidence reference block to the report."""
        text = params.get("reference_text", "Forensic Evidence")
        link = params.get("source_link", "")
        data = params.get("evidence_data", [])
        columns = params.get("columns") # Pass columns if provided
        
        if not data and not text:
            return {"success": False, "error": "Missing evidence_data or reference_text."}
            
        block_id = self.cm.report_engine.add_evidence(
            reference_text=text, 
            source_link=link, 
            evidence_data=data, 
            columns=columns,
            author="ai"
        )
        self.cm.report_engine.save_report()
        return {"success": True, "block_id": block_id, "message": f"Evidence reference added to report."}

    def handle_report_add_image(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Include a forensic image or screenshot in the report."""
        path = params.get("image_path")
        caption = params.get("caption", "Forensic Image")

        if not path:
            return {"success": False, "error": "Missing image_path."}

        # Security: only embed real image files that live INSIDE the case
        # directory. The path is model-supplied; without this it could embed
        # arbitrary local file bytes into the report (info disclosure).
        allowed_ext = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}
        ext = os.path.splitext(path)[1].lower()
        if ext not in allowed_ext:
            return {"success": False,
                    "error": f"Unsupported image type '{ext}'. Allowed: {', '.join(sorted(allowed_ext))}."}

        case_dir = getattr(self.cm, "case_directory", None)
        if not case_dir:
            return {"success": False, "error": "No case directory available; cannot validate image path."}
        try:
            real_path = os.path.realpath(path)
            real_case = os.path.realpath(str(case_dir))
        except Exception as e:
            return {"success": False, "error": f"Invalid image path: {e}"}
        if not (real_path == real_case or real_path.startswith(real_case + os.sep)):
            return {"success": False,
                    "error": "Access Denied: image must be inside the case directory. "
                             "Place exhibits in the case folder and reference them there."}
        if not os.path.isfile(real_path):
            return {"success": False, "error": f"Image not found: {path}"}

        block_id = self.cm.report_engine.add_image(real_path, caption, author="ai")
        self.cm.report_engine.save_report() # Auto-save
        return {"success": True, "block_id": block_id, "message": f"Image added to report (ID: {block_id})."}

    def handle_report_edit_section(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Update the content of an existing report section."""
        block_id = params.get("block_id")
        new_content = params.get("new_content")
        
        if not block_id or new_content is None:
            return {"success": False, "error": "Missing block_id or new_content."}
            
        success = self.cm.report_engine.edit_section(block_id, new_content, "ai")
        
        if not success:

            valid_ids = [b.block_id for b in self.cm.report_engine.blocks if b.block_type == "text"]
            return {
                "success": False, 
                "error": f"Section ID '{block_id}' not found or not editable.",
                "available_text_section_ids": valid_ids
            }

        self.cm.report_engine.save_report() # Auto-save
        return {"success": True, "message": f"Report section '{block_id}' updated successfully."}

    def handle_report_delete_section(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Remove a section from the report."""
        block_id = params.get("block_id")
        
        if not block_id:
            return {"success": False, "error": "Missing block_id."}
            
        success = self.cm.report_engine.delete_section(block_id, "ai")

        if not success:

            valid_ids = [b.block_id for b in self.cm.report_engine.blocks]
            return {
                "success": False, 
                "error": f"Block ID '{block_id}' not found.",
                "available_block_ids": valid_ids
            }

        self.cm.report_engine.save_report() # Auto-save
        return {"success": True, "message": f"Block '{block_id}' deleted from report."}

    def handle_report_add_chat_transcript(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a styled chat transcript block to the forensic report."""
        messages = params.get("messages", [])
        if not messages:
            return {"success": False, "error": "No messages provided for transcript."}
            
        block_id = self.cm.report_engine.add_chat_transcript(messages, "ai")
        self.cm.report_engine.save_report() # Auto-save
        return {"success": True, "block_id": block_id, "message": "Chat transcript added to report."}

    def handle_report_add_chart(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a data visualization chart (Bar, Line, Pie, etc.) to the forensic report."""
        title = params.get("title", "Forensic Data Chart")
        chart_type = params.get("chart_type", "bar")
        labels = params.get("labels", [])
        datasets = params.get("datasets", [])
        
        if not labels or not datasets:
            return {"success": False, "error": "Missing labels or datasets for chart."}
            

        block_id = self.cm.report_engine.add_chart_enhanced(
            title=title, 
            labels=labels, 
            datasets=datasets, 
            chart_type=chart_type,
            color_scheme=params.get("color_scheme", "forensic"),
            author="ai"
        )
        self.cm.report_engine.save_report() # Auto-save
        return {"success": True, "block_id": block_id, "message": f"Chart '{title}' (type: {chart_type}) added to report."}

    def handle_report_add_timeline(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a chronological timeline visualization to the report."""
        title = params.get("title", "Investigation Timeline")
        events = params.get("events", [])
        
        if not events:
            return {"success": False, "error": "No events provided for timeline."}
            
        block_id = self.cm.report_engine.add_timeline(
            title=title, 
            events=events,
            color_scheme=params.get("color_scheme", "forensic"),
            author="ai"
        )
        self.cm.report_engine.save_report() # Auto-save
        return {"success": True, "block_id": block_id, "message": f"Timeline '{title}' with {len(events)} events added."}

    def handle_report_add_heatmap(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add an intensity heatmap to the report."""
        title = params.get("title", "Activity Heatmap")
        x_labels = params.get("x_labels", [])
        y_labels = params.get("y_labels", [])
        intensity_values = params.get("intensity_values", [])
        
        if not x_labels or not y_labels or not intensity_values:
            return {"success": False, "error": "Missing labels or intensity values for heatmap."}
            
        block_id = self.cm.report_engine.add_heatmap(
            title=title,
            x_labels=x_labels,
            y_labels=y_labels,
            intensity_values=intensity_values,
            color_scheme=params.get("color_scheme", "sequential"),
            author="ai"
        )
        self.cm.report_engine.save_report() # Auto-save
        return {"success": True, "block_id": block_id, "message": f"Heatmap '{title}' added to report."}

    def handle_report_add_chain_of_custody(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a forensic chain of custody block to the report."""
        entries = params.get("entries", [])
        if not entries:
            return {"success": False, "error": "No entries provided for chain of custody."}
            
        try:
            block_id = self.cm.report_engine.add_chain_of_custody(entries, author="ai")
            self.cm.report_engine.save_report() # Auto-save
            return {"success": True, "block_id": block_id, "message": f"Chain of custody for {len(entries)} events documented."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def handle_export_report(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Trigger the export of the current report workspace to a file."""
        fmt = params.get("format", "html").lower()
        
        if fmt not in ["html", "pdf", "markdown", "md"]:
            return {"success": False, "error": f"Unsupported export format: {fmt}"}
            
        # Determine a friendly report type (e.g., "technical_analysis")

        # as the ReportEngine/CaseDirectoryManager will do it more reliably.
        report_type = params.get("report_type") or params.get("title") or "Forensic_Report"
        
        # Sanitize report type for filename
        import re
        report_type = re.sub(r'[^\w\-]', '_', report_type)
        
        try:
            if fmt == "html":
                self.cm.report_engine.export_html(report_type)
            elif fmt == "pdf":
                self.cm.report_engine.export_pdf(report_type)
            elif fmt in ["markdown", "md"]:
                self.cm.report_engine.export_markdown_file(report_type)
                    
            return {
                "success": True, 
                "format": fmt, 
                "report_type": report_type,
                "message": f"Report exported successfully as {fmt.upper()} to the case 'Reports' directory."
            }
        except Exception as e:
            self.logger.error(f"Failed to export report: {e}")
            return {"success": False, "error": f"Export failed: {str(e)}"}
