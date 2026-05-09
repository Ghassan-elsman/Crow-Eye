"""
Default intelligence gathering rules registry.

Contains 15 pre-configured rules across 8 forensic categories.
"""

from typing import Dict, List, Tuple
from dynamic_mapping.rules.base import DefaultRule


class SIDUsernameRule(DefaultRule):
    """Rule for SID_to_Username."""

    def __init__(self):
        super().__init__(
            name="SID_to_Username",
            category="SID",
            description="Map Windows SIDs to usernames from SAM/Registry",
            target_db_name="registry_data.db"
        )

    def get_query(self) -> str:
        """Generate SQL query with ATTACH statements for SID_to_Username mapping."""
        return """
            SELECT 
                user_sid AS value,
                username AS key,
                'UserProfiles' AS source
            FROM TargetDB.UserProfiles
            WHERE user_sid IS NOT NULL AND username IS NOT NULL
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        """Extract mappings from query results, filtering out NULL values."""
        return [(str(row[0]), str(row[1]), str(row[2])) 
                for row in query_results 
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class SIDProfileRule(DefaultRule):
    """Rule for SID_to_ProfilePath."""

    def __init__(self):
        super().__init__(
            name="SID_to_ProfilePath",
            category="SID",
            description="Map SIDs to user profile paths",
            target_db_name="registry_data.db"
        )

    def get_query(self) -> str:
        """Generate SQL query with ATTACH statements for SID_to_ProfilePath mapping."""
        return """
            SELECT 
                user_sid AS value,
                profile_path AS key,
                'UserProfiles' AS source
            FROM TargetDB.UserProfiles
            WHERE user_sid IS NOT NULL AND profile_path IS NOT NULL
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        """Extract mappings from query results, filtering out NULL values."""
        return [(str(row[0]), str(row[1]), str(row[2])) 
                for row in query_results 
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class MACNetworkRule(DefaultRule):
    """Rule for MAC_to_NetworkName."""

    def __init__(self):
        super().__init__(
            name="MAC_to_NetworkName",
            category="MAC",
            description="Map MAC addresses to network SSIDs",
            target_db_name="registry_data.db"
        )

    def get_query(self) -> str:
        """Generate SQL query with ATTACH statements for MAC_to_NetworkName mapping."""
        return """
            SELECT 
                gateway_mac AS value,
                network_name AS key,
                'Network_list' AS source
            FROM TargetDB.Network_list
            WHERE gateway_mac IS NOT NULL AND network_name IS NOT NULL
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        """Extract mappings from query results, filtering out NULL values."""
        return [(str(row[0]), str(row[1]), str(row[2])) 
                for row in query_results 
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class MACDeviceRule(DefaultRule):
    """Rule for MAC_to_DeviceName."""

    def __init__(self):
        super().__init__(
            name="MAC_to_DeviceName",
            category="MAC",
            description="Map MAC addresses to device names",
            target_db_name="Network.db"
        )

    def get_query(self) -> str:
        """Generate SQL query with ATTACH statements for MAC_to_DeviceName mapping."""
        return """
            SELECT 
                mac_address AS value,
                device_name AS key,
                'network_devices' AS source
            FROM TargetDB.network_devices
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        """Extract mappings from query results, filtering out NULL values."""
        return [(str(row[0]), str(row[1]), str(row[2])) 
                for row in query_results 
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class HashFilenameRule(DefaultRule):
    """Rule for Hash_to_Filename."""

    def __init__(self):
        super().__init__(
            name="Hash_to_Filename",
            category="Hash",
            description="Map file hashes to original filenames",
            target_db_name="amcache.db"
        )

    def get_query(self) -> str:
        """Generate SQL query with ATTACH statements for Hash_to_Filename mapping."""
        return """
            SELECT 
                file_id AS value,
                original_file_name AS key,
                'InventoryApplicationFile' AS source
            FROM TargetDB.InventoryApplicationFile
            WHERE original_file_name IS NOT NULL
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        """Extract mappings from query results, filtering out NULL values."""
        return [(str(row[0]), str(row[1]), str(row[2])) 
                for row in query_results 
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class HashAppRule(DefaultRule):
    """Rule for Hash_to_ApplicationName."""

    def __init__(self):
        super().__init__(
            name="Hash_to_ApplicationName",
            category="Hash",
            description="Map hashes to known application names",
            target_db_name="Known_Hashes.db"
        )

    def get_query(self) -> str:
        """Generate SQL query with ATTACH statements for Hash_to_ApplicationName mapping."""
        return """
            SELECT 
                hash AS value,
                app_name AS key,
                'known_hashes' AS source
            FROM TargetDB.known_hashes
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        """Extract mappings from query results, filtering out NULL values."""
        return [(str(row[0]), str(row[1]), str(row[2])) 
                for row in query_results 
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class GUIDAppRule(DefaultRule):
    """Rule for GUID_to_ApplicationName."""

    def __init__(self):
        super().__init__(
            name="GUID_to_ApplicationName",
            category="GUID",
            description="Map GUIDs to application names from Known_GUIDs.csv",
            target_db_name="Known_GUIDs.db"
        )

    def get_query(self) -> str:
        """Generate SQL query with ATTACH statements for GUID_to_ApplicationName mapping."""
        return """
            SELECT 
                guid AS value,
                app_name AS key,
                'known_guids' AS source
            FROM TargetDB.known_guids
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        """Extract mappings from query results, filtering out NULL values."""
        return [(str(row[0]), str(row[1]), str(row[2])) 
                for row in query_results 
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class AppIDAppRule(DefaultRule):
    """Rule for AppID_to_ApplicationName."""

    def __init__(self):
        super().__init__(
            name="AppID_to_ApplicationName",
            category="AppID",
            description="Map AppIDs to application names from Known_AppIDs.csv",
            target_db_name="Known_AppIDs.db"
        )

    def get_query(self) -> str:
        """Generate SQL query with ATTACH statements for AppID_to_ApplicationName mapping."""
        return """
            SELECT 
                appid AS value,
                app_name AS key,
                'known_appids' AS source
            FROM TargetDB.known_appids
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        """Extract mappings from query results, filtering out NULL values."""
        return [(str(row[0]), str(row[1]), str(row[2])) 
                for row in query_results 
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class CLSIDComponentRule(DefaultRule):
    """Rule for CLSID_to_ComponentName."""

    def __init__(self):
        super().__init__(
            name="CLSID_to_ComponentName",
            category="CLSID",
            description="Map CLSIDs to COM component names",
            target_db_name="Registry.db"
        )

    def get_query(self) -> str:
        """Generate SQL query with ATTACH statements for CLSID_to_ComponentName mapping."""
        return """
            SELECT 
                clsid AS value,
                component_name AS key,
                'clsid_registry' AS source
            FROM TargetDB.clsid_registry
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        """Extract mappings from query results, filtering out NULL values."""
        return [(str(row[0]), str(row[1]), str(row[2])) 
                for row in query_results 
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class ProcessIDRule(DefaultRule):
    """Rule for ProcessID_to_ProcessName."""

    def __init__(self):
        super().__init__(
            name="ProcessID_to_ProcessName",
            category="ProcessID",
            description="Map process IDs to process names",
            target_db_name="Execution.db"
        )

    def get_query(self) -> str:
        """Generate SQL query with ATTACH statements for ProcessID_to_ProcessName mapping."""
        return """
            SELECT 
                process_id AS value,
                process_name AS key,
                'process_events' AS source
            FROM TargetDB.process_events
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        """Extract mappings from query results, filtering out NULL values."""
        return [(str(row[0]), str(row[1]), str(row[2])) 
                for row in query_results 
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class VolumeRule(DefaultRule):
    """Rule for VolumeGUID_to_VolumeName."""

    def __init__(self):
        super().__init__(
            name="VolumeGUID_to_VolumeName",
            category="VolumeGUID",
            description="Map volume GUIDs to volume labels",
            target_db_name="Disk.db"
        )

    def get_query(self) -> str:
        """Generate SQL query with ATTACH statements for VolumeGUID_to_VolumeName mapping."""
        return """
            SELECT 
                volume_guid AS value,
                volume_label AS key,
                'volume_info' AS source
            FROM TargetDB.volume_info
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        """Extract mappings from query results, filtering out NULL values."""
        return [(str(row[0]), str(row[1]), str(row[2])) 
                for row in query_results 
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class IPHostnameRule(DefaultRule):
    """Rule for IP_to_Hostname."""

    def __init__(self):
        super().__init__(
            name="IP_to_Hostname",
            category="IP",
            description="Map IP addresses to hostnames from DNS cache",
            target_db_name="DNS.db"
        )

    def get_query(self) -> str:
        """Generate SQL query with ATTACH statements for IP_to_Hostname mapping."""
        return """
            SELECT 
                ip_address AS value,
                hostname AS key,
                'dns_cache' AS source
            FROM TargetDB.dns_cache
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        """Extract mappings from query results, filtering out NULL values."""
        return [(str(row[0]), str(row[1]), str(row[2])) 
                for row in query_results 
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class USBRule(DefaultRule):
    """Rule for USBSerial_to_DeviceName."""

    def __init__(self):
        super().__init__(
            name="USBSerial_to_DeviceName",
            category="USBSerial",
            description="Map USB serial numbers to device names",
            target_db_name="USB.db"
        )

    def get_query(self) -> str:
        """Generate SQL query with ATTACH statements for USBSerial_to_DeviceName mapping."""
        return """
            SELECT 
                serial_number AS value,
                device_name AS key,
                'usb_devices' AS source
            FROM TargetDB.usb_devices
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        """Extract mappings from query results, filtering out NULL values."""
        return [(str(row[0]), str(row[1]), str(row[2])) 
                for row in query_results 
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class ServiceRule(DefaultRule):
    """Rule for ServiceName_to_DisplayName."""

    def __init__(self):
        super().__init__(
            name="ServiceName_to_DisplayName",
            category="ServiceName",
            description="Map service names to display names",
            target_db_name="Services.db"
        )

    def get_query(self) -> str:
        """Generate SQL query with ATTACH statements for ServiceName_to_DisplayName mapping."""
        return """
            SELECT 
                service_name AS value,
                display_name AS key,
                'services' AS source
            FROM TargetDB.services
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        """Extract mappings from query results, filtering out NULL values."""
        return [(str(row[0]), str(row[1]), str(row[2])) 
                for row in query_results 
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class EventIDRule(DefaultRule):
    """Rule for EventID_to_EventDescription."""

    def __init__(self):
        super().__init__(
            name="EventID_to_EventDescription",
            category="EventID",
            description="Map event IDs to event descriptions",
            target_db_name="EventLog.db"
        )

    def get_query(self) -> str:
        """Generate SQL query with ATTACH statements for EventID_to_EventDescription mapping."""
        return """
            SELECT 
                event_id AS value,
                description AS key,
                'event_logs' AS source
            FROM TargetDB.event_logs
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        """Extract mappings from query results, filtering out NULL values."""
        return [(str(row[0]), str(row[1]), str(row[2])) 
                for row in query_results 
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class WellKnownSIDRule(DefaultRule):
    """Rule for mapping common Windows well-known SIDs."""

    def __init__(self):
        super().__init__(
            name="Well_Known_SIDs",
            category="SID",
            description="Map common Windows SIDs (System, LocalService, etc.) to names",
            target_db_name=None # Internal rule
        )

    def get_query(self) -> str:
        return ""

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        well_known = [
            ("S-1-5-18", "NT AUTHORITY\\SYSTEM", "Windows_Internals"),
            ("S-1-5-19", "NT AUTHORITY\\LOCAL SERVICE", "Windows_Internals"),
            ("S-1-5-20", "NT AUTHORITY\\NETWORK SERVICE", "Windows_Internals"),
            ("S-1-5-17", "IUSR", "Windows_Internals"),
            ("S-1-0", "Null Authority", "Windows_Internals"),
            ("S-1-1", "Everyone", "Windows_Internals"),
            ("S-1-2", "Local", "Windows_Internals"),
            ("S-1-3", "Creator Owner", "Windows_Internals"),
            ("S-1-5-32-544", "Administrators", "Windows_Internals"),
            ("S-1-5-32-545", "Users", "Windows_Internals"),
            ("S-1-5-32-546", "Guests", "Windows_Internals"),
            ("S-1-5-32-547", "Power Users", "Windows_Internals"),
            ("S-1-5-32-548", "Account Operators", "Windows_Internals"),
            ("S-1-5-32-549", "Server Operators", "Windows_Internals"),
            ("S-1-5-32-550", "Print Operators", "Windows_Internals"),
            ("S-1-5-32-551", "Backup Operators", "Windows_Internals"),
            ("S-1-5-32-552", "Replicators", "Windows_Internals"),
            ("S-1-5-11", "Authenticated Users", "Windows_Internals"),
            ("S-1-5-12", "Restricted Code", "Windows_Internals"),
            ("S-1-5-4", "Interactive", "Windows_Internals"),
            ("S-1-5-6", "Service", "Windows_Internals"),
            ("S-1-5-7", "Anonymous", "Windows_Internals"),
        ]
        return well_known


# Default Rules Registry
DEFAULT_RULES: Dict[str, DefaultRule] = {
    "SID_to_Username": SIDUsernameRule(),
    "SID_to_ProfilePath": SIDProfileRule(),
    "MAC_to_NetworkName": MACNetworkRule(),
    "MAC_to_DeviceName": MACDeviceRule(),
    "Hash_to_Filename": HashFilenameRule(),
    "Hash_to_ApplicationName": HashAppRule(),
    "GUID_to_ApplicationName": GUIDAppRule(),
    "AppID_to_ApplicationName": AppIDAppRule(),
    "CLSID_to_ComponentName": CLSIDComponentRule(),
    "ProcessID_to_ProcessName": ProcessIDRule(),
    "VolumeGUID_to_VolumeName": VolumeRule(),
    "IP_to_Hostname": IPHostnameRule(),
    "USBSerial_to_DeviceName": USBRule(),
    "ServiceName_to_DisplayName": ServiceRule(),
    "EventID_to_EventDescription": EventIDRule(),
    "Well_Known_SIDs": WellKnownSIDRule(),
}
