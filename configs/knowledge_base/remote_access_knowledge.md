# Remote Access & Network Protocol Intelligence

This article provides forensic guidance for interpreting remote access and network protocols discovered by EYE.

## Windows Logon Types for Remote Activity
- **Type 3 (Network)**: Connection to a shared resource (folder, printer) or IIS authentication. Common for lateral movement.
- **Type 10 (RemoteInteractive)**: Remote Desktop Protocol (RDP) connection. Indicates direct terminal control.
- **Type 12 (CachedRemoteInteractive)**: Login using cached credentials (often RDP when the domain controller is offline).

## Common Remote Control Artifacts
- **TeamViewer**: Leaves artifacts in `SYSTEM\CurrentControlSet\Services\TeamViewer` and application logs.
- **AnyDesk**: Known for `ad.exe` execution and configuration files in `%AppData%\AnyDesk`.
- **WinRM (Windows Remote Management)**: Uses port 5985 (HTTP) or 5986 (HTTPS). Enabled via `winrm quickconfig`.
- **PsExec**: Part of Sysinternals. Leaves a service named `PSEXESVC` during execution.

## Analysis Strategy
1. Cross-reference **Logon Type 10** with **SRUM** network data to see volume of data transferred during the session.
2. Check **UserAssist** or **Prefetch** for execution of remote client binaries (e.g., `TeamViewer.exe`).
3. Pivot from **Network Connectivity Profiles** to identify the physical location (via Gateway MAC) of the host during the remote session.
