"""Automated forensic reporting engine for Crow Eye."""

import os
import json
import sqlite3
import base64
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple, Union
from dataclasses import dataclass, asdict
from pathlib import Path
import logging
import hashlib
from enum import Enum
import tempfile

try:
    from jinja2 import Template, Environment, FileSystemLoader
    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False

try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.figure import Figure
    import seaborn as sns
    import pandas as pd
    import numpy as np
    PLOTTING_AVAILABLE = True
except ImportError:
    PLOTTING_AVAILABLE = False


class ReportFormat(Enum):
    """Supported report formats."""
    HTML = "html"
    JSON = "json"
    CSV = "csv"
    PDF = "pdf"
    MARKDOWN = "md"


class SeverityLevel(Enum):
    """Severity levels for findings."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class Finding:
    """Represents a forensic finding."""
    title: str
    description: str
    severity: SeverityLevel
    artifact_type: str
    evidence: List[Dict[str, Any]]
    timestamps: List[str]
    confidence: float  # 0.0 to 1.0
    iocs: List[str]  # Indicators of Compromise
    recommendations: List[str]
    metadata: Dict[str, Any]


@dataclass
class ReportSection:
    """Represents a section in the report."""
    title: str
    content: str
    charts: List[str]  # Paths to chart images
    tables: List[Dict[str, Any]]
    subsections: List['ReportSection']


@dataclass
class ForensicReport:
    """Complete forensic report."""
    case_name: str
    examiner: str
    created_at: datetime
    time_range_start: Optional[datetime]
    time_range_end: Optional[datetime]
    executive_summary: str
    findings: List[Finding]
    sections: List[ReportSection]
    statistics: Dict[str, Any]
    metadata: Dict[str, Any]


class ReportGenerator:
    """Generate comprehensive forensic reports from Crow Eye data."""
    
    def __init__(self, database_paths: Dict[str, str], output_dir: str = "reports"):
        """Initialize the report generator.
        
        Args:
            database_paths: Dictionary mapping artifact types to database paths
            output_dir: Directory to save generated reports
        """
        self.database_paths = database_paths
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.logger = logging.getLogger(__name__)
        
        # Initialize template environment
        if JINJA2_AVAILABLE:
            self.template_env = Environment(
                loader=FileSystemLoader(self._get_template_dir())
            )
        
    def _get_template_dir(self) -> str:
        """Get the template directory path."""
        # Use templates in the same directory as this file
        return str(Path(__file__).parent / "templates")
    
    def generate_report(
        self,
        case_name: str,
        examiner: str = "Crow Eye Analyst",
        report_format: ReportFormat = ReportFormat.HTML,
        include_charts: bool = True,
        custom_template: Optional[str] = None
    ) -> str:
        """Generate a comprehensive forensic report.
        
        Args:
            case_name: Name of the case
            examiner: Name of the examiner
            report_format: Output format for the report
            include_charts: Whether to include charts and visualizations
            custom_template: Path to custom template file
            
        Returns:
            Path to the generated report file
        """
        self.logger.info(f"Generating {report_format.value} report for case: {case_name}")
        
        # Collect and analyze data
        findings = self.analyze_artifacts()
        statistics = self.generate_statistics()
        sections = self.create_report_sections(include_charts)
        
        # Create report object
        report = ForensicReport(
            case_name=case_name,
            examiner=examiner,
            created_at=datetime.now(),
            time_range_start=self._get_earliest_timestamp(),
            time_range_end=self._get_latest_timestamp(),
            executive_summary=self._generate_executive_summary(findings, statistics),
            findings=findings,
            sections=sections,
            statistics=statistics,
            metadata=self._get_system_metadata()
        )
        
        # Generate report in requested format
        if report_format == ReportFormat.HTML:
            return self._generate_html_report(report, custom_template)
        elif report_format == ReportFormat.JSON:
            return self._generate_json_report(report)
        elif report_format == ReportFormat.CSV:
            return self._generate_csv_report(report)
        elif report_format == ReportFormat.MARKDOWN:
            return self._generate_markdown_report(report)
        else:
            raise ValueError(f"Unsupported report format: {report_format}")
    
    def analyze_artifacts(self) -> List[Finding]:
        """Analyze artifacts and generate findings."""
        findings = []
        
        # Analyze each artifact type
        for artifact_type, db_path in self.database_paths.items():
            if not os.path.exists(db_path):
                continue
                
            try:
                artifact_findings = self._analyze_single_artifact(artifact_type, db_path)
                findings.extend(artifact_findings)
            except Exception as e:
                self.logger.error(f"Error analyzing {artifact_type}: {e}")
        
        # Perform cross-artifact analysis
        cross_findings = self._perform_cross_artifact_analysis()
        findings.extend(cross_findings)
        
        # Sort findings by severity and confidence
        findings.sort(key=lambda f: (f.severity.value, -f.confidence))
        
        return findings
    
    def _analyze_single_artifact(self, artifact_type: str, db_path: str) -> List[Finding]:
        """Analyze a single artifact type for findings."""
        findings = []
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get all tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            
            for table_row in tables:
                table_name = table_row[0]
                
                # Apply artifact-specific analysis
                if artifact_type.lower() == 'prefetch':
                    findings.extend(self._analyze_prefetch_table(cursor, table_name))
                elif artifact_type.lower() == 'registry':
                    findings.extend(self._analyze_registry_table(cursor, table_name))
                elif artifact_type.lower() == 'logs':
                    findings.extend(self._analyze_logs_table(cursor, table_name))
                elif artifact_type.lower() in ['lnk', 'jumplist']:
                    findings.extend(self._analyze_lnk_table(cursor, table_name))
                elif artifact_type.lower() == 'amcache':
                    findings.extend(self._analyze_amcache_table(cursor, table_name))
                
            conn.close()
            
        except Exception as e:
            self.logger.error(f"Error analyzing {artifact_type} database: {e}")
        
        return findings
    
    def _analyze_prefetch_table(self, cursor, table_name: str) -> List[Finding]:
        """Analyze prefetch data for suspicious activity."""
        findings = []
        
        try:
            # Get all prefetch records
            cursor.execute(f"SELECT * FROM {table_name}")
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            
            for row in rows:
                record = dict(zip(columns, row))
                
                # Check for suspicious executables
                filename = record.get('filename', '').lower()
                executable = record.get('executable', '').lower()
                
                suspicious_patterns = [
                    'powershell', 'cmd', 'wscript', 'cscript', 'mshta',
                    'regsvr32', 'rundll32', 'certutil', 'bitsadmin'
                ]
                
                for pattern in suspicious_patterns:
                    if pattern in filename or pattern in executable:
                        finding = Finding(
                            title=f"Suspicious Executable Execution: {record.get('executable', 'Unknown')}",
                            description=f"Detected execution of potentially suspicious executable: {executable}",
                            severity=SeverityLevel.MEDIUM,
                            artifact_type="prefetch",
                            evidence=[record],
                            timestamps=[record.get('last_run_time', '')],
                            confidence=0.7,
                            iocs=[executable],
                            recommendations=[
                                "Investigate the purpose and origin of this executable",
                                "Check for related artifacts in other data sources",
                                "Verify if this execution was authorized"
                            ],
                            metadata={"table": table_name, "pattern_matched": pattern}
                        )
                        findings.append(finding)
                        break
                
                # Check for unusual execution patterns
                run_count = record.get('run_count', 0)
                if isinstance(run_count, (int, str)) and int(run_count) > 100:
                    finding = Finding(
                        title=f"High Execution Count: {record.get('executable', 'Unknown')}",
                        description=f"Executable run {run_count} times, which may indicate automation or persistence",
                        severity=SeverityLevel.LOW,
                        artifact_type="prefetch",
                        evidence=[record],
                        timestamps=[record.get('last_run_time', '')],
                        confidence=0.5,
                        iocs=[record.get('executable', '')],
                        recommendations=[
                            "Investigate why this executable was run so frequently",
                            "Check if this is normal behavior for this system"
                        ],
                        metadata={"table": table_name, "run_count": run_count}
                    )
                    findings.append(finding)
                    
        except Exception as e:
            self.logger.error(f"Error analyzing prefetch table {table_name}: {e}")
        
        return findings
    
    def _analyze_registry_table(self, cursor, table_name: str) -> List[Finding]:
        """Analyze registry data for suspicious activity."""
        findings = []
        
        try:
            cursor.execute(f"SELECT * FROM {table_name}")
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            
            for row in rows:
                record = dict(zip(columns, row))
                
                # Check for suspicious registry entries
                key_path = record.get('key_path', '').lower()
                value_name = record.get('value_name', '').lower()
                value_data = str(record.get('value_data', '')).lower()
                
                # Check for persistence mechanisms
                persistence_keys = [
                    'currentversion\\run',
                    'currentversion\\runonce',
                    'winlogon\\shell',
                    'winlogon\\userinit',
                    'currentversion\\windows\\load',
                    'currentversion\\windows\\run'
                ]
                
                for persist_key in persistence_keys:
                    if persist_key in key_path:
                        finding = Finding(
                            title=f"Potential Persistence Mechanism: {value_name}",
                            description=f"Registry entry in common persistence location: {key_path}",
                            severity=SeverityLevel.MEDIUM,
                            artifact_type="registry",
                            evidence=[record],
                            timestamps=[record.get('last_modified', '')],
                            confidence=0.6,
                            iocs=[value_data] if value_data else [],
                            recommendations=[
                                "Verify the legitimacy of this registry entry",
                                "Check if the referenced file exists and is signed",
                                "Investigate when this entry was created"
                            ],
                            metadata={"table": table_name, "persistence_type": persist_key}
                        )
                        findings.append(finding)
                        break
                        
        except Exception as e:
            self.logger.error(f"Error analyzing registry table {table_name}: {e}")
        
        return findings
    
    def _analyze_logs_table(self, cursor, table_name: str) -> List[Finding]:
        """Analyze event logs for suspicious activity."""
        findings = []
        
        try:
            cursor.execute(f"SELECT * FROM {table_name}")
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            
            failed_logons = 0
            successful_logons = 0
            
            for row in rows:
                record = dict(zip(columns, row))
                
                event_id = record.get('event_id', 0)
                
                # Track logon events
                if event_id == 4624:  # Successful logon
                    successful_logons += 1
                elif event_id == 4625:  # Failed logon
                    failed_logons += 1
                
                # Check for suspicious event IDs
                suspicious_events = {
                    4648: "Explicit credential logon",
                    4672: "Admin privileges assigned",
                    4720: "User account created",
                    4732: "User added to security-enabled local group",
                    4688: "Process creation"
                }
                
                if event_id in suspicious_events:
                    finding = Finding(
                        title=f"Security Event: {suspicious_events[event_id]}",
                        description=f"Event ID {event_id}: {suspicious_events[event_id]}",
                        severity=SeverityLevel.INFO,
                        artifact_type="logs",
                        evidence=[record],
                        timestamps=[record.get('timestamp', '')],
                        confidence=0.8,
                        iocs=[],
                        recommendations=[
                            "Review the context of this security event",
                            "Verify if this activity was authorized"
                        ],
                        metadata={"table": table_name, "event_id": event_id}
                    )
                    findings.append(finding)
            
            # Analyze failed logon patterns
            if failed_logons > 10:
                finding = Finding(
                    title="Multiple Failed Logon Attempts",
                    description=f"Detected {failed_logons} failed logon attempts",
                    severity=SeverityLevel.HIGH if failed_logons > 50 else SeverityLevel.MEDIUM,
                    artifact_type="logs",
                    evidence=[],
                    timestamps=[],
                    confidence=0.9,
                    iocs=[],
                    recommendations=[
                        "Investigate the source of failed logon attempts",
                        "Check for potential brute force attacks",
                        "Review account lockout policies"
                    ],
                    metadata={"table": table_name, "failed_logons": failed_logons}
                )
                findings.append(finding)
                
        except Exception as e:
            self.logger.error(f"Error analyzing logs table {table_name}: {e}")
        
        return findings
    
    def _analyze_lnk_table(self, cursor, table_name: str) -> List[Finding]:
        """Analyze LNK/Jump List data for suspicious activity."""
        findings = []
        
        try:
            cursor.execute(f"SELECT * FROM {table_name}")
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            
            for row in rows:
                record = dict(zip(columns, row))
                
                target_path = record.get('target_path', '').lower()
                
                # Check for suspicious target paths
                suspicious_locations = [
                    'temp', 'appdata\\roaming', 'programdata', 'system32',
                    'users\\public', 'downloads'
                ]
                
                for location in suspicious_locations:
                    if location in target_path and target_path.endswith('.exe'):
                        finding = Finding(
                            title=f"Suspicious LNK Target: {record.get('name', 'Unknown')}",
                            description=f"LNK file targets executable in suspicious location: {target_path}",
                            severity=SeverityLevel.MEDIUM,
                            artifact_type="lnk",
                            evidence=[record],
                            timestamps=[record.get('created_time', '')],
                            confidence=0.6,
                            iocs=[target_path],
                            recommendations=[
                                "Verify the legitimacy of the target executable",
                                "Check if the target file still exists",
                                "Investigate when this LNK was created"
                            ],
                            metadata={"table": table_name, "suspicious_location": location}
                        )
                        findings.append(finding)
                        break
                        
        except Exception as e:
            self.logger.error(f"Error analyzing LNK table {table_name}: {e}")
        
        return findings
    
    def _analyze_amcache_table(self, cursor, table_name: str) -> List[Finding]:
        """Analyze Amcache data for suspicious activity."""
        findings = []
        
        try:
            cursor.execute(f"SELECT * FROM {table_name}")
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            
            for row in rows:
                record = dict(zip(columns, row))
                
                file_path = record.get('full_path', '').lower()
                
                # Check for executables in suspicious locations
                if file_path.endswith('.exe'):
                    suspicious_dirs = [
                        'temp', 'appdata', 'programdata', 'users\\public'
                    ]
                    
                    for sus_dir in suspicious_dirs:
                        if sus_dir in file_path:
                            finding = Finding(
                                title=f"Executable in Suspicious Location: {os.path.basename(file_path)}",
                                description=f"Executable found in potentially suspicious directory: {file_path}",
                                severity=SeverityLevel.MEDIUM,
                                artifact_type="amcache",
                                evidence=[record],
                                timestamps=[record.get('last_modified_time', '')],
                                confidence=0.5,
                                iocs=[file_path],
                                recommendations=[
                                    "Investigate the purpose of this executable",
                                    "Check if this file is digitally signed",
                                    "Verify if this is legitimate software"
                                ],
                                metadata={"table": table_name, "suspicious_directory": sus_dir}
                            )
                            findings.append(finding)
                            break
                            
        except Exception as e:
            self.logger.error(f"Error analyzing Amcache table {table_name}: {e}")
        
        return findings
    
    def _perform_cross_artifact_analysis(self) -> List[Finding]:
        """Perform analysis across multiple artifact types."""
        findings = []
        
        try:
            # Look for correlated activities across different artifacts
            # This is a simplified example - more sophisticated correlation could be implemented
            
            # Example: Find executables that appear in both prefetch and amcache
            prefetch_exes = self._get_executables_from_prefetch()
            amcache_exes = self._get_executables_from_amcache()
            
            common_exes = set(prefetch_exes.keys()) & set(amcache_exes.keys())
            
            for exe in common_exes:
                if len(common_exes) > 0:  # Only report if there are correlations
                    finding = Finding(
                        title="Cross-Artifact Correlation",
                        description=f"Found {len(common_exes)} executables appearing in multiple artifact types",
                        severity=SeverityLevel.INFO,
                        artifact_type="correlation",
                        evidence=[],
                        timestamps=[],
                        confidence=0.8,
                        iocs=list(common_exes),
                        recommendations=[
                            "Review correlated executables for potential relationships",
                            "Investigate timeline of execution across artifacts"
                        ],
                        metadata={"correlated_executables": list(common_exes)}
                    )
                    findings.append(finding)
                    break  # Only add one correlation finding
                    
        except Exception as e:
            self.logger.error(f"Error in cross-artifact analysis: {e}")
        
        return findings
    
    def _get_executables_from_prefetch(self) -> Dict[str, Any]:
        """Get executable names from prefetch data."""
        executables = {}
        
        prefetch_db = self.database_paths.get('prefetch')
        if not prefetch_db or not os.path.exists(prefetch_db):
            return executables
        
        try:
            conn = sqlite3.connect(prefetch_db)
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            
            for table_row in tables:
                table_name = table_row[0]
                try:
                    cursor.execute(f"SELECT executable FROM {table_name}")
                    rows = cursor.fetchall()
                    for row in rows:
                        if row[0]:
                            executables[row[0].lower()] = {"source": "prefetch", "table": table_name}
                except:
                    continue
            
            conn.close()
        except Exception as e:
            self.logger.error(f"Error getting prefetch executables: {e}")
        
        return executables
    
    def _get_executables_from_amcache(self) -> Dict[str, Any]:
        """Get executable names from amcache data."""
        executables = {}
        
        amcache_db = self.database_paths.get('amcache')
        if not amcache_db or not os.path.exists(amcache_db):
            return executables
        
        try:
            conn = sqlite3.connect(amcache_db)
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            
            for table_row in tables:
                table_name = table_row[0]
                try:
                    cursor.execute(f"SELECT full_path FROM {table_name} WHERE full_path LIKE '%.exe'")
                    rows = cursor.fetchall()
                    for row in rows:
                        if row[0]:
                            exe_name = os.path.basename(row[0]).lower()
                            executables[exe_name] = {"source": "amcache", "table": table_name}
                except:
                    continue
            
            conn.close()
        except Exception as e:
            self.logger.error(f"Error getting amcache executables: {e}")
        
        return executables
    
    def generate_statistics(self) -> Dict[str, Any]:
        """Generate statistics from all artifacts."""
        stats = {
            "total_artifacts": 0,
            "artifact_counts": {},
            "date_range": {},
            "top_executables": [],
            "suspicious_indicators": 0
        }
        
        for artifact_type, db_path in self.database_paths.items():
            if not os.path.exists(db_path):
                continue
                
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor.fetchall()
                
                artifact_count = 0
                for table_row in tables:
                    table_name = table_row[0]
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    count = cursor.fetchone()[0]
                    artifact_count += count
                
                stats["artifact_counts"][artifact_type] = artifact_count
                stats["total_artifacts"] += artifact_count
                
                conn.close()
                
            except Exception as e:
                self.logger.error(f"Error generating statistics for {artifact_type}: {e}")
                stats["artifact_counts"][artifact_type] = 0
        
        return stats
    
    def create_report_sections(self, include_charts: bool = True) -> List[ReportSection]:
        """Create report sections with analysis and visualizations."""
        sections = []
        
        # Executive Summary section
        exec_section = ReportSection(
            title="Executive Summary",
            content=self._create_executive_summary_content(),
            charts=[],
            tables=[],
            subsections=[]
        )
        sections.append(exec_section)
        
        # Artifact Analysis sections
        for artifact_type in self.database_paths.keys():
            section = self._create_artifact_section(artifact_type, include_charts)
            if section:
                sections.append(section)
        
        # Timeline Analysis section
        timeline_section = self._create_timeline_section(include_charts)
        if timeline_section:
            sections.append(timeline_section)
        
        # Recommendations section
        recommendations_section = self._create_recommendations_section()
        sections.append(recommendations_section)
        
        return sections
    
    def _create_executive_summary_content(self) -> str:
        """Create executive summary content."""
        return """
        This forensic analysis was conducted using Crow Eye, an automated Windows forensic investigation tool.
        The analysis examined various Windows artifacts to identify potential security incidents, 
        suspicious activities, and indicators of compromise.
        
        Key areas of focus included:
        - Program execution analysis through Prefetch files
        - Registry analysis for persistence mechanisms
        - Event log analysis for security events
        - File system activity through LNK files and Jump Lists
        - Application execution tracking via Amcache
        """
    
    def _create_artifact_section(self, artifact_type: str, include_charts: bool) -> Optional[ReportSection]:
        """Create a section for a specific artifact type."""
        db_path = self.database_paths.get(artifact_type)
        if not db_path or not os.path.exists(db_path):
            return None
        
        content = f"Analysis of {artifact_type} artifacts revealed the following information:"
        charts = []
        tables = []
        
        try:
            # Generate charts if requested and plotting is available
            if include_charts and PLOTTING_AVAILABLE:
                chart_path = self._create_artifact_chart(artifact_type, db_path)
                if chart_path:
                    charts.append(chart_path)
            
            # Create summary table
            summary_table = self._create_artifact_summary_table(artifact_type, db_path)
            if summary_table:
                tables.append(summary_table)
                
        except Exception as e:
            self.logger.error(f"Error creating section for {artifact_type}: {e}")
        
        return ReportSection(
            title=f"{artifact_type.title()} Analysis",
            content=content,
            charts=charts,
            tables=tables,
            subsections=[]
        )
    
    def _create_artifact_chart(self, artifact_type: str, db_path: str) -> Optional[str]:
        """Create a chart for an artifact type."""
        try:
            conn = sqlite3.connect(db_path)
            
            # Create a simple count chart
            fig, ax = plt.subplots(figsize=(10, 6))
            fig.patch.set_facecolor('#0F172A')
            ax.set_facecolor('#0F172A')
            
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            
            table_names = []
            record_counts = []
            
            for table_row in tables:
                table_name = table_row[0]
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                table_names.append(table_name)
                record_counts.append(count)
            
            if table_names:
                bars = ax.bar(table_names, record_counts, color='#00FFFF', alpha=0.7)
                ax.set_title(f'{artifact_type.title()} Record Counts', color='#E2E8F0', fontsize=14)
                ax.set_xlabel('Tables', color='#E2E8F0')
                ax.set_ylabel('Record Count', color='#E2E8F0')
                ax.tick_params(colors='#E2E8F0')
                
                # Rotate x-axis labels if needed
                if len(table_names) > 5:
                    plt.xticks(rotation=45, ha='right')
                
                plt.tight_layout()
                
                # Save chart
                chart_filename = f"{artifact_type}_chart.png"
                chart_path = self.output_dir / chart_filename
                plt.savefig(chart_path, facecolor='#0F172A', dpi=150)
                plt.close()
                
                conn.close()
                return str(chart_path)
            
            conn.close()
            
        except Exception as e:
            self.logger.error(f"Error creating chart for {artifact_type}: {e}")
        
        return None
    
    def _create_artifact_summary_table(self, artifact_type: str, db_path: str) -> Optional[Dict[str, Any]]:
        """Create a summary table for an artifact type."""
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            
            summary_data = []
            for table_row in tables:
                table_name = table_row[0]
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                
                summary_data.append({
                    "Table": table_name,
                    "Record Count": count
                })
            
            conn.close()
            
            if summary_data:
                return {
                    "title": f"{artifact_type.title()} Summary",
                    "headers": ["Table", "Record Count"],
                    "data": summary_data
                }
                
        except Exception as e:
            self.logger.error(f"Error creating summary table for {artifact_type}: {e}")
        
        return None
    
    def _create_timeline_section(self, include_charts: bool) -> Optional[ReportSection]:
        """Create timeline analysis section."""
        return ReportSection(
            title="Timeline Analysis",
            content="Timeline analysis provides a chronological view of system activities across all artifacts.",
            charts=[],
            tables=[],
            subsections=[]
        )
    
    def _create_recommendations_section(self) -> ReportSection:
        """Create recommendations section."""
        content = """
        Based on the analysis, the following recommendations are provided:
        
        1. Regularly monitor system artifacts for signs of suspicious activity
        2. Implement proper logging and monitoring solutions
        3. Keep systems updated with latest security patches
        4. Use application whitelisting to prevent unauthorized software execution
        5. Conduct regular forensic reviews of critical systems
        """
        
        return ReportSection(
            title="Recommendations",
            content=content,
            charts=[],
            tables=[],
            subsections=[]
        )
    
    def _generate_executive_summary(self, findings: List[Finding], statistics: Dict[str, Any]) -> str:
        """Generate executive summary based on findings and statistics."""
        critical_count = len([f for f in findings if f.severity == SeverityLevel.CRITICAL])
        high_count = len([f for f in findings if f.severity == SeverityLevel.HIGH])
        medium_count = len([f for f in findings if f.severity == SeverityLevel.MEDIUM])
        
        summary = f"""
        Forensic analysis completed on {len(self.database_paths)} artifact types, 
        processing {statistics.get('total_artifacts', 0)} total artifacts.
        
        Key Findings:
        - {critical_count} Critical severity findings
        - {high_count} High severity findings  
        - {medium_count} Medium severity findings
        - {len(findings)} Total findings identified
        
        The analysis focused on identifying indicators of compromise, persistence mechanisms,
        and suspicious activities across multiple Windows artifact types.
        """
        
        return summary.strip()
    
    def _get_earliest_timestamp(self) -> Optional[datetime]:
        """Get the earliest timestamp across all artifacts."""
        # Implementation would scan all databases for earliest timestamp
        return datetime.now() - timedelta(days=30)  # Placeholder
    
    def _get_latest_timestamp(self) -> Optional[datetime]:
        """Get the latest timestamp across all artifacts."""
        # Implementation would scan all databases for latest timestamp
        return datetime.now()  # Placeholder
    
    def _get_system_metadata(self) -> Dict[str, Any]:
        """Get system metadata for the report."""
        return {
            "tool_name": "Crow Eye",
            "tool_version": "2.0",
            "databases_analyzed": list(self.database_paths.keys()),
            "report_generated_by": "Automated Analysis Engine"
        }
    
    def _generate_html_report(self, report: ForensicReport, custom_template: Optional[str] = None) -> str:
        """Generate HTML report."""
        if not JINJA2_AVAILABLE:
            # Fallback to simple HTML generation
            return self._generate_simple_html_report(report)
        
        try:
            template_name = custom_template or "forensic_report.html"
            template = self.template_env.get_template(template_name)
            
            html_content = template.render(
                report=report,
                findings_by_severity=self._group_findings_by_severity(report.findings),
                current_time=datetime.now()
            )
            
            output_file = self.output_dir / f"{report.case_name}_report.html"
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
                
            return str(output_file)
            
        except Exception as e:
            self.logger.error(f"Error generating HTML report: {e}")
            return self._generate_simple_html_report(report)
    
    def _generate_simple_html_report(self, report: ForensicReport) -> str:
        """Generate a simple HTML report without templates."""
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Forensic Report - {report.case_name}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
                .header {{ background-color: #2c3e50; color: white; padding: 20px; border-radius: 5px; }}
                .section {{ background-color: white; margin: 20px 0; padding: 20px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .finding {{ border-left: 4px solid #e74c3c; padding: 10px; margin: 10px 0; background-color: #fdf2f2; }}
                .finding.critical {{ border-color: #c0392b; }}
                .finding.high {{ border-color: #e74c3c; }}
                .finding.medium {{ border-color: #f39c12; }}
                .finding.low {{ border-color: #f1c40f; }}
                .finding.info {{ border-color: #3498db; }}
                table {{ width: 100%; border-collapse: collapse; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Forensic Analysis Report</h1>
                <p><strong>Case:</strong> {report.case_name}</p>
                <p><strong>Examiner:</strong> {report.examiner}</p>
                <p><strong>Generated:</strong> {report.created_at.strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
            
            <div class="section">
                <h2>Executive Summary</h2>
                <p>{report.executive_summary}</p>
            </div>
            
            <div class="section">
                <h2>Key Findings</h2>
        """
        
        for finding in report.findings:
            html_content += f"""
                <div class="finding {finding.severity.value}">
                    <h3>{finding.title}</h3>
                    <p><strong>Severity:</strong> {finding.severity.value.upper()}</p>
                    <p><strong>Confidence:</strong> {finding.confidence:.1%}</p>
                    <p>{finding.description}</p>
                    <p><strong>Recommendations:</strong></p>
                    <ul>
            """
            for rec in finding.recommendations:
                html_content += f"<li>{rec}</li>"
            html_content += "</ul></div>"
        
        html_content += """
            </div>
            
            <div class="section">
                <h2>Statistics</h2>
                <table>
                    <tr><th>Metric</th><th>Value</th></tr>
        """
        
        for key, value in report.statistics.items():
            html_content += f"<tr><td>{key.replace('_', ' ').title()}</td><td>{value}</td></tr>"
        
        html_content += """
                </table>
            </div>
        </body>
        </html>
        """
        
        output_file = self.output_dir / f"{report.case_name}_report.html"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
            
        return str(output_file)
    
    def _generate_json_report(self, report: ForensicReport) -> str:
        """Generate JSON report."""
        # Convert datetime objects to strings for JSON serialization
        report_dict = asdict(report)
        report_dict['created_at'] = report.created_at.isoformat()
        if report.time_range_start:
            report_dict['time_range_start'] = report.time_range_start.isoformat()
        if report.time_range_end:
            report_dict['time_range_end'] = report.time_range_end.isoformat()
        
        # Convert enum values to strings
        for finding in report_dict['findings']:
            finding['severity'] = finding['severity'].value if hasattr(finding['severity'], 'value') else str(finding['severity'])
        
        output_file = self.output_dir / f"{report.case_name}_report.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report_dict, f, indent=2, default=str)
            
        return str(output_file)
    
    def _generate_csv_report(self, report: ForensicReport) -> str:
        """Generate CSV report of findings."""
        import csv
        
        output_file = self.output_dir / f"{report.case_name}_findings.csv"
        
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Write header
            writer.writerow([
                'Title', 'Severity', 'Confidence', 'Artifact Type', 
                'Description', 'IOCs', 'Recommendations'
            ])
            
            # Write findings
            for finding in report.findings:
                writer.writerow([
                    finding.title,
                    finding.severity.value,
                    f"{finding.confidence:.1%}",
                    finding.artifact_type,
                    finding.description,
                    '; '.join(finding.iocs),
                    '; '.join(finding.recommendations)
                ])
        
        return str(output_file)
    
    def _generate_markdown_report(self, report: ForensicReport) -> str:
        """Generate Markdown report."""
        md_content = f"""# Forensic Analysis Report

**Case:** {report.case_name}  
**Examiner:** {report.examiner}  
**Generated:** {report.created_at.strftime('%Y-%m-%d %H:%M:%S')}

## Executive Summary

{report.executive_summary}

## Key Findings

"""
        
        for finding in report.findings:
            md_content += f"""### {finding.title}

**Severity:** {finding.severity.value.upper()}  
**Confidence:** {finding.confidence:.1%}  
**Artifact Type:** {finding.artifact_type}

{finding.description}

**Recommendations:**
"""
            for rec in finding.recommendations:
                md_content += f"- {rec}\n"
            
            if finding.iocs:
                md_content += f"\n**IOCs:** {', '.join(finding.iocs)}\n"
            
            md_content += "\n---\n\n"
        
        md_content += f"""## Statistics

| Metric | Value |
|--------|-------|
"""
        
        for key, value in report.statistics.items():
            md_content += f"| {key.replace('_', ' ').title()} | {value} |\n"
        
        output_file = self.output_dir / f"{report.case_name}_report.md"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(md_content)
            
        return str(output_file)
    
    def _group_findings_by_severity(self, findings: List[Finding]) -> Dict[str, List[Finding]]:
        """Group findings by severity level."""
        grouped = {level.value: [] for level in SeverityLevel}
        
        for finding in findings:
            grouped[finding.severity.value].append(finding)
        
        return grouped


# Utility functions

def create_default_template_dir():
    """Create default templates directory with basic templates."""
    template_dir = Path(__file__).parent / "templates"
    template_dir.mkdir(exist_ok=True)
    
    # Create basic HTML template
    html_template = """<!DOCTYPE html>
<html>
<head>
    <title>Forensic Report - {{ report.case_name }}</title>
    <style>
        body { font-family: 'Segoe UI', Arial, sans-serif; margin: 0; background: #0F172A; color: #E2E8F0; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .header { background: linear-gradient(135deg, #1E293B, #334155); padding: 30px; border-radius: 10px; margin-bottom: 30px; }
        .section { background: #1E293B; margin: 20px 0; padding: 25px; border-radius: 8px; border: 1px solid #475569; }
        .finding { border-left: 4px solid; padding: 15px; margin: 15px 0; background: rgba(30, 41, 59, 0.5); border-radius: 5px; }
        .finding.critical { border-color: #EF4444; background: rgba(239, 68, 68, 0.1); }
        .finding.high { border-color: #F59E0B; background: rgba(245, 158, 11, 0.1); }
        .finding.medium { border-color: #3B82F6; background: rgba(59, 130, 246, 0.1); }
        .finding.low { border-color: #10B981; background: rgba(16, 185, 129, 0.1); }
        .finding.info { border-color: #00FFFF; background: rgba(0, 255, 255, 0.1); }
        table { width: 100%; border-collapse: collapse; margin: 15px 0; }
        th, td { border: 1px solid #475569; padding: 12px; text-align: left; }
        th { background: #334155; color: #00FFFF; font-weight: bold; }
        .accent { color: #00FFFF; }
        .meta { color: #94A3B8; font-size: 0.9em; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 class="accent">🔍 Crow Eye Forensic Analysis Report</h1>
            <div class="meta">
                <p><strong>Case:</strong> {{ report.case_name }}</p>
                <p><strong>Examiner:</strong> {{ report.examiner }}</p>
                <p><strong>Generated:</strong> {{ report.created_at.strftime('%Y-%m-%d %H:%M:%S UTC') }}</p>
                {% if report.time_range_start %}
                <p><strong>Analysis Period:</strong> {{ report.time_range_start.strftime('%Y-%m-%d') }} to {{ report.time_range_end.strftime('%Y-%m-%d') }}</p>
                {% endif %}
            </div>
        </div>
        
        <div class="section">
            <h2 class="accent">📋 Executive Summary</h2>
            <p>{{ report.executive_summary | replace('\n', '<br>') }}</p>
        </div>
        
        <div class="section">
            <h2 class="accent">🔍 Key Findings ({{ report.findings | length }})</h2>
            {% for severity, findings_list in findings_by_severity.items() %}
                {% if findings_list %}
                    <h3>{{ severity.title() }} Severity ({{ findings_list | length }})</h3>
                    {% for finding in findings_list %}
                        <div class="finding {{ finding.severity.value }}">
                            <h4>{{ finding.title }}</h4>
                            <p class="meta">
                                <strong>Confidence:</strong> {{ "%.1f" | format(finding.confidence * 100) }}% | 
                                <strong>Artifact:</strong> {{ finding.artifact_type | title }}
                            </p>
                            <p>{{ finding.description }}</p>
                            {% if finding.iocs %}
                                <p><strong>IOCs:</strong> <code>{{ finding.iocs | join(', ') }}</code></p>
                            {% endif %}
                            {% if finding.recommendations %}
                                <p><strong>Recommendations:</strong></p>
                                <ul>
                                    {% for rec in finding.recommendations %}
                                        <li>{{ rec }}</li>
                                    {% endfor %}
                                </ul>
                            {% endif %}
                        </div>
                    {% endfor %}
                {% endif %}
            {% endfor %}
        </div>
        
        <div class="section">
            <h2 class="accent">📊 Analysis Statistics</h2>
            <table>
                <tr><th>Metric</th><th>Value</th></tr>
                {% for key, value in report.statistics.items() %}
                    <tr><td>{{ key.replace('_', ' ').title() }}</td><td>{{ value }}</td></tr>
                {% endfor %}
            </table>
        </div>
        
        <div class="section">
            <h2 class="accent">🔧 Tool Information</h2>
            <p class="meta">
                Report generated by {{ report.metadata.tool_name }} v{{ report.metadata.tool_version }}<br>
                Databases analyzed: {{ report.metadata.databases_analyzed | join(', ') }}
            </p>
        </div>
    </div>
</body>
</html>"""
    
    template_file = template_dir / "forensic_report.html"
    with open(template_file, 'w', encoding='utf-8') as f:
        f.write(html_template)
    
    return template_dir


# Initialize templates on import
try:
    create_default_template_dir()
except Exception as e:
    logging.getLogger(__name__).warning(f"Could not create default templates: {e}")