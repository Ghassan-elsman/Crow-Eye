
def A_CJL_LNK_Claw(case_root=None):
    
    from JLParser import Claw
    import sqlite3
    import os
    from datetime import datetime

    # Set folder path based on case_root
    if case_root:
        folder_path = os.path.join(case_root, "Target_Artifacts", "C_AJL_Lnk")
        db_path = os.path.join(case_root, "Target_Artifacts", "LnkDB.db")
        # Create the directory if it doesn't exist
        os.makedirs(folder_path, exist_ok=True)
    else:
        folder_path = "Artifacts Collectors/Target Artifacts/C,AJL and LNK/Recent"
        db_path = "LnkDB.db"
    
    print(f"[Offline LNK] Using folder path: {folder_path}")
    print(f"[Offline LNK] Using database path: {db_path}")
    
    # Check if folder exists and has files
    if not os.path.exists(folder_path):
        print(f"[Offline LNK Warning] Folder does not exist: {folder_path}")
        print(f"[Offline LNK] Please place LNK files and Jump Lists in the case directory")
        return
    
    if not os.listdir(folder_path):
        print(f"[Offline LNK Warning] No files found in: {folder_path}")
        print(f"[Offline LNK] Please place LNK files and Jump Lists in this directory")
        return

    def create_DB():
        with sqlite3.connect(db_path) as conn:
            C = conn.cursor()
            C.execute("""
            CREATE TABLE IF NOT EXISTS JLCE (
                Source_Name TEXT,
                Source_Path TEXT,
                Owner_UID INTEGER,
                Owner_GID INTEGER,
                Time_Access TEXT,
                Time_Creation TEXT,
                Time_Modification TEXT,
                AppType TEXT,
                AppID TEXT,
                Artifact TEXT,
                Data_Flags TEXT,
                Local_Path TEXT,  
                Common_Path TEXT,
                Location_Flags TEXT,
                LNK_Class_ID TEXT,
                File_Attributes TEXT,
                FileSize TEXT,
                Header_Size INTEGER,
                IconIndex INTEGER,
                ShowWindow TEXT,
                Drive_Type TEXT,
                Drive_SN TEXT,
                Volume_Label TEXT,
                entry_number TEXT,
                Network_Device_Name TEXT,
                Network_Providers TEXT,
                Network_Share_Flags TEXT,
                Network_Share_Name TEXT,
                Network_Share_Name_uni TEXT,
                File_Permissions TEXT,
                Num_Hard_Links INTEGER,
                Device_ID INTEGER,
                Inode_Number INTEGER
            );
            """)
            conn.commit()

    create_DB()


    def create_custom_jumplist_DB():
        with sqlite3.connect(db_path) as conn:
            C = conn.cursor()
            C.execute("""
            CREATE TABLE IF NOT EXISTS Custom_JLCE (
                Source_Name TEXT,
                Source_Path TEXT,
                Owner_UID INTEGER,
                Owner_GID INTEGER,
                Time_Access TEXT,
                Time_Creation TEXT,
                Time_Modification TEXT,
                FileSize TEXT,
                File_Permissions TEXT,
                Num_Hard_Links INTEGER,
                Device_ID INTEGER,
                Inode_Number INTEGER,
                Artifact TEXT
            );
            """)
            conn.commit()

    create_custom_jumplist_DB()


    custom_jump_lists = []
    automatic_jump_lists = []
    lnk_files = []
    unparsed_files = []

    def detect_artifact(file_path):
        file_name = os.path.basename(file_path)
        if file_name.endswith(".lnk"):
            return "lnk"
        elif "customDestinations-ms" in file_name:
            return "Custom JumpList"
        elif "automaticDestinations-ms" in file_name:
            return "Automatic JumpList"
        else:
            return "Unknown"

    # Walk through the directory and collect files by type
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            artifact_type = detect_artifact(file_path)
            if artifact_type == "lnk":
                lnk_files.append(file_path)
            elif artifact_type == "Custom JumpList":
                custom_jump_lists.append(file_path)
            elif artifact_type == "Automatic JumpList":
                automatic_jump_lists.append(file_path)


    from datetime import datetime

    def format_time(timestamp):
        try:
            return datetime.fromtimestamp(int(timestamp)).strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            # If timestamp is already in 'YYYY-MM-DDTHH:MM:SS' format
            return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')



    def format_size(size):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
    print("Automatic Jump Lists:", automatic_jump_lists)
    def JL_Custom(file_path):
        try:
            stat_info = os.stat(file_path)
            
            # Collecting relevant statistics
            file_data = {
                'access_time':  format_time(stat_info.st_atime),
                'creation_time': format_time(stat_info.st_ctime),
                'modification_time': format_time(stat_info.st_mtime),
                'file_size': format_size(stat_info.st_size),
                'file_permissions': oct(stat_info.st_mode),
                'owner_uid': stat_info.st_uid,
                'owner_gid': stat_info.st_gid,
                'num_hard_links': stat_info.st_nlink,
                'device_id': stat_info.st_dev,
                'inode_number': stat_info.st_ino,
                'file_name': os.path.basename(file_path),
                'artifact': detect_artifact(file_path)
            }

            # Manually parse the LNK file
            with open(file_path, 'rb') as f:
                content = f.read()
                header = content[:76]
                lnk_clsid = header[4:20]
                lnk_clsid_str = '-'.join([lnk_clsid[i:i+4].hex() for i in range(0, len(lnk_clsid), 4)])
                file_data['source_name'] = os.path.basename(file_path)
                file_data['source_path'] = file_path
            for key, value in file_data.items():
                print(f"{key}: {value}")
            with sqlite3.connect(db_path) as conn:
                C = conn.cursor()
                C.execute("""
                INSERT INTO Custom_JLCE (
                    Source_Name, Source_Path, Owner_UID, Owner_GID,
                    Time_Access, Time_Creation, Time_Modification,
                    FileSize, File_Permissions, Num_Hard_Links, Device_ID,
                    Inode_Number, Artifact)
                VALUES (
                    :source_name, :source_path, :owner_uid, :owner_gid,
                    :access_time, :creation_time, :modification_time,
                    :file_size, :file_permissions, :num_hard_links, :device_id,
                    :inode_number, :artifact)
                """, file_data)
                conn.commit()
            return file_data
        except FileNotFoundError:
            print(f'The file {file_path} does not exist.')
            return None
        except Exception as e:
            print(f'An error occurred: {e}')
            return None

    # Process each file with Claw(file).CE_dec()
    with sqlite3.connect(db_path) as conn:
        C = conn.cursor()
        for file in lnk_files + automatic_jump_lists:  # Combine both lists
            try:
                stat_info = os.stat(file)
                Owner_uid = stat_info.st_uid
                owner_gid = stat_info.st_gid
                try:
                    u_l_file = Claw(file).CE_dec()
                    for item in u_l_file:
                        file_permissions = oct(stat_info.st_mode)
                        Source_Name = os.path.basename(file)
                        Source_Path = file
                        Time_Access = item["Time_Access"]
                        Time_Creation = item["Time_Creation"]
                        Time_Modification = item["Time_Modification"]
                        AppType = item["AppType"]
                        AppID = item["AppID"]
                        Artifact = detect_artifact(file)

                        # Insert data into the database
                        C.execute("""
                        INSERT INTO JLCE (
                            Source_Name, Source_Path, Owner_UID, Owner_GID, 
                            Time_Access, Time_Creation, Time_Modification, 
                            AppType, AppID, Artifact, Data_Flags, Local_Path, 
                            Common_Path, Location_Flags, LNK_Class_ID, File_Attributes, 
                            FileSize, Header_Size, IconIndex, ShowWindow, 
                            Drive_Type, Drive_SN, Volume_Label, entry_number, 
                            Network_Device_Name, Network_Providers, Network_Share_Flags, 
                            Network_Share_Name, Network_Share_Name_uni, File_Permissions, 
                            Num_Hard_Links, Device_ID, Inode_Number)
                        VALUES (
                            :Source_Name, :Source_Path, :Owner_UID, :Owner_GID, 
                            :Time_Access, :Time_Creation, :Time_Modification, 
                            :AppType, :AppID, :Artifact, :Data_Flags, :Local_Path, 
                            :Common_Path, :Location_Flags, :LNK_Class_ID, :File_Attributes, 
                            :FileSize, :Header_Size, :IconIndex, :ShowWindow, 
                            :Drive_Type, :Drive_SN, :Volume_Label, :entry_number, 
                            :Network_Device_Name, :Network_Providers, :Network_Share_Flags, 
                            :Network_Share_Name, :Network_Share_Name_uni, :File_Permissions, 
                            :Num_Hard_Links, :Device_ID, :Inode_Number)
                        """, {
                            "Source_Name": Source_Name,
                            "Source_Path": Source_Path,
                            "Owner_UID": Owner_uid,
                            "Owner_GID": owner_gid,
                            "Time_Access": Time_Access,
                            "Time_Creation": Time_Creation,
                            "Time_Modification": Time_Modification,
                            "AppType": AppType,
                            "AppID": AppID,
                            "Artifact": Artifact,
                            "Data_Flags": item.get("Data_Flags"),
                            "Local_Path": item.get("Local_Path"),
                            "Common_Path": item.get("Common_Path"),
                            "Location_Flags": item.get("Location_Flags"),
                            "LNK_Class_ID": item.get("LNK_Class_ID"),
                            "File_Attributes": item.get("File_Attributes"),
                            "FileSize": format_size(stat_info.st_size),
                            "Header_Size": item.get("Header_Size"),
                            "IconIndex": item.get("IconIndex"),
                            "ShowWindow": item.get("ShowWindow"),
                            "Drive_Type": item.get("Drive_Type"),
                            "Drive_SN": item.get("Drive_SN"),
                            "Volume_Label": item.get("Volume_Label"),
                            "entry_number": item.get("entry_number"),
                            "Network_Device_Name": item.get("Network_Device_Name"),
                            "Network_Providers": item.get("Network_Providers"),
                            "Network_Share_Flags": item.get("Network_Share_Flags"),
                            "Network_Share_Name": item.get("Network_Share_Name"),
                            "Network_Share_Name_uni": item.get("Network_Share_Name_uni"),
                            "File_Permissions": file_permissions,
                            "Num_Hard_Links": stat_info.st_nlink,
                            "Device_ID": stat_info.st_dev,
                            "Inode_Number": stat_info.st_ino
                        })
                        conn.commit()
                except Exception as e:
                    print(f'Error processing file {file}: {e}')
                    unparsed_files.append(file)
            except FileNotFoundError:
                print(f'The file {file} does not exist.')
                unparsed_files.append(file)


    for CJL in custom_jump_lists:
        JL_Custom(CJL)




    def print_database_content(db_file):
        try:
            with sqlite3.connect(db_file) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM JLCE")
                rows = cursor.fetchall()
                for row in rows:
                    print(row)
        except Exception as e:
            print(f'An error occurred while reading the database: {e}')

    print_database_content(db_path)



    print("Custom Jump Lists:", custom_jump_lists)
    print("Automatic Jump Lists:", automatic_jump_lists)
    print("LNK Files:", lnk_files)
    print("****Unparsed files*******:", unparsed_files)

if __name__ == "__main__":
    A_CJL_LNK_Claw()