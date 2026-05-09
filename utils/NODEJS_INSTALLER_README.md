# Node.js Automatic Installer for Crow Eye Timeline

## Overview

The Node.js installer (`nodejs_installer.py`) automatically downloads and installs Node.js and npm on Windows and Linux systems to ensure the React timeline visualization can be built successfully.

## Features

- **Cross-Platform Support**: Works on both Windows and Linux
- **Automatic Detection**: Checks if Node.js is already installed before downloading
- **Version Management**: Installs Node.js LTS v20.11.1 (configurable)
- **Progress Indication**: Shows download progress with visual progress bar
- **Seamless Integration**: Automatically called by Crow Eye during startup
- **Portable Installation**: Installs Node.js locally in Crow Eye directory (Windows) or user home (Linux)

## How It Works

### Startup Flow

1. **Crow Eye starts** → Runs `ensure_timeline_built()` function
2. **Check if timeline is built** → If `timeline/react-timeline/dist` doesn't exist:
   - Call `ensure_nodejs_installed()` from `utils/nodejs_installer.py`
   - Check if Node.js and npm are already available
   - If not available, download and install Node.js
   - Add Node.js to PATH for current session
3. **Build timeline** → Run `npm install` and `npm run build`
4. **Timeline ready** → Crow Eye continues startup

### Installation Locations

- **Windows**: `<Crow Eye Directory>/nodejs/`
- **Linux**: `~/.crow-eye/nodejs/`

### Supported Platforms

| Platform | Architecture | Node.js Package |
|----------|-------------|-----------------|
| Windows  | x64         | node-v20.11.1-win-x64.zip |
| Windows  | x86         | node-v20.11.1-win-x86.zip |
| Linux    | x64         | node-v20.11.1-linux-x64.tar.xz |
| Linux    | ARM64       | node-v20.11.1-linux-arm64.tar.xz |
| Linux    | ARMv7       | node-v20.11.1-linux-armv7l.tar.xz |

## Usage

### Automatic (Recommended)

The installer runs automatically when Crow Eye starts. No manual intervention required.

### Manual Testing

You can test the installer independently:

```bash
# Windows
python utils/nodejs_installer.py

# Linux
python3 utils/nodejs_installer.py
```

### Checking Installation

After Crow Eye starts, you should see:

```
============================================================
[NODE.JS INSTALLER] Installing Node.js and npm...
============================================================
  -> Node.js v20.11.1 and npm 10.2.4 already installed
[NODE.JS INSTALLER] Node.js and npm are already available
```

Or if installing for the first time:

```
============================================================
[NODE.JS INSTALLER] Installing Node.js and npm...
============================================================
  -> Detected system: windows (amd64)
  -> Installation directory: C:\CrowEye\nodejs
  -> Downloading Node.js v20.11.1...
  -> URL: https://nodejs.org/dist/v20.11.1/node-v20.11.1-win-x64.zip
  -> This may take a few minutes depending on your internet speed...
  -> Progress: [████████████████████████████████████████] 100%
  -> Download completed: C:\CrowEye\nodejs\node-v20.11.1-win-x64.zip
  -> Extracting Node.js archive...
  -> Extraction completed
  -> Cleaned up archive file
  -> Added Node.js to PATH: C:\CrowEye\nodejs\node-v20.11.1-win-x64
  -> Node.js v20.11.1 and npm 10.2.4 already installed
[NODE.JS INSTALLER] Installation completed successfully!
============================================================
```

## Configuration

### Changing Node.js Version

Edit `utils/nodejs_installer.py` and modify the version constant:

```python
# Node.js version to install (LTS version recommended)
NODEJS_VERSION = "20.11.1"  # Change this to desired version
```

### Custom Installation Directory

Modify the `_get_install_directory()` method in the `NodeJSInstaller` class:

```python
def _get_install_directory(self) -> Path:
    """Get the directory where Node.js should be installed."""
    if self.system == 'windows':
        return Path('C:/custom/path/nodejs')  # Custom Windows path
    else:
        return Path('/opt/crow-eye/nodejs')  # Custom Linux path
```

## Troubleshooting

### Issue: "Download failed"

**Cause**: Network connectivity issues or invalid URL

**Solution**:
1. Check your internet connection
2. Verify the Node.js version exists at https://nodejs.org/dist/
3. Try manually downloading and placing in the installation directory

### Issue: "Extraction failed"

**Cause**: Corrupted download or insufficient permissions

**Solution**:
1. Delete the downloaded archive and retry
2. Check disk space
3. Ensure write permissions to installation directory

### Issue: "Node.js is not accessible after installation"

**Cause**: PATH not updated or session needs restart

**Solution**:
1. Restart Crow Eye
2. Manually add Node.js to system PATH
3. Install Node.js manually from https://nodejs.org/

### Issue: "Timeline build fails after Node.js installation"

**Cause**: npm dependencies or build errors

**Solution**:
1. Check `timeline/react-timeline/package.json` for errors
2. Manually run `npm install` in `timeline/react-timeline/`
3. Check Node.js version compatibility

## Manual Installation Alternative

If automatic installation fails, you can manually install Node.js:

### Windows

1. Download Node.js installer from https://nodejs.org/
2. Run the installer and follow prompts
3. Restart Crow Eye

### Linux

```bash
# Using package manager (Ubuntu/Debian)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Using package manager (Fedora/RHEL)
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
sudo dnf install -y nodejs

# Using nvm (Node Version Manager)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash
nvm install 20
nvm use 20
```

## Security Considerations

- Downloads are from official Node.js distribution servers (https://nodejs.org/dist/)
- SHA256 checksums can be verified manually from Node.js website
- Installation is local to Crow Eye directory (no system-wide changes on Windows)
- No elevated privileges required

## Dependencies

The installer uses only Python standard library modules:

- `os` - File system operations
- `sys` - System-specific parameters
- `platform` - Platform identification
- `subprocess` - Process execution
- `urllib.request` - HTTP downloads
- `tarfile` - Archive extraction (Linux)
- `zipfile` - Archive extraction (Windows)
- `shutil` - File operations
- `pathlib` - Path handling

## License

GPL-3.0 - Same as Crow Eye main project

## Support

For issues or questions:
1. Check this README troubleshooting section
2. Review Crow Eye main documentation
3. Open an issue on the project repository
