# Global Database Schema Reference

This document contains the comprehensive schema for all parsed artifacts and correlation databases. Use this reference to write precise SQL queries without needing to call `get_schema` first.


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
| `timestamp` | TEXT |


### Table: `TimeZoneInfo`

| Column | Type |
|---|---|
| `time_zone_name` | TEXT |
| `standard_name` | TEXT |
| `daylight_name` | TEXT |
| `bias` | INTEGER |
| `active_time_bias` | INTEGER |
| `timestamp` | TEXT |


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
| `timestamp` | TEXT |


### Table: `Auto`

| Column | Type |
|---|---|
| `last_install_time` | TEXT |
| `au_options` | INTEGER |
| `scheduled_install_day` | INTEGER |
| `scheduled_install_time` | INTEGER |
| `timestamp` | TEXT |


### Table: `WindowsUpdateInfo`

| Column | Type |
|---|---|
| `last_check_time` | TEXT |
| `last_install_time` | TEXT |
| `au_options` | INTEGER |
| `scheduled_install_day` | INTEGER |
| `scheduled_install_time` | INTEGER |
| `timestamp` | TEXT |


### Table: `ShutdownInfo`

| Column | Type |
|---|---|
| `shutdown_time` | TEXT |
| `shutdown_count` | INTEGER |
| `shutdown_type` | TEXT |
| `clean_shutdown` | INTEGER |
| `timestamp` | TEXT |


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
| `timestamp` | TEXT |


### Table: `USBStorageVolumes`

| Column | Type |
|---|---|
| `device_id` | TEXT |
| `volume_guid` | TEXT |
| `volume_name` | TEXT |
| `drive_letter` | TEXT |
| `timestamp` | TEXT |


### Table: `BrowserHistory`

| Column | Type |
|---|---|
| `browser` | TEXT |
| `url` | TEXT |
| `title` | TEXT |
| `visit_count` | INTEGER |
| `last_visit` | TEXT |
| `timestamp` | TEXT |


### Table: `InstalledSoftware`

| Column | Type |
|---|---|
| `display_name` | TEXT |
| `display_version` | TEXT |
| `publisher` | TEXT |
| `install_date` | TEXT |
| `install_location` | TEXT |
| `uninstall_string` | TEXT |
| `timestamp` | TEXT |


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
| `timestamp` | TEXT |


### Table: `AutoStartPrograms`

| Column | Type |
|---|---|
| `location` | TEXT |
| `program_name` | TEXT |
| `command` | TEXT |
| `timestamp` | TEXT |


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
| `timestamp` | TEXT |


### Table: `UserAssist`

| Column | Type |
|---|---|
| `program_path` | TEXT |
| `run_count` | INTEGER |
| `last_execution` | TEXT |
| `focus_count` | INTEGER |
| `focus_time` | INTEGER |
| `user_sid` | TEXT |
| `timestamp` | TEXT |


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


### Table: `RunMRU`

| Column | Type |
|---|---|
| `command` | TEXT |
| `mru_position` | INTEGER |
| `access_date` | TEXT |
| `timestamp` | TEXT |


### Table: `MUICache`

| Column | Type |
|---|---|
| `app_path` | TEXT |
| `app_name` | TEXT |
| `file_extension` | TEXT |
| `parsed_at` | TEXT |


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
| `row_data` | TEXT |
| `parsed_at` | TEXT |


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
| `row_data` | TEXT |
| `parsed_at` | TEXT |


### Table: `UserProfiles`

| Column | Type |
|---|---|
| `user_sid` | TEXT |
| `username` | TEXT |
| `profile_path` | TEXT |
| `profile_image_path` | TEXT |
| `profile_loaded` | INTEGER |
| `timestamp` | TEXT |


### Table: `RecentDocs`

| Column | Type |
|---|---|
| `subkey` | TEXT |
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |


### Table: `TypedPaths`

| Column | Type |
|---|---|
| `name` | TEXT |
| `data` | TEXT |
| `type` | TEXT |


## Database: `shimcache.db`

### Table: `shimcache_entries`

| Column | Type |
|---|---|
| `id` | INTEGER |
| `filename` | TEXT |
| `path` | TEXT |
| `last_modified` | TEXT |
| `last_modified_readable` | TEXT |
| `data_size` | INTEGER |
| `entry_size` | INTEGER |
| `cache_entry_position` | INTEGER |
| `entry_hash` | TEXT |
| `parsed_timestamp` | TIMESTAMP |


### Table: `sqlite_sequence`

| Column | Type |
|---|---|
| `name` | UNKNOWN |
| `seq` | UNKNOWN |


## Database: `srum_data.db`

### Table: `srum_application_usage`

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


### Table: `srum_metadata`

| Column | Type |
|---|---|
| `id` | INTEGER |
| `parse_timestamp` | TEXT |
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
| `inserted_at` | TEXT |


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
| `inserted_at` | TEXT |


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

