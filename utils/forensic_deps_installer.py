"""
Forensic Image Parsing Dependencies Installer

This module handles the installation of forensic image parsing dependencies
with intelligent retry logic and status tracking.

Features:
- Platform-agnostic pip-based installation (using dissect pure-Python libraries)
- Status tracking (not_attempted, success, failed, skipped)
- Automatic retry on Crow Eye restart
- Detailed logging
"""

import os
import sys
import json
import subprocess
import platform
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime


class ForensicDepsInstaller:
    """
    Manages installation of forensic image parsing dependencies.
    
    Tracks installation status and uses standard python pip processes 
    for pure-python dependencies.
    """
    
    # Status file location
    STATUS_FILE = Path(__file__).parent / "forensic_deps_status.json"
    
    # Dependency definitions
    DEPENDENCIES = {
        'pycdlib': {
            'description': 'ISO 9660 optical disc image support',
            'platforms': ['Windows', 'Linux', 'Darwin'],
            'install_method': 'pip',
            'required': False,
            'fallback': None
        },
        'dissect.target': {
            'description': 'Forensic image file system and target access (E01, VMDK, VHDX, Raw)',
            'platforms': ['Windows', 'Linux', 'Darwin'],
            'install_method': 'pip',
            'required': True,
            'fallback': None
        },
        'dissect.volume': {
            'description': 'Forensic volume and partition parsing',
            'platforms': ['Windows', 'Linux', 'Darwin'],
            'install_method': 'pip',
            'required': True,
            'fallback': None
        },
        'google-genai': {
            'description': 'Google Gemini AI SDK for EYE Assistant',
            'platforms': ['Windows', 'Linux', 'Darwin'],
            'install_method': 'pip',
            'required': True,
            'fallback': None
        },
        'openai': {
            'description': 'OpenAI SDK for EYE Assistant',
            'platforms': ['Windows', 'Linux', 'Darwin'],
            'install_method': 'pip',
            'required': True,
            'fallback': None
        },
        'anthropic': {
            'description': 'Anthropic SDK for EYE Assistant',
            'platforms': ['Windows', 'Linux', 'Darwin'],
            'install_method': 'pip',
            'required': True,
            'fallback': None
        }
    }
    
    def __init__(self):
        """Initialize the installer."""
        self.platform = platform.system()
        self.status = self._load_status()
        self.results = []
    
    def _load_status(self) -> Dict:
        """Load installation status from JSON file."""
        if self.STATUS_FILE.exists():
            try:
                with open(self.STATUS_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[WARNING] Could not load status file: {e}")
                return {}
        return {}
    
    def _save_status(self):
        """Save installation status to JSON file."""
        try:
            self.STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(self.STATUS_FILE, 'w') as f:
                json.dump(self.status, f, indent=2)
        except Exception as e:
            print(f"[WARNING] Could not save status file: {e}")
    
    def _get_package_status(self, package: str) -> str:
        """Get current status of a package."""
        if package not in self.status:
            return 'not_attempted'
        return self.status[package].get('status', 'not_attempted')
    
    def _set_package_status(self, package: str, status: str, message: str = ''):
        """Set status of a package."""
        self.status[package] = {
            'status': status,
            'message': message,
            'timestamp': datetime.now().isoformat(),
            'platform': self.platform
        }
        self._save_status()
    
    def _check_if_installed(self, package: str) -> bool:
        """Check if a package is already installed."""
        try:
            if package.startswith('dissect.'):
                # special handling for namespace packages
                __import__(package)
                return True
            
            import importlib.util
            
            # Special handling for google-genai (package name != import name)
            if package == 'google-genai':
                return importlib.util.find_spec('google.genai') is not None
                
            return importlib.util.find_spec(package) is not None
        except ImportError:
            return False
            
    def _install_via_pip(self, package: str) -> Tuple[bool, str]:
        """Install package via pip."""
        try:
            print(f"  -> Installing {package} via pip...")
            
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'install', package],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode == 0:
                return True, "Installed successfully via pip"
            else:
                return False, f"pip install failed: {result.stderr[:200]}"
                
        except subprocess.TimeoutExpired:
            return False, "Installation timeout (>5 minutes)"
        except Exception as e:
            return False, f"Installation error: {str(e)}"
    
    def install_package(self, package: str) -> bool:
        """Install a single package."""
        if self._check_if_installed(package):
            print(f"  [+] {package} already installed")
            self._set_package_status(package, 'success', 'Already installed')
            return True
        
        dep_info = self.DEPENDENCIES.get(package, {})
        if self.platform not in dep_info.get('platforms', []):
            print(f"  [-] {package} not available on {self.platform}")
            fallback = dep_info.get('fallback', 'Not available')
            self._set_package_status(package, 'skipped', f'Not available on {self.platform}. Fallback: {fallback}')
            return False
        
        status = self._get_package_status(package)
        if status == 'success':
            print(f"  [+] {package} previously installed successfully")
            return True
        
        print(f"  -> Attempting to install {package}...")
        success, message = self._install_via_pip(package)
        
        if success:
            print(f"  [+] {package} installed successfully")
            self._set_package_status(package, 'success', message)
        else:
            print(f"  [!] {package} installation failed: {message}")
            self._set_package_status(package, 'failed', message)
        
        return success
    
    def install_all(self, verbose: bool = True) -> Dict[str, bool]:
        """Install all forensic image parsing dependencies."""
        if verbose:
            print('\n' + '='*70)
            print('FORENSIC IMAGE PARSING DEPENDENCIES INSTALLATION')
            print('='*70)
            print(f'Platform: {self.platform}')
            print(f'Python: {sys.version.split()[0]}')
            print('='*70 + '\n')
        
        results = {}
        for package, info in self.DEPENDENCIES.items():
            if verbose:
                print(f"[{package}] {info['description']}")
            success = self.install_package(package)
            results[package] = success
            if verbose:
                print()
        
        if verbose:
            self._print_summary(results)
        
        return results
    
    def _print_summary(self, results: Dict[str, bool]):
        """Print installation summary."""
        print('='*70)
        print('INSTALLATION SUMMARY')
        print('='*70)
        
        success_count = sum(1 for v in results.values() if v)
        total_count = len(results)
        
        print(f'\nSuccessfully installed: {success_count}/{total_count} packages\n')
        
        installed = []
        failed = []
        skipped = []
        
        for package, success in results.items():
            status_info = self.status.get(package, {})
            status = status_info.get('status', 'unknown')
            message = status_info.get('message', '')
            
            if status == 'success':
                installed.append(package)
            elif status == 'failed':
                failed.append((package, message))
            elif status == 'skipped':
                skipped.append((package, message))
        
        if installed:
            print('[+] INSTALLED:')
            for pkg in installed:
                print(f'  - {pkg}')
            print()
        
        if skipped:
            print('[-] SKIPPED (Not available on this platform):')
            for pkg, msg in skipped:
                print(f'  - {pkg}')
                print(f'    {msg}')
            print()
        
        if failed:
            print('[!] FAILED:')
            for pkg, msg in failed:
                print(f'  - {pkg}')
                print(f'    {msg}')
            print()
            
        print('='*70 + '\n')
    
    def get_installation_report(self) -> Dict:
        """Get detailed installation report."""
        report = {
            'platform': self.platform,
            'timestamp': datetime.now().isoformat(),
            'packages': {}
        }
        
        for package, info in self.DEPENDENCIES.items():
            installed = self._check_if_installed(package)
            status_info = self.status.get(package, {})
            
            report['packages'][package] = {
                'description': info['description'],
                'installed': installed,
                'status': status_info.get('status', 'not_attempted'),
                'message': status_info.get('message', ''),
                'last_attempt': status_info.get('timestamp', 'Never'),
                'fallback': info.get('fallback', 'None')
            }
        
        return report

def install_forensic_dependencies(verbose: bool = True) -> Dict[str, bool]:
    installer = ForensicDepsInstaller()
    return installer.install_all(verbose=verbose)

def get_installation_status() -> Dict:
    installer = ForensicDepsInstaller()
    return installer.get_installation_report()

if __name__ == '__main__':
    install_forensic_dependencies(verbose=True)
