"""
Node.js and NPM Automatic Installer for Crow Eye Timeline
==========================================================

This module automatically downloads and installs Node.js and npm on Windows and Linux
systems to ensure the React timeline visualization can be built successfully.

Features:
- Cross-platform support (Windows and Linux)
- Automatic detection of existing Node.js installation
- Downloads appropriate Node.js version for the platform
- Verifies installation success
- Integrates seamlessly with Crow Eye startup

Author: Crow Eye Development Team
License: GPL-3.0
"""

import os
import sys
import platform
import subprocess
import urllib.request
import tarfile
import zipfile
import shutil
from pathlib import Path

# Node.js version to install (LTS version recommended)
NODEJS_VERSION = "20.11.1"  # Latest LTS as of 2024

class NodeJSInstaller:
    """Handles automatic Node.js and npm installation across platforms."""
    
    def __init__(self):
        self.system = platform.system().lower()
        self.machine = platform.machine().lower()
        self.install_dir = self._get_install_directory()
        
    def _get_install_directory(self) -> Path:
        """Get the directory where Node.js should be installed."""
        if self.system == 'windows':
            # Install in Crow Eye directory for portability
            return Path(__file__).parent.parent / 'nodejs'
        else:
            # Linux: Install in user's home directory
            return Path.home() / '.crow-eye' / 'nodejs'
    
    def is_nodejs_installed(self) -> bool:
        """Check if Node.js and npm are already installed and accessible."""
        # First, try to see if it's already in the PATH
        if self._check_node_in_path():
            return True
            
        # Second, try to bootstrap from local installation directory
        if self.install_dir.exists():
            print(f"  -> Found local Node.js directory at {self.install_dir}")
            if self._setup_environment():
                # Re-check after adding to PATH
                if self._check_node_in_path():
                    return True
        
        return False

    def _check_node_in_path(self) -> bool:
        """Check if 'node' and 'npm' are currently in the PATH and working."""
        try:
            # Check node version
            node_result = subprocess.run(
                ['node', '--version'],
                capture_output=True,
                text=True,
                timeout=5,
                shell=platform.system().lower() == 'windows'
            )
            
            # Check npm version
            npm_result = subprocess.run(
                ['npm', '--version'],
                capture_output=True,
                text=True,
                timeout=5,
                shell=platform.system().lower() == 'windows'
            )
            
            if node_result.returncode == 0 and npm_result.returncode == 0:
                node_version = node_result.stdout.strip()
                npm_version = npm_result.stdout.strip()
                print(f"  -> Node.js {node_version} and npm {npm_version} detected")
                return True
                
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            pass
        
        return False
    
    def _get_download_url(self) -> str:
        """Get the appropriate Node.js download URL for the current platform."""
        base_url = f"https://nodejs.org/dist/v{NODEJS_VERSION}"
        
        if self.system == 'windows':
            # Windows: Download zip archive
            if 'amd64' in self.machine or 'x86_64' in self.machine:
                return f"{base_url}/node-v{NODEJS_VERSION}-win-x64.zip"
            else:
                return f"{base_url}/node-v{NODEJS_VERSION}-win-x86.zip"
        
        elif self.system == 'linux':
            # Linux: Download tar.xz archive
            if 'aarch64' in self.machine or 'arm64' in self.machine:
                return f"{base_url}/node-v{NODEJS_VERSION}-linux-arm64.tar.xz"
            elif 'armv7' in self.machine:
                return f"{base_url}/node-v{NODEJS_VERSION}-linux-armv7l.tar.xz"
            else:
                return f"{base_url}/node-v{NODEJS_VERSION}-linux-x64.tar.xz"
        
        else:
            raise OSError(f"Unsupported operating system: {self.system}")
    
    def _download_nodejs(self, url: str, dest_path: Path) -> bool:
        """Download Node.js archive with progress indication."""
        try:
            print(f"  -> Downloading Node.js v{NODEJS_VERSION}...")
            print(f"  -> URL: {url}")
            print(f"  -> This may take a few minutes depending on your internet speed...")
            
            # Using Request to add a standard User-Agent, bypassing some restrictive firewalls/proxies
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            )
            
            with urllib.request.urlopen(req, timeout=30) as response, open(dest_path, 'wb') as out_file:
                total_size = int(response.info().get('Content-Length', 0))
                block_size = 8192
                downloaded = 0
                
                while True:
                    buffer = response.read(block_size)
                    if not buffer:
                        break
                    out_file.write(buffer)
                    downloaded += len(buffer)
                    
                    if total_size > 0:
                        percent = min(100, (downloaded * 100) // total_size)
                        bar_length = 40
                        filled = int(bar_length * percent / 100)
                        bar = '█' * filled + '░' * (bar_length - filled)
                        print(f"\r  -> Progress: [{bar}] {percent}%", end='', flush=True)
                        
            print()  # New line after progress bar
            print(f"  -> Download completed: {dest_path}")
            return True
            
        except Exception as e:
            print(f"  -> Download failed: {e}")
            return False
    
    def _extract_archive(self, archive_path: Path, extract_to: Path) -> bool:
        """Extract the downloaded Node.js archive."""
        try:
            print(f"  -> Extracting Node.js archive...")
            
            if archive_path.suffix == '.zip':
                # Windows zip extraction
                with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_to)
            
            elif archive_path.suffix in ['.xz', '.gz'] or '.tar' in archive_path.name:
                # Linux tar.xz extraction
                with tarfile.open(archive_path, 'r:*') as tar_ref:
                    tar_ref.extractall(extract_to)
            
            else:
                print(f"  -> Unsupported archive format: {archive_path.suffix}")
                return False
            
            print(f"  -> Extraction completed")
            return True
            
        except Exception as e:
            print(f"  -> Extraction failed: {e}")
            return False
    
    def _setup_environment(self) -> bool:
        """Add Node.js to PATH for the current session."""
        try:
            if self.system == 'windows':
                # Find the extracted node directory
                node_dirs = list(self.install_dir.glob('node-v*-win-*'))
                if not node_dirs:
                    print("  -> Could not find extracted Node.js directory")
                    return False
                
                node_bin = node_dirs[0]
                
            else:  # Linux
                # Find the extracted node directory
                node_dirs = list(self.install_dir.glob('node-v*-linux-*'))
                if not node_dirs:
                    print("  -> Could not find extracted Node.js directory")
                    return False
                
                node_bin = node_dirs[0] / 'bin'
            
            # Add to PATH for current session
            current_path = os.environ.get('PATH', '')
            os.environ['PATH'] = f"{node_bin}{os.pathsep}{current_path}"
            
            print(f"  -> Added Node.js to PATH: {node_bin}")
            return True
            
        except Exception as e:
            print(f"  -> Failed to setup environment: {e}")
            return False
    
    def install(self) -> bool:
        """
        Main installation method.
        
        Returns:
            bool: True if installation successful, False otherwise
        """
        print('\n' + '='*60)
        print('[NODE.JS INSTALLER] Installing Node.js and npm...')
        print('='*60)
        
        # Check if already installed
        if self.is_nodejs_installed():
            print('[NODE.JS INSTALLER] Node.js and npm are already available')
            return True
        
        print(f"  -> Detected system: {self.system} ({self.machine})")
        print(f"  -> Installation directory: {self.install_dir}")
        
        # Create installation directory
        try:
            self.install_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"  -> Failed to create installation directory: {e}")
            return False
        
        # Get download URL
        try:
            download_url = self._get_download_url()
        except OSError as e:
            print(f"  -> {e}")
            return False
        
        # Determine archive filename and path
        archive_name = download_url.split('/')[-1]
        archive_path = self.install_dir / archive_name
        
        # Download Node.js
        if not self._download_nodejs(download_url, archive_path):
            return False
        
        # Extract archive
        if not self._extract_archive(archive_path, self.install_dir):
            return False
        
        # Clean up archive
        try:
            archive_path.unlink()
            print(f"  -> Cleaned up archive file")
        except Exception as e:
            print(f"  -> Warning: Could not delete archive: {e}")
        
        # Setup environment
        if not self._setup_environment():
            return False
        
        # Verify installation
        if self.is_nodejs_installed():
            print('[NODE.JS INSTALLER] Installation completed successfully!')
            print('='*60 + '\n')
            return True
        else:
            print('[NODE.JS INSTALLER] Installation completed but Node.js is not accessible')
            print('[NODE.JS INSTALLER] You may need to restart Crow Eye or add Node.js to your system PATH')
            print('='*60 + '\n')
            return False


def ensure_nodejs_installed() -> bool:
    """
    Ensure Node.js and npm are installed and available.
    
    This function is called by Crow Eye during startup to guarantee
    that the timeline visualization dependencies are met.
    
    Returns:
        bool: True if Node.js is available, False otherwise
    """
    installer = NodeJSInstaller()
    return installer.install()


if __name__ == '__main__':
    # Allow running as standalone script for testing
    success = ensure_nodejs_installed()
    sys.exit(0 if success else 1)
