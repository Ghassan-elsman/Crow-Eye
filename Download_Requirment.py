import subprocess
import sys
import os
from pathlib import Path

core_modules = [
    ("PyQt5", "5.15.9"),
    ("pyqt5-tools"),
    ("python-registry"),
    ("pywin32"), 
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

def get_venv_bin_path(venv_name=".venv", executable=""):
    """Get the correct path for the OS"""
    if sys.platform == "win32":
        return Path(venv_name) / "Scripts" / executable
    return Path(venv_name) / "bin" / executable

def install_packages(packages, venv_name=".venv"):
    """Install packages with proper error handling"""
    pip_path = get_venv_bin_path(venv_name, "pip.exe" if sys.platform == "win32" else "pip")
    results = {}
    
    for package in packages:
        if isinstance(package, tuple):
            name, version = package
            package_str = f"{name}=={version}"
        else:
            name = package
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
            results[name] = ("Success", version if isinstance(package, tuple) else "latest")
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to install {package_str}: {e}")
            if "python-registry" in package_str:
                print("  Note: If python-registry fails, try installing manually from:")
                print("  https://pypi.org/project/python-registry/#files")
            results[name] = ("Failed", str(e))
    
    return results

def run_post_install(venv_name=".venv"):
    """Run post-install steps for specific packages"""
    if sys.platform == "win32":
        try:
            print("\nRunning pywin32 post-install...")
            python_path = get_venv_bin_path(venv_name, "python.exe")
            subprocess.check_call([
                str(python_path),
                "-m", "pywin32_postinstall",
                "-install"
            ])
            print("✓ pywin32 post-install completed")
            return True
        except subprocess.CalledProcessError as e:
            print(f"✗ pywin32 post-install failed: {e}")
            return False

def get_installed_packages(venv_name=".venv"):
    """Get list of installed packages with versions"""
    pip_path = get_venv_bin_path(venv_name, "pip.exe" if sys.platform == "win32" else "pip")
    try:
        result = subprocess.check_output([str(pip_path), "list"])
        return result.decode('utf-8').splitlines()
    except subprocess.CalledProcessError:
        return []

def activate_environment(venv_name=".venv"):
    """Activate the virtual environment"""
    if sys.platform == "win32":
        activate_path = get_venv_bin_path(venv_name, "activate.bat")
        subprocess.call(f"call {activate_path}", shell=True)
    else:
        activate_path = get_venv_bin_path(venv_name, "activate")
        subprocess.call(f"source {activate_path}", shell=True)
    print("\n✓ Virtual environment activated")

def print_installation_report(core_results, additional_results, post_install_success, installed_packages):
    """Print detailed installation report"""
    print("\n" + "="*50)
    print("INSTALLATION REPORT".center(50))
    print("="*50)
    
    print("\nCORE MODULES:")
    for package, (status, version) in core_results.items():
        status_icon = "✓" if status == "Success" else "✗"
        print(f"{status_icon} {package}: {status} (Version: {version})")
    
    print("\nADDITIONAL MODULES:")
    for package, (status, version) in additional_results.items():
        status_icon = "✓" if status == "Success" else "✗"
        print(f"{status_icon} {package}: {status} (Version: {version})")
    
    print("\nPOST-INSTALLATION:")
    post_status = "✓ Success" if post_install_success else "✗ Failed"
    print(f"{post_status} - pywin32 post-install")
    
    print("\nINSTALLED PACKAGES:")
    for package in installed_packages:
        print(f"• {package}")

def main():
    # Create fresh environment
    if not create_virtual_environment():
        return
    
    # Activate environment
    activate_environment()
    
    # Install packages in correct order and collect results
    core_results = install_packages(core_modules)
    additional_results = install_packages(additional_modules)
    
    # Run post-install steps
    post_install_success = run_post_install()
    
    # Get list of installed packages
    installed_packages = get_installed_packages()
    
    # Print detailed report
    print_installation_report(core_results, additional_results, post_install_success, installed_packages)
    
    print("\nSETUP COMPLETE!")
    print("\nVirtual environment is now active. You can start using it.")


if __name__ == "__main__":
    main()
