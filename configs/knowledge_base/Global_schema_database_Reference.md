# Global Database Schema Reference

This document contains the comprehensive schema for all parsed artifacts and correlation databases. Use this reference to write precise SQL queries without needing to call `get_schema` first.

**`parsed_at` is parser bookkeeping** — it records when Crow-Eye parsed the artifact, not when the artifact activity occurred. Never use it as an event time. Case databases written by older Crow-Eye builds may still carry the legacy names `timestamp` (registry tables), `parsed_timestamp` (ShimCache), `parse_timestamp` (SRUM metadata) or `inserted_at` (USN); check the actual schema before querying an older case.


## Database: `amcache.db`

### Table: `InventoryApplication`

| Column | Type |
|---|---|
| `id` | TEXT |
| `name` | TEXT |
| `program_id` | TEXT |
| `program_instance_id` | TEXT |
| `version` | TEXT |
| `publisher` | TEXT |
| `language` | TEXT |
| `source` | TEXT |
| `root_dir_path` | TEXT |
| `store_app_type` | TEXT |
| `inbox_modern_app` | TEXT |
| `manifest_path` | TEXT |
| `package_full_name` | TEXT |
| `install_date` | TEXT |
| `bundle_manifest_path` | TEXT |
| `parsed_at` | TEXT |


### Table: `InventoryApplicationFile`

| Column | Type |
|---|---|
| `id` | TEXT |
| `name` | TEXT |
| `file_id` | TEXT |
| `lower_case_long_path` | TEXT |
| `original_file_name` | TEXT |
| `publisher` | TEXT |
| `version` | TEXT |
| `bin_file_version` | TEXT |
| `binary_type` | TEXT |
| `product_name` | TEXT |
| `product_version` | TEXT |
| `link_date` | TEXT |
| `bin_product_version` | TEXT |
| `size` | TEXT |
| `language` | TEXT |
| `usn` | TEXT |
| `parsed_at` | TEXT |


### Table: `InventoryApplicationShortcut`

| Column | Type |
|---|---|
| `id` | TEXT |
| `ShortcutPath` | TEXT |
| `ShortcutTargetPath` | TEXT |
| `ShortcutAumid` | TEXT |
| `ShortcutProgramId` | TEXT |
| `parsed_at` | TEXT |


### Table: `InventoryDriverBinary`

| Column | Type |
|---|---|
| `id` | TEXT |
| `driver_name` | TEXT |
| `inf` | TEXT |
| `driver_version` | TEXT |
| `product` | TEXT |
| `product_version` | TEXT |
| `wdf_version` | TEXT |
| `driver_company` | TEXT |
| `service` | TEXT |
| `driver_in_box` | TEXT |
| `driver_signed` | TEXT |
| `driver_is_kernel_mode` | TEXT |
| `driver_id` | TEXT |
| `driver_last_write_time` | TEXT |
| `driver_type` | TEXT |
| `driver_time_stamp` | TEXT |
| `driver_check_sum` | TEXT |
| `image_size` | TEXT |
| `parsed_at` | TEXT |


### Table: `InventoryDriverPackage`

| Column | Type |
|---|---|
| `id` | TEXT |
| `driver_package_strong_name` | TEXT |
| `provider` | TEXT |
| `driver_in_box` | TEXT |
| `inf_name` | TEXT |
| `hwids` | TEXT |
| `parsed_at` | TEXT |


### Table: `InventoryDeviceContainer`

| Column | Type |
|---|---|
| `id` | TEXT |
| `model_name` | TEXT |
| `icon` | TEXT |
| `friendly_name` | TEXT |
| `model_number` | TEXT |
| `manufacturer` | TEXT |
| `model_id` | TEXT |
| `primary_category` | TEXT |
| `categories` | TEXT |
| `is_machine_container` | TEXT |
| `discovery_method` | TEXT |
| `is_connected` | TEXT |
| `is_active` | TEXT |
| `is_paired` | TEXT |
| `is_networked` | TEXT |
| `state` | TEXT |
| `parsed_at` | TEXT |


### Table: `InventoryDevicePnp`

| Column | Type |
|---|---|
| `id` | TEXT |
| `service` | TEXT |
| `class` | TEXT |
| `class_guid` | TEXT |
| `model` | TEXT |
| `upper_filters` | TEXT |
| `lower_filters` | TEXT |
| `enumerator` | TEXT |
| `upper_class_filters` | TEXT |
| `lower_class_filters` | TEXT |
| `install_state` | TEXT |
| `device_state` | TEXT |
| `location_paths` | TEXT |
| `parsed_at` | TEXT |


### Table: `InventoryDeviceMediaClass`

| Column | Type |
|---|---|
| `id` | TEXT |
| `Audio_Render_Driver` | TEXT |
| `Audio_Capture_Driver` | TEXT |
| `parsed_at` | TEXT |


### Table: `InventoryDeviceInterface`

| Column | Type |
|---|---|
| `id` | TEXT |
| `parsed_at` | TEXT |


### Table: `InventoryDeviceUsbHubClass`

| Column | Type |
|---|---|
| `id` | TEXT |
| `device_capabilities` | TEXT |
| `device_speed` | TEXT |
| `parsed_at` | TEXT |


### Table: `InventoryMiscellaneous`

| Column | Type |
|---|---|
| `id` | TEXT |
| `misc_name` | TEXT |
| `misc_type` | TEXT |
| `misc_value` | TEXT |
| `misc_source` | TEXT |
| `parsed_at` | TEXT |


### Table: `InventoryMiscellaneousMemorySlotArrayInfo`

| Column | Type |
|---|---|
| `id` | TEXT |
| `memory_slot_array_id` | TEXT |
| `memory_slot_array_location` | TEXT |
| `memory_slot_array_use` | TEXT |
| `memory_slot_array_number_of_slots` | TEXT |
| `parsed_at` | TEXT |


### Table: `InventoryMiscellaneousUupInfo`

| Column | Type |
|---|---|
| `id` | TEXT |
| `uup_name` | TEXT |
| `uup_id` | TEXT |
| `uup_version` | TEXT |
| `uup_description` | TEXT |
| `uup_state` | TEXT |
| `uup_install_source` | TEXT |
| `uup_publisher` | TEXT |
| `parsed_at` | TEXT |


### Table: `InventoryMiscellaneousUser`

| Column | Type |
|---|---|
| `id` | TEXT |
| `user_name` | TEXT |
| `user_sid` | TEXT |
| `user_type` | TEXT |
| `parsed_at` | TEXT |


### Table: `Mare`

| Column | Type |
|---|---|
| `id` | TEXT |
| `mare_name` | TEXT |
| `mare_id` | TEXT |
| `mare_type` | TEXT |
| `mare_state` | TEXT |
| `mare_path` | TEXT |
| `mare_flags` | TEXT |
| `mare_data` | TEXT |
| `parsed_at` | TEXT |


### Table: `DeviceCensus`

| Column | Type |
|---|---|
| `id` | TEXT |
| `data` | TEXT |
| `parsed_at` | TEXT |


### Table: `UnknownSubkeys`

| Column | Type |
|---|---|
| `id` | TEXT |
| `subkey_name` | TEXT |
| `data` | TEXT |
| `parsed_at` | TEXT |


## Database: `LnkDB.db`

### Table: `LNK_Files`

`Target_Source` names the structure the target was recovered from, because a shortcut does not have
to record it the same way twice:

- `LinkInfo` - a literal path, the classic case.
- `EnvironmentVariableDataBlock` - the shortcut sets ForceNoLinkInfo and stores the target as a
  variable reference, e.g. `%windir%\system32\mstsc.exe`. Most of a stock Start Menu is like this.
  **The value is stored unexpanded**: expanding it would use the environment of the machine running
  Crow-Eye, which for an image acquired elsewhere is the wrong machine.
- `IDList` - reconstructed from the shell item chain, and only used when it reduces to a
  drive-letter or UNC path. A shell-namespace path stays in `Property_Metadata.IDList_Path` rather
  than being presented as a target.
- empty - the entry records no recoverable target, e.g. a DestList row with no embedded shortcut.

Measured against Windows' own `WScript.Shell` resolver over 144 real shortcuts: 106 exact matches,
32 in variable form, none missing and none wrong.

| Column | Type |
|---|---|
| `Source_Name` | TEXT |
| `Source_Path` | TEXT |
| `Owner_UID` | INTEGER |
| `Owner_GID` | INTEGER |
| `File_Permission` | TEXT |
| `Num_Hard_Links` | INTEGER |
| `Device_ID` | INTEGER |
| `Inode_Number` | INTEGER |
| `Time_Access` | TEXT |
| `Time_Creation` | TEXT |
| `Time_Modification` | TEXT |
| `LNK_Class_ID` | TEXT |
| `Link_Flags` | TEXT |
| `File_Attributes_Flags` | TEXT |
| `FileSize` | TEXT |
| `IconIndex` | INTEGER |
| `Show_Window_Command` | TEXT |
| `Hot_Key_Flags` | TEXT |
| `Hot_Key_Value` | TEXT |
| `Local_Path` | TEXT |
| `Target_Source` | TEXT |
| `Network_Share_Name` | TEXT |
| `Common_Path` | TEXT |
| `Relative_Path` | TEXT |
| `Working_Directory` | TEXT |
| `Command_Line_Arguments` | TEXT |
| `Icon_Location` | TEXT |
| `Description` | TEXT |
| `Volume_Type` | TEXT |
| `Volume_Serial` | TEXT |
| `Volume_Label` | TEXT |
| `MFT_Entry_Number` | TEXT |
| `MFT_Sequence_Number` | TEXT |
| `Tracker_NetBIOS` | TEXT |
| `Tracker_MAC` | TEXT |
| `Property_Metadata` | TEXT |
| `Darwin_ID` | TEXT |
| `Environment_Variables` | TEXT |
| `Known_Folder_GUID` | TEXT |

### Table: `Automatic_JumpLists`

| Column | Type |
|---|---|
| `Source_Name` | TEXT |
| `Source_Path` | TEXT |
| `entry_number` | TEXT |
| `Owner_UID` | INTEGER |
| `Owner_GID` | INTEGER |
| `File_Permission` | TEXT |
| `Num_Hard_Links` | INTEGER |
| `Device_ID` | INTEGER |
| `Inode_Number` | INTEGER |
| `AppID` | TEXT |
| `AppType` | TEXT |
| `AppDesc` | TEXT |
| `Time_Access` | TEXT |
| `Time_Creation` | TEXT |
| `Time_Modification` | TEXT |
| `LNK_Class_ID` | TEXT |
| `Link_Flags` | TEXT |
| `File_Attributes_Flags` | TEXT |
| `FileSize` | TEXT |
| `IconIndex` | INTEGER |
| `Show_Window_Command` | TEXT |
| `Hot_Key_Flags` | TEXT |
| `Hot_Key_Value` | TEXT |
| `Local_Path` | TEXT |
| `Target_Source` | TEXT |
| `Network_Share_Name` | TEXT |
| `Common_Path` | TEXT |
| `Relative_Path` | TEXT |
| `Working_Directory` | TEXT |
| `Command_Line_Arguments` | TEXT |
| `Icon_Location` | TEXT |
| `Description` | TEXT |
| `Volume_Type` | TEXT |
| `Volume_Serial` | TEXT |
| `Volume_Label` | TEXT |
| `MFT_Entry_Number` | TEXT |
| `MFT_Sequence_Number` | TEXT |
| `Tracker_NetBIOS` | TEXT |
| `Tracker_MAC` | TEXT |
| `DestList_Version_Number` | INTEGER |
| `DestList_OS_Version` | TEXT |
| `DestList_Total_Current_Entries` | INTEGER |
| `DestList_Total_Pinned_Entries` | INTEGER |
| `DestList_Last_ID` | INTEGER |
| `DestList_Actions_Count` | INTEGER |
| `DestList_Checksum` | TEXT |
| `DestList_New_Volume_ID` | TEXT |
| `DestList_New_Object_ID` | TEXT |
| `Birth_Volume_ID` | TEXT |
| `Birth_Object_ID` | TEXT |
| `Birth_Object_ID_MAC` | TEXT |
| `DestList_Access_Counter` | INTEGER |
| `DestList_Pin_Status` | TEXT |
| `Embedded_LNK` | TEXT |
| `Property_Metadata` | TEXT |
| `Darwin_ID` | TEXT |
| `Environment_Variables` | TEXT |
| `Known_Folder_GUID` | TEXT |

### Table: `Custom_JumpLists`

| Column | Type |
|---|---|
| `entry_id` | INTEGER |
| `Source_Name` | TEXT |
| `Source_Path` | TEXT |
| `Owner_UID` | INTEGER |
| `Owner_GID` | INTEGER |
| `File_Permission` | TEXT |
| `Num_Hard_Links` | INTEGER |
| `Device_ID` | INTEGER |
| `Inode_Number` | INTEGER |
| `AppID` | TEXT |
| `AppType` | TEXT |
| `AppDesc` | TEXT |
| `Category` | TEXT |
| `Footer_Signature_Valid` | INTEGER |
| `Time_Access` | TEXT |
| `Time_Creation` | TEXT |
| `Time_Modification` | TEXT |
| `LNK_Class_ID` | TEXT |
| `Link_Flags` | TEXT |
| `File_Attributes_Flags` | TEXT |
| `FileSize` | TEXT |
| `IconIndex` | INTEGER |
| `Show_Window_Command` | TEXT |
| `Hot_Key_Flags` | TEXT |
| `Hot_Key_Value` | TEXT |
| `Local_Path` | TEXT |
| `Target_Source` | TEXT |
| `Network_Share_Name` | TEXT |
| `Common_Path` | TEXT |
| `Relative_Path` | TEXT |
| `Working_Directory` | TEXT |
| `Command_Line_Arguments` | TEXT |
| `Icon_Location` | TEXT |
| `Description` | TEXT |
| `Volume_Type` | TEXT |
| `Volume_Serial` | TEXT |
| `Volume_Label` | TEXT |
| `MFT_Entry_Number` | TEXT |
| `MFT_Sequence_Number` | TEXT |
| `Tracker_NetBIOS` | TEXT |
| `Tracker_MAC` | TEXT |
| `Embedded_LNK` | TEXT |
| `Property_Metadata` | TEXT |
| `Darwin_ID` | TEXT |
| `Environment_Variables` | TEXT |
| `Known_Folder_GUID` | TEXT |


## Database: `Log_Claw.db`

### Table: `SystemLogs`

| Column | Type |
|---|---|
| `EventID` | INTEGER |
| `Source` | TEXT |
| `EventType` | TEXT |
| `Category` | TEXT |
| `EventTimestampUTC` | TEXT |
| `ComputerName` | TEXT |
| `User` | TEXT |
| `Keywords` | TEXT |
| `EventDescription` | TEXT |


### Table: `ApplicationLogs`

| Column | Type |
|---|---|
| `EventID` | INTEGER |
| `Source` | TEXT |
| `EventType` | TEXT |
| `Category` | TEXT |
| `EventTimestampUTC` | TEXT |
| `ComputerName` | TEXT |
| `User` | TEXT |
| `Keywords` | TEXT |
| `EventDescription` | TEXT |


### Table: `SecurityLogs`

| Column | Type |
|---|---|
| `EventID` | INTEGER |
| `Source` | TEXT |
| `EventType` | TEXT |
| `Category` | TEXT |
| `EventTimestampUTC` | TEXT |
| `ComputerName` | TEXT |
| `User` | TEXT |
| `Keywords` | TEXT |
| `TaskCategory` | TEXT |
| `EventDescription` | TEXT |


## Database: `mft_claw_analysis.db`

### Table: `mft_records`

| Column | Type |
|---|---|
| `record_number` | INTEGER |
| `file_name` | TEXT |
| `volume_letter` | TEXT |
| `extension` | TEXT |
| `file_size` | INTEGER |
| `in_use` | INTEGER |
| `is_directory` | INTEGER |
| `flags` | INTEGER |
| `mft_sequence_number` | INTEGER |
| `has_ads` | INTEGER |
| `ads_count` | INTEGER |
| `created_time` | TIMESTAMP |
| `modified_time` | TIMESTAMP |
| `accessed_time` | TIMESTAMP |
| `mft_modified_time` | TIMESTAMP |
| `file_attributes` | INTEGER |


### Table: `mft_standard_info`

| Column | Type |
|---|---|
| `record_number` | INTEGER |
| `file_name` | TEXT |
| `volume_letter` | TEXT |
| `created` | TIMESTAMP |
| `modified` | TIMESTAMP |
| `accessed` | TIMESTAMP |
| `mft_modified` | TIMESTAMP |
| `flags` | INTEGER |
| `max_versions` | INTEGER |
| `version_number` | INTEGER |
| `class_id` | INTEGER |
| `owner_id` | INTEGER |
| `security_id` | INTEGER |
| `quota_charged` | INTEGER |
| `usn` | INTEGER |


### Table: `mft_file_names`

| Column | Type |
|---|---|
| `record_number` | INTEGER |
| `file_name` | TEXT |
| `volume_letter` | TEXT |
| `parent_record` | INTEGER |
| `parent_sequence` | INTEGER |
| `namespace` | INTEGER |
| `created` | TIMESTAMP |
| `modified` | TIMESTAMP |
| `accessed` | TIMESTAMP |
| `mft_modified` | TIMESTAMP |
| `allocated_size` | INTEGER |
| `real_size` | INTEGER |
| `flags` | INTEGER |


### Table: `mft_data_attributes`

| Column | Type |
|---|---|
| `record_number` | INTEGER |
| `file_name` | TEXT |
| `volume_letter` | TEXT |
| `attribute_name` | TEXT |
| `resident` | INTEGER |
| `size` | INTEGER |
| `data_type` | TEXT |


### Table: `filename_changes`

| Column | Type |
|---|---|
| `record_number` | INTEGER |
| `old_filename` | TEXT |
| `volume_letter` | TEXT |
| `new_filename` | TEXT |
| `change_timestamp` | TEXT |
| `namespace` | TEXT |


## Database: `mft_usn_correlated_analysis.db`

### Table: `mft_usn_correlated`

| Column | Type |
|---|---|
| `mft_record_number` | INTEGER |
| `fn_filename` | TEXT |
| `mft_sequence_number` | INTEGER |
| `mft_flags` | TEXT |
| `is_directory` | INTEGER |
| `is_deleted` | INTEGER |
| `si_creation_time` | TEXT |
| `si_modification_time` | TEXT |
| `si_access_time` | TEXT |
| `si_mft_entry_change_time` | TEXT |
| `si_file_attributes` | TEXT |
| `fn_parent_record_number` | INTEGER |
| `fn_parent_sequence_number` | INTEGER |
| `fn_namespace` | TEXT |
| `fn_creation_time` | TEXT |
| `fn_modification_time` | TEXT |
| `fn_access_time` | TEXT |
| `fn_mft_entry_change_time` | TEXT |
| `fn_allocated_size` | INTEGER |
| `fn_real_size` | INTEGER |
| `fn_file_attributes` | TEXT |
| `reconstructed_path` | TEXT |
| `usn_event_id` | INTEGER |
| `usn_timestamp` | TEXT |
| `usn_reason` | TEXT |
| `usn_source_info` | TEXT |
| `usn_file_attributes` | TEXT |
| `has_mft_record` | INTEGER |
| `has_usn_event` | INTEGER |
| `correlation_confidence` | TEXT |
| `filename_change_timeline` | TEXT |
| `namespace_evolution` | TEXT |
| `created_at` | TEXT |


## Database: `prefetch_data.db`

### Table: `prefetch_data`

| Column | Type |
|---|---|
| `filename` | TEXT |
| `executable_name` | TEXT |
| `hash` | TEXT |
| `run_count` | INTEGER |
| `last_executed` | TIMESTAMP |
| `run_times` | JSON |
| `volumes` | JSON |
| `directories` | JSON |
| `resources` | JSON |
| `created_on` | TIMESTAMP |
| `modified_on` | TIMESTAMP |
| `accessed_on` | TIMESTAMP |


## Database: `recyclebin_analysis.db`

### Table: `recycle_bin_entries`

| Column | Type |
|---|---|
| `original_filename` | TEXT |
| `original_path` | TEXT |
| `deletion_time` | TEXT |
| `formatted_file_size` | TEXT |
| `user_sid` | TEXT |
| `recycle_bin_path` | TEXT |
| `r_file_path` | TEXT |
| `random_i_filename` | TEXT |
| `random_r_filename` | TEXT |
| `file_signature` | TEXT |
| `recovery_status` | TEXT |
| `parsed_at` | TEXT |


## Database: `registry_data.db`

### Table: `machine_run`

| Column | Type |
|---|---|
| `name` | TEXT |
| `row_data` | TEXT |
| `type` | TEXT |


### Table: `machine_run_once`

| Column | Type |
|---|---|
| `name` | TEXT |
| `row_data` | TEXT |
| `type` | TEXT |


### Table: `user_run`

| Column | Type |
|---|---|
| `name` | TEXT |
| `row_data` | TEXT |
| `type` | TEXT |


### Table: `user_run_once`

| Column | Type |
|---|---|
| `name` | TEXT |
| `row_data` | TEXT |
| `type` | TEXT |


### Table: `Windows_lastupdate`

| Column | Type |
|---|---|
| `name` | TEXT |
| `row_data` | TEXT |
| `type` | TEXT |


### Table: `Windows_lastupdate_subkeys`

| Column | Type |
|---|---|
| `subkey` | TEXT |
| `name` | TEXT |
| `row_data` | TEXT |
| `type` | TEXT |


### Table: `computer_Name`

| Column | Type |
|---|---|
| `name` | TEXT |
| `row_data` | TEXT |
| `type` | TEXT |


### Table: `time_zone`

| Column | Type |
|---|---|
| `name` | TEXT |
| `row_data` | TEXT |
| `type` | TEXT |


### Table: `network_interfaces`

| Column | Type |
|---|---|
| `subkey` | TEXT |
| `name` | TEXT |
| `row_data` | TEXT |
| `type` | TEXT |


### Table: `shutdown_information`

| Column | Type |
|---|---|
| `name` | TEXT |
| `row_data` | TEXT |
| `type` | TEXT |


### Table: `ComputerNameInfo`

| Column | Type |
|---|---|
| `computer_name` | TEXT |
| `registered_owner` | TEXT |
| `registered_organization` | TEXT |
| `product_id` | TEXT |
| `installation_date` | TEXT |
| `parsed_at` | TEXT |


### Table: `TimeZoneInfo`

| Column | Type |
|---|---|
| `time_zone_name` | TEXT |
| `standard_name` | TEXT |
| `daylight_name` | TEXT |
| `bias` | INTEGER |
| `active_time_bias` | INTEGER |
| `parsed_at` | TEXT |


### Table: `NetworkInterfacesInfo`

| Column | Type |
|---|---|
| `interface_id` | TEXT |
| `ip_address` | TEXT |
| `subnet_mask` | TEXT |
| `default_gateway` | TEXT |
| `dhcp_enabled` | INTEGER |
| `dhcp_server` | TEXT |
| `dns_servers` | TEXT |
| `mac_address` | TEXT |
| `parsed_at` | TEXT |


### Table: `Auto`

| Column | Type |
|---|---|
| `last_install_time` | TEXT |
| `au_options` | INTEGER |
| `scheduled_install_day` | INTEGER |
| `scheduled_install_time` | INTEGER |
| `parsed_at` | TEXT |


### Table: `WindowsUpdateInfo`

| Column | Type |
|---|---|
| `last_check_time` | TEXT |
| `last_install_time` | TEXT |
| `au_options` | INTEGER |
| `scheduled_install_day` | INTEGER |
| `scheduled_install_time` | INTEGER |
| `parsed_at` | TEXT |


### Table: `ShutdownInfo`

| Column | Type |
|---|---|
| `shutdown_time` | TEXT |
| `shutdown_count` | INTEGER |
| `shutdown_type` | TEXT |
| `clean_shutdown` | INTEGER |
| `parsed_at` | TEXT |


### Table: `USBDevices`

| Column | Type |
|---|---|
| `device_id` | TEXT |
| `description` | TEXT |
| `manufacturer` | TEXT |
| `friendly_name` | TEXT |
| `last_connected` | TEXT |


### Table: `USBProperties`

| Column | Type |
|---|---|
| `device_id` | TEXT |
| `property_name` | TEXT |
| `property_value` | TEXT |
| `property_type` | TEXT |


### Table: `USBInstances`

| Column | Type |
|---|---|
| `device_id` | TEXT |
| `instance_id` | TEXT |
| `parent_id` | TEXT |
| `service` | TEXT |
| `status` | TEXT |


### Table: `USBStorageDevices`

| Column | Type |
|---|---|
| `device_id` | TEXT |
| `friendly_name` | TEXT |
| `serial_number` | TEXT |
| `vendor_id` | TEXT |
| `product_id` | TEXT |
| `revision` | TEXT |
| `first_connected` | TEXT |
| `last_connected` | TEXT |
| `last_removed` | TEXT |
| `parsed_at` | TEXT |


### Table: `USBStorageVolumes`

| Column | Type |
|---|---|
| `device_id` | TEXT |
| `volume_guid` | TEXT |
| `volume_name` | TEXT |
| `drive_letter` | TEXT |
| `parsed_at` | TEXT |


### Table: `BrowserHistory`

URLs typed into the Internet Explorer address bar, from `NTUSER\Software\Microsoft\Internet
Explorer\TypedURLs`. Registry-derived only - this is not a full browser history, and modern Edge
does not write here.

`last_visit` comes from the sibling `TypedURLsTime` key, which pairs each `urlN` with a FILETIME.
That key is Windows 8 and later, so an empty `last_visit` on an older system means the timestamp was
never recorded, not that it was missed.

| Column | Type |
|---|---|
| `browser` | TEXT |
| `url` | TEXT |
| `title` | TEXT |
| `visit_count` | INTEGER |
| `last_visit` | TEXT |
| `parsed_at` | TEXT |
| `user_name` | TEXT |


### Table: `InstalledSoftware`

| Column | Type |
|---|---|
| `display_name` | TEXT |
| `display_version` | TEXT |
| `publisher` | TEXT |
| `install_date` | TEXT |
| `install_location` | TEXT |
| `uninstall_string` | TEXT |
| `parsed_at` | TEXT |


### Table: `SystemServices`

| Column | Type |
|---|---|
| `service_name` | TEXT |
| `display_name` | TEXT |
| `description` | TEXT |
| `image_path` | TEXT |
| `start_type` | INTEGER |
| `service_type` | INTEGER |
| `error_control` | INTEGER |
| `status` | TEXT |
| `parsed_at` | TEXT |


### Persistence / ASEP tables

`winlogon`, `image_file_execution_options`, `appinit_dlls`, `appcert_dlls`, `active_setup`,
`run_services`, `run_services_once`, `policies_explorer_run`, `user_shell_folders`, `lsa_packages`,
`boot_execute`, `clsid_inprocserver32`, `command_processor`, `drivers32`,
`shell_service_object_delay_load`, `browser_helper_objects`, `shared_task_scheduler`,
`shell_icon_overlay_identifiers`, `credential_providers`, `netsh_helper_dlls`, `amsi_providers`,
`security_providers`, `print_monitors`, `print_processors`, `network_providers`,
`wmi_autorecover_mofs`, `windows_load_run`, `shell_open_command`.

Auto-start extensibility points, one table per registry launch point. All share one schema, and
anything naming an executable is also rolled up into `AutoStartPrograms`.

Tables are named for the artifact, never for the technique that abuses it - `shell_open_command`,
not "uac_bypass". `clsid_inprocserver32` was previously called `com_hijack`; case databases written
before the rename still carry the old table name.

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Forensic coverage tables

| Table | Key columns |
|---|---|
| `SecurityPosture` | `setting`, `value_raw`, `value_decoded`, `default_value`, `assessment`, `meaning`, `key_path`, `parsed_at` |
| `DefenderExclusions` | `exclusion_type`, `value`, `source`, `key_path`, `parsed_at` |
| `FirewallRules` | `rule_type`, `rule_name`, `display_name`, `action`, `direction`, `enabled`, `protocol`, `local_port`, `remote_port`, `application`, `service`, `profile`, `key_path`, `parsed_at` |
| `NetworkShares` | `share_name`, `share_path`, `remark`, `raw`, `key_path`, `parsed_at` |
| `ConnectedDevices` | `device_type`, `device_id`, `friendly_name`, `details`, `key_path`, `parsed_at` |
| `MountPoints2` | `user_name`, `mount_id`, `mount_type`, `key_path`, `parsed_at` |
| `RDPClientMRU` | `user_name`, `entry_type`, `server`, `username_hint`, `key_path`, `parsed_at` |
| `OfficeDocuments` | `user_name`, `application`, `version`, `kind`, `document`, `raw`, `key_path`, `parsed_at` |
| `FeatureUsage` | `user_name`, `usage_type`, `program`, `count`, `key_path`, `parsed_at` |
| `CompatibilityAssistant` | `user_name`, `program_path`, `blob_size`, `key_path`, `parsed_at` |
| `RecentApps` | `user_name`, `app_id`, `app_path`, `launch_count`, `last_accessed`, `key_path`, `parsed_at` |
| `ApplicationArtifacts` | `user_name`, `application`, `artifact`, `name`, `value`, `key_path`, `parsed_at` |
| `rdp_tcp` | `setting`, `value`, `default_value`, `meaning`, `key_path`, `parsed_at` |
| `usbstor_start` | `setting`, `value`, `decoded`, `default_value`, `key_path`, `parsed_at` |
| `windows_script_host` | `setting`, `value`, `default_value`, `meaning`, `key_path`, `parsed_at` |
| `dnscache_parameters` | `name`, `value`, `key_path`, `parsed_at` |
| `files_not_to_snapshot` | `entry`, `value`, `key_path`, `parsed_at` |
| `winevt_channels` | `channel`, `source`, `enabled`, `max_size`, `retention`, `log_file`, `reason`, `key_path`, `parsed_at` |
| `wpdbusenum` | `device_id`, `friendly_name`, `volume_guid`, `key_path`, `parsed_at` |
| `device_classes` | `class_guid`, `class_name`, `device_instance`, `key_path`, `parsed_at` |
| `volume_info_cache` | `drive_letter`, `volume_label`, `file_system`, `key_path`, `parsed_at` |
| `machine_guid` | `name`, `value`, `key_path`, `parsed_at` |
| `product_options` | `name`, `value`, `meaning`, `key_path`, `parsed_at` |
| `os_install_history` | `name`, `value`, `key_path`, `parsed_at` |
| `active_computer_name` | `name`, `value`, `key_path`, `parsed_at` |
| `hivelist` | `hive`, `file_path`, `key_path`, `parsed_at` |
| `system_environment` | `name`, `value`, `key_path`, `parsed_at` |
| `network_adapters` | `adapter_guid`, `name`, `value`, `key_path`, `parsed_at` |
| `group_policy_history` | `scope`, `gpo_id`, `name`, `value`, `key_path`, `parsed_at` |
| `file_exts` | `user_name`, `extension`, `choice_type`, `progid`, `key_path`, `parsed_at` |
| `cid_size_mru` | `user_name`, `position`, `application`, `key_path`, `parsed_at` |
| `programs_cache` | `user_name`, `value_name`, `blob_size`, `key_path`, `parsed_at` |
| `regedit_lastkey` | `user_name`, `name`, `value`, `key_path`, `parsed_at` |
| `printer_connections` | `user_name`, `connection`, `server`, `printer`, `key_path`, `parsed_at` |
| `explorer_advanced` | `user_name`, `setting`, `value`, `default_value`, `meaning`, `key_path`, `parsed_at` |
| `local_groups` | `scope`, `rid`, `group_name`, `comment`, `member_sid`, `member_name`, `member_count`, `last_write`, `parsed_at` — PK (scope, rid, member_sid) |
| `lsa_policy` | `name`, `key_path`, `value`, `meaning`, `last_write`, `parsed_at` — PK (name) |
| `audit_policy` | `name`, `key_path`, `decoded`, `raw_hex`, `raw_size`, `last_write`, `note`, `parsed_at` — PK (name) |
| `lsa_secrets` | `secret_name`, `key_path`, `value_kind`, `size_bytes`, `updated`, `last_write`, `parsed_at` — PK (secret_name, value_kind) |
| `cached_domain_logons` | `slot`, `key_path`, `size_bytes`, `occupied`, `last_write`, `parsed_at` — PK (slot) |

`assessment` in `SecurityPosture` is `default` / `hardened` / `weakened` / `informational`; only
`weakened` is a finding. Rows are written even when the registry value is absent.

`winevt_channels` merges two sources: `source` is `EventLog (classic)` for the legacy
Security/System/Application logs under `Services\EventLog`, or `WINEVT` for Vista-era channels.
Only classic logs, a watch list, and channels with a non-default `MaxSize` are recorded - `reason`
says which. Dumping all ~1166 WINEVT channels would bury the finding.

`active_computer_name` and `hivelist` come from **volatile** keys that Windows builds at runtime and
never writes to a hive file. They populate on live acquisitions and are correctly empty for image or
hive-set cases.

`local_groups` holds **one row per group member**, and one row with an empty `member_sid` for a
group with none — so an empty group and an unparsed one are distinguishable.

The four LSA tables come from the SECURITY hive, which the live parser exports with
`SeBackupPrivilege` because its root key denies Administrators. `audit_policy` stores the raw
blob and decodes it only when it validates against the legacy layout — see
`registry_knowledge.md`. `lsa_secrets` records secret names, sizes and update times, never
plaintext. `cached_domain_logons` is empty when the `Cache` key is absent, which is the normal
state for a machine no domain account has logged on to.

### Table: `UserAccounts`

Local accounts, SAM merged with ProfileList. The table that maps a SID to a person.

| Column | Type |
|---|---|
| `user_sid` | TEXT (PK) |
| `rid` | INTEGER |
| `username` | TEXT |
| `display_name` | TEXT |
| `full_name` | TEXT |
| `comment` | TEXT |
| `account_type` | TEXT |
| `well_known` | TEXT |
| `account_enabled` | INTEGER |
| `account_flags` | TEXT |
| `last_logon` | TEXT |
| `password_last_set` | TEXT |
| `account_expires` | TEXT |
| `last_incorrect_password` | TEXT |
| `login_count` | INTEGER |
| `bad_password_count` | INTEGER |
| `profile_path` | TEXT |
| `profile_loaded` | INTEGER |
| `source` | TEXT |
| `parsed_at` | TEXT |

### Table: `ScheduledTasks`

Windows Task Scheduler entries, from `SOFTWARE\Microsoft\Windows NT\CurrentVersion\Schedule\TaskCache`.
Persistence and execution evidence: what runs, as whom, when it last ran and whether it succeeded.

| Column | Type |
|---|---|
| `task_path` | TEXT |
| `task_guid` | TEXT |
| `command` | TEXT |
| `arguments` | TEXT |
| `working_dir` | TEXT |
| `run_context` | TEXT |
| `triggers_index` | TEXT |
| `task_registered` | TEXT |
| `last_run` | TEXT |
| `last_completed` | TEXT |
| `last_result` | INTEGER |
| `parsed_at` | TEXT |

### Table: `AutoStartPrograms`

| Column | Type |
|---|---|
| `location` | TEXT |
| `program_name` | TEXT |
| `command` | TEXT |
| `parsed_at` | TEXT |


### Table: `DAM`

| Column | Type |
|---|---|
| `subkey` | TEXT |
| `name` | TEXT |
| `row_data` | TEXT |
| `type` | TEXT |
| `app_name` | TEXT |
| `process_path` | TEXT |
| `sid` | TEXT |
| `last_execution` | TEXT |
| `execution_count` | INTEGER |
| `parsed_at` | TEXT |


### Table: `BAM`

| Column | Type |
|---|---|
| `subkey` | TEXT |
| `name` | TEXT |
| `row_data` | TEXT |
| `type` | TEXT |
| `app_name` | TEXT |
| `process_path` | TEXT |
| `sid` | TEXT |
| `last_execution` | TEXT |
| `execution_flags` | INTEGER |
| `parsed_at` | TEXT |


### Table: `WordWheelQuery`

| Column | Type |
|---|---|
| `search_term` | TEXT |
| `search_type` | TEXT |
| `mru_position` | INTEGER |
| `access_date` | TEXT |
| `parsed_at` | TEXT |
| `user_name` | TEXT |


### Table: `UserAssist`

| Column | Type |
|---|---|
| `program_path` | TEXT |
| `run_count` | INTEGER |
| `last_execution` | TEXT |
| `focus_count` | INTEGER |
| `focus_time` | INTEGER |
| `user_sid` | TEXT |
| `parsed_at` | TEXT |


### Table: `Shellbags`

| Column | Type |
|---|---|
| `file_name` | TEXT |
| `short_name` | TEXT |
| `shell_item_type` | TEXT |
| `mru_position` | TEXT |
| `created_date` | TEXT |
| `modified_date` | TEXT |
| `accessed_date` | TEXT |
| `attributes` | TEXT |
| `file_size` | INTEGER |
| `special_folder` | TEXT |
| `network_share` | TEXT |
| `server_name` | TEXT |
| `share_name` | TEXT |
| `drive_letter` | TEXT |
| `mft_record_number` | INTEGER |
| `registry_path` | TEXT |
| `parent_path` | TEXT |
| `parsed_at` | TEXT |
| `user_name` | TEXT |


### Table: `RunMRU`

| Column | Type |
|---|---|
| `command` | TEXT |
| `mru_position` | INTEGER |
| `access_date` | TEXT |
| `parsed_at` | TEXT |
| `user_name` | TEXT |


### Table: `MUICache`

Application display names Windows caches when a program is shown in the shell - an execution
signal, from `MuiCache` and the older `ShellNoRoam\MUICache`.

Windows stores one registry value per PROPERTY of an executable, named `<path>.FriendlyAppName`,
`<path>.ApplicationCompany` and so on. Those are pivoted into **one row per executable**:
`app_path` is the real path with the property suffix removed, `app_name` is the friendly name and
`company` the publisher. Because `app_path` is the true path, it joins against Prefetch, Amcache,
ShimCache and BAM, which all record the same path.

| Column | Type |
|---|---|
| `app_path` | TEXT |
| `app_name` | TEXT |
| `company` | TEXT |
| `file_extension` | TEXT |
| `parsed_at` | TEXT |
| `user_name` | TEXT |


### Table: `Network_list`

| Column | Type |
|---|---|
| `subkey` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `network_name` | TEXT |
| `connection_date` | TEXT |
| `gateway_mac` | TEXT |
| `is_hidden` | INTEGER |


### Table: `OpenSaveMRU`

| Column | Type |
|---|---|
| `subkey` | TEXT |
| `name` | TEXT |
| `type` | TEXT |
| `file_path` | TEXT |
| `file_name` | TEXT |
| `extension` | TEXT |
| `drive_letter` | TEXT |
| `access_date` | TEXT |
| `key_last_write` | TEXT |
| `row_data` | TEXT |
| `parsed_at` | TEXT |
| `user_name` | TEXT |

`access_date` is empty by design. An MRU list carries no per-entry timestamp,
so the only time this artifact holds is the key's own last-write, in
`key_last_write` - a fact about the key, not about whichever entry sits at MRU
position 0. `mru_position` gives the recency order.

### Table: `LastSaveMRU`

| Column | Type |
|---|---|
| `mru_number` | TEXT |
| `type` | TEXT |
| `application` | TEXT |
| `folder_path` | TEXT |
| `folder_name` | TEXT |
| `drive_letter` | TEXT |
| `access_date` | TEXT |
| `key_last_write` | TEXT |
| `row_data` | TEXT |
| `parsed_at` | TEXT |
| `user_name` | TEXT |

`access_date` is empty for the same reason as `OpenSaveMRU` above; the key's
own last-write is in `key_last_write`.

### Table: `UserProfiles`

| Column | Type |
|---|---|
| `user_sid` | TEXT |
| `username` | TEXT |
| `profile_path` | TEXT |
| `profile_image_path` | TEXT |
| `profile_loaded` | INTEGER |
| `parsed_at` | TEXT |


### Table: `RecentDocs`

Documents opened through Explorer, from `NTUSER\...\Explorer\RecentDocs`. The main key holds every
recent item (`subkey` = `main`); one subkey per file extension holds the same items grouped by type,
and `Folder` holds folders.

`mru_position` is decoded from that key's `MRUListEx`: **0 is the most recently opened**, and the
value `name` is only the entry's slot number, not its order. `key_last_write` is the containing key's
own last-write time - for `.pdf` it is when a PDF was most recently opened, so the per-extension rows
give a last-use time per file type. The registry stores no per-entry timestamp, so `key_last_write`
tells you about the newest entry in that key, not about the row it sits on.

| Column | Type |
|---|---|
| `subkey` | TEXT |
| `name` | TEXT |
| `row_data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `mru_position` | INTEGER |
| `key_last_write` | TEXT |
| `parsed_at` | TEXT |


### Table: `TypedPaths`

Paths typed into the Explorer address bar, from `NTUSER\...\Explorer\TypedPaths`. Strong evidence
of intent: the user typed this rather than clicking to it, and entries survive after the location is
gone.

Values are named `url1`, `url2`, ... where **`url1` is the most recent**; `mru_position` normalises
that to 0-based to match every other MRU table. There is no `MRUListEx` here. `key_last_write` is
when the most recent path was typed - it applies to the key, so only the `mru_position = 0` row can
be tied to it.

| Column | Type |
|---|---|
| `name` | TEXT |
| `row_data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `mru_position` | INTEGER |
| `key_last_write` | TEXT |
| `parsed_at` | TEXT |


### Table: `ApplicationArtifacts`

| Column | Type |
|---|---|
| `user_name` | TEXT |
| `application` | TEXT |
| `artifact` | TEXT |
| `name` | TEXT |
| `value` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `CompatibilityAssistant`

| Column | Type |
|---|---|
| `user_name` | TEXT |
| `program_path` | TEXT |
| `blob_size` | INTEGER |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `ConnectedDevices`

| Column | Type |
|---|---|
| `device_type` | TEXT |
| `device_id` | TEXT |
| `friendly_name` | TEXT |
| `details` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `DefenderExclusions`

| Column | Type |
|---|---|
| `exclusion_type` | TEXT |
| `value` | TEXT |
| `source` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `FeatureUsage`

| Column | Type |
|---|---|
| `user_name` | TEXT |
| `usage_type` | TEXT |
| `program` | TEXT |
| `count` | INTEGER |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `FirewallRules`

| Column | Type |
|---|---|
| `rule_type` | TEXT |
| `rule_name` | TEXT |
| `display_name` | TEXT |
| `action` | TEXT |
| `direction` | TEXT |
| `enabled` | TEXT |
| `protocol` | TEXT |
| `local_port` | TEXT |
| `remote_port` | TEXT |
| `application` | TEXT |
| `service` | TEXT |
| `profile` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `MountPoints2`

| Column | Type |
|---|---|
| `user_name` | TEXT |
| `mount_id` | TEXT |
| `mount_type` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `NetworkShares`

| Column | Type |
|---|---|
| `share_name` | TEXT |
| `share_path` | TEXT |
| `remark` | TEXT |
| `raw` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `OfficeDocuments`

| Column | Type |
|---|---|
| `user_name` | TEXT |
| `application` | TEXT |
| `version` | TEXT |
| `kind` | TEXT |
| `document` | TEXT |
| `raw` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `RDPClientMRU`

| Column | Type |
|---|---|
| `user_name` | TEXT |
| `entry_type` | TEXT |
| `server` | TEXT |
| `username_hint` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `RecentApps`

| Column | Type |
|---|---|
| `user_name` | TEXT |
| `app_id` | TEXT |
| `app_path` | TEXT |
| `launch_count` | INTEGER |
| `last_accessed` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `SecurityPosture`

| Column | Type |
|---|---|
| `setting` | TEXT |
| `value_raw` | TEXT |
| `value_decoded` | TEXT |
| `default_value` | TEXT |
| `assessment` | TEXT |
| `meaning` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `active_computer_name`

| Column | Type |
|---|---|
| `name` | TEXT |
| `value` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `active_setup`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `amsi_providers`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `appcert_dlls`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `appinit_dlls`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `audit_policy`

| Column | Type |
|---|---|
| `name` | TEXT |
| `key_path` | TEXT |
| `decoded` | TEXT |
| `raw_hex` | TEXT |
| `raw_size` | INTEGER |
| `last_write` | TEXT |
| `note` | TEXT |
| `parsed_at` | TEXT |

### Table: `boot_execute`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `browser_helper_objects`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `cached_domain_logons`

| Column | Type |
|---|---|
| `slot` | TEXT |
| `key_path` | TEXT |
| `size_bytes` | INTEGER |
| `occupied` | INTEGER |
| `last_write` | TEXT |
| `parsed_at` | TEXT |

### Table: `cid_size_mru`

| Column | Type |
|---|---|
| `user_name` | TEXT |
| `position` | INTEGER |
| `application` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `clsid_inprocserver32`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `command_processor`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `credential_providers`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `device_classes`

| Column | Type |
|---|---|
| `class_guid` | TEXT |
| `class_name` | TEXT |
| `device_instance` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `dnscache_parameters`

| Column | Type |
|---|---|
| `name` | TEXT |
| `value` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `drivers32`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `explorer_advanced`

| Column | Type |
|---|---|
| `user_name` | TEXT |
| `setting` | TEXT |
| `value` | TEXT |
| `default_value` | TEXT |
| `meaning` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `file_exts`

| Column | Type |
|---|---|
| `user_name` | TEXT |
| `extension` | TEXT |
| `choice_type` | TEXT |
| `progid` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `files_not_to_snapshot`

| Column | Type |
|---|---|
| `entry` | TEXT |
| `value` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `group_policy_history`

| Column | Type |
|---|---|
| `scope` | TEXT |
| `gpo_id` | TEXT |
| `name` | TEXT |
| `value` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `hivelist`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `file_path` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `image_file_execution_options`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `local_groups`

| Column | Type |
|---|---|
| `scope` | TEXT |
| `rid` | INTEGER |
| `group_name` | TEXT |
| `comment` | TEXT |
| `member_sid` | TEXT |
| `member_name` | TEXT |
| `member_count` | INTEGER |
| `last_write` | TEXT |
| `parsed_at` | TEXT |

### Table: `lsa_packages`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `lsa_policy`

| Column | Type |
|---|---|
| `name` | TEXT |
| `key_path` | TEXT |
| `value` | TEXT |
| `meaning` | TEXT |
| `last_write` | TEXT |
| `parsed_at` | TEXT |

### Table: `lsa_secrets`

| Column | Type |
|---|---|
| `secret_name` | TEXT |
| `key_path` | TEXT |
| `value_kind` | TEXT |
| `size_bytes` | INTEGER |
| `updated` | TEXT |
| `last_write` | TEXT |
| `parsed_at` | TEXT |

### Table: `machine_guid`

| Column | Type |
|---|---|
| `name` | TEXT |
| `value` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `netsh_helper_dlls`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `network_adapters`

| Column | Type |
|---|---|
| `adapter_guid` | TEXT |
| `name` | TEXT |
| `value` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `network_providers`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `os_install_history`

| Column | Type |
|---|---|
| `name` | TEXT |
| `value` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `policies_explorer_run`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `print_monitors`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `print_processors`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `printer_connections`

| Column | Type |
|---|---|
| `user_name` | TEXT |
| `connection` | TEXT |
| `server` | TEXT |
| `printer` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `product_options`

| Column | Type |
|---|---|
| `name` | TEXT |
| `value` | TEXT |
| `meaning` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `programs_cache`

| Column | Type |
|---|---|
| `user_name` | TEXT |
| `value_name` | TEXT |
| `blob_size` | INTEGER |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `rdp_tcp`

| Column | Type |
|---|---|
| `setting` | TEXT |
| `value` | TEXT |
| `default_value` | TEXT |
| `meaning` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `regedit_lastkey`

| Column | Type |
|---|---|
| `user_name` | TEXT |
| `name` | TEXT |
| `value` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `run_services`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `run_services_once`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `security_providers`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `shared_task_scheduler`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `shell_icon_overlay_identifiers`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `shell_open_command`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `shell_service_object_delay_load`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `system_environment`

| Column | Type |
|---|---|
| `name` | TEXT |
| `value` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `usbstor_start`

| Column | Type |
|---|---|
| `setting` | TEXT |
| `value` | TEXT |
| `decoded` | TEXT |
| `default_value` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `user_shell_folders`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `volume_info_cache`

| Column | Type |
|---|---|
| `drive_letter` | TEXT |
| `volume_label` | TEXT |
| `file_system` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `windows_load_run`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `windows_script_host`

| Column | Type |
|---|---|
| `setting` | TEXT |
| `value` | TEXT |
| `default_value` | TEXT |
| `meaning` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `winevt_channels`

| Column | Type |
|---|---|
| `channel` | TEXT |
| `source` | TEXT |
| `enabled` | TEXT |
| `max_size` | TEXT |
| `retention` | TEXT |
| `log_file` | TEXT |
| `reason` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |

### Table: `winlogon`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `wmi_autorecover_mofs`

| Column | Type |
|---|---|
| `hive` | TEXT |
| `key_path` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |
| `user_name` | TEXT |
| `parsed_at` | TEXT |

### Table: `wpdbusenum`

| Column | Type |
|---|---|
| `device_id` | TEXT |
| `friendly_name` | TEXT |
| `volume_guid` | TEXT |
| `key_path` | TEXT |
| `parsed_at` | TEXT |


## Database: `shimcache.db`

### Table: `shimcache_entries`

Windows Application Compatibility Cache - evidence that a program was present, and on many builds
that it ran. Read from `SYSTEM\CurrentControlSet\Control\Session Manager\AppCompatCache`.

**Not every entry names a file.** Store and UWP applications are recorded as seven tab-separated
fields instead of a path, so each row carries `entry_type`:

- `file` - `path` and `filename` are a real filesystem path, as before.
- `packaged app` - `path` is empty and the identity is `package_family_name`
  (`Claude_pzs8sxrjxfjjc`), with `package_version` and `architecture` decoded alongside. The
  original record is kept verbatim in `raw_entry`.

`package_family_name` is the column to join on for packaged applications - it is the same identifier
Amcache and `Get-AppxPackage` use. On a live machine all 65 distinct family names matched an
installed package exactly.

`last_modified` is the file's modification time as the cache recorded it, not an execution time.

| Column | Type |
|---|---|
| `id` | INTEGER |
| `filename` | TEXT |
| `path` | TEXT |
| `entry_type` | TEXT |
| `package_family_name` | TEXT |
| `package_version` | TEXT |
| `architecture` | TEXT |
| `raw_entry` | TEXT |
| `last_modified` | TEXT |
| `last_modified_readable` | TEXT |
| `data_size` | INTEGER |
| `entry_size` | INTEGER |
| `cache_entry_position` | INTEGER |
| `entry_hash` | TEXT |
| `parsed_at` | TIMESTAMP |


### Table: `sqlite_sequence`

| Column | Type |
|---|---|
| `name` | UNKNOWN |
| `seq` | UNKNOWN |


## Database: `srum_data.db`

### Table: `srum_application_usage`

`user_sid` is a plain SID (`S-1-5-21-...`), decoded from the binary structure rather than through
`win32security` - whose `str()` returns a Python repr (`PySID:S-1-5-...`) that matches nothing else
in a case.

SRUM records an application identity two ways, and which one a table uses decides how a shared host
process is told apart.

The resource and network tables use a device path, and Windows appends the hosted service to it -
`\Device\HarddiskVolume3\Windows\System32\svchost.exe [DcomLaunch]`. 35546 of 221230 application
usage rows carry a service that way, so svchost rows are distinguished by `app_path`; `app_name` is
only the basename and reads `svchost.exe` for all of them.

The `!!name!time!hex![services]` form is used exclusively by `srum_app_timeline`, which is why
`hosted_services` exists only on that table. Adding the column to the four tables above produced a
column empty on every row, because none of them reference an AppId of that form.

| Column | Type |
|---|---|
| `id` | INTEGER |
| `timestamp` | TEXT |
| `app_name` | TEXT |
| `app_path` | TEXT |
| `user_sid` | TEXT |
| `user_name` | TEXT |
| `foreground_cycle_time` | INTEGER |
| `background_cycle_time` | INTEGER |
| `face_time` | INTEGER |
| `foreground_context_switches` | INTEGER |
| `background_context_switches` | INTEGER |
| `foreground_bytes_read` | INTEGER |
| `foreground_bytes_written` | INTEGER |
| `foreground_num_read_operations` | INTEGER |
| `foreground_num_write_operations` | INTEGER |
| `foreground_number_of_flushes` | INTEGER |
| `background_bytes_read` | INTEGER |
| `background_bytes_written` | INTEGER |
| `background_num_read_operations` | INTEGER |
| `background_num_write_operations` | INTEGER |
| `background_number_of_flushes` | INTEGER |


### Table: `sqlite_sequence`

| Column | Type |
|---|---|
| `name` | UNKNOWN |
| `seq` | UNKNOWN |


### Table: `srum_network_connectivity`

| Column | Type |
|---|---|
| `id` | INTEGER |
| `timestamp` | TEXT |
| `app_name` | TEXT |
| `app_path` | TEXT |
| `user_sid` | TEXT |
| `user_name` | TEXT |
| `interface_luid` | INTEGER |
| `l2_profile_id` | INTEGER |
| `l2_profile_flags` | INTEGER |
| `connected_time` | INTEGER |
| `connect_start_time` | TEXT |


### Table: `srum_network_data_usage`

| Column | Type |
|---|---|
| `id` | INTEGER |
| `timestamp` | TEXT |
| `app_name` | TEXT |
| `app_path` | TEXT |
| `user_sid` | TEXT |
| `user_name` | TEXT |
| `interface_luid` | INTEGER |
| `l2_profile_id` | INTEGER |
| `bytes_sent` | INTEGER |
| `bytes_received` | INTEGER |


### Table: `srum_energy_usage`

| Column | Type |
|---|---|
| `id` | INTEGER |
| `timestamp` | TEXT |
| `app_name` | TEXT |
| `app_path` | TEXT |
| `user_sid` | TEXT |
| `user_name` | TEXT |
| `event_timestamp` | TEXT |
| `state_transition` | INTEGER |
| `charge_level` | INTEGER |
| `cycle_count` | INTEGER |


### Table: `srum_app_timeline`

Application timeline provider. Records how an application was used, not only
that it ran: seconds in focus, seconds of keyboard and mouse input. This is the
only SRUM table whose AppId uses the `!!name!time!hash![services]` form, so it
is the only one that carries `hosted_services` - the service list that tells one
svchost.exe record from another.

The interaction columns are sparse by nature. A service accrues CPU cycles for
hours and never sees a keystroke, so a NULL there means no such activity in that
window, not a failed decode.

| Column | Type |
|---|---|
| `id` | INTEGER |
| `timestamp` | TEXT |
| `app_name` | TEXT |
| `app_path` | TEXT |
| `hosted_services` | TEXT |
| `user_sid` | TEXT |
| `user_name` | TEXT |
| `end_time` | TEXT |
| `duration_ms` | INTEGER |
| `span_ms` | INTEGER |
| `timeline_end` | INTEGER |
| `flags` | INTEGER |
| `in_focus_s` | INTEGER |
| `psm_foreground_s` | INTEGER |
| `user_input_s` | INTEGER |
| `keyboard_input_s` | INTEGER |
| `mouse_input_s` | INTEGER |
| `display_required_s` | INTEGER |
| `comp_rendered_s` | INTEGER |
| `comp_dirtied_s` | INTEGER |
| `comp_propagated_s` | INTEGER |
| `audio_in_s` | INTEGER |
| `audio_out_s` | INTEGER |
| `cycles` | INTEGER |
| `cycles_attr` | INTEGER |
| `cycles_wob` | INTEGER |
| `disk_raw` | INTEGER |
| `network_bytes_raw` | INTEGER |
| `network_tail_raw` | INTEGER |


### Table: `srum_metadata`

| Column | Type |
|---|---|
| `id` | INTEGER |
| `parsed_at` | TEXT |
| `srudb_path` | TEXT |
| `total_records_parsed` | INTEGER |
| `parsing_duration_seconds` | REAL |
| `windows_version` | TEXT |
| `notes` | TEXT |


## Database: `USN_journal.db`

### Table: `journal_events`

| Column | Type |
|---|---|
| `volume_letter` | TEXT |
| `filename` | TEXT |
| `usn` | INTEGER |
| `major_version` | INTEGER |
| `frn` | TEXT |
| `parent_frn` | TEXT |
| `timestamp` | TEXT |
| `reason` | TEXT |
| `source_info` | TEXT |
| `security_id` | INTEGER |
| `file_attributes` | TEXT |
| `record_length` | INTEGER |
| `parsed_at` | TEXT |


### Table: `deleted_entries`

| Column | Type |
|---|---|
| `volume_letter` | TEXT |
| `gap_start_usn` | INTEGER |
| `gap_end_usn` | INTEGER |
| `gap_size` | INTEGER |
| `detection_timestamp` | TEXT |
| `last_known_usn` | INTEGER |
| `next_valid_usn` | INTEGER |
| `forensic_significance` | TEXT |
| `potential_activity` | TEXT |
| `parsed_at` | TEXT |


## Database: `correlation_results.db`

### Table: `executions`

| Column | Type |
|---|---|
| `execution_id` | INTEGER |
| `run_name` | TEXT |
| `pipeline_name` | TEXT |
| `execution_time` | TIMESTAMP |
| `execution_duration_seconds` | REAL |
| `total_wings` | INTEGER |
| `total_matches` | INTEGER |
| `total_records_scanned` | INTEGER |
| `output_directory` | TEXT |
| `case_name` | TEXT |
| `investigator` | TEXT |
| `errors` | TEXT |
| `warnings` | TEXT |
| `engine_type` | TEXT |
| `wing_config_json` | TEXT |
| `pipeline_config_json` | TEXT |
| `time_period_start` | TEXT |
| `time_period_end` | TEXT |
| `identity_filters_json` | TEXT |
| `run_number` | INTEGER |


### Table: `sqlite_sequence`

| Column | Type |
|---|---|
| `name` | UNKNOWN |
| `seq` | UNKNOWN |


### Table: `results`

| Column | Type |
|---|---|
| `result_id` | INTEGER |
| `execution_id` | INTEGER |
| `wing_id` | TEXT |
| `wing_name` | TEXT |
| `total_matches` | INTEGER |
| `feathers_processed` | INTEGER |
| `total_records_scanned` | INTEGER |
| `duplicates_prevented` | INTEGER |
| `matches_failed_validation` | INTEGER |
| `execution_duration_seconds` | REAL |
| `anchor_feather_id` | TEXT |
| `anchor_selection_reason` | TEXT |
| `filters_applied` | TEXT |
| `feather_metadata` | TEXT |
| `status` | TEXT |
| `progress_info` | TEXT |


### Table: `matches`

| Column | Type |
|---|---|
| `match_id` | TEXT |
| `result_id` | INTEGER |
| `timestamp` | TEXT |
| `match_score` | REAL |
| `confidence_score` | REAL |
| `confidence_category` | TEXT |
| `feather_count` | INTEGER |
| `time_spread_seconds` | REAL |
| `anchor_feather_id` | TEXT |
| `anchor_artifact_type` | TEXT |
| `matched_application` | TEXT |
| `matched_file_path` | TEXT |
| `matched_event_id` | TEXT |
| `is_duplicate` | BOOLEAN |
| `weighted_score_value` | REAL |
| `weighted_score_interpretation` | TEXT |
| `feather_records` | TEXT |
| `score_breakdown` | TEXT |
| `anchor_start_time` | TEXT |
| `anchor_end_time` | TEXT |
| `anchor_record_count` | INTEGER |
| `semantic_data` | TEXT |
| `compressed` | BOOLEAN |


### Table: `feather_metadata`

| Column | Type |
|---|---|
| `metadata_id` | INTEGER |
| `result_id` | INTEGER |
| `feather_id` | TEXT |
| `artifact_type` | TEXT |
| `database_path` | TEXT |
| `total_records` | INTEGER |
| `identities_extracted` | INTEGER |
| `identities_found` | INTEGER |

