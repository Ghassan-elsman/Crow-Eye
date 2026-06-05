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


# class MACDeviceRule(DefaultRule):
#     """Rule for MAC_to_DeviceName."""
#
#     def __init__(self):
#         super().__init__(
#             name="MAC_to_DeviceName",
#             category="MAC",
#             description="Map MAC addresses to device names",
#             target_db_name="Network.db"
#         )
#
#     def get_query(self) -> str:
#         """Generate SQL query with ATTACH statements for MAC_to_DeviceName mapping."""
#         return """
#             SELECT 
#                 mac_address AS value,
#                 device_name AS key,
#                 'network_devices' AS source
#             FROM TargetDB.network_devices
#         """
#
#     def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
#         """Extract mappings from query results, filtering out NULL values."""
#         return [(str(row[0]), str(row[1]), str(row[2])) 
#                 for row in query_results 
#                 if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]
#

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
        """Generate SQL query with ATTACH statements for Hash_to_Filename mapping.
        Filters out garbage placeholders (like *.exe, @productname, fx_ver_...) and falls back to name."""
        return """
            SELECT 
                file_id AS value,
                CASE 
                    WHEN original_file_name IS NULL OR original_file_name = '' OR original_file_name = '*.exe' 
                         OR original_file_name LIKE '%@productname' 
                         OR original_file_name LIKE 'fx_ver_%'
                         OR original_file_name LIKE '@%'
                    THEN name
                    ELSE original_file_name
                END AS key,
                'InventoryApplicationFile' AS source
            FROM TargetDB.InventoryApplicationFile
            WHERE (original_file_name IS NOT NULL AND original_file_name != '') OR (name IS NOT NULL AND name != '')
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        """Extract mappings from query results, filtering out NULL values."""
        return [(str(row[0]), str(row[1]), str(row[2])) 
                for row in query_results 
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


# class HashAppRule(DefaultRule):
#     """Rule for Hash_to_ApplicationName."""
#
#     def __init__(self):
#         super().__init__(
#             name="Hash_to_ApplicationName",
#             category="Hash",
#             description="Map hashes to known application names",
#             target_db_name="Known_Hashes.db"
#         )
#
#     def get_query(self) -> str:
#         """Generate SQL query with ATTACH statements for Hash_to_ApplicationName mapping."""
#         return """
#             SELECT 
#                 hash AS value,
#                 app_name AS key,
#                 'known_hashes' AS source
#             FROM TargetDB.known_hashes
#         """
#
#     def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
#         """Extract mappings from query results, filtering out NULL values."""
#         return [(str(row[0]), str(row[1]), str(row[2])) 
#                 for row in query_results 
#                 if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]
#

# class GUIDAppRule(DefaultRule):
#     """Rule for GUID_to_ApplicationName."""
#
#     def __init__(self):
#         super().__init__(
#             name="GUID_to_ApplicationName",
#             category="GUID",
#             description="Map GUIDs to application names from Known_GUIDs.csv",
#             target_db_name="Known_GUIDs.db"
#         )
#
#     def get_query(self) -> str:
#         """Generate SQL query with ATTACH statements for GUID_to_ApplicationName mapping."""
#         return """
#             SELECT 
#                 guid AS value,
#                 app_name AS key,
#                 'known_guids' AS source
#             FROM TargetDB.known_guids
#         """
#
#     def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
#         """Extract mappings from query results, filtering out NULL values."""
#         return [(str(row[0]), str(row[1]), str(row[2])) 
#                 for row in query_results 
#                 if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]
#

# class AppIDAppRule(DefaultRule):
#     """Rule for AppID_to_ApplicationName."""
#
#     def __init__(self):
#         super().__init__(
#             name="AppID_to_ApplicationName",
#             category="AppID",
#             description="Map AppIDs to application names from Known_AppIDs.csv",
#             target_db_name="Known_AppIDs.db"
#         )
#
#     def get_query(self) -> str:
#         """Generate SQL query with ATTACH statements for AppID_to_ApplicationName mapping."""
#         return """
#             SELECT 
#                 appid AS value,
#                 app_name AS key,
#                 'known_appids' AS source
#             FROM TargetDB.known_appids
#         """
#
#     def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
#         """Extract mappings from query results, filtering out NULL values."""
#         return [(str(row[0]), str(row[1]), str(row[2])) 
#                 for row in query_results 
#                 if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]
#

# class CLSIDComponentRule(DefaultRule):
#     """Rule for CLSID_to_ComponentName."""
#
#     def __init__(self):
#         super().__init__(
#             name="CLSID_to_ComponentName",
#             category="CLSID",
#             description="Map CLSIDs to COM component names",
#             target_db_name="Registry.db"
#         )
#
#     def get_query(self) -> str:
#         """Generate SQL query with ATTACH statements for CLSID_to_ComponentName mapping."""
#         return """
#             SELECT 
#                 clsid AS value,
#                 component_name AS key,
#                 'clsid_registry' AS source
#             FROM TargetDB.clsid_registry
#         """
#
#     def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
#         """Extract mappings from query results, filtering out NULL values."""
#         return [(str(row[0]), str(row[1]), str(row[2])) 
#                 for row in query_results 
#                 if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]
#

# class ProcessIDRule(DefaultRule):
#     """Rule for ProcessID_to_ProcessName."""
#
#     def __init__(self):
#         super().__init__(
#             name="ProcessID_to_ProcessName",
#             category="ProcessID",
#             description="Map process IDs to process names",
#             target_db_name="Execution.db"
#         )
#
#     def get_query(self) -> str:
#         """Generate SQL query with ATTACH statements for ProcessID_to_ProcessName mapping."""
#         return """
#             SELECT 
#                 process_id AS value,
#                 process_name AS key,
#                 'process_events' AS source
#             FROM TargetDB.process_events
#         """
#
#     def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
#         """Extract mappings from query results, filtering out NULL values."""
#         return [(str(row[0]), str(row[1]), str(row[2])) 
#                 for row in query_results 
#                 if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]
#

class VolumeRule(DefaultRule):
    """Rule for VolumeGUID_to_VolumeName."""

    def __init__(self):
        super().__init__(
            name="VolumeGUID_to_VolumeName",
            category="VolumeGUID",
            description="Map partition GUIDs to volume labels",
            target_db_name="partition_analysis.db"
        )

    def get_query(self) -> str:
        """Generate SQL query with ATTACH statements for VolumeGUID_to_VolumeName mapping."""
        return """
            SELECT 
                partition_guid AS value,
                volume_label AS key,
                'partitions' AS source
            FROM TargetDB.partitions
            WHERE partition_guid IS NOT NULL AND volume_label IS NOT NULL
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        """Extract mappings from query results, filtering out NULL values."""
        return [(str(row[0]), str(row[1]), str(row[2])) 
                for row in query_results 
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


# class IPHostnameRule(DefaultRule):
#     """Rule for IP_to_Hostname."""
#
#     def __init__(self):
#         super().__init__(
#             name="IP_to_Hostname",
#             category="IP",
#             description="Map IP addresses to hostnames from DNS cache",
#             target_db_name="DNS.db"
#         )
#
#     def get_query(self) -> str:
#         """Generate SQL query with ATTACH statements for IP_to_Hostname mapping."""
#         return """
#             SELECT 
#                 ip_address AS value,
#                 hostname AS key,
#                 'dns_cache' AS source
#             FROM TargetDB.dns_cache
#         """
#
#     def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
#         """Extract mappings from query results, filtering out NULL values."""
#         return [(str(row[0]), str(row[1]), str(row[2])) 
#                 for row in query_results 
#                 if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]
#

class USBRule(DefaultRule):
    """Rule for USBSerial_to_DeviceName."""

    def __init__(self):
        super().__init__(
            name="USBSerial_to_DeviceName",
            category="USBSerial",
            description="Map USB serial numbers to device names",
            target_db_name="registry_data.db"
        )

    def get_query(self) -> str:
        """Generate SQL query with ATTACH statements for USBSerial_to_DeviceName mapping."""
        return """
            SELECT 
                serial_number AS value,
                friendly_name AS key,
                'USBStorageDevices' AS source
            FROM TargetDB.USBStorageDevices
            WHERE serial_number IS NOT NULL AND friendly_name IS NOT NULL
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
            target_db_name="registry_data.db"
        )

    def get_query(self) -> str:
        """Generate SQL query with ATTACH statements for ServiceName_to_DisplayName mapping."""
        return """
            SELECT 
                service_name AS value,
                display_name AS key,
                'SystemServices' AS source
            FROM TargetDB.SystemServices
            WHERE service_name IS NOT NULL AND display_name IS NOT NULL
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
            target_db_name="Log_Claw.db"
        )

    def get_query(self) -> str:
        """Generate SQL query with ATTACH statements for EventID_to_EventDescription mapping."""
        return """
            SELECT 
                EventID AS value,
                EventDescription AS key,
                'SystemLogs' AS source
            FROM TargetDB.SystemLogs
            WHERE EventID IS NOT NULL AND EventDescription IS NOT NULL
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


# =====================================================================
# NEW RULES — Derived from real forensic database output
# =====================================================================

class MUICacheAppRule(DefaultRule):
    """Map raw executable paths to human-readable application names via MUICache."""

    def __init__(self):
        super().__init__(
            name="AppPath_to_AppName",
            category="AppPath",
            description="Map executable paths to application names from MUICache",
            target_db_name="registry_data.db"
        )

    def get_query(self) -> str:
        return """
            SELECT
                app_path AS value,
                app_name AS key,
                'MUICache' AS source
            FROM TargetDB.MUICache
            WHERE app_path IS NOT NULL AND app_name IS NOT NULL
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        return [(str(row[0]), str(row[1]), str(row[2]))
                for row in query_results
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class UserAssistRunCountRule(DefaultRule):
    """Map program paths to their execution run counts from UserAssist."""

    def __init__(self):
        super().__init__(
            name="ProgramPath_to_RunCount",
            category="Execution",
            description="Map program paths to execution run counts from UserAssist",
            target_db_name="registry_data.db"
        )

    def get_query(self) -> str:
        return """
            SELECT
                program_path AS value,
                CAST(run_count AS TEXT) || ' executions' AS key,
                'UserAssist' AS source
            FROM TargetDB.UserAssist
            WHERE program_path IS NOT NULL AND run_count > 0
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        return [(str(row[0]), str(row[1]), str(row[2]))
                for row in query_results
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class BAMProcessRule(DefaultRule):
    """Map executed process paths to usernames/SIDs via Background Activity Monitor."""

    def __init__(self):
        super().__init__(
            name="BAM_ProcessPath_to_Username",
            category="Execution",
            description="Map executed process paths to usernames from BAM and UserProfiles",
            target_db_name="registry_data.db"
        )

    def get_query(self) -> str:
        return """
            SELECT DISTINCT
                BAM.process_path AS value,
                COALESCE(
                    UserProfiles.username,
                    CASE BAM.sid
                        WHEN 'S-1-5-18' THEN 'SYSTEM'
                        WHEN 'S-1-5-19' THEN 'LOCAL SERVICE'
                        WHEN 'S-1-5-20' THEN 'NETWORK SERVICE'
                        ELSE BAM.sid
                    END
                ) AS key,
                'BAM' AS source
            FROM TargetDB.BAM
            LEFT JOIN TargetDB.UserProfiles ON BAM.sid = UserProfiles.user_sid
            WHERE BAM.process_path IS NOT NULL AND BAM.sid IS NOT NULL
                AND BAM.process_path != BAM.sid
                AND BAM.process_path NOT IN ('Version', 'SequenceNumber')
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        return [(str(row[0]), str(row[1]), str(row[2]))
                for row in query_results
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class USBDeviceDescriptionRule(DefaultRule):
    """Map USB device IDs to their human-readable descriptions."""

    def __init__(self):
        super().__init__(
            name="USBDeviceID_to_Description",
            category="USBDevice",
            description="Map USB device IDs to device descriptions",
            target_db_name="registry_data.db"
        )

    def get_query(self) -> str:
        return """
            SELECT
                device_id AS value,
                description AS key,
                'USBDevices' AS source
            FROM TargetDB.USBDevices
            WHERE device_id IS NOT NULL AND description IS NOT NULL
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        return [(str(row[0]), str(row[1]), str(row[2]))
                for row in query_results
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class VolumeSerialLabelRule(DefaultRule):
    """Map volume serial numbers from LNK files to volume labels."""

    def __init__(self):
        super().__init__(
            name="VolumeSerial_to_VolumeLabel",
            category="Volume",
            description="Map volume serial numbers to volume labels from LNK files",
            target_db_name="LnkDB.db"
        )

    def get_query(self) -> str:
        return """
            SELECT DISTINCT
                Volume_Serial AS value,
                Volume_Label AS key,
                'LNK_Files' AS source
            FROM TargetDB.LNK_Files
            WHERE Volume_Serial IS NOT NULL AND Volume_Serial != ''
              AND Volume_Label IS NOT NULL AND Volume_Label != '' AND Volume_Label != 'Not Labeled'
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        return [(str(row[0]), str(row[1]), str(row[2]))
                for row in query_results
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class InstalledAppPublisherRule(DefaultRule):
    """Map installed application names to their publishers for provenance tracking."""

    def __init__(self):
        super().__init__(
            name="InstalledApp_to_Publisher",
            category="Application",
            description="Map installed application names to publishers",
            target_db_name="registry_data.db"
        )

    def get_query(self) -> str:
        return """
            SELECT
                display_name AS value,
                publisher AS key,
                'InstalledSoftware' AS source
            FROM TargetDB.InstalledSoftware
            WHERE display_name IS NOT NULL AND publisher IS NOT NULL AND publisher != ''
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        return [(str(row[0]), str(row[1]), str(row[2]))
                for row in query_results
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class ProgramIDAppNameRule(DefaultRule):
    """Map Amcache cryptographic program IDs to installed application names."""

    def __init__(self):
        super().__init__(
            name="ProgramID_to_AppName",
            category="ProgramID",
            description="Map Amcache program IDs to application names",
            target_db_name="amcache.db"
        )

    def get_query(self) -> str:
        return """
            SELECT
                program_id AS value,
                name AS key,
                'InventoryApplication' AS source
            FROM TargetDB.InventoryApplication
            WHERE program_id IS NOT NULL AND name IS NOT NULL
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        return [(str(row[0]), str(row[1]), str(row[2]))
                for row in query_results
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class DriverCompanyRule(DefaultRule):
    """Map driver filenames to their signing company — critical for detecting suspicious drivers."""

    def __init__(self):
        super().__init__(
            name="DriverName_to_DriverCompany",
            category="Driver",
            description="Map driver filenames to their signing company from Amcache",
            target_db_name="amcache.db"
        )

    def get_query(self) -> str:
        return """
            SELECT
                driver_name AS value,
                driver_company AS key,
                'InventoryDriverBinary' AS source
            FROM TargetDB.InventoryDriverBinary
            WHERE driver_name IS NOT NULL AND driver_company IS NOT NULL AND driver_company != ''
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        return [(str(row[0]), str(row[1]), str(row[2]))
                for row in query_results
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class DeviceContainerNameRule(DefaultRule):
    """Map device container GUIDs to human-readable device names."""

    def __init__(self):
        super().__init__(
            name="DeviceContainerID_to_FriendlyName",
            category="DeviceContainer",
            description="Map device container GUIDs to friendly names from Amcache",
            target_db_name="amcache.db"
        )

    def get_query(self) -> str:
        return """
            SELECT
                id AS value,
                friendly_name AS key,
                'InventoryDeviceContainer' AS source
            FROM TargetDB.InventoryDeviceContainer
            WHERE id IS NOT NULL AND friendly_name IS NOT NULL AND friendly_name != ''
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        return [(str(row[0]), str(row[1]), str(row[2]))
                for row in query_results
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class JumpListAppIDRule(DefaultRule):
    """Map JumpList AppIDs to application descriptions."""

    def __init__(self):
        super().__init__(
            name="AppID_to_AppDesc_JumpList",
            category="AppID",
            description="Map JumpList AppIDs to application descriptions",
            target_db_name="LnkDB.db"
        )

    def get_query(self) -> str:
        return """
            SELECT DISTINCT
                AppID AS value,
                AppDesc AS key,
                'Automatic_JumpLists' AS source
            FROM TargetDB.Automatic_JumpLists
            WHERE AppID IS NOT NULL AND AppDesc IS NOT NULL
              AND AppDesc != '' AND AppDesc != 'Unknown'
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        return [(str(row[0]), str(row[1]), str(row[2]))
                for row in query_results
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class TrackerMACNetBIOSRule(DefaultRule):
    """Map MAC addresses embedded in LNK tracking data to machine NetBIOS names."""

    def __init__(self):
        super().__init__(
            name="TrackerMAC_to_NetBIOS",
            category="MAC",
            description="Map LNK tracker MAC addresses to NetBIOS machine names",
            target_db_name="LnkDB.db"
        )

    def get_query(self) -> str:
        return """
            SELECT DISTINCT
                Tracker_MAC AS value,
                Tracker_NetBIOS AS key,
                'LNK_Files' AS source
            FROM TargetDB.LNK_Files
            WHERE Tracker_MAC IS NOT NULL AND Tracker_MAC != ''
              AND Tracker_NetBIOS IS NOT NULL AND Tracker_NetBIOS != ''
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        return [(str(row[0]), str(row[1]), str(row[2]))
                for row in query_results
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class ShimCacheHashRule(DefaultRule):
    """Map ShimCache entry hashes to their executable filenames."""

    def __init__(self):
        super().__init__(
            name="ShimHash_to_Filename",
            category="Hash",
            description="Map ShimCache entry hashes to executable filenames",
            target_db_name="shimcache.db"
        )

    def get_query(self) -> str:
        return """
            SELECT
                entry_hash AS value,
                filename AS key,
                'shimcache_entries' AS source
            FROM TargetDB.shimcache_entries
            WHERE entry_hash IS NOT NULL AND filename IS NOT NULL
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        return [(str(row[0]), str(row[1]), str(row[2]))
                for row in query_results
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


class SRUMAppPathRule(DefaultRule):
    """Map SRUM app identifiers to their full disk paths — resolves package names to executables."""

    def __init__(self):
        super().__init__(
            name="SRUMApp_to_AppPath",
            category="Application",
            description="Map SRUM app identifiers to executable disk paths",
            target_db_name="srum_data.db"
        )

    def get_query(self) -> str:
        return """
            SELECT DISTINCT
                app_name AS value,
                app_path AS key,
                'srum_network_data_usage' AS source
            FROM TargetDB.srum_network_data_usage
            WHERE app_name IS NOT NULL AND app_path IS NOT NULL
              AND app_name != app_path AND app_path != ''
        """

    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        return [(str(row[0]), str(row[1]), str(row[2]))
                for row in query_results
                if row[0] and str(row[0]).strip() and row[1] and str(row[1]).strip()]


# =====================================================================
# Default Rules Registry
# =====================================================================
DEFAULT_RULES: Dict[str, DefaultRule] = {
    # --- SID mappings ---
    "SID_to_Username": SIDUsernameRule(),
    "SID_to_ProfilePath": SIDProfileRule(),
    "Well_Known_SIDs": WellKnownSIDRule(),
    # --- MAC / Network ---
    "MAC_to_NetworkName": MACNetworkRule(),
    # "MAC_to_DeviceName": MACDeviceRule(),
    "TrackerMAC_to_NetBIOS": TrackerMACNetBIOSRule(),
    # --- Hash ---
    "Hash_to_Filename": HashFilenameRule(),
    # "Hash_to_ApplicationName": HashAppRule(),
    "ShimHash_to_Filename": ShimCacheHashRule(),
    # --- Application / Execution ---
    "AppPath_to_AppName": MUICacheAppRule(),
    "ProgramPath_to_RunCount": UserAssistRunCountRule(),
    "BAM_ProcessPath_to_Username": BAMProcessRule(),
    "ProgramID_to_AppName": ProgramIDAppNameRule(),
    "InstalledApp_to_Publisher": InstalledAppPublisherRule(),
    "SRUMApp_to_AppPath": SRUMAppPathRule(),
    # --- GUID / AppID ---
    # "GUID_to_ApplicationName": GUIDAppRule(),
    # "AppID_to_ApplicationName": AppIDAppRule(),
    "AppID_to_AppDesc_JumpList": JumpListAppIDRule(),
    # --- Device / Driver ---
    "DriverName_to_DriverCompany": DriverCompanyRule(),
    "DeviceContainerID_to_FriendlyName": DeviceContainerNameRule(),
    "USBSerial_to_DeviceName": USBRule(),
    "USBDeviceID_to_Description": USBDeviceDescriptionRule(),
    # --- Volume ---
    "VolumeGUID_to_VolumeName": VolumeRule(),
    "VolumeSerial_to_VolumeLabel": VolumeSerialLabelRule(),
    # --- CLSID / ProcessID (optional reference DBs) ---
    # "CLSID_to_ComponentName": CLSIDComponentRule(),
    # "ProcessID_to_ProcessName": ProcessIDRule(),
    # --- Network / Service / Event ---
    # "IP_to_Hostname": IPHostnameRule(),
    "ServiceName_to_DisplayName": ServiceRule(),
    "EventID_to_EventDescription": EventIDRule(),
}
