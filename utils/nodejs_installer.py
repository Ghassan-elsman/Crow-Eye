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
from pathlib import Path

# Node.js version to install (LTS version recommended)
NODEJS_VERSION = "22.14.0"  # LTS version compatible with modern Vite

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
        """Check if Node.js and npm are already installed and accessible with the correct version."""
        # 1. Try to see if it's already in the CURRENT PATH (might be system or already-setup local)
        if self._check_node_in_path():
            return True
            
        # 2. If not found or too old, try to bootstrap from local installation directory
        if self.install_dir.exists():
            # Try to setup path from local install
            if self._setup_environment():
                # Re-verify after path setup
                return self._check_node_in_path()
        
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
                # Check version ONLY if the command succeeded
                node_version_out = node_result.stdout.strip().lstrip('v')
                version_parts = [int(p) for p in node_version_out.split('.')]
                
                # Require at least Node 22.12.0 for modern Vite compatibility
                min_version = [22, 12, 0]
                is_version_ok = version_parts >= min_version
                
                if is_version_ok:
                    node_version = node_result.stdout.strip()
                    npm_version = npm_result.stdout.strip()
                    # Sanitize output - check for null bytes or weird control chars
                    if '\x00' in node_version or not node_version.startswith('v'):
                        return False
                        
                    print(f"  -> Node.js {node_version} and npm {npm_version} detected")
                    return True
                else:
                    print(f"  -> Detected Node.js {node_version_out} is below minimum requirement ({'.'.join(map(str, min_version))})")
                    return False
                
        except Exception:
            pass
        
        return False
    
    def _get_download_url(self) -> str:
        """Get the appropriate Node.js download URL for the current platform."""
        base_url = f"https://nodejs.org/dist/v{NODEJS_VERSION}"
        
        # Normalize architecture for user-friendly display and selection
        is_64bit = any(arch in self.machine for arch in ['amd64', 'x86_64', 'x64', 'intel64'])
        
        if self.system == 'windows':
            # Windows: Download zip archive
            if is_64bit:
                print(f"  -> Selecting Node.js Windows x64 (Intel/AMD 64-bit)")
                return f"{base_url}/node-v{NODEJS_VERSION}-win-x64.zip"
            elif 'arm64' in self.machine or 'aarch64' in self.machine:
                print(f"  -> Selecting Node.js Windows ARM64")
                return f"{base_url}/node-v{NODEJS_VERSION}-win-arm64.zip"
            else:
                # 32-bit Windows is rarely used in modern forensics and untested for this project
                raise OSError(f"Unsupported architecture: 32-bit Windows is not supported by Node.js {NODEJS_VERSION}")
        
        elif self.system == 'linux':
            # Linux: Download tar.xz archive
            if 'aarch64' in self.machine or 'arm64' in self.machine:
                print(f"  -> Selecting Node.js Linux ARM64")
                return f"{base_url}/node-v{NODEJS_VERSION}-linux-arm64.tar.xz"
            elif 'armv7' in self.machine:
                print(f"  -> Selecting Node.js Linux ARMv7")
                return f"{base_url}/node-v{NODEJS_VERSION}-linux-armv7l.tar.xz"
            elif is_64bit:
                print(f"  -> Selecting Node.js Linux x64 (Intel/AMD 64-bit)")
                return f"{base_url}/node-v{NODEJS_VERSION}-linux-x64.tar.xz"
            else:
                # Node.js dropped 32-bit Linux support after v10
                raise OSError(f"Unsupported architecture: 32-bit Linux is not supported by Node.js {NODEJS_VERSION}")
        
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
            
            # timeout=30 applies to the initial connection and individual socket read() calls.
            # It does NOT bound the total wall-clock time for the download.
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
                        bar = '#' * filled + '-' * (bar_length - filled)
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
            
            # More robust suffix check using Path.suffixes (e.g. .tar.xz -> ['.tar', '.xz'])
            all_suffixes = [s.lower() for s in archive_path.suffixes]
            
            # Helper for path traversal guard
            def is_within_directory(directory, target):
                abs_directory = os.path.abspath(directory)
                abs_target = os.path.abspath(target)
                # Ensure target is either the directory itself or a child (with separator)
                # This prevents prefix spoofing (e.g. /tmp/nodejs matching /tmp/nodejs-evil)
                return abs_target == abs_directory or abs_target.startswith(abs_directory + os.sep)

            if '.zip' in all_suffixes:
                # Windows zip extraction with path traversal guard
                with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                    for member in zip_ref.namelist():
                        member_path = os.path.join(extract_to, member)
                        if not is_within_directory(extract_to, member_path):
                            raise Exception(f"Attempted Path Traversal in Zip File: {member}")
                    zip_ref.extractall(extract_to)
            
            elif '.tar' in all_suffixes or any(s in all_suffixes for s in ['.xz', '.gz', '.bz2']):
                # Linux/Unix tar extraction with path traversal and LINK traversal guards.
                # Note: The two-pass approach (getmembers() then extractall()) is safe here 
                # because tarfile caches the member list after the first pass on disk files.
                with tarfile.open(archive_path, 'r:*') as tar_ref:
                    for member in tar_ref.getmembers():
                        # Guard 1: Member Path Traversal
                        # Normalizes member path to check if it's within extract_to
                        member_path = os.path.normpath(os.path.join(extract_to, member.name))
                        if not is_within_directory(extract_to, member_path):
                            raise Exception(f"Attempted Path Traversal in Tar File: {member.name}")
                        
                        # Guard 2: Link Target Traversal (Symlinks/Hardlinks).
                        # Note: Absolute symlink targets are intentionally rejected by is_within_directory() 
                        # as a security-by-default policy, as Node.js archives use only relative links.
                        if member.issym() or member.islnk():
                            # Normalize member.name to make this guard standalone-safe against prefix/traversal spoofing
                            # even if Guard 1 were to be removed or refactored.
                            safe_member_name = os.path.normpath(member.name)
                            member_parent = os.path.normpath(os.path.join(extract_to, os.path.dirname(safe_member_name)))
                            link_target = os.path.normpath(os.path.join(member_parent, member.linkname))
                            
                            if not is_within_directory(extract_to, link_target):
                                raise Exception(f"Attempted Link Traversal in Tar File: {member.linkname}")
                                
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
                # Find the extracted node directory for the SPECIFIC version
                # Deterministic sorting ensures we pick the same dir if multiple exist
                node_dirs = sorted(list(self.install_dir.glob(f'node-v{NODEJS_VERSION}-win-*')))
                if not node_dirs:
                    print(f"  -> Could not find extracted Node.js v{NODEJS_VERSION} directory")
                    return False
                
                node_bin = node_dirs[0]
                
            else:  # Linux
                # Find the extracted node directory for the SPECIFIC version
                node_dirs = sorted(list(self.install_dir.glob(f'node-v{NODEJS_VERSION}-linux-*')))
                if not node_dirs:
                    print(f"  -> Could not find extracted Node.js v{NODEJS_VERSION} directory")
                    return False
                
                node_bin = node_dirs[0] / 'bin'
            
            # Add to PATH for current session ONLY if not already there
            current_path = os.environ.get('PATH', '')
            path_list = current_path.split(os.pathsep)
            
            # Use absolute path and normalize for comparison
            target_path = str(node_bin.resolve())
            base_install_dir = str(self.install_dir.resolve())
            
            # Clean up any existing entries that point EXACTLY to our install_dir base
            # to prevent growth while avoiding overly broad substring matches.
            new_path_list = []
            for p in path_list:
                if not p: continue
                try:
                    p_path = str(Path(p).resolve())
                    # Only filter out if it matches exactly or is a subpath of our install_dir
                    # We add os.sep to ensure we don't accidentally match prefixes (e.g. nodejs vs nodejs-tools)
                    if p_path == base_install_dir or p_path.startswith(base_install_dir + os.sep):
                        continue
                except:
                    # If we can't resolve it, KEEP it in the path to avoid breaking it
                    pass
                new_path_list.append(p)
                
            os.environ['PATH'] = os.pathsep.join([target_path] + new_path_list)
            
            print(f"  -> Prioritizing Node.js in PATH: {node_bin}")
            return True
            
        except Exception as e:
            print(f"  -> Failed to setup environment: {e}")
            return False
    
    def install(self, force: bool = False) -> bool:
        """Main entry point to ensure Node.js is installed and set up."""
        print('\n' + '='*60)
        print('[NODE.JS INSTALLER] Installing Node.js and npm...')
        print('='*60)
        
        # 1. Check if already installed in system or current session
        if not force and self.is_nodejs_installed():
            print('[NODE.JS INSTALLER] Node.js and npm are already available')
            return True
        
        print(f"  -> Detected system: {self.system} ({self.machine})")
        print(f"  -> Installation directory: {self.install_dir}")
        
        # 2. If a local directory exists, try to set it up first (recovery path)
        if self.install_dir.exists():
            print(f"  -> Verifying existing local installation at {self.install_dir}...")
            if self._setup_environment():
                # Direct check after setup to avoid double PATH mutation in is_nodejs_installed()
                if self._check_node_in_path():
                    return True
        
        # 3. Download and Install if needed
        try:
            download_url = self._get_download_url()
            archive_name = download_url.split('/')[-1]
            # Archive path should be INSIDE install_dir to keep it contained
            archive_path = self.install_dir / archive_name
            
            # Ensure installation directory exists
            self.install_dir.mkdir(parents=True, exist_ok=True)
            
            # Download if archive doesn't exist, is forcing, OR is clearly too small (corrupt).
            # Node.js archives are typically >15MB. 1MB is a safe domain-specific floor 
            # to detect incomplete downloads while allowing for potential future smaller builds.
            existing_size = archive_path.stat().st_size if archive_path.exists() else 0
            is_corrupt = existing_size < 1_000_000 # Treats 0-byte and small files as corrupt/incomplete
            
            if force or is_corrupt:
                if is_corrupt and existing_size > 0:
                    print(f"  -> Found partial/corrupt archive ({existing_size} bytes), re-downloading...")
                elif is_corrupt:
                    print(f"  -> Archive missing or empty, downloading...")
                    
                if not self._download_nodejs(download_url, archive_path):
                    return False
            else:
                print(f"  -> Using existing archive: {archive_path} ({existing_size} bytes)")
                
            # Extract (this will overwrite existing files)
            if not self._extract_archive(archive_path, self.install_dir):
                return False
                
            # Setup environment
            if not self._setup_environment():
                return False
                
            # Final verification (direct check to avoid redundant setup calls)
            if self._check_node_in_path():
                # ONLY cleanup archive on total success
                if archive_path.exists():
                    try:
                        archive_path.unlink()
                        print(f"  -> Cleaned up archive file")
                    except Exception:
                        pass
                print('[NODE.JS INSTALLER] Node.js and npm are now fully available!')
                print('='*60 + '\n')
                return True
            else:
                print('[NODE.JS INSTALLER] FAILED: Verification failed after installation.')
                print('='*60 + '\n')
                return False
                
        except OSError as e:
            print(f"  -> System error: {e}")
            return False
        except Exception as e:
            print(f"  -> Unexpected error: {e}")
            return False


def ensure_nodejs_installed() -> bool:
    """
    Ensure Node.js and npm are installed and available.
    
    This function is called by Crow Eye during startup to guarantee
    that the timeline visualization dependencies are met.
    
    Returns:
        bool: True if Node.js is available, False otherwise
    """
    try:
        installer = NodeJSInstaller()
        return installer.install()
    except Exception as e:
        print(f"[NODE.JS INSTALLER] Fatal error during setup: {e}")
        return False


if __name__ == '__main__':
    # Allow running as standalone script for testing
    success = ensure_nodejs_installed()
    sys.exit(0 if success else 1)
