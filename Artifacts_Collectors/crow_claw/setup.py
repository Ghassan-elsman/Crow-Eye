"""
Setup configuration for Crow-Claw artifact acquisition tool.

Installation:
    pip install -e .

Or from PyPI:
    pip install crow-claw

Usage:
    crow-claw
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README
readme_path = Path(__file__).parent / "README.md"
long_description = ""
if readme_path.exists():
    long_description = readme_path.read_text(encoding="utf-8")

setup(
    name="crow-claw",
    version="1.0.0",
    description="Windows Forensic Artifact Acquisition Tool",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Crow-Eye Development Team",
    url="https://github.com/yourusername/crow-eye",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "PyQt5>=5.15.0",
        "setuptools>=45",
        "wheel>=0.36",
    ],
    entry_points={
        "console_scripts": [
            "crow-claw=crow_claw.Crow_claw:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: Information Technology",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Operating System :: Microsoft :: Windows",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Systems Administration",
        "Topic :: System :: Forensics",
    ],
    keywords="forensics windows artifacts collection acquisition digital-investigation",
    project_urls={
        "Documentation": "https://github.com/yourusername/crow-eye/wiki",
        "Source": "https://github.com/yourusername/crow-eye",
        "Tracker": "https://github.com/yourusername/crow-eye/issues",
    },
)
