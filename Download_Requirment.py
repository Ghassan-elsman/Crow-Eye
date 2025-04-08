import subprocess
import sys
import os
from pathlib import Path

# Core packages with specific versions to prevent conflicts
core_modules = [
    ("PyQt5", "5.15.9"),
    ("PyQt5-Qt5", "5.15.2"),
    ("PyQt5-sip", "12.11.0"),
    ("pyqt5-tools", "5.15.9.3.3"),
    ("python-registry", "1.3.1"),
    ("pywin32", "306"),  # Specific version that includes post-install
]

# Additional packages
additional_modules = [
    "pandas",
    "streamlit",
    "altair",
    "olefile",
    "windowsprefetch",
]

def create_virtual_environment(venv_name=".venv"):
    """Create a fresh virtual environment"""
    try:
        print(f"\nCreating virtual environment '{venv_name}'...")
        subprocess.check_call([sys.executable, "-m", "venv", venv_name])
        print(f"✓ Virtual environment created")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to create virtual environment: {e}")
        return False

def get_pip_path(venv_name=".venv"):
    """Get the correct pip path for the OS"""
    if sys.platform == "win32":
        return Path(venv_name) / "Scripts" / "pip.exe"
    return Path(venv_name) / "bin" / "pip"

def install_packages(packages, venv_name=".venv"):
    """Install packages with proper error handling"""
    pip_path = get_pip_path(venv_name)
    
    for package in packages:
        if isinstance(package, tuple):
            name, version = package
            package_str = f"{name}=={version}"
        else:
            package_str = package
            
        try:
            print(f"\nInstalling {package_str}...")
            subprocess.check_call([
                str(pip_path), 
                "install", 
                "--no-cache-dir",  # Avoid cached corrupt packages
                package_str
            ])
            print(f"✓ Successfully installed {package_str}")
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to install {package_str}: {e}")
            if "python-registry" in package_str:
                print("  Note: If python-registry fails, try installing manually from:")
                print("  https://pypi.org/project/python-registry/#files")

def run_post_install(venv_name=".venv"):
    """Run post-install steps for specific packages"""
    if sys.platform == "win32":
        try:
            print("\nRunning pywin32 post-install...")
            python_path = Path(venv_name) / "Scripts" / "python.exe"
            subprocess.check_call([
                str(python_path),
                "-m", "pywin32_postinstall",
                "-install"
            ])
            print("✓ pywin32 post-install completed")
        except subprocess.CalledProcessError as e:
            print(f"✗ pywin32 post-install failed: {e}")

def verify_installation(venv_name=".venv"):
    """Verify critical packages installed correctly"""
    python_path = Path(venv_name) / "Scripts" / "python.exe"
    
    tests = [
        ("PyQt5", "from PyQt5 import QtCore; print('PyQt5 OK')"),
        ("python-registry", "from python_registry import Registry; print('Registry OK')"),
        ("pywin32", "import win32evtlog; print('pywin32 OK')")
    ]
    
    for package, test in tests:
        try:
            print(f"\nVerifying {package}...")
            subprocess.check_call([str(python_path), "-c", test])
            print(f"✓ {package} verified")
        except subprocess.CalledProcessError:
            print(f"✗ {package} verification failed")

def main():
    # Create fresh environment
    if not create_virtual_environment():
        return
    
    # Install packages in correct order
    install_packages(core_modules)
    install_packages(additional_modules)
    
    # Run post-install steps
    run_post_install()
    
    # Verify installation
    verify_installation()
    
    print("\nSETUP COMPLETE!")
    print("\nNext steps:")
    print("1. Activate the virtual environment:")
    if sys.platform == "win32":
        print("   .\\.venv\\Scripts\\activate")
    else:
        print("   source .venv/bin/activate")


if __name__ == "__main__":
    main()
