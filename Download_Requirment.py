import subprocess
import sys

# List of modules to install
modules = [
    "PyQt5",
    "pandas",
    "streamlit",
    "altair",
    "JLParser",
    "os",
    "datetime",
    "json",
    "struct",
    "uuid",
    "re",
    "argparse",
    "olefile",
    "windowsprefetch",
    "Registry",
    "binascii",
    "win32evtlog"
]

# Function to install modules
def install_modules(modules):
    for module in modules:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", module])
        except subprocess.CalledProcessError as e:
            print(f"Failed to install {module}: {e}")

# Install the modules
install_modules(modules)