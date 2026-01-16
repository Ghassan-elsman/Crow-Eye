"""
Semantic Mapping System

Unified module for semantic value mappings in correlation results.
Maps technical values (e.g., Event IDs, status codes, file patterns) to human-readable semantic meanings.

This module provides:
- SemanticMapping: Basic semantic value mapping with pattern matching
- SemanticCondition: Single condition for advanced multi-value rules
- SemanticRule: Advanced semantic rule with AND/OR logic and wildcard support
- SemanticMappingManager: Manager for all semantic mappings

Features:
- Artifact-specific mappings for ALL forensic artifacts
- Pattern matching with regex support
- Multi-field conditional matching
- AND/OR logic for complex rules
- Wildcard (*) support for "any value" matching
- Confidence scoring
- Mapping source tracking (global/wing/pipeline/built-in)
"""

import json
import logging
import re
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# BASIC SEMANTIC MAPPING
# =============================================================================

@dataclass
class SemanticMapping:
    """
    Basic semantic value mapping with universal artifact support.
    
    Maps technical values to human-readable semantic meanings with support for:
    - Pattern matching (regex)
    - Multi-field conditions
    - Confidence scoring
    - Artifact-specific rules
    
    Attributes:
        source: Source of the value (e.g., "SecurityLogs", "Prefetch")
        field: Field name (e.g., "EventID", "executable_name")
        technical_value: Technical value to match (e.g., "4624", "chrome.exe")
        semantic_value: Human-readable meaning (e.g., "User Login", "Web Browser")
        description: Optional detailed description
        artifact_type: Artifact type for filtering
        category: Semantic category
        severity: Severity level
        pattern: Regex pattern for matching (empty = exact match)
        conditions: Multi-field conditions
        confidence: Confidence score (0.0 to 1.0)
        mapping_source: Source of mapping (built-in, global, wing)
        scope: Scope of mapping (global, wing, pipeline)
        wing_id: Wing ID if scope is "wing"
        pipeline_id: Pipeline ID if scope is "pipeline"
    """
    source: str
    field: str
    technical_value: str
    semantic_value: str
    description: str = ""
    
    # Enhanced fields
    artifact_type: str = ""
    category: str = ""
    severity: str = "info"
    pattern: str = ""
    conditions: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0
    mapping_source: str = "built-in"
    
    # Scope fields
    scope: str = "global"
    wing_id: Optional[str] = None
    pipeline_id: Optional[str] = None
    
    # Compiled pattern cache (not serialized)
    _compiled_pattern: Optional[re.Pattern] = field(default=None, init=False, repr=False)
    
    def compile_pattern(self):
        """Compile regex pattern for efficient matching."""
        if self.pattern and not self._compiled_pattern:
            try:
                self._compiled_pattern = re.compile(self.pattern, re.IGNORECASE)
            except re.error as e:
                logger.error(f"Invalid regex pattern '{self.pattern}': {e}")
                self._compiled_pattern = None
    
    def matches(self, value: str) -> bool:
        """
        Check if value matches this mapping.
        
        Args:
            value: Value to check
            
        Returns:
            True if matches, False otherwise
        """
        if self.pattern:
            if not self._compiled_pattern:
                self.compile_pattern()
            if self._compiled_pattern:
                return bool(self._compiled_pattern.search(value))
            return False
        else:
            return value.lower() == self.technical_value.lower()
    
    def evaluate_conditions(self, record: Dict[str, Any]) -> bool:
        """
        Evaluate multi-field conditions against a record.
        
        Args:
            record: Record dictionary to evaluate
            
        Returns:
            True if all conditions match, False otherwise
        """
        if not self.conditions:
            return True
        
        for condition in self.conditions:
            field_name = condition.get("field")
            operator = condition.get("operator", "equals")
            expected_value = condition.get("value")
            
            if field_name not in record:
                return False
            
            actual_value = record[field_name]
            
            if operator == "equals":
                if str(actual_value).lower() != str(expected_value).lower():
                    return False
            elif operator == "in":
                if str(actual_value) not in expected_value:
                    return False
            elif operator == "regex":
                if not re.search(expected_value, str(actual_value), re.IGNORECASE):
                    return False
            elif operator == "greater_than":
                try:
                    if float(actual_value) <= float(expected_value):
                        return False
                except (ValueError, TypeError):
                    return False
            elif operator == "less_than":
                try:
                    if float(actual_value) >= float(expected_value):
                        return False
                except (ValueError, TypeError):
                    return False
            elif operator == "contains":
                if expected_value.lower() not in str(actual_value).lower():
                    return False
        
        return True


# =============================================================================
# ADVANCED SEMANTIC RULES (Multi-Value with AND/OR Logic)
# =============================================================================

@dataclass
class SemanticCondition:
    """
    Single condition in a multi-value semantic rule.
    
    Supports multiple operators for flexible matching:
    - equals: Exact match (case-insensitive)
    - contains: Substring match (case-insensitive)
    - regex: Regular expression match
    - wildcard: Match any non-empty value (when value is "*")
    
    Attributes:
        feather_id: ID of the feather this condition applies to
        field_name: Name of the field to match
        value: Value to match, or "*" for wildcard
        operator: Match operator (equals, contains, regex, wildcard)
    """
    feather_id: str
    field_name: str
    value: str
    operator: str = "equals"
    
    # Compiled pattern cache (not serialized)
    _compiled_pattern: Optional[re.Pattern] = field(default=None, init=False, repr=False, compare=False)
    
    def __post_init__(self):
        """Post-initialization processing."""
        if self.value == "*" and self.operator == "equals":
            self.operator = "wildcard"
        if self.operator == "regex":
            self._compile_pattern()
    
    def _compile_pattern(self):
        """Compile regex pattern for efficient matching."""
        if self.operator == "regex" and self.value and not self._compiled_pattern:
            try:
                self._compiled_pattern = re.compile(self.value, re.IGNORECASE)
            except re.error as e:
                logger.error(f"Invalid regex pattern '{self.value}': {e}")
                self._compiled_pattern = None
    
    def matches(self, record: Dict[str, Any]) -> bool:
        """
        Check if this condition matches the record with SMART field name matching.
        
        Smart matching handles field name variations from different forensic tools:
        - Case-insensitive field names (EventID, eventid, event_id)
        - Underscore/CamelCase variations (target_path, TargetPath, targetpath)
        - Common abbreviations and synonyms
        
        Args:
            record: Dictionary containing field values to match against
            
        Returns:
            True if the condition matches, False otherwise
        """
        # Smart field name lookup - find the actual field in the record
        field_value = self._smart_field_lookup(record, self.field_name)
        
        if field_value is None:
            return False
        
        field_value_str = str(field_value)
        
        # Wildcard matching
        if self.value == "*" or self.operator == "wildcard":
            return bool(field_value_str.strip())
        
        # Equals matching (case-insensitive)
        if self.operator == "equals":
            return field_value_str.lower() == self.value.lower()
        
        # Contains matching (case-insensitive)
        if self.operator == "contains":
            return self.value.lower() in field_value_str.lower()
        
        # Regex matching
        if self.operator == "regex":
            if not self._compiled_pattern:
                self._compile_pattern()
            if self._compiled_pattern:
                return bool(self._compiled_pattern.search(field_value_str))
            return False
        
        # Default to equals
        return field_value_str.lower() == self.value.lower()
    
    def _smart_field_lookup(self, record: Dict[str, Any], field_name: str) -> Optional[Any]:
        """
        Smart field lookup that handles field name variations from different tools.
        
        Matching strategy (in order of priority):
        1. Exact match
        2. Case-insensitive match
        3. Normalized match (remove underscores, lowercase)
        4. Synonym/alias match (e.g., 'url' matches 'visited_url', 'address')
        
        Args:
            record: Dictionary containing field values
            field_name: The field name to look for
            
        Returns:
            The field value if found, None otherwise
        """
        # 1. Exact match
        if field_name in record:
            return record[field_name]
        
        # 2. Case-insensitive match
        field_name_lower = field_name.lower()
        for key in record.keys():
            if key.lower() == field_name_lower:
                return record[key]
        
        # 3. Normalized match (remove underscores, spaces, dashes)
        normalized_target = self._normalize_field_name(field_name)
        for key in record.keys():
            if self._normalize_field_name(key) == normalized_target:
                return record[key]
        
        # 4. Synonym/alias match
        aliases = self._get_field_aliases(field_name)
        for alias in aliases:
            # Try exact alias match
            if alias in record:
                return record[alias]
            # Try normalized alias match
            normalized_alias = self._normalize_field_name(alias)
            for key in record.keys():
                if self._normalize_field_name(key) == normalized_alias:
                    return record[key]
        
        return None
    
    @staticmethod
    def _normalize_field_name(name: str) -> str:
        """
        Normalize field name for comparison.
        
        Removes underscores, dashes, spaces, dots and converts to lowercase.
        Examples:
            'EventID' -> 'eventid'
            'event_id' -> 'eventid'
            'Event_ID' -> 'eventid'
            'target_path' -> 'targetpath'
            'TargetPath' -> 'targetpath'
        """
        return name.lower().replace('_', '').replace('-', '').replace(' ', '').replace('.', '')
    
    @staticmethod
    def _get_field_aliases(field_name: str) -> List[str]:
        """
        Get common aliases/synonyms for a field name.
        
        Different forensic tools use different names for the same data.
        This provides a mapping of common variations.
        """
        # Normalize the input for lookup
        normalized = SemanticCondition._normalize_field_name(field_name)
        
        # Common field name aliases grouped by semantic meaning
        alias_groups = {
            # =================================================================
            # EVENT/LOG IDENTIFIERS
            # =================================================================
            'eventid': [
                'EventID', 'Event_ID', 'event_id', 'eventid', 'Id', 'ID', 'id',
                'event_code', 'EventCode', 'eventcode', 'code', 'Code',
                'event_type', 'EventType', 'eventtype', 'type_id', 'TypeID',
                'log_id', 'LogID', 'logid', 'record_id', 'RecordID', 'recordid',
                'message_id', 'MessageID', 'messageid', 'evt_id', 'EvtID',
                'event_number', 'EventNumber', 'eventnumber', 'evtx_id', 'EvtxID'
            ],
            
            'eventtype': [
                'EventType', 'event_type', 'eventtype', 'type', 'Type',
                'log_type', 'LogType', 'logtype', 'category', 'Category',
                'event_category', 'EventCategory', 'eventcategory'
            ],
            
            'channel': [
                'Channel', 'channel', 'log_name', 'LogName', 'logname',
                'source', 'Source', 'provider', 'Provider', 'log_source', 'LogSource'
            ],
            
            # =================================================================
            # EXECUTABLE/PROCESS NAMES
            # =================================================================
            'executablename': [
                'executable_name', 'ExecutableName', 'executablename', 'Executable', 'executable',
                'exe_name', 'ExeName', 'exename', 'exe', 'Exe', 'EXE',
                'filename', 'FileName', 'file_name', 'Filename', 'name', 'Name',
                'process_name', 'ProcessName', 'processname', 'process', 'Process',
                'image', 'Image', 'image_name', 'ImageName', 'imagename',
                'image_path', 'ImagePath', 'imagepath', 'binary', 'Binary',
                'binary_name', 'BinaryName', 'binaryname', 'app_name', 'AppName', 'appname',
                'application', 'Application', 'application_name', 'ApplicationName',
                'program', 'Program', 'program_name', 'ProgramName', 'programname',
                'command', 'Command', 'cmd', 'Cmd', 'CMD',
                'new_process_name', 'NewProcessName', 'newprocessname',
                'target_filename', 'TargetFilename', 'targetfilename'
            ],
            
            'filename': [
                'filename', 'FileName', 'file_name', 'Filename', 'name', 'Name',
                'file', 'File', 'fname', 'FName', 'f_name', 'document', 'Document',
                'document_name', 'DocumentName', 'documentname', 'object_name', 'ObjectName'
            ],
            
            'processid': [
                'ProcessID', 'process_id', 'processid', 'pid', 'PID', 'Pid',
                'process_identifier', 'ProcessIdentifier', 'proc_id', 'ProcID',
                'new_process_id', 'NewProcessID', 'newprocessid'
            ],
            
            'parentprocessid': [
                'ParentProcessID', 'parent_process_id', 'parentprocessid', 'ppid', 'PPID',
                'parent_pid', 'ParentPID', 'parentpid', 'creator_process_id', 'CreatorProcessID'
            ],
            
            'commandline': [
                'CommandLine', 'command_line', 'commandline', 'cmd_line', 'CmdLine', 'cmdline',
                'command', 'Command', 'arguments', 'Arguments', 'args', 'Args',
                'parameters', 'Parameters', 'params', 'Params', 'process_command_line',
                'ProcessCommandLine', 'processcommandline'
            ],
            
            # =================================================================
            # FILE PATHS
            # =================================================================
            'targetpath': [
                'target_path', 'TargetPath', 'targetpath', 'target', 'Target',
                'path', 'Path', 'file_path', 'FilePath', 'filepath',
                'full_path', 'FullPath', 'fullpath', 'absolute_path', 'AbsolutePath',
                'location', 'Location', 'file_location', 'FileLocation', 'filelocation',
                'destination', 'Destination', 'dest_path', 'DestPath', 'destpath',
                'target_file', 'TargetFile', 'targetfile', 'object_path', 'ObjectPath',
                'link_target', 'LinkTarget', 'linktarget', 'shortcut_target', 'ShortcutTarget'
            ],
            
            'path': [
                'path', 'Path', 'folder_path', 'FolderPath', 'folderpath',
                'directory', 'Directory', 'dir', 'Dir', 'folder', 'Folder',
                'location', 'Location', 'file_path', 'FilePath', 'filepath',
                'full_path', 'FullPath', 'fullpath', 'absolute_path', 'AbsolutePath',
                'shell_path', 'ShellPath', 'shellpath', 'accessed_path', 'AccessedPath'
            ],
            
            'sourcepath': [
                'source_path', 'SourcePath', 'sourcepath', 'source', 'Source',
                'src_path', 'SrcPath', 'srcpath', 'src', 'Src', 'origin', 'Origin',
                'original_path', 'OriginalPath', 'originalpath', 'from_path', 'FromPath'
            ],
            
            # =================================================================
            # REGISTRY
            # =================================================================
            'keypath': [
                'key_path', 'KeyPath', 'keypath', 'registry_key', 'RegistryKey', 'registrykey',
                'key', 'Key', 'reg_key', 'RegKey', 'regkey', 'hive_path', 'HivePath', 'hivepath',
                'registry_path', 'RegistryPath', 'registrypath', 'reg_path', 'RegPath', 'regpath',
                'target_object', 'TargetObject', 'targetobject', 'object', 'Object',
                'registry_hive', 'RegistryHive', 'registryhive', 'hive', 'Hive'
            ],
            
            'valuename': [
                'value_name', 'ValueName', 'valuename', 'value', 'Value',
                'registry_value', 'RegistryValue', 'registryvalue', 'reg_value', 'RegValue',
                'data_name', 'DataName', 'dataname', 'entry', 'Entry'
            ],
            
            'valuedata': [
                'value_data', 'ValueData', 'valuedata', 'data', 'Data',
                'registry_data', 'RegistryData', 'registrydata', 'content', 'Content',
                'details', 'Details', 'new_value', 'NewValue', 'newvalue'
            ],
            
            # =================================================================
            # NETWORK
            # =================================================================
            'remoteaddress': [
                'remote_address', 'RemoteAddress', 'remoteaddress', 'remote_ip', 'RemoteIP', 'remoteip',
                'destination_ip', 'DestinationIP', 'destinationip', 'dest_ip', 'DestIP', 'destip',
                'dst_ip', 'DstIP', 'dstip', 'dst_addr', 'DstAddr', 'dstaddr',
                'target_ip', 'TargetIP', 'targetip', 'ip_address', 'IPAddress', 'ipaddress',
                'ip', 'IP', 'Ip', 'address', 'Address', 'host', 'Host',
                'destination_address', 'DestinationAddress', 'destinationaddress',
                'remote_host', 'RemoteHost', 'remotehost', 'server', 'Server',
                'server_ip', 'ServerIP', 'serverip', 'external_ip', 'ExternalIP', 'externalip'
            ],
            
            'sourceaddress': [
                'source_address', 'SourceAddress', 'sourceaddress', 'source_ip', 'SourceIP', 'sourceip',
                'src_ip', 'SrcIP', 'srcip', 'src_addr', 'SrcAddr', 'srcaddr',
                'local_ip', 'LocalIP', 'localip', 'local_address', 'LocalAddress', 'localaddress',
                'client_ip', 'ClientIP', 'clientip', 'origin_ip', 'OriginIP', 'originip',
                'internal_ip', 'InternalIP', 'internalip'
            ],
            
            'remoteport': [
                'remote_port', 'RemotePort', 'remoteport', 'destination_port', 'DestinationPort',
                'dest_port', 'DestPort', 'destport', 'dst_port', 'DstPort', 'dstport',
                'target_port', 'TargetPort', 'targetport', 'server_port', 'ServerPort', 'serverport',
                'port', 'Port'
            ],
            
            'sourceport': [
                'source_port', 'SourcePort', 'sourceport', 'src_port', 'SrcPort', 'srcport',
                'local_port', 'LocalPort', 'localport', 'client_port', 'ClientPort', 'clientport',
                'origin_port', 'OriginPort', 'originport'
            ],
            
            'protocol': [
                'protocol', 'Protocol', 'proto', 'Proto', 'network_protocol', 'NetworkProtocol',
                'ip_protocol', 'IPProtocol', 'ipprotocol', 'transport', 'Transport'
            ],
            
            # =================================================================
            # URL/WEB
            # =================================================================
            'url': [
                'url', 'URL', 'Url', 'visited_url', 'VisitedUrl', 'visitedurl',
                'address', 'Address', 'web_address', 'WebAddress', 'webaddress',
                'link', 'Link', 'uri', 'URI', 'Uri', 'href', 'Href', 'HREF',
                'site', 'Site', 'website', 'Website', 'web_site', 'WebSite',
                'page_url', 'PageUrl', 'pageurl', 'page', 'Page',
                'target_url', 'TargetUrl', 'targeturl', 'destination_url', 'DestinationUrl',
                'request_url', 'RequestUrl', 'requesturl', 'location', 'Location'
            ],
            
            'domain': [
                'domain', 'Domain', 'host', 'Host', 'hostname', 'HostName', 'host_name',
                'server', 'Server', 'server_name', 'ServerName', 'servername',
                'site', 'Site', 'website', 'Website', 'fqdn', 'FQDN', 'Fqdn'
            ],
            
            # =================================================================
            # TIMESTAMPS
            # =================================================================
            'timestamp': [
                'timestamp', 'Timestamp', 'TimeStamp', 'time_stamp',
                'time', 'Time', 'datetime', 'DateTime', 'date_time', 'Datetime',
                'date', 'Date', 'event_time', 'EventTime', 'eventtime',
                'log_time', 'LogTime', 'logtime', 'record_time', 'RecordTime', 'recordtime',
                'generated_time', 'GeneratedTime', 'generatedtime', 'when', 'When',
                'occurred', 'Occurred', 'occurred_time', 'OccurredTime'
            ],
            
            'createdtime': [
                'created_time', 'CreatedTime', 'createdtime', 'creation_time', 'CreationTime',
                'create_time', 'CreateTime', 'createtime', 'birth_time', 'BirthTime', 'birthtime',
                'created', 'Created', 'created_date', 'CreatedDate', 'createddate',
                'creation_date', 'CreationDate', 'creationdate', 'date_created', 'DateCreated',
                'fn_created', 'FNCreated', 'si_created', 'SICreated'
            ],
            
            'modifiedtime': [
                'modified_time', 'ModifiedTime', 'modifiedtime', 'modification_time', 'ModificationTime',
                'modify_time', 'ModifyTime', 'modifytime', 'modified', 'Modified',
                'last_modified', 'LastModified', 'lastmodified', 'modified_date', 'ModifiedDate',
                'change_time', 'ChangeTime', 'changetime', 'updated', 'Updated',
                'update_time', 'UpdateTime', 'updatetime', 'last_write', 'LastWrite', 'lastwrite',
                'fn_modified', 'FNModified', 'si_modified', 'SIModified'
            ],
            
            'accessedtime': [
                'accessed_time', 'AccessedTime', 'accessedtime', 'access_time', 'AccessTime',
                'last_accessed', 'LastAccessed', 'lastaccessed', 'accessed', 'Accessed',
                'last_access', 'LastAccess', 'lastaccess', 'read_time', 'ReadTime', 'readtime',
                'fn_accessed', 'FNAccessed', 'si_accessed', 'SIAccessed'
            ],
            
            # =================================================================
            # USER/ACCOUNT
            # =================================================================
            'username': [
                'username', 'UserName', 'user_name', 'Username', 'user', 'User',
                'account_name', 'AccountName', 'accountname', 'account', 'Account',
                'logon_name', 'LogonName', 'logonname', 'login_name', 'LoginName', 'loginname',
                'subject_user_name', 'SubjectUserName', 'subjectusername',
                'target_user_name', 'TargetUserName', 'targetusername',
                'owner', 'Owner', 'owner_name', 'OwnerName', 'ownername',
                'principal', 'Principal', 'identity', 'Identity', 'sid_name', 'SIDName'
            ],
            
            'usersid': [
                'user_sid', 'UserSID', 'usersid', 'sid', 'SID', 'Sid',
                'security_id', 'SecurityID', 'securityid', 'subject_user_sid', 'SubjectUserSID',
                'target_user_sid', 'TargetUserSID', 'account_sid', 'AccountSID', 'accountsid',
                'owner_sid', 'OwnerSID', 'ownersid'
            ],
            
            'userdomain': [
                'user_domain', 'UserDomain', 'userdomain', 'domain', 'Domain',
                'account_domain', 'AccountDomain', 'accountdomain', 'logon_domain', 'LogonDomain',
                'subject_domain_name', 'SubjectDomainName', 'target_domain_name', 'TargetDomainName',
                'workgroup', 'Workgroup', 'realm', 'Realm'
            ],
            
            # =================================================================
            # AUTHENTICATION
            # =================================================================
            'logontype': [
                'LogonType', 'logon_type', 'logontype', 'login_type', 'LoginType', 'logintype',
                'type', 'Type', 'auth_type', 'AuthType', 'authtype',
                'authentication_type', 'AuthenticationType', 'authenticationtype',
                'logon_method', 'LogonMethod', 'logonmethod', 'access_type', 'AccessType'
            ],
            
            'logonid': [
                'LogonID', 'logon_id', 'logonid', 'login_id', 'LoginID', 'loginid',
                'session_id', 'SessionID', 'sessionid', 'subject_logon_id', 'SubjectLogonID',
                'target_logon_id', 'TargetLogonID', 'auth_id', 'AuthID', 'authid'
            ],
            
            'status': [
                'status', 'Status', 'result', 'Result', 'outcome', 'Outcome',
                'success', 'Success', 'failure', 'Failure', 'error_code', 'ErrorCode',
                'return_code', 'ReturnCode', 'returncode', 'exit_code', 'ExitCode', 'exitcode',
                'status_code', 'StatusCode', 'statuscode', 'response_code', 'ResponseCode'
            ],
            
            # =================================================================
            # FILE SYSTEM
            # =================================================================
            'reason': [
                'reason', 'Reason', 'action', 'Action', 'operation', 'Operation',
                'change_reason', 'ChangeReason', 'changereason', 'update_reason', 'UpdateReason',
                'usn_reason', 'USNReason', 'usnreason', 'file_action', 'FileAction', 'fileaction',
                'event_action', 'EventAction', 'eventaction', 'activity', 'Activity',
                'change_type', 'ChangeType', 'changetype', 'modification_type', 'ModificationType'
            ],
            
            'size': [
                'size', 'Size', 'file_size', 'FileSize', 'filesize',
                'length', 'Length', 'bytes', 'Bytes', 'byte_count', 'ByteCount', 'bytecount',
                'data_size', 'DataSize', 'datasize', 'content_length', 'ContentLength',
                'allocated_size', 'AllocatedSize', 'allocatedsize', 'logical_size', 'LogicalSize'
            ],
            
            'hash': [
                'hash', 'Hash', 'md5', 'MD5', 'Md5', 'sha1', 'SHA1', 'Sha1',
                'sha256', 'SHA256', 'Sha256', 'sha512', 'SHA512', 'Sha512',
                'file_hash', 'FileHash', 'filehash', 'checksum', 'Checksum',
                'digest', 'Digest', 'imphash', 'ImpHash', 'imphash',
                'hash_value', 'HashValue', 'hashvalue', 'hashes', 'Hashes'
            ],
            
            'extension': [
                'extension', 'Extension', 'ext', 'Ext', 'file_extension', 'FileExtension',
                'file_ext', 'FileExt', 'fileext', 'suffix', 'Suffix'
            ],
            
            # =================================================================
            # DEVICE/HARDWARE
            # =================================================================
            'devicename': [
                'device_name', 'DeviceName', 'devicename', 'device', 'Device',
                'hardware_name', 'HardwareName', 'hardwarename', 'drive', 'Drive',
                'drive_name', 'DriveName', 'drivename', 'volume', 'Volume',
                'volume_name', 'VolumeName', 'volumename', 'disk', 'Disk',
                'disk_name', 'DiskName', 'diskname', 'media', 'Media'
            ],
            
            'serialnumber': [
                'serial_number', 'SerialNumber', 'serialnumber', 'serial', 'Serial',
                'device_serial', 'DeviceSerial', 'deviceserial', 'sn', 'SN',
                'hardware_id', 'HardwareID', 'hardwareid', 'device_id', 'DeviceID', 'deviceid',
                'unique_id', 'UniqueID', 'uniqueid', 'instance_id', 'InstanceID', 'instanceid'
            ],
            
            'vendorid': [
                'vendor_id', 'VendorID', 'vendorid', 'vendor', 'Vendor',
                'manufacturer', 'Manufacturer', 'make', 'Make', 'brand', 'Brand',
                'vid', 'VID', 'Vid'
            ],
            
            'productid': [
                'product_id', 'ProductID', 'productid', 'product', 'Product',
                'model', 'Model', 'pid', 'PID', 'Pid', 'device_model', 'DeviceModel'
            ],
            
            # =================================================================
            # BROWSER/WEB HISTORY
            # =================================================================
            'title': [
                'title', 'Title', 'page_title', 'PageTitle', 'pagetitle',
                'document_title', 'DocumentTitle', 'documenttitle', 'name', 'Name',
                'heading', 'Heading', 'subject', 'Subject', 'caption', 'Caption'
            ],
            
            'visitcount': [
                'visit_count', 'VisitCount', 'visitcount', 'visits', 'Visits',
                'count', 'Count', 'access_count', 'AccessCount', 'accesscount',
                'hit_count', 'HitCount', 'hitcount', 'frequency', 'Frequency'
            ],
            
            'referrer': [
                'referrer', 'Referrer', 'referer', 'Referer', 'referring_url', 'ReferringUrl',
                'source_url', 'SourceUrl', 'sourceurl', 'from_url', 'FromUrl', 'fromurl',
                'previous_url', 'PreviousUrl', 'previousurl', 'origin_url', 'OriginUrl'
            ],
            
            # =================================================================
            # MISCELLANEOUS
            # =================================================================
            'description': [
                'description', 'Description', 'desc', 'Desc', 'details', 'Details',
                'message', 'Message', 'msg', 'Msg', 'text', 'Text',
                'comment', 'Comment', 'note', 'Note', 'notes', 'Notes',
                'info', 'Info', 'information', 'Information', 'summary', 'Summary'
            ],
            
            'version': [
                'version', 'Version', 'ver', 'Ver', 'file_version', 'FileVersion',
                'product_version', 'ProductVersion', 'productversion', 'build', 'Build',
                'revision', 'Revision', 'release', 'Release'
            ],
            
            'company': [
                'company', 'Company', 'company_name', 'CompanyName', 'companyname',
                'publisher', 'Publisher', 'vendor', 'Vendor', 'manufacturer', 'Manufacturer',
                'developer', 'Developer', 'author', 'Author', 'creator', 'Creator'
            ],
        }
        
        # Find which group this field belongs to
        for group_key, aliases in alias_groups.items():
            # Check if the normalized field name matches the group key
            if normalized == group_key:
                return aliases
            # Check if the normalized field name matches any alias in the group
            for alias in aliases:
                if SemanticCondition._normalize_field_name(alias) == normalized:
                    return aliases
        
        # No aliases found - try fuzzy matching as fallback
        return SemanticCondition._fuzzy_find_aliases(field_name, alias_groups)
    
    @staticmethod
    def _fuzzy_find_aliases(field_name: str, alias_groups: Dict[str, List[str]]) -> List[str]:
        """
        Fuzzy matching to find aliases when exact match fails.
        Uses substring matching and common word detection.
        """
        normalized = SemanticCondition._normalize_field_name(field_name)
        
        # Common words that indicate field type
        keyword_mappings = {
            'event': ['eventid', 'eventtype'],
            'process': ['executablename', 'processid', 'commandline'],
            'file': ['filename', 'path', 'targetpath', 'size', 'hash', 'extension'],
            'path': ['path', 'targetpath', 'sourcepath', 'keypath'],
            'user': ['username', 'usersid', 'userdomain'],
            'time': ['timestamp', 'createdtime', 'modifiedtime', 'accessedtime'],
            'date': ['timestamp', 'createdtime', 'modifiedtime'],
            'ip': ['remoteaddress', 'sourceaddress'],
            'port': ['remoteport', 'sourceport'],
            'url': ['url', 'domain'],
            'registry': ['keypath', 'valuename', 'valuedata'],
            'reg': ['keypath', 'valuename', 'valuedata'],
            'hash': ['hash'],
            'device': ['devicename', 'serialnumber'],
            'logon': ['logontype', 'logonid', 'username'],
            'login': ['logontype', 'logonid', 'username'],
            'address': ['remoteaddress', 'sourceaddress', 'url'],
            'name': ['filename', 'username', 'executablename', 'devicename'],
            'id': ['eventid', 'processid', 'logonid', 'usersid'],
            'exe': ['executablename', 'commandline'],
            'cmd': ['commandline', 'executablename'],
            'src': ['sourceaddress', 'sourceport', 'sourcepath'],
            'dst': ['remoteaddress', 'remoteport', 'targetpath'],
            'dest': ['remoteaddress', 'remoteport', 'targetpath'],
            'remote': ['remoteaddress', 'remoteport'],
            'local': ['sourceaddress', 'sourceport'],
            'target': ['targetpath', 'remoteaddress'],
            'source': ['sourcepath', 'sourceaddress'],
            'created': ['createdtime'],
            'modified': ['modifiedtime'],
            'accessed': ['accessedtime'],
            'account': ['username', 'usersid'],
            'sid': ['usersid'],
            'domain': ['userdomain', 'domain'],
            'host': ['domain', 'remoteaddress'],
            'server': ['domain', 'remoteaddress'],
        }
        
        # Check if any keyword is in the field name
        for keyword, group_keys in keyword_mappings.items():
            if keyword in normalized:
                for group_key in group_keys:
                    if group_key in alias_groups:
                        return alias_groups[group_key]
        
        return []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'feather_id': self.feather_id,
            'field_name': self.field_name,
            'value': self.value,
            'operator': self.operator
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SemanticCondition':
        """Create SemanticCondition from dictionary."""
        required_fields = ['feather_id', 'field_name', 'value']
        missing_fields = [f for f in required_fields if f not in data]
        if missing_fields:
            raise ValueError(f"Missing required fields: {missing_fields}")
        
        return cls(
            feather_id=data['feather_id'],
            field_name=data['field_name'],
            value=data['value'],
            operator=data.get('operator', 'equals')
        )
    
    def __str__(self) -> str:
        """Human-readable string representation."""
        if self.operator == "wildcard" or self.value == "*":
            return f"{self.feather_id}.{self.field_name} has any value"
        return f"{self.feather_id}.{self.field_name} {self.operator} '{self.value}'"



@dataclass
class SemanticRule:
    """
    Advanced semantic rule with multi-value support.
    
    Supports:
    - Multiple conditions with AND/OR logic
    - Wildcard matching for "any value" patterns
    - Scope-based rules (global, wing, pipeline)
    - Confidence scoring and severity levels
    
    Attributes:
        rule_id: Unique identifier for the rule
        name: Human-readable name
        semantic_value: Result value when rule matches
        description: Detailed description of the rule
        conditions: List of conditions to evaluate
        logic_operator: "AND" or "OR" for combining conditions
        scope: Rule scope (global, wing, pipeline)
        wing_id: Wing ID if scope is "wing"
        pipeline_id: Pipeline ID if scope is "pipeline"
        category: Semantic category
        severity: Severity level (info, low, medium, high, critical)
        confidence: Confidence score (0.0 to 1.0)
    """
    rule_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    semantic_value: str = ""
    description: str = ""
    
    # Multi-value conditions
    conditions: List[SemanticCondition] = field(default_factory=list)
    logic_operator: str = "AND"
    
    # Scope
    scope: str = "global"
    wing_id: Optional[str] = None
    pipeline_id: Optional[str] = None
    
    # Metadata
    category: str = ""
    severity: str = "info"
    confidence: float = 1.0
    
    def __post_init__(self):
        """Post-initialization validation."""
        self.logic_operator = self.logic_operator.upper()
        if self.logic_operator not in ("AND", "OR"):
            logger.warning(f"Invalid logic operator '{self.logic_operator}', defaulting to AND")
            self.logic_operator = "AND"
        
        if not 0.0 <= self.confidence <= 1.0:
            logger.warning(f"Confidence {self.confidence} out of range, clamping to [0.0, 1.0]")
            self.confidence = max(0.0, min(1.0, self.confidence))
    
    def evaluate(self, records: Dict[str, Dict[str, Any]]) -> Tuple[bool, List[str]]:
        """
        Evaluate rule against records from multiple feathers.
        
        Args:
            records: Dict mapping feather_id to record data
            
        Returns:
            Tuple of (matches: bool, matched_conditions: List[str])
        """
        if not self.conditions:
            return True, []
        
        matched_conditions = []
        
        for condition in self.conditions:
            record = records.get(condition.feather_id, {})
            if condition.matches(record):
                matched_conditions.append(f"{condition.feather_id}.{condition.field_name}")
        
        if self.logic_operator == "AND":
            matches = len(matched_conditions) == len(self.conditions)
        else:
            matches = len(matched_conditions) > 0
        
        return matches, matched_conditions
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'rule_id': self.rule_id,
            'name': self.name,
            'semantic_value': self.semantic_value,
            'description': self.description,
            'conditions': [c.to_dict() for c in self.conditions],
            'logic_operator': self.logic_operator,
            'scope': self.scope,
            'wing_id': self.wing_id,
            'pipeline_id': self.pipeline_id,
            'category': self.category,
            'severity': self.severity,
            'confidence': self.confidence
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SemanticRule':
        """Create SemanticRule from dictionary."""
        required_fields = ['rule_id', 'semantic_value', 'conditions']
        missing_fields = [f for f in required_fields if f not in data]
        if missing_fields:
            raise ValueError(f"Missing required fields: {missing_fields}")
        
        conditions = []
        for cond_data in data.get('conditions', []):
            try:
                conditions.append(SemanticCondition.from_dict(cond_data))
            except ValueError as e:
                raise ValueError(f"Invalid condition in rule: {e}")
        
        return cls(
            rule_id=data['rule_id'],
            name=data.get('name', ''),
            semantic_value=data['semantic_value'],
            description=data.get('description', ''),
            conditions=conditions,
            logic_operator=data.get('logic_operator', 'AND'),
            scope=data.get('scope', 'global'),
            wing_id=data.get('wing_id'),
            pipeline_id=data.get('pipeline_id'),
            category=data.get('category', ''),
            severity=data.get('severity', 'info'),
            confidence=data.get('confidence', 1.0)
        )
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'SemanticRule':
        """Create SemanticRule from JSON string."""
        return cls.from_dict(json.loads(json_str))
    
    def get_human_readable(self) -> str:
        """Get human-readable description of the rule."""
        if not self.conditions:
            return f"'{self.name}' → {self.semantic_value} (always matches)"
        
        condition_strs = [str(c) for c in self.conditions]
        logic_word = " AND " if self.logic_operator == "AND" else " OR "
        conditions_text = logic_word.join(condition_strs)
        
        return f"'{self.name}': IF {conditions_text} THEN → {self.semantic_value}"
    
    def __str__(self) -> str:
        return self.get_human_readable()


# =============================================================================
# SEMANTIC MAPPING MANAGER
# =============================================================================

class SemanticMappingManager:
    """
    Unified semantic mapping manager.
    
    Provides hierarchical mapping system with:
    1. Global mappings (apply to all Wings)
    2. Pipeline-specific mappings (apply to all Wings in a Pipeline)
    3. Wing-specific mappings (apply only to that Wing)
    
    Priority: Wing-specific > Pipeline-specific > Global
    
    Features:
    - Artifact-specific mapping index for efficient lookup
    - Pattern matching with compiled regex
    - Multi-field conditional matching
    - Advanced rules with AND/OR logic
    - Confidence scoring
    """
    
    def __init__(self):
        """Initialize SemanticMappingManager."""
        # Basic mappings storage
        self.global_mappings: Dict[str, List[SemanticMapping]] = {}
        self.wing_mappings: Dict[str, List[SemanticMapping]] = {}
        self.pipeline_mappings: Dict[str, List[SemanticMapping]] = {}
        
        # Artifact-specific mapping index
        self.artifact_mappings: Dict[str, List[SemanticMapping]] = {}
        
        # Advanced rules storage
        self.global_rules: List[SemanticRule] = []
        self.wing_rules: Dict[str, List[SemanticRule]] = {}
        self.pipeline_rules: Dict[str, List[SemanticRule]] = {}
        
        # Compiled pattern cache
        self.pattern_cache: Dict[str, re.Pattern] = {}
        
        # JSON configuration paths
        self.config_dir = Path("Crow-Eye/configs")
        self.default_rules_path = self.config_dir / "semantic_rules_default.json"
        self.custom_rules_path = self.config_dir / "semantic_rules_custom.json"
        
        # Load default mappings and rules
        self._load_default_mappings()
        self._load_default_rules()
        
        # Load rules from JSON files
        self._load_rules_from_json()
    
    def _load_default_rules(self):
        """
        Load default semantic rules for forensic investigators.
        
        These rules use AND/OR logic to identify common user activities:
        - User Activity (login, logoff, session lock/unlock)
        - File Operations (file access, creation, deletion)
        - Application Execution (app run, app close)
        - System Events (startup, shutdown, sleep, wake)
        - Suspicious Activity (failed logins, privilege escalation)
        """
        default_rules = []
        
        # =================================================================
        # USER ACTIVITY RULES
        # =================================================================
        
        # User Login (Interactive)
        default_rules.append(SemanticRule(
            rule_id="default-user-login-interactive",
            name="User Login (Interactive)",
            semantic_value="User Login - Interactive",
            description="User logged in interactively (Type 2) - physical access to machine",
            conditions=[
                SemanticCondition("SecurityLogs", "EventID", "4624", "equals"),
                SemanticCondition("SecurityLogs", "LogonType", "2", "equals"),
            ],
            logic_operator="AND",
            scope="global",
            category="authentication",
            severity="info",
            confidence=0.95
        ))
        
        # User Login (Remote/RDP)
        default_rules.append(SemanticRule(
            rule_id="default-user-login-remote",
            name="User Login (Remote/RDP)",
            semantic_value="User Login - Remote Desktop",
            description="User logged in via Remote Desktop (Type 10)",
            conditions=[
                SemanticCondition("SecurityLogs", "EventID", "4624", "equals"),
                SemanticCondition("SecurityLogs", "LogonType", "10", "equals"),
            ],
            logic_operator="AND",
            scope="global",
            category="authentication",
            severity="low",
            confidence=0.95
        ))
        
        # User Login (Network)
        default_rules.append(SemanticRule(
            rule_id="default-user-login-network",
            name="User Login (Network)",
            semantic_value="User Login - Network",
            description="User logged in via network (Type 3) - file share access",
            conditions=[
                SemanticCondition("SecurityLogs", "EventID", "4624", "equals"),
                SemanticCondition("SecurityLogs", "LogonType", "3", "equals"),
            ],
            logic_operator="AND",
            scope="global",
            category="authentication",
            severity="info",
            confidence=0.90
        ))
        
        # User Logoff
        default_rules.append(SemanticRule(
            rule_id="default-user-logoff",
            name="User Logoff",
            semantic_value="User Logoff",
            description="User logged off (Event 4634 or 4647)",
            conditions=[
                SemanticCondition("SecurityLogs", "EventID", "4634", "equals"),
                SemanticCondition("SecurityLogs", "EventID", "4647", "equals"),
            ],
            logic_operator="OR",
            scope="global",
            category="authentication",
            severity="info",
            confidence=0.95
        ))
        
        # Session Lock
        default_rules.append(SemanticRule(
            rule_id="default-session-lock",
            name="Session Locked",
            semantic_value="Session Locked",
            description="User locked their workstation",
            conditions=[
                SemanticCondition("SecurityLogs", "EventID", "4800", "equals"),
            ],
            logic_operator="AND",
            scope="global",
            category="authentication",
            severity="info",
            confidence=0.95
        ))
        
        # Session Unlock
        default_rules.append(SemanticRule(
            rule_id="default-session-unlock",
            name="Session Unlocked",
            semantic_value="Session Unlocked",
            description="User unlocked their workstation",
            conditions=[
                SemanticCondition("SecurityLogs", "EventID", "4801", "equals"),
            ],
            logic_operator="AND",
            scope="global",
            category="authentication",
            severity="info",
            confidence=0.95
        ))
        
        # =================================================================
        # FILE OPERATION RULES
        # =================================================================
        
        # File Access via ShellBags (folder navigation)
        default_rules.append(SemanticRule(
            rule_id="default-folder-access-shellbags",
            name="Folder Access (ShellBags)",
            semantic_value="Folder Accessed",
            description="User navigated to a folder (evidence from ShellBags)",
            conditions=[
                SemanticCondition("ShellBags", "path", "*", "wildcard"),
            ],
            logic_operator="AND",
            scope="global",
            category="file_access",
            severity="info",
            confidence=0.85
        ))
        
        # File Access via LNK (recent file)
        default_rules.append(SemanticRule(
            rule_id="default-file-access-lnk",
            name="File Accessed (LNK)",
            semantic_value="File Accessed - Recent",
            description="User accessed a file (evidence from LNK shortcut)",
            conditions=[
                SemanticCondition("LNK", "target_path", "*", "wildcard"),
            ],
            logic_operator="AND",
            scope="global",
            category="file_access",
            severity="info",
            confidence=0.90
        ))
        
        # File Creation (MFT)
        default_rules.append(SemanticRule(
            rule_id="default-file-created-mft",
            name="File Created (MFT)",
            semantic_value="File Created",
            description="New file was created (evidence from MFT)",
            conditions=[
                SemanticCondition("MFT", "file_name", "*", "wildcard"),
                SemanticCondition("MFT", "created_time", "*", "wildcard"),
            ],
            logic_operator="AND",
            scope="global",
            category="file_access",
            severity="info",
            confidence=0.85
        ))
        
        # File Deletion (USN Journal)
        default_rules.append(SemanticRule(
            rule_id="default-file-deleted-usn",
            name="File Deleted (USN)",
            semantic_value="File Deleted",
            description="File was deleted (evidence from USN Journal)",
            conditions=[
                SemanticCondition("USN", "reason", "FILE_DELETE", "contains"),
            ],
            logic_operator="AND",
            scope="global",
            category="file_access",
            severity="low",
            confidence=0.90
        ))
        
        # File Renamed (USN Journal)
        default_rules.append(SemanticRule(
            rule_id="default-file-renamed-usn",
            name="File Renamed (USN)",
            semantic_value="File Renamed",
            description="File was renamed (evidence from USN Journal)",
            conditions=[
                SemanticCondition("USN", "reason", "RENAME", "contains"),
            ],
            logic_operator="AND",
            scope="global",
            category="file_access",
            severity="info",
            confidence=0.90
        ))
        
        # =================================================================
        # MULTI-FEATHER RULES (Cross-Artifact Correlation)
        # Smart field matching handles variations automatically
        # =================================================================
        
        # 1. Application Execution with File Access (Prefetch + LNK)
        default_rules.append(SemanticRule(
            rule_id="default-app-execution-file-access",
            name="Application Executed with File Access",
            semantic_value="App Execution + File Access",
            description="Application was executed AND a file was accessed (evidence from Prefetch + LNK)",
            conditions=[
                SemanticCondition("Prefetch", "executable_name", "*", "wildcard"),
                SemanticCondition("LNK", "target_path", "*", "wildcard"),
            ],
            logic_operator="AND",
            scope="global",
            category="user_activity",
            severity="info",
            confidence=0.85
        ))
        
        # 2. USB Device Usage (Registry + EventLogs)
        default_rules.append(SemanticRule(
            rule_id="default-usb-device-usage",
            name="USB Device Connected with Activity",
            semantic_value="USB Device Usage",
            description="USB device was connected AND related activity detected",
            conditions=[
                SemanticCondition("Registry", "key_path", "USBSTOR", "contains"),
                SemanticCondition("EventLogs", "EventID", "*", "wildcard"),
            ],
            logic_operator="AND",
            scope="global",
            category="device_activity",
            severity="medium",
            confidence=0.80
        ))
        
        # 3. User Login + File Access (SecurityLogs + ShellBags)
        default_rules.append(SemanticRule(
            rule_id="default-login-file-access",
            name="User Login with Folder Navigation",
            semantic_value="Login + Folder Access",
            description="User logged in AND navigated to folders",
            conditions=[
                SemanticCondition("SecurityLogs", "EventID", "4624", "equals"),
                SemanticCondition("ShellBags", "path", "*", "wildcard"),
            ],
            logic_operator="AND",
            scope="global",
            category="user_activity",
            severity="info",
            confidence=0.85
        ))
        
        # 4. Browser Activity (Prefetch + BrowserHistory)
        default_rules.append(SemanticRule(
            rule_id="default-browser-activity",
            name="Browser Execution with Web Activity",
            semantic_value="Browser Activity",
            description="Browser was executed AND web activity detected",
            conditions=[
                SemanticCondition("Prefetch", "executable_name", "chrome|firefox|msedge|edge|iexplore|opera|brave|safari", "regex"),
                SemanticCondition("BrowserHistory", "url", "*", "wildcard"),
            ],
            logic_operator="AND",
            scope="global",
            category="web_activity",
            severity="info",
            confidence=0.90
        ))
        
        # 5. Data Exfiltration Pattern (USB + File Access + Network)
        default_rules.append(SemanticRule(
            rule_id="default-data-exfiltration-pattern",
            name="Potential Data Exfiltration",
            semantic_value="Data Exfiltration Pattern",
            description="USB device connected OR file accessed OR network activity - potential data movement",
            conditions=[
                SemanticCondition("Registry", "key_path", "USBSTOR", "contains"),
                SemanticCondition("LNK", "target_path", "*", "wildcard"),
                SemanticCondition("NetworkConnections", "remote_address", "*", "wildcard"),
            ],
            logic_operator="OR",
            scope="global",
            category="suspicious_activity",
            severity="high",
            confidence=0.70
        ))
        
        # =================================================================
        # ADDITIONAL MULTI-FEATHER RULES
        # =================================================================
        
        # Process Creation with Network Activity
        default_rules.append(SemanticRule(
            rule_id="default-process-network-activity",
            name="Process with Network Connection",
            semantic_value="Process + Network Activity",
            description="Process was created AND established network connection",
            conditions=[
                SemanticCondition("SecurityLogs", "EventID", "4688", "equals"),
                SemanticCondition("NetworkConnections", "remote_address", "*", "wildcard"),
            ],
            logic_operator="AND",
            scope="global",
            category="network_activity",
            severity="medium",
            confidence=0.80
        ))
        
        # Failed Login Attempts
        default_rules.append(SemanticRule(
            rule_id="default-failed-login-attempts",
            name="Failed Login Attempt",
            semantic_value="Failed Authentication",
            description="Failed login attempt detected (Event 4625 or 4771)",
            conditions=[
                SemanticCondition("SecurityLogs", "EventID", "4625", "equals"),
                SemanticCondition("SecurityLogs", "EventID", "4771", "equals"),
            ],
            logic_operator="OR",
            scope="global",
            category="authentication",
            severity="medium",
            confidence=0.95
        ))
        
        # Privilege Escalation Pattern
        default_rules.append(SemanticRule(
            rule_id="default-privilege-escalation",
            name="Privilege Escalation",
            semantic_value="Privilege Escalation",
            description="Special privileges assigned to new logon (Event 4672)",
            conditions=[
                SemanticCondition("SecurityLogs", "EventID", "4672", "equals"),
            ],
            logic_operator="AND",
            scope="global",
            category="authentication",
            severity="high",
            confidence=0.90
        ))
        
        # Application Installation (Prefetch + Registry)
        default_rules.append(SemanticRule(
            rule_id="default-app-installation",
            name="Application Installation",
            semantic_value="App Installation",
            description="New application installed (evidence from Prefetch + Registry)",
            conditions=[
                SemanticCondition("Prefetch", "executable_name", "msiexec|setup|install|installer", "regex"),
                SemanticCondition("Registry", "key_path", "Uninstall", "contains"),
            ],
            logic_operator="AND",
            scope="global",
            category="software_activity",
            severity="low",
            confidence=0.75
        ))
        
        # Remote Access Tool Detection
        default_rules.append(SemanticRule(
            rule_id="default-remote-access-tool",
            name="Remote Access Tool Activity",
            semantic_value="Remote Access Tool",
            description="Remote access tool executed (TeamViewer, AnyDesk, VNC, RDP, LogMeIn, etc.)",
            conditions=[
                SemanticCondition("Prefetch", "executable_name", "teamviewer|anydesk|vnc|rdp|logmein|ammyy|ultraviewer|rustdesk|parsec|splashtop", "regex"),
            ],
            logic_operator="AND",
            scope="global",
            category="remote_access",
            severity="medium",
            confidence=0.85
        ))
        
        # Add all default rules to the manager
        for rule in default_rules:
            self.add_rule(rule)
        
        logger.info(f"Loaded {len(default_rules)} default semantic rules")
    
    def _load_default_mappings(self):
        """Load default semantic mappings for all artifact types."""
        # User Activity Events (Security Logs)
        user_activity_mappings = [
            SemanticMapping("SecurityLogs", "EventID", "4624", "User Login", 
                          "Successful user logon (Type 2: Interactive, Type 10: Remote)",
                          artifact_type="Logs", category="authentication", severity="info"),
            SemanticMapping("SecurityLogs", "EventID", "4634", "User Logoff", 
                          "User logoff event",
                          artifact_type="Logs", category="authentication", severity="info"),
            SemanticMapping("SecurityLogs", "EventID", "4647", "User Logoff", 
                          "User initiated logoff",
                          artifact_type="Logs", category="authentication", severity="info"),
            SemanticMapping("SecurityLogs", "EventID", "4800", "Session Locked", 
                          "Workstation locked",
                          artifact_type="Logs", category="authentication", severity="info"),
            SemanticMapping("SecurityLogs", "EventID", "4801", "Session Unlocked", 
                          "Workstation unlocked",
                          artifact_type="Logs", category="authentication", severity="info"),
            SemanticMapping("SecurityLogs", "EventID", "4648", "Account Switch", 
                          "Logon with explicit credentials (account switch)",
                          artifact_type="Logs", category="authentication", severity="low"),
        ]
        
        # System Events (System Logs)
        system_event_mappings = [
            SemanticMapping("SystemLogs", "EventID", "6005", "System Startup", 
                          "Event Log service started",
                          artifact_type="Logs", category="system_power", severity="info"),
            SemanticMapping("SystemLogs", "EventID", "6006", "System Shutdown", 
                          "Event Log service stopped",
                          artifact_type="Logs", category="system_power", severity="info"),
            SemanticMapping("SystemLogs", "EventID", "1074", "System Restart", 
                          "System restart or shutdown initiated",
                          artifact_type="Logs", category="system_power", severity="info"),
            SemanticMapping("SystemLogs", "EventID", "42", "System Sleep", 
                          "System entering sleep mode",
                          artifact_type="Logs", category="system_power", severity="info"),
            SemanticMapping("SystemLogs", "EventID", "1", "System Wake", 
                          "System resuming from sleep",
                          artifact_type="Logs", category="system_power", severity="info"),
            SemanticMapping("SystemLogs", "EventID", "6008", "Unexpected Shutdown", 
                          "Previous system shutdown was unexpected",
                          artifact_type="Logs", category="system_power", severity="medium"),
            SemanticMapping("SystemLogs", "EventID", "107", "Hibernate Resume", 
                          "System resumed from hibernation",
                          artifact_type="Logs", category="system_power", severity="info"),
        ]
        
        # Process Execution Events (Security Logs)
        process_execution_mappings = [
            SemanticMapping("SecurityLogs", "EventID", "4688", "Process Creation", 
                          "A new process was created",
                          artifact_type="Logs", category="process_execution", severity="info"),
            SemanticMapping("SecurityLogs", "EventID", "4689", "Process Termination", 
                          "A process has exited",
                          artifact_type="Logs", category="process_execution", severity="info"),
        ]
        
        # Add all default mappings
        for mapping in user_activity_mappings + system_event_mappings + process_execution_mappings:
            self.add_mapping(mapping)
        
        logger.info(f"Loaded {len(user_activity_mappings + system_event_mappings + process_execution_mappings)} default semantic mappings")
    
    # =========================================================================
    # BASIC MAPPING METHODS
    # =========================================================================
    
    def add_mapping(self, mapping: SemanticMapping):
        """Add a semantic mapping with artifact indexing."""
        key = f"{mapping.source}.{mapping.field}"
        
        if mapping.scope == "global":
            if key not in self.global_mappings:
                self.global_mappings[key] = []
            self.global_mappings[key].append(mapping)
        elif mapping.scope == "wing" and mapping.wing_id:
            if mapping.wing_id not in self.wing_mappings:
                self.wing_mappings[mapping.wing_id] = []
            self.wing_mappings[mapping.wing_id].append(mapping)
        elif mapping.scope == "pipeline" and mapping.pipeline_id:
            if mapping.pipeline_id not in self.pipeline_mappings:
                self.pipeline_mappings[mapping.pipeline_id] = []
            self.pipeline_mappings[mapping.pipeline_id].append(mapping)
        
        if mapping.artifact_type:
            if mapping.artifact_type not in self.artifact_mappings:
                self.artifact_mappings[mapping.artifact_type] = []
            self.artifact_mappings[mapping.artifact_type].append(mapping)
        
        if mapping.pattern:
            mapping.compile_pattern()
    
    def add_artifact_mappings(self, artifact_type: str, mappings: List[SemanticMapping]):
        """Add multiple mappings for a specific artifact type."""
        for mapping in mappings:
            mapping.artifact_type = artifact_type
            self.add_mapping(mapping)
        logger.info(f"Added {len(mappings)} mappings for artifact type '{artifact_type}'")
    
    def get_mappings_by_artifact(self, artifact_type: str) -> List[SemanticMapping]:
        """Get all mappings for a specific artifact type."""
        return self.artifact_mappings.get(artifact_type, [])
    
    def get_all_mappings(self, scope: str = "global",
                        wing_id: Optional[str] = None,
                        pipeline_id: Optional[str] = None) -> List[SemanticMapping]:
        """Get all mappings for a given scope."""
        if scope == "global":
            return [m for mappings in self.global_mappings.values() for m in mappings]
        elif scope == "wing" and wing_id:
            return self.wing_mappings.get(wing_id, [])
        elif scope == "pipeline" and pipeline_id:
            return self.pipeline_mappings.get(pipeline_id, [])
        return []
    
    def remove_mapping(self, source: str, field: str, technical_value: str,
                      scope: str = "global", 
                      wing_id: Optional[str] = None,
                      pipeline_id: Optional[str] = None):
        """Remove a semantic mapping."""
        if scope == "global":
            key = f"{source}.{field}"
            if key in self.global_mappings:
                self.global_mappings[key] = [
                    m for m in self.global_mappings[key]
                    if not m.matches(technical_value)
                ]
        elif scope == "wing" and wing_id and wing_id in self.wing_mappings:
            self.wing_mappings[wing_id] = [
                m for m in self.wing_mappings[wing_id]
                if not (m.source == source and m.field == field and m.matches(technical_value))
            ]
        elif scope == "pipeline" and pipeline_id and pipeline_id in self.pipeline_mappings:
            self.pipeline_mappings[pipeline_id] = [
                m for m in self.pipeline_mappings[pipeline_id]
                if not (m.source == source and m.field == field and m.matches(technical_value))
            ]

    # =========================================================================
    # ADVANCED RULE METHODS
    # =========================================================================
    
    def add_rule(self, rule: SemanticRule):
        """Add an advanced semantic rule."""
        if rule.scope == "global":
            self.global_rules.append(rule)
        elif rule.scope == "wing" and rule.wing_id:
            if rule.wing_id not in self.wing_rules:
                self.wing_rules[rule.wing_id] = []
            self.wing_rules[rule.wing_id].append(rule)
        elif rule.scope == "pipeline" and rule.pipeline_id:
            if rule.pipeline_id not in self.pipeline_rules:
                self.pipeline_rules[rule.pipeline_id] = []
            self.pipeline_rules[rule.pipeline_id].append(rule)
    
    def get_rules(self, scope: str = "global",
                 wing_id: Optional[str] = None,
                 pipeline_id: Optional[str] = None) -> List[SemanticRule]:
        """Get all rules for a given scope."""
        if scope == "global":
            return self.global_rules.copy()
        elif scope == "wing" and wing_id:
            return self.wing_rules.get(wing_id, []).copy()
        elif scope == "pipeline" and pipeline_id:
            return self.pipeline_rules.get(pipeline_id, []).copy()
        return []
    
    def get_all_rules_for_execution(self, wing_id: Optional[str] = None,
                                   pipeline_id: Optional[str] = None) -> List[SemanticRule]:
        """
        Get all applicable rules for execution with proper priority.
        
        Priority: Wing-specific > Pipeline-specific > Global
        """
        rules = []
        
        # Add wing-specific rules first (highest priority)
        if wing_id and wing_id in self.wing_rules:
            rules.extend(self.wing_rules[wing_id])
        
        # Add pipeline-specific rules
        if pipeline_id and pipeline_id in self.pipeline_rules:
            rules.extend(self.pipeline_rules[pipeline_id])
        
        # Add global rules (lowest priority)
        rules.extend(self.global_rules)
        
        return rules
    
    def remove_rule(self, rule_id: str, scope: str = "global",
                   wing_id: Optional[str] = None,
                   pipeline_id: Optional[str] = None):
        """Remove a semantic rule by ID."""
        if scope == "global":
            self.global_rules = [r for r in self.global_rules if r.rule_id != rule_id]
        elif scope == "wing" and wing_id and wing_id in self.wing_rules:
            self.wing_rules[wing_id] = [r for r in self.wing_rules[wing_id] if r.rule_id != rule_id]
        elif scope == "pipeline" and pipeline_id and pipeline_id in self.pipeline_rules:
            self.pipeline_rules[pipeline_id] = [r for r in self.pipeline_rules[pipeline_id] if r.rule_id != rule_id]
    
    # =========================================================================
    # PATTERN MATCHING
    # =========================================================================
    
    def pattern_match(self, pattern: str, value: str) -> bool:
        """Match value against regex pattern with caching."""
        if pattern not in self.pattern_cache:
            try:
                self.pattern_cache[pattern] = re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                logger.error(f"Invalid regex pattern '{pattern}': {e}")
                return False
        return bool(self.pattern_cache[pattern].search(value))
    
    def evaluate_conditions(self, conditions: List[Dict[str, Any]], record: Dict[str, Any]) -> bool:
        """Evaluate multi-field conditions against a record."""
        if not conditions:
            return True
        
        logic = "AND"
        if conditions and isinstance(conditions[0], dict) and "logic" in conditions[0]:
            logic = conditions[0]["logic"].upper()
            conditions = conditions[1:]
        
        results = []
        for condition in conditions:
            if isinstance(condition, dict):
                result = self._evaluate_single_condition(condition, record)
                results.append(result)
        
        return any(results) if logic == "OR" else all(results)
    
    def _evaluate_single_condition(self, condition: Dict[str, Any], record: Dict[str, Any]) -> bool:
        """Evaluate a single condition."""
        field_name = condition.get("field") or condition.get("field_name")
        operator = condition.get("operator", "equals")
        expected_value = condition.get("value")
        condition_feather_id = condition.get("feather_id")
        
        # Check feather_id match if specified in condition
        if condition_feather_id:
            record_feather_id = record.get("_feather_id", "")
            # Case-insensitive comparison and handle common variations
            if not self._feather_id_matches(condition_feather_id, record_feather_id):
                return False
        
        if field_name not in record:
            return False
        
        actual_value = record[field_name]
        
        if operator == "equals":
            return str(actual_value).lower() == str(expected_value).lower()
        elif operator == "in":
            return str(actual_value) in expected_value
        elif operator == "regex":
            return self.pattern_match(expected_value, str(actual_value))
        elif operator == "greater_than":
            try:
                return float(actual_value) > float(expected_value)
            except (ValueError, TypeError):
                return False
        elif operator == "less_than":
            try:
                return float(actual_value) < float(expected_value)
            except (ValueError, TypeError):
                return False
        elif operator == "contains":
            return expected_value.lower() in str(actual_value).lower()
        elif operator == "wildcard":
            # Wildcard matches any non-empty value
            return bool(actual_value) and str(actual_value).strip() != ""
        
        return False
    
    def _feather_id_matches(self, condition_feather_id: str, record_feather_id: str) -> bool:
        """Check if feather IDs match with common variations."""
        if not condition_feather_id or not record_feather_id:
            return not condition_feather_id  # If no condition feather_id, match any
        
        # Normalize both IDs for comparison
        cond_lower = condition_feather_id.lower().replace("_", "").replace("-", "")
        rec_lower = record_feather_id.lower().replace("_", "").replace("-", "")
        
        # Direct match
        if cond_lower == rec_lower:
            return True
        
        # Common mappings between rule feather IDs and actual feather IDs
        feather_id_mappings = {
            "securitylogs": ["systemlogs", "security", "eventlogs", "winevt"],
            "systemlogs": ["securitylogs", "security", "eventlogs", "winevt"],
            "prefetch": ["prefetch", "pf"],
            "lnk": ["lnk", "shortcut", "link"],
            "mft": ["mft", "mftusn", "ntfs"],
            "usn": ["usn", "usnjournal", "mftusn"],
            "shellbags": ["shellbags", "shell"],
            "registry": ["registry", "reg"],
            "amcache": ["amcache", "amcacheapp", "amcachefile", "inventoryapplication"],
            "shimcache": ["shimcache", "appcompat"],
            "jumplist": ["jumplist", "jumplistauto", "jumplistcustom", "automaticjumplist", "customjumplist"],
            "srum": ["srum", "srumapp", "srumusage"],
            "browserhistory": ["browserhistory", "browser", "webhistory"],
            "networkconnections": ["networkconnections", "network", "connections"],
            "eventlogs": ["eventlogs", "winevt", "systemlogs", "securitylogs"],
        }
        
        # Check if condition feather ID maps to record feather ID
        for key, variations in feather_id_mappings.items():
            if cond_lower == key or cond_lower in variations:
                if rec_lower == key or rec_lower in variations:
                    return True
        
        # Partial match (one contains the other)
        if cond_lower in rec_lower or rec_lower in cond_lower:
            return True
        
        return False
    
    # =========================================================================
    # APPLY MAPPINGS TO RECORDS
    # =========================================================================
    
    def apply_to_record(self, record: Dict[str, Any], artifact_type: Optional[str] = None,
                       wing_id: Optional[str] = None, pipeline_id: Optional[str] = None) -> List[SemanticMapping]:
        """
        Apply all matching semantic mappings to a record.
        
        Returns list of all mappings that match the record, sorted by confidence.
        """
        matching_mappings = []
        candidates = []
        
        if artifact_type:
            candidates.extend(self.get_mappings_by_artifact(artifact_type))
        if wing_id and wing_id in self.wing_mappings:
            candidates.extend(self.wing_mappings[wing_id])
        if pipeline_id and pipeline_id in self.pipeline_mappings:
            candidates.extend(self.pipeline_mappings[pipeline_id])
        for mappings_list in self.global_mappings.values():
            candidates.extend(mappings_list)
        
        for mapping in candidates:
            if mapping.field not in record:
                continue
            field_value = str(record[mapping.field])
            if not mapping.matches(field_value):
                continue
            if not mapping.evaluate_conditions(record):
                continue
            matching_mappings.append(mapping)
        
        matching_mappings.sort(key=lambda m: m.confidence, reverse=True)
        return matching_mappings
    
    def get_semantic_value(self, source: str, field: str, 
                          technical_value: str,
                          wing_id: Optional[str] = None,
                          pipeline_id: Optional[str] = None) -> Optional[str]:
        """
        Get semantic value for a technical value.
        
        Priority: Wing-specific > Pipeline-specific > Global
        """
        # Check wing-specific mappings first
        if wing_id and wing_id in self.wing_mappings:
            for mapping in self.wing_mappings[wing_id]:
                if (mapping.source == source and mapping.field == field and
                    mapping.matches(technical_value)):
                    return mapping.semantic_value
        
        # Check pipeline-specific mappings
        if pipeline_id and pipeline_id in self.pipeline_mappings:
            for mapping in self.pipeline_mappings[pipeline_id]:
                if (mapping.source == source and mapping.field == field and
                    mapping.matches(technical_value)):
                    return mapping.semantic_value
        
        # Check global mappings
        key = f"{source}.{field}"
        if key in self.global_mappings:
            for mapping in self.global_mappings[key]:
                if mapping.matches(technical_value):
                    return mapping.semantic_value
        
        return None
    
    # =========================================================================
    # NORMALIZATION UTILITIES
    # =========================================================================
    
    def normalize_field_value(self, field_type: str, value: str, wing_id: Optional[str] = None) -> str:
        """Normalize a field value using semantic mappings."""
        if not value:
            return value
        
        value_lower = value.lower()
        
        if field_type == 'application':
            app_mappings = {
                'chrome.exe': 'Google Chrome',
                'firefox.exe': 'Mozilla Firefox',
                'msedge.exe': 'Microsoft Edge',
                'iexplore.exe': 'Internet Explorer',
                'explorer.exe': 'Windows Explorer',
                'notepad.exe': 'Notepad',
                'cmd.exe': 'Command Prompt',
                'powershell.exe': 'PowerShell',
                'python.exe': 'Python',
                'java.exe': 'Java',
                'code.exe': 'Visual Studio Code',
                'excel.exe': 'Microsoft Excel',
                'word.exe': 'Microsoft Word',
                'outlook.exe': 'Microsoft Outlook'
            }
            for exe_name, normalized_name in app_mappings.items():
                if exe_name in value_lower:
                    return normalized_name
            return value
        
        elif field_type == 'path':
            path_mappings = {
                'c:\\program files\\': '%ProgramFiles%\\',
                'c:\\program files (x86)\\': '%ProgramFiles(x86)%\\',
                'c:\\windows\\': '%Windows%\\',
                'c:\\users\\': '%UserProfile%\\',
                'c:\\programdata\\': '%ProgramData%\\'
            }
            for original, replacement in path_mappings.items():
                if value_lower.startswith(original):
                    return replacement + value[len(original):]
            return value
        
        return value
    
    def calculate_semantic_similarity(self, values: List[str]) -> float:
        """Calculate semantic similarity score for a list of values."""
        if not values or len(values) < 2:
            return 1.0
        
        unique_values = set(values)
        if len(unique_values) == 1:
            return 1.0
        
        from collections import Counter
        counter = Counter(values)
        most_common_count = counter.most_common(1)[0][1]
        return most_common_count / len(values)
    
    # =========================================================================
    # FILE I/O
    # =========================================================================
    
    def save_to_file(self, file_path: Path, scope: str = "global",
                    wing_id: Optional[str] = None,
                    pipeline_id: Optional[str] = None):
        """Save mappings and rules to JSON file."""
        mappings = self.get_all_mappings(scope, wing_id, pipeline_id)
        rules = self.get_rules(scope, wing_id, pipeline_id)
        
        data = {
            'mappings': [],
            'rules': []
        }
        
        for m in mappings:
            m_dict = asdict(m)
            m_dict.pop('_compiled_pattern', None)
            data['mappings'].append(m_dict)
        
        for r in rules:
            data['rules'].append(r.to_dict())
        
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Saved {len(mappings)} mappings and {len(rules)} rules to {file_path}")
    
    def load_from_file(self, file_path: Path):
        """Load mappings and rules from JSON file."""
        if not file_path.exists():
            logger.warning(f"Semantic mappings file not found: {file_path}")
            return
        
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        # Handle both old format (list) and new format (dict with mappings/rules)
        if isinstance(data, list):
            # Old format - just mappings
            for mapping_dict in data:
                mapping_dict.pop('_compiled_pattern', None)
                mapping = SemanticMapping(**mapping_dict)
                self.add_mapping(mapping)
            logger.info(f"Loaded {len(data)} semantic mappings from {file_path}")
        else:
            # New format
            mappings_data = data.get('mappings', [])
            rules_data = data.get('rules', [])
            
            for mapping_dict in mappings_data:
                mapping_dict.pop('_compiled_pattern', None)
                mapping = SemanticMapping(**mapping_dict)
                self.add_mapping(mapping)
            
            for rule_dict in rules_data:
                rule = SemanticRule.from_dict(rule_dict)
                self.add_rule(rule)
            
            logger.info(f"Loaded {len(mappings_data)} mappings and {len(rules_data)} rules from {file_path}")
    
    # =========================================================================
    # JSON CONFIGURATION METHODS
    # =========================================================================
    
    def _ensure_config_directory(self):
        """Ensure the configs directory exists."""
        if not self.config_dir.exists():
            self.config_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created config directory: {self.config_dir}")
    
    def _load_rules_from_json(self):
        """
        Load rules from JSON files with fallback to built-in rules.
        
        Load order:
        1. Try to load default rules from JSON
        2. If missing, export built-in rules to JSON
        3. If corrupted, use built-in rules and log warning
        4. Load custom rules if present
        5. Merge custom rules over defaults
        """
        self._ensure_config_directory()
        
        # Track loading status for logging
        default_rules_dict = {}
        custom_rules_dict = {}
        default_loaded = False
        custom_loaded = False
        fallback_used = False
        
        # Store built-in rules count for comparison
        built_in_count = len(self.global_rules)
        
        # Load default rules
        if not self.default_rules_path.exists():
            logger.info(f"Default rules file not found, exporting built-in rules to {self.default_rules_path}")
            try:
                self.export_default_rules_to_json()
                logger.info(f"Successfully created default rules file with {built_in_count} built-in rules")
                # Use built-in rules that are already loaded
                default_rules_dict = {rule.rule_id: rule for rule in self.global_rules}
                default_loaded = True
            except Exception as e:
                logger.error(f"Failed to export default rules: {e}")
                logger.warning("Using built-in rules from code")
                fallback_used = True
                default_rules_dict = {rule.rule_id: rule for rule in self.global_rules}
        else:
            try:
                # Load default rules without adding to manager yet
                default_rules_dict = self.load_rules_from_json(self.default_rules_path, add_to_manager=False)
                default_loaded = True
                logger.info(f"✓ Loaded {len(default_rules_dict)} default rules from JSON")
            except json.JSONDecodeError as e:
                logger.error(f"JSON syntax error in {self.default_rules_path}: {e}")
                logger.warning("⚠ Falling back to built-in rules due to corrupted default rules file")
                fallback_used = True
                self._show_fallback_warning("default", str(e))
                # Use built-in rules that are already loaded
                default_rules_dict = {rule.rule_id: rule for rule in self.global_rules}
            except Exception as e:
                logger.error(f"Failed to load default rules from JSON: {e}")
                logger.warning("⚠ Falling back to built-in rules")
                fallback_used = True
                self._show_fallback_warning("default", str(e))
                # Use built-in rules that are already loaded
                default_rules_dict = {rule.rule_id: rule for rule in self.global_rules}
        
        # Load custom rules if present
        if self.custom_rules_path.exists():
            try:
                custom_rules_dict = self.load_rules_from_json(self.custom_rules_path, add_to_manager=False)
                custom_loaded = True
                logger.info(f"✓ Loaded {len(custom_rules_dict)} custom rules from JSON")
            except json.JSONDecodeError as e:
                logger.error(f"JSON syntax error in {self.custom_rules_path}: {e}")
                logger.warning("⚠ Skipping custom rules due to corrupted file")
                self._show_fallback_warning("custom", str(e))
            except Exception as e:
                logger.error(f"Failed to load custom rules from JSON: {e}")
                logger.warning("⚠ Skipping custom rules")
        else:
            logger.info("No custom rules file found (this is normal)")
        
        # Merge custom rules over defaults if we have both
        if default_loaded and custom_rules_dict:
            merged_rules = self.merge_rules(default_rules_dict, custom_rules_dict)
            
            # Clear and rebuild global_rules with merged results
            self.global_rules.clear()
            for rule in merged_rules.values():
                self.global_rules.append(rule)
        elif default_loaded and not fallback_used:
            # Only default rules loaded from JSON, replace built-in rules
            self.global_rules.clear()
            for rule in default_rules_dict.values():
                self.global_rules.append(rule)
        # else: keep built-in rules that are already loaded
        
        # Log final status
        total_rules = len(self.global_rules)
        default_count = len(default_rules_dict)
        custom_count = len(custom_rules_dict)
        
        if fallback_used:
            logger.warning(f"⚠ Using {total_rules} built-in rules (fallback mode)")
        elif default_loaded and custom_loaded:
            logger.info(f"✓ Successfully loaded rules: {default_count} default + {custom_count} custom = {total_rules} total")
        elif default_loaded:
            logger.info(f"✓ Successfully loaded {total_rules} default rules from JSON")
        else:
            logger.info(f"✓ Using {total_rules} built-in rules")
    
    def _show_fallback_warning(self, file_type: str, error_message: str):
        """
        Show warning notification when falling back to built-in rules.
        
        Args:
            file_type: "default" or "custom"
            error_message: Error message to display
        """
        # This method can be enhanced to show GUI notifications
        # For now, it just logs the warning
        file_name = "semantic_rules_default.json" if file_type == "default" else "semantic_rules_custom.json"
        logger.warning(f"""
╔══════════════════════════════════════════════════════════════════════════╗
║ WARNING: Semantic Rules Configuration Error                              ║
╚══════════════════════════════════════════════════════════════════════════╝

File: {file_name}
Error: {error_message}

Action Taken:
  {'Using built-in default rules from code' if file_type == 'default' else 'Skipping custom rules, using defaults only'}

To Fix:
  1. Open Settings → Semantic Mapping tab
  2. Click "Validate Rule Files" to see detailed errors
  3. Fix the JSON syntax or use "Export Default Rules" to reset

The system will continue operating normally with {'built-in' if file_type == 'default' else 'default'} rules.
        """)
    
    def load_rules_from_json(self, json_path: Path, add_to_manager: bool = False) -> Dict[str, SemanticRule]:
        """
        Load semantic rules from JSON file.
        
        Args:
            json_path: Path to JSON file
            add_to_manager: If True, automatically add rules to manager (default: False)
            
        Returns:
            Dictionary of rules keyed by rule_id
            
        Raises:
            Exception: If file cannot be loaded or parsed
        """
        if not json_path.exists():
            return {}
        
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load JSON from {json_path}: {e}")
            raise
        
        if not isinstance(data, dict) or "rules" not in data:
            logger.error(f"Invalid JSON structure in {json_path}: missing 'rules' array")
            return {}
        
        rules_dict = {}
        for rule_data in data["rules"]:
            try:
                # Convert conditions from dict to SemanticCondition objects
                conditions = []
                for cond_data in rule_data.get("conditions", []):
                    condition = SemanticCondition(
                        feather_id=cond_data["feather_id"],
                        field_name=cond_data["field_name"],
                        value=cond_data["value"],
                        operator=cond_data.get("operator", "equals")
                    )
                    conditions.append(condition)
                
                # Create SemanticRule object
                rule = SemanticRule(
                    rule_id=rule_data["rule_id"],
                    name=rule_data["name"],
                    semantic_value=rule_data["semantic_value"],
                    description=rule_data.get("description", ""),
                    conditions=conditions,
                    logic_operator=rule_data["logic_operator"],
                    scope=rule_data.get("scope", "global"),
                    category=rule_data.get("category", ""),
                    severity=rule_data.get("severity", "info"),
                    confidence=rule_data.get("confidence", 1.0),
                    wing_id=rule_data.get("wing_id"),
                    pipeline_id=rule_data.get("pipeline_id")
                )
                
                rules_dict[rule.rule_id] = rule
                
                # Optionally add to manager
                if add_to_manager:
                    self.add_rule(rule)
                
            except Exception as e:
                logger.error(f"Failed to parse rule from JSON: {e}")
                continue
        
        return rules_dict
    
    def export_default_rules_to_json(self, output_path: Optional[Path] = None):
        """
        Export built-in default rules to JSON file.
        
        Args:
            output_path: Optional output path (defaults to default_rules_path)
        """
        if output_path is None:
            output_path = self.default_rules_path
        
        self._ensure_config_directory()
        
        # Convert global rules to JSON format
        rules_data = []
        for rule in self.global_rules:
            rule_dict = {
                "rule_id": rule.rule_id,
                "name": rule.name,
                "semantic_value": rule.semantic_value,
                "description": rule.description,
                "conditions": [
                    {
                        "feather_id": cond.feather_id,
                        "field_name": cond.field_name,
                        "value": cond.value,
                        "operator": cond.operator
                    }
                    for cond in rule.conditions
                ],
                "logic_operator": rule.logic_operator,
                "scope": rule.scope,
                "category": rule.category,
                "severity": rule.severity,
                "confidence": rule.confidence
            }
            
            if rule.wing_id:
                rule_dict["wing_id"] = rule.wing_id
            if rule.pipeline_id:
                rule_dict["pipeline_id"] = rule.pipeline_id
            
            rules_data.append(rule_dict)
        
        # Write to file with 2-space indentation
        data = {"rules": rules_data}
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Exported {len(rules_data)} default rules to {output_path}")
    
    def validate_json_rules(self, json_path: Path) -> Tuple[bool, List[str]]:
        """
        Validate JSON rules file and return errors.
        
        Args:
            json_path: Path to JSON file to validate
            
        Returns:
            Tuple of (is_valid, error_list)
        """
        from .semantic_rule_validator import SemanticRuleValidator
        
        validator = SemanticRuleValidator()
        result = validator.validate_file(json_path)
        
        error_messages = []
        for error in result.errors:
            error_messages.append(str(error))
        for warning in result.warnings:
            error_messages.append(str(warning))
        
        return result.is_valid, error_messages
    
    def reload_rules(self):
        """
        Reload rules from JSON files without restart.
        
        Clears current rules and reloads from JSON files.
        Emits a reload event via logging when complete.
        """
        logger.info("=" * 70)
        logger.info("RELOAD EVENT: Reloading semantic rules from JSON files...")
        logger.info("=" * 70)
        
        # Clear current global rules (keep built-in as fallback)
        rules_before = len(self.global_rules)
        
        # Store built-in rules as backup
        built_in_rules = self.global_rules.copy()
        
        # Clear rules
        self.global_rules.clear()
        logger.info(f"Cleared {rules_before} existing rules")
        
        # Reload built-in rules first (as fallback)
        self._load_default_rules()
        
        # Try to reload from JSON
        try:
            self._load_rules_from_json()
            rules_after = len(self.global_rules)
            logger.info(f"✓ Successfully reloaded rules: {rules_before} → {rules_after}")
            
            # Emit reload event
            logger.info("=" * 70)
            logger.info("RELOAD EVENT COMPLETE: Rules successfully reloaded")
            logger.info(f"  - Previous count: {rules_before}")
            logger.info(f"  - New count: {rules_after}")
            logger.info(f"  - Change: {rules_after - rules_before:+d}")
            logger.info("=" * 70)
            
        except Exception as e:
            logger.error(f"Failed to reload rules: {e}")
            # Restore built-in rules
            self.global_rules = built_in_rules
            logger.warning("⚠ Restored previous rules due to reload failure")
            
            # Emit reload failure event
            logger.warning("=" * 70)
            logger.warning("RELOAD EVENT FAILED: Restored previous rules")
            logger.warning("=" * 70)
            raise
    
    def merge_rules(self, default_rules: Dict[str, SemanticRule], 
                   custom_rules: Dict[str, SemanticRule]) -> Dict[str, SemanticRule]:
        """
        Merge custom rules over default rules.
        
        Args:
            default_rules: Dictionary of default rules keyed by rule_id
            custom_rules: Dictionary of custom rules keyed by rule_id
            
        Returns:
            Merged dictionary with custom rules overriding defaults
        """
        merged = default_rules.copy()
        overridden_count = 0
        added_count = 0
        
        for rule_id, custom_rule in custom_rules.items():
            if rule_id in merged:
                overridden_count += 1
                logger.debug(f"Custom rule '{rule_id}' overrides default rule")
            else:
                added_count += 1
                logger.debug(f"Custom rule '{rule_id}' added to rule set")
            merged[rule_id] = custom_rule
        
        logger.info(f"Rule merge complete: {len(default_rules)} default + {len(custom_rules)} custom = {len(merged)} total ({overridden_count} overridden, {added_count} added)")
        
        return merged

    def save_rule_to_custom_json(self, rule: SemanticRule):
        """
        Save a rule to the custom rules JSON file.
        
        Args:
            rule: SemanticRule to save
        """
        import json
        
        # Ensure config directory exists
        self._ensure_config_directory()
        
        # Load existing custom rules or create empty structure
        custom_rules = {"rules": []}
        
        if self.custom_rules_path.exists():
            try:
                with open(self.custom_rules_path, 'r', encoding='utf-8') as f:
                    custom_rules = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load existing custom rules: {e}")
                custom_rules = {"rules": []}
        
        # Convert rule to dict
        rule_dict = {
            "rule_id": rule.rule_id,
            "name": rule.name,
            "semantic_value": rule.semantic_value,
            "conditions": [
                {
                    "feather_id": cond.feather_id,
                    "field_name": cond.field_name,
                    "value": cond.value,
                    "operator": cond.operator
                }
                for cond in rule.conditions
            ],
            "logic_operator": rule.logic_operator,
            "scope": rule.scope,
            "category": rule.category if hasattr(rule, 'category') else "",
            "severity": rule.severity if hasattr(rule, 'severity') else "info",
            "confidence": rule.confidence if hasattr(rule, 'confidence') else 1.0,
            "description": rule.description if hasattr(rule, 'description') else ""
        }
        
        # Check if rule already exists (by rule_id)
        existing_index = None
        for i, existing_rule in enumerate(custom_rules["rules"]):
            if existing_rule.get("rule_id") == rule.rule_id:
                existing_index = i
                break
        
        if existing_index is not None:
            # Update existing rule
            custom_rules["rules"][existing_index] = rule_dict
            logger.info(f"Updated existing rule '{rule.rule_id}' in custom rules")
        else:
            # Add new rule
            custom_rules["rules"].append(rule_dict)
            logger.info(f"Added new rule '{rule.rule_id}' to custom rules")
        
        # Save to file
        with open(self.custom_rules_path, 'w', encoding='utf-8') as f:
            json.dump(custom_rules, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved rule to {self.custom_rules_path}")
