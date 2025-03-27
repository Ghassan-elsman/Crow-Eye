import subprocess
import sys
import os
from pathlib import Path

# List of modules to install
modules = [
    "PyQt5",
    "pyqt5-tools",
    "PyQt5-Qt5",
    "PyQt5-sip",   
    "pandas",
    "streamlit",
    "altair",
    "olefile",
    "windowsprefetch",
    "binascii",
    "pywin32",
    "python-registry"
]

# Built-in modules (do not need installation)
builtin_modules = [
    "os",
    "datetime",
    "json",
    "struct",
    "uuid",
    "re",
    "argparse",
]

def create_virtual_environment(venv_name=".venv"):
    """Create a Python virtual environment"""
    try:
        print(f"\nCreating virtual environment '{venv_name}'...")
        subprocess.check_call([sys.executable, "-m", "venv", venv_name])
        print(f"Virtual environment created successfully at {Path(venv_name).resolve()}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to create virtual environment: {e}")
        return False

def activate_environment(venv_name=".venv"):
    """Activate the virtual environment"""
    if sys.platform == "win32":
        activate_script = Path(venv_name) / "Scripts" / "activate.bat"
    else:
        activate_script = Path(venv_name) / "bin" / "activate"
    
    if not activate_script.exists():
        print("Virtual environment activation script not found!")
        return False
    
    print(f"\nActivating virtual environment...")
    print(f"Run this manually if needed: {activate_script.resolve()}")
    return True

def install_modules(modules, venv_name=".venv"):
    """Install modules in the virtual environment"""
    pip_path = Path(venv_name) / "Scripts" / "pip.exe" if sys.platform == "win32" else Path(venv_name) / "bin" / "pip"
    
    for module in modules:
        try:
            print(f"\nInstalling {module}...")
            subprocess.check_call([str(pip_path), "install", module])
            print(f"Successfully installed {module}.")
        except subprocess.CalledProcessError as e:
            print(f"Failed to install {module}: {e}")

def check_builtin_modules(modules):
    """Check built-in modules"""
    print("\nChecking built-in modules...")
    for module in modules:
        print(f"{module} is a built-in module and does not need installation.")

def main():
    # Create virtual environment
    if not create_virtual_environment():
        return
    
    # Activate environment (note: activation only affects subprocesses)
    activate_environment()
    
    # Install modules in the virtual environment
    print("\nInstalling required modules in virtual environment...")
    install_modules(modules)
    
    # Check built-in modules
    check_builtin_modules(builtin_modules)
    
    print("\nSetup completed successfully!")
    print(f"\nTo activate the virtual environment manually, run:")
    if sys.platform == "win32":
        print(f"  .\\.venv\\Scripts\\activate")
    else:
        print(f"  source .venv/bin/activate")

if __name__ == "__main__":
    main()