Crow Eye - Windows Forensics Tool Documentation
Created by Ghassan Elsman

Overview
Crow Eye is a Windows forensics tool designed to parse various Windows artifacts and present them via a user-friendly GUI for easier analysis. The tool focuses on collecting and analyzing key forensic artifacts from Windows systems.

How to Use Crow Eye
1. Automatic/Custom Jump Lists and LNK Files
Automatic Parsing:
The tool will parse these artifacts automatically from the system.

Selective Parsing:
To analyze specific artifacts only:

Copy the Jump Lists/LNK files you want to analyze

Paste them into:
CrowEye/Artifacts Collectors/Target Artifacts

2. Registry Analysis
To parse registry information:

Copy these three registry files to:
CrowEye/Artifacts Collectors/Target Artifacts

NTUSER.DAT from C:\Users\<Username>\NTUSER.DAT

SOFTWARE from C:\Windows\System32\config\SOFTWARE

SYSTEM from C:\Windows\System32\config\SYSTEM

Important Notes:

Crow Eye cannot access these registry files while Windows is running

You cannot copy these files while Windows is running

To collect these files:

Boot from external media (WinPE/Live CD)

Use forensic acquisition tools

Analyze a disk image

3. Prefetch Files
The tool automatically parses prefetch files from:
C:\Windows\Prefetch

4. Event Logs
Parsed using win32evtlog

Saved into database for analysis


Data Collected by Crow Eye
1. Registry 
Network interfaces

Network list (networks the computer accessed)

Machine auto-run programs

User auto-run programs

Last Windows update

Last Windows shutdown time

Time zone information

2. File Activity Tab
Recent documents

Searches via Explorer bar

Typed paths

Open/Save MRU (Most Recently Used)

Last save MRU

3. Prefetch Files
Executable name

Run counts

File size

Last modified time

Last accessed time

Creation time

File node

Inode number

Device ID

User UID

Group UID

4. Jump Lists and LNK Files
(Using modified version of JumpList_Lnk_Parser by Saleh Muhaysin)

Source name

Source path

Owner UID

Group UID

Time accessed

Time created

Time modified

Data flag

Local path

File size header size

Show window settings

File permissions

Device ID

Inode number

5. Logs
Application logs

System logs

Security logs

Screenshots
Crow Eye Interface

Technical Notes
The tool incorporates a modified version of the JumpList_Lnk_Parser Python module

Registry parsing requires complete registry hive files

Some artifacts require special handling due to Windows file locking mechanisms

Development Credits
Jump List/LNK parsing based on work by Saleh Muhaysin


![Screenshot 2025-04-03 225113](https://github.com/user-attachments/assets/515aa6c5-c5e4-43aa-8b2e-2cbfe3f5ebd6)
![Screenshot 2025-04-08 134045](https://github.com/user-attachments/assets/f0da8f6f-bca4-4724-b13f-6d2044b1584f)
![Screenshot 2025-04-08 134131](https://github.com/user-attachments/assets/09e953aa-be3e-4273-b7ec-ffe529bbb50f)


