"""
Template Manager for EYE Forensic Report Enhancement.

This module implements the TemplateManager class that manages report templates
with predefined structures for different report types.

"""

from typing import Dict, Any, List, Optional
import logging


# Built-in template structures
TEMPLATES = {
    "executive_summary": {
        "sections": [
            {"type": "cover_page", "required": True},
            {"type": "table_of_contents", "required": True},
            {"type": "text", "title": "Case Overview", "required": True},
            {"type": "text", "title": "Key Findings", "required": True},
            {"type": "text", "title": "Conclusions", "required": True},
            {"type": "text", "title": "Recommendations", "required": True},
        ],
        "formatting": {
            "section_numbering": True,
            "page_breaks": True,
        }
    },
    "technical_analysis": {
        "sections": [
            {"type": "cover_page", "required": True},
            {"type": "table_of_contents", "required": True},
            {"type": "text", "title": "Methodology", "required": True},
            {"type": "text", "title": "Detailed Findings", "required": True},
            {"type": "text", "title": "Evidence References", "required": True},
            {"type": "text", "title": "Technical Appendices", "required": True},
        ],
        "formatting": {
            "section_numbering": True,
            "page_breaks": True,
        }
    },
    "timeline_report": {
        "sections": [
            {"type": "cover_page", "required": True},
            {"type": "table_of_contents", "required": True},
            {"type": "timeline", "title": "Event Timeline", "required": True},
            {"type": "text", "title": "Chronological Event Listing", "required": True},
        ],
        "formatting": {
            "section_numbering": True,
            "page_breaks": True,
        }
    }
}


class TemplateManager:
    """
    Manages report templates with predefined structures.
    
    """
    
    def __init__(self):
        """Initialize with built-in templates."""
        self.templates = TEMPLATES.copy()
        self.logger = logging.getLogger(__name__)
    
    def get_template(self, template_name: str) -> Dict[str, Any]:
        """
        Get template structure by name.
        
        Args:
            template_name: executive_summary, technical_analysis, timeline_report
            
        Returns:
            Template structure dictionary with sections and formatting
            
        Raises:
            ValueError: If template_name is not found
            
        """
        if template_name not in self.templates:
            raise ValueError(
                f"Template '{template_name}' not found. "
                f"Available templates: {', '.join(self.list_templates())}"
            )
        
        return self.templates[template_name].copy()
    
    def list_templates(self) -> List[str]:
        """
        List available template names.
        
        Returns:
            List of template names
            
        """
        return list(self.templates.keys())
    
    def apply_template(
        self,
        report_engine: 'ReportEngine',
        template_name: str,
        case_metadata: Dict[str, Any]
    ) -> None:
        """
        Apply template to report engine, initializing sections.
        
        Args:
            report_engine: ReportEngine instance
            template_name: Name of template to apply
            case_metadata: Case metadata for cover page
            
        Raises:
            ValueError: If template_name is not found
            
        """
        template = self.get_template(template_name)
        
        # Apply formatting options
        formatting = template.get("formatting", {})
        if formatting.get("section_numbering", False):
            report_engine.enable_section_numbering(True)
        
        # Initialize sections
        sections = template.get("sections", [])
        for section in sections:
            section_type = section.get("type")
            title = section.get("title", "")
            
            if section_type == "cover_page":
                # Set cover page with case metadata
                report_engine.set_cover_page(case_metadata)
            elif section_type == "table_of_contents":
                # Mark that TOC should be generated
                report_engine._toc_enabled = True
            elif section_type == "text":
                # Add placeholder text section
                report_engine.append_section(
                    title=title,
                    markdown_content=f"*{title} content will be added here.*",
                    author="template"
                )
            elif section_type == "timeline":
                # Add placeholder timeline
                report_engine.add_timeline(
                    title=title,
                    events=[],
                    author="template"
                )
            
            # Insert page break if configured
            if formatting.get("page_breaks", False):
                report_engine.insert_page_break()
        
        self.logger.info(
            f"Applied template '{template_name}' with {len(sections)} sections"
        )
