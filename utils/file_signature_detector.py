#!/usr/bin/env python3
"""
Crow Eye File Signature Detection Utility

A comprehensive file signature detection system for forensic analysis.
This utility can identify file types based on magic bytes (file signatures)
and heuristic analysis, supporting 310+ file formats commonly found in
forensic investigations, including:

- Microsoft Office documents (legacy and modern formats)
- Multimedia files (video, audio, images)
- Windows forensic artifacts (registry hives, memory dumps, NTFS structures)
- Archive and compression formats
- Database files (SQLite, Access, MySQL, PostgreSQL, etc.)
- Executable and binary formats (Windows, Linux, macOS, mobile)
- Development artifacts and configuration files

Features:
- 310+ magic byte signatures for comprehensive file type detection
- Multi-offset signature scanning for complex file formats
- Text-based heuristic analysis for script and configuration files
- Robust error handling for corrupted or incomplete files
- Optimized for Windows forensic environments
- Fallback mechanisms for maximum compatibility

Author: Ghassan Elsman (Crow Eye Development)
License: Open Source
"""

import os
import logging
from typing import Tuple, List, Optional
from ctypes import WinDLL, wintypes
import subprocess

# Configure logging
logger = logging.getLogger(__name__)

# Comprehensive file signature database for forensic analysis
FILE_SIGNATURES = {
    # Microsoft Office and document formats
    b'\x50\x4B\x03\x04': {'ext': ['docx', 'xlsx', 'pptx', 'zip', 'jar', 'apk', 'odt', 'ods', 'odp'], 'desc': 'ZIP/Office Open XML/JAR/APK/OpenDocument'},
    b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1': {'ext': ['doc', 'xls', 'ppt', 'msi', 'msg'], 'desc': 'Microsoft Office Binary Format/MSI/Outlook Message'},
    b'\x25\x50\x44\x46': {'ext': ['pdf'], 'desc': 'Adobe PDF Document'},
    b'\x25\x21\x50\x53': {'ext': ['ps', 'eps'], 'desc': 'PostScript Document'},
    b'\xC5\xD0\xD3\xC6': {'ext': ['eps'], 'desc': 'Encapsulated PostScript'},
    b'\x38\x42\x50\x53': {'ext': ['psd'], 'desc': 'Adobe Photoshop Document'},
    b'\x46\x57\x53': {'ext': ['swf'], 'desc': 'Adobe Flash (Uncompressed)'},
    b'\x43\x57\x53': {'ext': ['swf'], 'desc': 'Adobe Flash (Compressed)'},
    b'\x5A\x57\x53': {'ext': ['swf'], 'desc': 'Adobe Flash (LZMA Compressed)'},
    b'{\\rtf1': {'ext': ['rtf'], 'desc': 'Rich Text Format'},
    b'\xDB\xA5\x2D\x00': {'ext': ['doc'], 'desc': 'Microsoft Word Document (Legacy)'},
    b'\xEC\xA5\xC1\x00': {'ext': ['doc'], 'desc': 'Microsoft Word Document (Legacy)'},
    b'\x09\x08\x06\x00\x00\x00\x10\x00': {'ext': ['xls'], 'desc': 'Microsoft Excel Spreadsheet (Legacy)'},
    b'\xFD\xFF\xFF\xFF': {'ext': ['xls'], 'desc': 'Microsoft Excel Spreadsheet (Legacy)'},
    b'\x0F\x00\xE8\x03': {'ext': ['ppt'], 'desc': 'Microsoft PowerPoint Presentation (Legacy)'},
    b'\xA0\x46\x1D\xF0': {'ext': ['ppt'], 'desc': 'Microsoft PowerPoint Presentation (Legacy)'},
    
    # eBook and publishing formats
    b'TPZ3': {'ext': ['tpz'], 'desc': 'Amazon Topaz eBook'},
    b'BOOKMOBI': {'ext': ['azw', 'mobi'], 'desc': 'Amazon Kindle eBook'},
    b'\x1A\x45\xDF\xA3\x93\x42\x82\x88': {'ext': ['epub'], 'desc': 'EPUB eBook'},
    
    # Text encoding formats
    b'\xEF\xBB\xBF': {'ext': ['txt', 'csv', 'json', 'xml'], 'desc': 'UTF-8 BOM Text File'},
    b'\xFF\xFE': {'ext': ['txt'], 'desc': 'UTF-16 LE BOM Text File'},
    b'\xFE\xFF': {'ext': ['txt'], 'desc': 'UTF-16 BE BOM Text File'},
    b'\xFF\xFE\x00\x00': {'ext': ['txt'], 'desc': 'UTF-32 Little Endian Text'},
    b'\x00\x00\xFE\xFF': {'ext': ['txt'], 'desc': 'UTF-32 Big Endian Text'},
    
    # Scientific and academic formats
    b'\\documentclass': {'ext': ['tex'], 'desc': 'LaTeX Document'},
    b'\\begin{document}': {'ext': ['tex'], 'desc': 'LaTeX Document'},
    b'%!PS-Adobe': {'ext': ['ps', 'eps'], 'desc': 'PostScript/EPS Document'},
    
    # Help and documentation formats
    b'ITSF': {'ext': ['chm'], 'desc': 'Microsoft Compiled HTML Help'},
    b'LN\x02\x00': {'ext': ['hlp'], 'desc': 'Windows Help File'},
    b'?_\x03\x00': {'ext': ['hlp'], 'desc': 'Windows Help File'},
    
    # Database files (Critical for forensic analysis)
    b'SQLite format 3\x00': {'ext': ['db', 'sqlite', 'sqlite3'], 'desc': 'SQLite Database'},
    b'\x53\x51\x4C\x69\x74\x65\x20\x66': {'ext': ['db', 'sqlite', 'sqlite3'], 'desc': 'SQLite Database'},
    b'\x00\x01\x00\x00\x53\x74\x61\x6E\x64\x61\x72\x64\x20\x4A\x65\x74\x20\x44\x42': {'ext': ['mdb'], 'desc': 'Microsoft Access Database'},
    b'\x4D\x53\x49\x53\x41\x4D': {'ext': ['mdb'], 'desc': 'Microsoft Access Database (MSISAM)'},
    
    # Oracle database files
    b'\x00\x22\x00\x00': {'ext': ['dbf'], 'desc': 'dBASE Database'},
    b'\x03\x00\x00\x00': {'ext': ['dbf'], 'desc': 'dBASE III Database'},
    b'\x04\x00\x00\x00': {'ext': ['dbf'], 'desc': 'dBASE IV Database'},
    b'\x05\x00\x00\x00': {'ext': ['dbf'], 'desc': 'dBASE V Database'},
    b'\x30\x00\x00\x00': {'ext': ['dbf'], 'desc': 'Visual FoxPro Database'},
    b'\x43\x00\x00\x00': {'ext': ['dbf'], 'desc': 'dBASE IV with memo'},
    b'\x7B\x00\x00\x00': {'ext': ['dbf'], 'desc': 'dBASE IV with SQL table'},
    b'\x83\x00\x00\x00': {'ext': ['dbf'], 'desc': 'dBASE III+ with memo'},
    b'\x8B\x00\x00\x00': {'ext': ['dbf'], 'desc': 'dBASE IV with memo'},
    b'\x8E\x00\x00\x00': {'ext': ['dbf'], 'desc': 'dBASE IV with SQL table'},
    b'\xF5\x00\x00\x00': {'ext': ['dbf'], 'desc': 'FoxPro 2.x with memo'},
    b'\xFB\x00\x00\x00': {'ext': ['dbf'], 'desc': 'FoxBASE'},
    
    # MySQL database files
    b'\xFE\x01\x00\x00': {'ext': ['myi'], 'desc': 'MySQL MyISAM Index'},
    b'\xFE\x01\x00\x01': {'ext': ['myd'], 'desc': 'MySQL MyISAM Data'},
    
    # PostgreSQL database files
    b'PGDMP': {'ext': ['dump'], 'desc': 'PostgreSQL Database Dump'},
    
    # Microsoft SQL Server files
    b'\x01\x0F\x00\x00': {'ext': ['mdf'], 'desc': 'Microsoft SQL Server Database'},
    
    # Berkeley DB files
    b'\x00\x05\x31\x62': {'ext': ['db'], 'desc': 'Berkeley DB (Hash)'},
    b'\x00\x05\x31\x63': {'ext': ['db'], 'desc': 'Berkeley DB (Btree)'},
    b'\x00\x05\x31\x64': {'ext': ['db'], 'desc': 'Berkeley DB (Queue)'},
    b'\x00\x05\x31\x65': {'ext': ['db'], 'desc': 'Berkeley DB (Recno)'},
    
    # Other database formats
    b'GDBM': {'ext': ['gdbm'], 'desc': 'GNU Database Manager'},
    b'TDB file': {'ext': ['tdb'], 'desc': 'Trivial Database'},
    b'LMDB': {'ext': ['mdb'], 'desc': 'Lightning Memory-Mapped Database'},
    b'CDB\x00': {'ext': ['cdb'], 'desc': 'Constant Database'},
    
    # Embedded database formats
    b'** This file contains an SQLite': {'ext': ['db'], 'desc': 'SQLite Database (Text Header)'},
    b'HSQLDB': {'ext': ['hsqldb'], 'desc': 'HSQLDB Database'},
    b'H2 Database': {'ext': ['h2'], 'desc': 'H2 Database'},
    
    # Programming language source files
    b'#!/usr/bin/python': {'ext': ['py'], 'desc': 'Python Script (shebang)'},
    b'#!/usr/bin/env python': {'ext': ['py'], 'desc': 'Python Script (env shebang)'},
    b'#!/bin/bash': {'ext': ['sh', 'bash'], 'desc': 'Bash Script'},
    b'#!/bin/sh': {'ext': ['sh'], 'desc': 'Shell Script'},
    b'<?php': {'ext': ['php'], 'desc': 'PHP Script'},
    b'<script': {'ext': ['js', 'html'], 'desc': 'JavaScript/HTML with Script'},
    
    # Development tools and IDEs
    b'\xCA\xFE\xBA\xBE': {'ext': ['class'], 'desc': 'Java Class File'},
    b'\xFE\xED\xFA\xCE': {'ext': [''], 'desc': 'Mach-O Binary (macOS)'},
    b'\xFE\xED\xFA\xCF': {'ext': [''], 'desc': 'Mach-O Binary 64-bit (macOS)'},
    b'\xCE\xFA\xED\xFE': {'ext': [''], 'desc': 'Mach-O Binary (reverse endian)'},
    b'\xCF\xFA\xED\xFE': {'ext': [''], 'desc': 'Mach-O Binary 64-bit (reverse endian)'},
    
    # Version control and project files
    b'gitdir: ': {'ext': ['git'], 'desc': 'Git Directory Reference'},
    b'[core]': {'ext': ['gitconfig'], 'desc': 'Git Configuration'},
    b'{\n  "name"': {'ext': ['json'], 'desc': 'JSON Package/Config File'},
    b'{\r\n  "name"': {'ext': ['json'], 'desc': 'JSON Package/Config File (CRLF)'},
    b'<project': {'ext': ['xml', 'proj'], 'desc': 'Project XML File'},
    
    # Container and virtualization
    b'\x1F\x8B\x08': {'ext': ['tar.gz', 'tgz'], 'desc': 'Gzipped TAR Archive'},
    b'FROM ': {'ext': ['dockerfile'], 'desc': 'Docker File'},
    b'version: ': {'ext': ['yml', 'yaml'], 'desc': 'YAML Configuration'},
    b'apiVersion:': {'ext': ['yml', 'yaml'], 'desc': 'Kubernetes YAML'},
    
    # Image formats
    b'\xFF\xD8\xFF': {'ext': ['jpg', 'jpeg'], 'desc': 'JPEG Image'},
    b'\x89\x50\x4E\x47\x0D\x0A\x1A\x0A': {'ext': ['png'], 'desc': 'PNG Image'},
    b'\x47\x49\x46\x38\x37\x61': {'ext': ['gif'], 'desc': 'GIF Image (87a)'},
    b'\x47\x49\x46\x38\x39\x61': {'ext': ['gif'], 'desc': 'GIF Image (89a)'},
    b'\x42\x4D': {'ext': ['bmp'], 'desc': 'BMP Image'},
    b'\x00\x00\x01\x00': {'ext': ['ico'], 'desc': 'Windows Icon'},
    b'\x00\x00\x02\x00': {'ext': ['cur'], 'desc': 'Windows Cursor'},
    b'\x52\x49\x46\x46': {'ext': ['wav', 'avi', 'webp'], 'desc': 'RIFF Container (WAV/AVI/WebP)'},
    b'WEBP': {'ext': ['webp'], 'desc': 'WebP Image'},
    b'\x49\x49\x2A\x00': {'ext': ['tiff', 'tif'], 'desc': 'TIFF Image (Little Endian)'},
    b'\x4D\x4D\x00\x2A': {'ext': ['tiff', 'tif'], 'desc': 'TIFF Image (Big Endian)'},
    b'\x00\x00\x00\x0C\x4A\x58\x4C\x20\x0D\x0A\x87\x0A': {'ext': ['jxl'], 'desc': 'JPEG XL Image'},
    b'\xFF\x0A': {'ext': ['jxr'], 'desc': 'JPEG XR Image'},
    b'\x76\x2F\x31\x01': {'ext': ['exr'], 'desc': 'OpenEXR Image'},
    b'8BPS': {'ext': ['psd'], 'desc': 'Adobe Photoshop Document'},
    b'FORM': {'ext': ['iff'], 'desc': 'IFF Image'},
    b'\x59\xA6\x6A\x95': {'ext': ['ras'], 'desc': 'Sun Raster Image'},
    b'\x01\xDA\x01\x01\x00\x03': {'ext': ['rgb'], 'desc': 'Silicon Graphics Image'},
    b'\x53\x44\x50\x58': {'ext': ['dpx'], 'desc': 'Digital Picture Exchange'},
    b'P1\n': {'ext': ['pbm'], 'desc': 'Portable Bitmap (ASCII)'},
    b'P2\n': {'ext': ['pgm'], 'desc': 'Portable Graymap (ASCII)'},
    b'P3\n': {'ext': ['ppm'], 'desc': 'Portable Pixmap (ASCII)'},
    b'P4\n': {'ext': ['pbm'], 'desc': 'Portable Bitmap (Binary)'},
    b'P5\n': {'ext': ['pgm'], 'desc': 'Portable Graymap (Binary)'},
    b'P6\n': {'ext': ['ppm'], 'desc': 'Portable Pixmap (Binary)'},
    b'P7\n': {'ext': ['pam'], 'desc': 'Portable Arbitrary Map'},
    b'\x0A\x05\x01\x08': {'ext': ['pcx'], 'desc': 'PCX Image'},
    b'qoif': {'ext': ['qoi'], 'desc': 'Quite OK Image Format'},
    b'\x00\x00\x00\x14\x66\x74\x79\x70\x68\x65\x69\x63': {'ext': ['heic'], 'desc': 'HEIC Image'},
    b'\x00\x00\x00\x18\x66\x74\x79\x70\x68\x65\x69\x63': {'ext': ['heic'], 'desc': 'HEIC Image'},
    b'\x00\x00\x00\x20\x66\x74\x79\x70\x68\x65\x69\x63': {'ext': ['heic'], 'desc': 'HEIC Image'},
    b'\x00\x00\x00\x14\x66\x74\x79\x70\x6D\x69\x66\x31': {'ext': ['heif'], 'desc': 'HEIF Image'},
    b'\x00\x00\x00\x18\x66\x74\x79\x70\x6D\x69\x66\x31': {'ext': ['heif'], 'desc': 'HEIF Image'},
    b'\xFF\xFB': {'ext': ['mp3'], 'desc': 'MP3 Audio (MPEG-1 Layer 3)'},
    b'\xFF\xF3': {'ext': ['mp3'], 'desc': 'MP3 Audio (MPEG-1 Layer 3)'},
    b'\xFF\xF2': {'ext': ['mp3'], 'desc': 'MP3 Audio (MPEG-1 Layer 3)'},
    
    # Audio/Video formats
    b'\xFF\xFB': {'ext': ['mp3'], 'desc': 'MP3 Audio (MPEG-1 Layer 3)'},
    b'\xFF\xF3': {'ext': ['mp3'], 'desc': 'MP3 Audio (MPEG-1 Layer 3)'},
    b'\xFF\xF2': {'ext': ['mp3'], 'desc': 'MP3 Audio (MPEG-1 Layer 3)'},
    b'\x49\x44\x33': {'ext': ['mp3'], 'desc': 'MP3 Audio (ID3 tag)'},
    b'OggS': {'ext': ['ogg', 'ogv', 'oga'], 'desc': 'Ogg Media'},
    b'fLaC': {'ext': ['flac'], 'desc': 'FLAC Audio'},
    b'\x1A\x45\xDF\xA3': {'ext': ['mkv', 'webm'], 'desc': 'Matroska/WebM Video'},
    
    # Video formats
    b'\x00\x00\x00\x14ftypmp41': {'ext': ['mp4'], 'desc': 'MP4 Video (MPEG-4 Part 14)'},
    b'\x00\x00\x00\x18ftypmp41': {'ext': ['mp4'], 'desc': 'MP4 Video (MPEG-4 Part 14)'},
    b'\x00\x00\x00\x1Cftypmp41': {'ext': ['mp4'], 'desc': 'MP4 Video (MPEG-4 Part 14)'},
    b'\x00\x00\x00\x20ftypmp41': {'ext': ['mp4'], 'desc': 'MP4 Video (MPEG-4 Part 14)'},
    b'\x00\x00\x00\x14ftypisom': {'ext': ['mp4'], 'desc': 'MP4 Video (ISO Base)'},
    b'\x00\x00\x00\x18ftypisom': {'ext': ['mp4'], 'desc': 'MP4 Video (ISO Base)'},
    b'\x00\x00\x00\x1Cftypisom': {'ext': ['mp4'], 'desc': 'MP4 Video (ISO Base)'},
    b'\x00\x00\x00\x20ftypisom': {'ext': ['mp4'], 'desc': 'MP4 Video (ISO Base)'},
    b'\x00\x00\x00\x14ftypM4V ': {'ext': ['m4v'], 'desc': 'iTunes Video'},
    b'\x00\x00\x00\x18ftypM4V ': {'ext': ['m4v'], 'desc': 'iTunes Video'},
    b'\x00\x00\x00\x14ftypM4A ': {'ext': ['m4a'], 'desc': 'iTunes Audio'},
    b'\x00\x00\x00\x18ftypM4A ': {'ext': ['m4a'], 'desc': 'iTunes Audio'},
    b'\x00\x00\x00\x14ftypqt  ': {'ext': ['mov'], 'desc': 'QuickTime Movie'},
    b'\x00\x00\x00\x18ftypqt  ': {'ext': ['mov'], 'desc': 'QuickTime Movie'},
    b'\x00\x00\x00\x14ftyp3gp4': {'ext': ['3gp'], 'desc': '3GPP Video'},
    b'\x00\x00\x00\x14ftyp3gp5': {'ext': ['3gp'], 'desc': '3GPP Video'},
    b'\x00\x00\x00\x14ftyp3g2a': {'ext': ['3g2'], 'desc': '3GPP2 Video'},
    b'\x00\x00\x00\x14ftyp3g2b': {'ext': ['3g2'], 'desc': '3GPP2 Video'},
    b'\x00\x00\x00\x14ftyp3g2c': {'ext': ['3g2'], 'desc': '3GPP2 Video'},
    b'FLV\x01': {'ext': ['flv'], 'desc': 'Flash Video'},
    b'\x30\x26\xB2\x75\x8E\x66\xCF\x11': {'ext': ['wmv', 'asf'], 'desc': 'Windows Media Video/ASF'},
    b'\x00\x00\x01\xBA': {'ext': ['mpg', 'mpeg'], 'desc': 'MPEG Video (Program Stream)'},
    b'\x00\x00\x01\xB3': {'ext': ['mpg', 'mpeg'], 'desc': 'MPEG Video (Sequence Header)'},
    b'\x47': {'ext': ['ts'], 'desc': 'MPEG Transport Stream'},
    b'RIFF': {'ext': ['avi', 'wav', 'webp'], 'desc': 'RIFF Container (AVI/WAV/WebP)'},
    
    # Additional audio formats
    b'FORM': {'ext': ['aiff', 'aif'], 'desc': 'Audio Interchange File Format'},
    b'\x2E\x73\x6E\x64': {'ext': ['au', 'snd'], 'desc': 'Sun/NeXT Audio'},
    b'dns.': {'ext': ['au'], 'desc': 'Sun Audio (reverse)'},
    b'wvpk': {'ext': ['wv'], 'desc': 'WavPack Audio'},
    b'MAC ': {'ext': ['ape'], 'desc': 'Monkey\'s Audio'},
    b'TTA1': {'ext': ['tta'], 'desc': 'True Audio'},
    b'\x00\x00\x00\x20ftypM4A ': {'ext': ['m4a'], 'desc': 'MPEG-4 Audio'},
    b'\x00\x00\x00\x1CftypM4A ': {'ext': ['m4a'], 'desc': 'MPEG-4 Audio'},
    b'ADIF': {'ext': ['aac'], 'desc': 'AAC Audio (ADIF)'},
    b'\xFF\xF1': {'ext': ['aac'], 'desc': 'AAC Audio (ADTS)'},
    b'\xFF\xF9': {'ext': ['aac'], 'desc': 'AAC Audio (ADTS)'},
    b'#!AMR\n': {'ext': ['amr'], 'desc': 'Adaptive Multi-Rate Audio'},
    b'#!AMR-WB\n': {'ext': ['awb'], 'desc': 'Adaptive Multi-Rate Wideband Audio'},
    b'\x43\x44\x30\x30\x31': {'ext': ['cda'], 'desc': 'CD Audio Track'},
    b'\x00\x00\x00\x18\x66\x74\x79\x70': {'ext': ['mp4'], 'desc': 'MP4 Video'},
    b'\x00\x00\x00\x20\x66\x74\x79\x70': {'ext': ['mp4'], 'desc': 'MP4 Video'},
    
    # Executable and binary formats
    b'\x4D\x5A': {'ext': ['exe', 'dll', 'sys', 'scr', 'com', 'pif'], 'desc': 'Windows Executable/DLL/System'},
    b'\x7F\x45\x4C\x46': {'ext': ['elf', 'so', 'bin'], 'desc': 'Linux/Unix Executable/Shared Library'},
    b'\xFE\xED\xFA\xCE': {'ext': ['macho', 'dylib'], 'desc': 'macOS Executable/Library (32-bit)'},
    b'\xFE\xED\xFA\xCF': {'ext': ['macho', 'dylib'], 'desc': 'macOS Executable/Library (64-bit)'},
    b'\xCE\xFA\xED\xFE': {'ext': ['macho'], 'desc': 'macOS Executable (32-bit, reverse)'},
    b'\xCF\xFA\xED\xFE': {'ext': ['macho'], 'desc': 'macOS Executable (64-bit, reverse)'},
    b'\xCA\xFE\xBA\xBE': {'ext': ['class', 'jar'], 'desc': 'Java Class File/Universal Binary'},
    b'\xCA\xFE\xD0\x0D': {'ext': ['class'], 'desc': 'Java Class File (Alternate)'},
    
    # Additional Windows executable formats
    b'NE': {'ext': ['exe', 'dll'], 'desc': 'Windows New Executable (16-bit)'},
    b'LE': {'ext': ['exe', 'dll'], 'desc': 'Windows Linear Executable'},
    b'LX': {'ext': ['exe', 'dll'], 'desc': 'OS/2 Linear Executable'},
    b'PE\x00\x00': {'ext': ['exe', 'dll'], 'desc': 'Windows Portable Executable'},
    
    # DOS and legacy formats
    b'\xE9': {'ext': ['com'], 'desc': 'DOS COM Executable (JMP)'},
    b'\xEB': {'ext': ['com'], 'desc': 'DOS COM Executable (JMP short)'},
    b'\xB8': {'ext': ['com'], 'desc': 'DOS COM Executable (MOV AX)'},
    b'\xB4': {'ext': ['com'], 'desc': 'DOS COM Executable (MOV AH)'},
    
    # Script and bytecode formats
    b'\x03\xF3\x0D\x0A': {'ext': ['pyc'], 'desc': 'Python Bytecode (3.0)'},
    b'\x6F\x0D\x0D\x0A': {'ext': ['pyc'], 'desc': 'Python Bytecode (2.7)'},
    b'\xEE\x0C\x0D\x0A': {'ext': ['pyc'], 'desc': 'Python Bytecode (2.6)'},
    b'\xD1\xF2\x0D\x0A': {'ext': ['pyc'], 'desc': 'Python Bytecode (2.5)'},
    b'\x87\xC6\x0D\x0A': {'ext': ['pyc'], 'desc': 'Python Bytecode (2.4)'},
    b'\x3B\xF2\x0D\x0A': {'ext': ['pyc'], 'desc': 'Python Bytecode (2.3)'},
    b'\x2D\xED\x0D\x0A': {'ext': ['pyc'], 'desc': 'Python Bytecode (2.2)'},
    b'\x78\x9C': {'ext': ['pyo'], 'desc': 'Python Optimized Bytecode'},
    
    # .NET and managed code
    b'BSJB': {'ext': ['dll', 'exe'], 'desc': '.NET Assembly Metadata'},
    
    # Mobile and embedded formats
    b'dex\n': {'ext': ['dex'], 'desc': 'Android Dalvik Executable'},
    b'dey\n': {'ext': ['dey'], 'desc': 'Android Dalvik Executable (Optimized)'},
    
    # Firmware and embedded systems
    b'ANDROID!': {'ext': ['img'], 'desc': 'Android Boot Image'},
    b'CHROMEOS': {'ext': ['img'], 'desc': 'Chrome OS Image'},
    
    # Game and multimedia executables
    b'UNREAL': {'ext': ['exe'], 'desc': 'Unreal Engine Executable'},
    b'Unity': {'ext': ['exe'], 'desc': 'Unity Engine Executable'},
    b'RGSS': {'ext': ['exe'], 'desc': 'RPG Maker Executable'},
    
    # Debugging and analysis formats
    b'CORE': {'ext': ['core'], 'desc': 'Unix Core Dump'},
    
    # Archive and compression formats
    b'PK\x03\x04': {'ext': ['zip', 'jar', 'war', 'ear', 'apk', 'ipa'], 'desc': 'ZIP Archive/Java Archive/Android APK'},
    b'PK\x05\x06': {'ext': ['zip'], 'desc': 'ZIP Archive (Empty)'},
    b'PK\x07\x08': {'ext': ['zip'], 'desc': 'ZIP Archive (Spanned)'},
    b'PK\x30\x30': {'ext': ['zip'], 'desc': 'ZIP Archive (WinZip)'},
    b'Rar!\x1A\x07\x00': {'ext': ['rar'], 'desc': 'RAR Archive (v1.5-4.x)'},
    b'Rar!\x1A\x07\x01\x00': {'ext': ['rar'], 'desc': 'RAR Archive (v5.0+)'},
    b'\x52\x61\x72\x21\x1A\x07': {'ext': ['rar'], 'desc': 'RAR Archive'},
    b'\x37\x7A\xBC\xAF\x27\x1C': {'ext': ['7z'], 'desc': '7-Zip Archive'},
    b'\x75\x73\x74\x61\x72': {'ext': ['tar'], 'desc': 'TAR Archive'},
    b'ustar\x00': {'ext': ['tar'], 'desc': 'TAR Archive (POSIX)'},
    b'ustar  \x00': {'ext': ['tar'], 'desc': 'TAR Archive (GNU)'},
    b'\x1F\x8B': {'ext': ['gz', 'gzip', 'tgz'], 'desc': 'GZIP Compressed Archive'},
    b'\x1F\x9D': {'ext': ['z'], 'desc': 'Unix Compress (LZW)'},
    b'\x1F\xA0': {'ext': ['z'], 'desc': 'Unix Compress (LZH)'},
    b'\x42\x5A\x68': {'ext': ['bz2', 'tbz2'], 'desc': 'BZIP2 Compressed Archive'},
    b'BZh': {'ext': ['bz2'], 'desc': 'BZIP2 Archive'},
    b'\xFD\x37\x7A\x58\x5A\x00': {'ext': ['xz'], 'desc': 'XZ Compressed Archive'},
    b'\x28\xB5\x2F\xFD': {'ext': ['zst'], 'desc': 'Zstandard Archive'},
    b'\x04\x22\x4D\x18': {'ext': ['lz4'], 'desc': 'LZ4 Compressed Archive'},
    b'LZIP': {'ext': ['lz'], 'desc': 'LZIP Compressed Archive'},
    b'\x89\x4C\x5A\x4F\x00\x0D\x0A\x1A\x0A': {'ext': ['lzo'], 'desc': 'LZO Compressed Archive'},
    
    # Cabinet and installer formats
    b'MSCF': {'ext': ['cab'], 'desc': 'Microsoft Cabinet Archive'},
    b'ISc(': {'ext': ['cab'], 'desc': 'InstallShield Cabinet'},
    b'SZDD': {'ext': ['cab'], 'desc': 'Microsoft Compressed File'},
    b'KWAJ': {'ext': ['cab'], 'desc': 'Microsoft Compressed File'},
    b'MZ\x90\x00\x03': {'ext': ['exe'], 'desc': 'Self-Extracting Archive'},
    
    # Disk image formats
    b'MSDOS5.0': {'ext': ['img'], 'desc': 'Disk Image'},
    b'\xEB\x3C\x90': {'ext': ['img'], 'desc': 'FAT12/16 Disk Image'},
    b'\xEB\x58\x90': {'ext': ['img'], 'desc': 'FAT32 Disk Image'},
    b'conectix': {'ext': ['vhd'], 'desc': 'Virtual Hard Disk'},
    b'vhdx': {'ext': ['vhdx'], 'desc': 'Virtual Hard Disk v2'},
    b'KDMV': {'ext': ['vmdk'], 'desc': 'VMware Virtual Disk'},
    b'QFI\xFB': {'ext': ['qcow'], 'desc': 'QEMU Copy-On-Write Disk'},
    b'QFI\xFB\x00\x00\x00\x03': {'ext': ['qcow2'], 'desc': 'QEMU Copy-On-Write Disk v2'},
    b'VDI\x01\x00\x00\x00': {'ext': ['vdi'], 'desc': 'VirtualBox Disk Image'},
    
    # Legacy archive formats
    b'\x60\xEA': {'ext': ['arj'], 'desc': 'ARJ Archive'},
    b'LHA\'s SFX': {'ext': ['lha', 'lzh'], 'desc': 'LHA/LZH Archive'},
    b'-lh0-': {'ext': ['lha', 'lzh'], 'desc': 'LHA Archive (No compression)'},
    b'-lh1-': {'ext': ['lha', 'lzh'], 'desc': 'LHA Archive (LZ77)'},
    b'-lh5-': {'ext': ['lha', 'lzh'], 'desc': 'LHA Archive (LZ77)'},
    b'UC2\x1A': {'ext': ['uc2'], 'desc': 'UltraCompressor II Archive'},
    b'ZOO ': {'ext': ['zoo'], 'desc': 'ZOO Archive'},
    b'\x1A\x0B': {'ext': ['pak'], 'desc': 'PAK Archive'},
    b'HLSQ': {'ext': ['sqz'], 'desc': 'HLSQ Archive'},
    
    # Certificate and security files
    b'\x30\x82': {'ext': ['cer', 'crt', 'der'], 'desc': 'DER Certificate'},
    b'-----BEGIN CERTIFICATE-----': {'ext': ['pem', 'crt'], 'desc': 'PEM Certificate'},
    b'-----BEGIN PRIVATE KEY-----': {'ext': ['pem', 'key'], 'desc': 'PEM Private Key'},
    b'-----BEGIN RSA PRIVATE KEY-----': {'ext': ['pem', 'key'], 'desc': 'PEM RSA Private Key'},
    b'ssh-rsa ': {'ext': ['pub'], 'desc': 'SSH Public Key'},
    b'ssh-ed25519 ': {'ext': ['pub'], 'desc': 'SSH ED25519 Public Key'},
    
    # Web and markup formats
    b'\x3C\x3F\x78\x6D\x6C': {'ext': ['xml'], 'desc': 'XML Document'},
    b'\x3C\x68\x74\x6D\x6C': {'ext': ['html', 'htm'], 'desc': 'HTML Document'},
    b'<!DOCTYPE html': {'ext': ['html', 'htm'], 'desc': 'HTML5 Document'},
    b'<!doctype html': {'ext': ['html', 'htm'], 'desc': 'HTML5 Document (lowercase)'},
    b'\xEF\xBB\xBF': {'ext': ['txt', 'csv', 'json', 'xml'], 'desc': 'UTF-8 BOM Text File'},
    b'\xFF\xFE': {'ext': ['txt'], 'desc': 'UTF-16 LE BOM Text File'},
    b'\xFE\xFF': {'ext': ['txt'], 'desc': 'UTF-16 BE BOM Text File'},
    
    # Configuration and data files
    b'[': {'ext': ['ini', 'cfg', 'conf'], 'desc': 'INI Configuration File'},
    b'#!': {'ext': ['sh', 'py', 'pl', 'rb'], 'desc': 'Script with Shebang'},
    b'import ': {'ext': ['py'], 'desc': 'Python Source File'},
    b'from ': {'ext': ['py'], 'desc': 'Python Source File'},
    b'def ': {'ext': ['py'], 'desc': 'Python Source File'},
    b'class ': {'ext': ['py', 'java', 'cpp', 'cs'], 'desc': 'Object-Oriented Source File'},
    b'function ': {'ext': ['js', 'php'], 'desc': 'JavaScript/PHP Source File'},
    b'var ': {'ext': ['js'], 'desc': 'JavaScript Source File'},
    b'const ': {'ext': ['js', 'ts'], 'desc': 'JavaScript/TypeScript Source File'},
    b'let ': {'ext': ['js', 'ts'], 'desc': 'JavaScript/TypeScript Source File'},
    
    # Virtual machine and disk images
    b'VMDK': {'ext': ['vmdk'], 'desc': 'VMware Virtual Disk'},
    b'conectix': {'ext': ['vhd'], 'desc': 'Virtual Hard Disk'},
    b'vhdx': {'ext': ['vhdx'], 'desc': 'Virtual Hard Disk v2'},
    b'QFI\xFB': {'ext': ['qcow2'], 'desc': 'QEMU Copy-On-Write v2'},
    b'VDI\x7F': {'ext': ['vdi'], 'desc': 'VirtualBox Disk Image'},
    
    # Font files
    b'\x00\x01\x00\x00': {'ext': ['ttf'], 'desc': 'TrueType Font'},
    b'OTTO': {'ext': ['otf'], 'desc': 'OpenType Font'},
    b'wOFF': {'ext': ['woff'], 'desc': 'Web Open Font Format'},
    b'wOF2': {'ext': ['woff2'], 'desc': 'Web Open Font Format 2'},
    
    # Backup and system files
    b'MDMP': {'ext': ['dmp'], 'desc': 'Windows Memory Dump'},
    b'PAGEDU': {'ext': ['dmp'], 'desc': 'Windows Page File Dump'},
    b'regf': {'ext': ['reg', 'dat'], 'desc': 'Windows Registry Hive'},
    b'REGF': {'ext': ['reg', 'dat'], 'desc': 'Windows Registry Hive'},
    b'\xFF\xFE#': {'ext': ['reg'], 'desc': 'Windows Registry Export (Unicode)'},
    b'Windows Registry Editor': {'ext': ['reg'], 'desc': 'Windows Registry Export'},
    
    # Windows forensic artifacts and system files
    b'SCCA': {'ext': ['pf'], 'desc': 'Windows Prefetch File'},
    b'\x11\x00\x00\x00\x53\x43\x43\x41': {'ext': ['pf'], 'desc': 'Windows Prefetch File'},
    b'regf': {'ext': ['reg', 'dat'], 'desc': 'Windows Registry Hive'},
    b'REGF': {'ext': ['reg', 'dat'], 'desc': 'Windows Registry Hive'},
    b'Elf-File': {'ext': ['evtx'], 'desc': 'Windows Event Log'},
    b'LfLe': {'ext': ['evtx'], 'desc': 'Windows Event Log'},
    b'\x30\x00\x00\x00\x4C\x66\x4C\x65': {'ext': ['evtx'], 'desc': 'Windows Event Log'},
    b'hbin': {'ext': ['dat'], 'desc': 'Windows Registry Hive Block'},
    b'PAGEFILEPAGE': {'ext': ['sys'], 'desc': 'Windows Page File'},
    b'HIBERFIL': {'ext': ['sys'], 'desc': 'Windows Hibernation File'},
    b'SWAPFILE': {'ext': ['sys'], 'desc': 'Windows Swap File'},
    b'MEMORY.DMP': {'ext': ['dmp'], 'desc': 'Windows Memory Dump'},
    b'PAGEDUMP': {'ext': ['dmp'], 'desc': 'Windows Page Dump'},
    b'DMP\x00': {'ext': ['dmp'], 'desc': 'Windows Crash Dump'},
    b'\x4D\x44\x4D\x50\x93\xA7': {'ext': ['dmp'], 'desc': 'Windows Minidump'},
    
    # Windows system and configuration files
    b'[version]': {'ext': ['inf'], 'desc': 'Windows Setup Information'},
    b'[autorun]': {'ext': ['inf'], 'desc': 'Windows Autorun Information'},
    b'Windows Registry Editor': {'ext': ['reg'], 'desc': 'Windows Registry Export'},
    b'REGEDIT4': {'ext': ['reg'], 'desc': 'Windows Registry Export (Legacy)'},
    
    # NTFS and file system artifacts
    b'FILE0': {'ext': ['mft'], 'desc': 'NTFS Master File Table'},
    b'INDX': {'ext': ['idx'], 'desc': 'NTFS Index'},
    b'BAAD': {'ext': ['bad'], 'desc': 'NTFS Bad Cluster File'},
    b'HOLE': {'ext': ['hole'], 'desc': 'NTFS Sparse File'},
    b'CHKD': {'ext': ['chk'], 'desc': 'CHKDSK Recovery File'},
    
    # Windows shortcuts and links
    b'\x4C\x00\x00\x00\x01\x14\x02\x00': {'ext': ['lnk'], 'desc': 'Windows Shortcut'},
    b'L\x00\x00\x00': {'ext': ['lnk'], 'desc': 'Windows Shortcut (Alternative)'},
    
    # Windows thumbnail cache
    b'CMMM': {'ext': ['db'], 'desc': 'Windows Thumbnail Cache'},
    b'IMMM': {'ext': ['db'], 'desc': 'Windows Thumbnail Cache'},
    
    # Windows search and indexing
    b'MSSearch': {'ext': ['edb'], 'desc': 'Windows Search Database'},
    b'JET\x00': {'ext': ['edb'], 'desc': 'Extensible Storage Engine Database'},
    
    # Windows event tracing
    b'WMI\x00': {'ext': ['etl'], 'desc': 'Windows Event Trace Log'},
    b'ETL\x00': {'ext': ['etl'], 'desc': 'Windows Event Trace Log'},
    
    # Windows performance monitoring
    b'PerfMon': {'ext': ['blg'], 'desc': 'Windows Performance Monitor Log'},
    b'PDH\x01': {'ext': ['blg'], 'desc': 'Windows Performance Data Helper Log'},
    
    # Windows backup and restore
    b'WBCAT': {'ext': ['wbcat'], 'desc': 'Windows Backup Catalog'},
    b'Microsoft Tape Format': {'ext': ['bkf'], 'desc': 'Windows Backup File'},
    
    # Windows security and authentication
    b'SECURITY': {'ext': ['dat'], 'desc': 'Windows Security Registry Hive'},
    b'SAM\x00': {'ext': ['dat'], 'desc': 'Windows SAM Registry Hive'},
    b'SYSTEM': {'ext': ['dat'], 'desc': 'Windows System Registry Hive'},
    b'SOFTWARE': {'ext': ['dat'], 'desc': 'Windows Software Registry Hive'},
    b'NTUSER': {'ext': ['dat'], 'desc': 'Windows User Registry Hive'},
    
    # Network and communication
    b'\xD4\xC3\xB2\xA1': {'ext': ['pcap'], 'desc': 'PCAP Network Capture'},
    b'\xA1\xB2\xC3\xD4': {'ext': ['pcap'], 'desc': 'PCAP Network Capture (swapped)'},
    b'\x0A\x0D\x0D\x0A': {'ext': ['pcapng'], 'desc': 'PCAP-NG Network Capture'},
    
    # Cryptocurrency and blockchain
    b'\xF9\xBE\xB4\xD9': {'ext': ['dat'], 'desc': 'Bitcoin Block Data'},
    b'wallet': {'ext': ['dat'], 'desc': 'Cryptocurrency Wallet'},
    
    # Development artifacts
    b'node_modules': {'ext': [''], 'desc': 'Node.js Dependencies Directory'},
    b'__pycache__': {'ext': [''], 'desc': 'Python Cache Directory'},
    b'.git': {'ext': [''], 'desc': 'Git Repository Directory'},
    b'.svn': {'ext': [''], 'desc': 'Subversion Repository Directory'},
    b'Thumbs.db': {'ext': ['db'], 'desc': 'Windows Thumbnail Cache'},
    b'desktop.ini': {'ext': ['ini'], 'desc': 'Windows Desktop Configuration'},
}


class FileSignatureDetector:
    """
    Advanced file signature detection system for forensic analysis.
    
    This class provides comprehensive file type identification based on:
    - Magic bytes (file signatures) detection with 310+ signatures
    - Multi-offset signature scanning for complex file formats
    - Text-based heuristic analysis for scripts and configuration files
    - File extension hints as fallback mechanism
    - Robust error handling for forensic environments
    
    Supported File Categories:
        - Microsoft Office documents (legacy and modern formats)
        - Multimedia files (video, audio, images)
        - Windows forensic artifacts (registry hives, memory dumps, NTFS)
        - Archive and compression formats (ZIP, RAR, 7-Zip, TAR, etc.)
        - Database files (SQLite, Access, MySQL, PostgreSQL, etc.)
        - Executable and binary formats (Windows, Linux, macOS, mobile)
        - Development artifacts and configuration files
        - Network capture files and forensic tools output
    
    Features:
        - Supports 310+ file signatures for comprehensive detection
        - Handles Windows forensic artifacts and system files
        - Multi-fallback file reading methods (Windows API, Python, PowerShell)
        - Forensic-grade error handling for corrupted files
        - Optimized for Windows environments and forensic workflows
        - Text-based heuristic detection for scripts and configuration files
    
    Example:
        >>> detector = FileSignatureDetector()
        >>> signature, extension = detector.detect_file_signature("suspicious_file.bin")
        >>> print(f"File type: {signature} [{extension}]")
        
        >>> # Get list of all supported signatures
        >>> signatures = detector.list_supported_signatures()
        >>> print(f"Supports {len(signatures)} file types")
    """
    
    def __init__(self):
        """Initialize the file signature detector."""
        self._init_windows_api()
    
    def detect_file_signature(self, file_path: str) -> Tuple[str, str]:
        """
        Enhanced file type detection based on file signature (magic bytes) with multi-offset support.
        
        Args:
            file_path (str): Path to the file to analyze
            
        Returns:
            Tuple[str, str]: (Signature description, File extension) or ("Unknown", "")
        """
        try:
            # Check if file exists first
            if not os.path.exists(file_path):
                return "File not found", ""
            
            # Check if file has content
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                return "Empty file", ""
            
            # Read more data for better detection (up to 512 bytes for complex signatures)
            read_size = min(512, file_size)
            file_data = None
            
            # Try multiple methods to read the file
            # Method 1: Try Windows API method
            try:
                file_data = self._read_file_with_windows_api(file_path, max_bytes=read_size)
            except Exception as e:
                logger.debug(f"Windows API read failed: {e}")
            
            # Method 2: Fallback to standard Python file reading
            if not file_data:
                try:
                    with open(file_path, 'rb') as f:
                        file_data = f.read(read_size)
                except Exception as e:
                    logger.debug(f"Standard file read failed: {e}")
            
            # Method 3: Try PowerShell method as last resort
            if not file_data:
                try:
                    file_data = self._read_file_with_powershell(file_path, max_bytes=read_size)
                except Exception as e:
                    logger.debug(f"PowerShell read failed: {e}")
            
            if not file_data:
                return "Cannot read file", ""
            
            # Enhanced signature detection with priority and context
            detected_signatures = []
            
            # Check against known signatures with different strategies
            for signature, info in FILE_SIGNATURES.items():
                # Strategy 1: Exact match at beginning
                if file_data.startswith(signature):
                    detected_signatures.append((info['desc'], info['ext'][0], 'exact_start', len(signature)))
                    continue
                
                # Strategy 2: Check for signature anywhere in first 64 bytes (for offset signatures)
                if len(signature) <= 32:  # Only for reasonable signature lengths
                    for offset in range(min(64, len(file_data) - len(signature) + 1)):
                        if file_data[offset:offset + len(signature)] == signature:
                            detected_signatures.append((info['desc'], info['ext'][0], f'offset_{offset}', len(signature)))
                            break
            
            # Additional heuristic checks for text-based files
            if not detected_signatures:
                detected_signatures.extend(self._detect_text_based_signatures(file_data, file_path))
            
            # Return the best match (prioritize exact start matches, then longer signatures)
            if detected_signatures:
                # Sort by: exact_start first, then by signature length (longer is better)
                detected_signatures.sort(key=lambda x: (x[2] != 'exact_start', -x[3]))
                return detected_signatures[0][0], detected_signatures[0][1]
                
            # No match found - show hex for debugging
            hex_signature = file_data[:16].hex().upper()
            return f"Unknown (hex: {hex_signature})", ""
            
        except Exception as e:
            logger.error(f"Failed to detect file signature for {os.path.basename(file_path)}: {e}")
            return "Error", ""
    
    def _detect_text_based_signatures(self, file_data: bytes, file_path: str) -> List[Tuple[str, str, str, int]]:
        """
        Detect text-based file signatures using heuristics.
        
        Args:
            file_data (bytes): File content to analyze
            file_path (str): File path for extension hints
            
        Returns:
            List[Tuple[str, str, str, int]]: List of (description, extension, match_type, confidence)
        """
        signatures = []
        
        try:
            # Try to decode as text for heuristic analysis
            text_content = ""
            for encoding in ['utf-8', 'ascii', 'latin-1']:
                try:
                    text_content = file_data[:256].decode(encoding).lower()
                    break
                except UnicodeDecodeError:
                    continue
            
            if text_content:
                # Python file detection
                python_indicators = ['import ', 'from ', 'def ', 'class ', 'if __name__', 'print(']
                if any(indicator in text_content for indicator in python_indicators):
                    signatures.append(("Python Source File (heuristic)", "py", "heuristic", 50))
                
                # JavaScript/TypeScript detection
                js_indicators = ['function ', 'var ', 'let ', 'const ', 'console.log', '=>', 'require(']
                if any(indicator in text_content for indicator in js_indicators):
                    signatures.append(("JavaScript Source File (heuristic)", "js", "heuristic", 50))
                
                # HTML detection
                html_indicators = ['<html', '<head', '<body', '<div', '<script', '<!doctype']
                if any(indicator in text_content for indicator in html_indicators):
                    signatures.append(("HTML Document (heuristic)", "html", "heuristic", 50))
                
                # CSS detection
                css_indicators = ['{', '}', ':', ';', 'color:', 'font-', 'margin:', 'padding:']
                css_count = sum(1 for indicator in css_indicators if indicator in text_content)
                if css_count >= 3:
                    signatures.append(("CSS Stylesheet (heuristic)", "css", "heuristic", 40))
                
                # JSON detection
                if text_content.strip().startswith('{') and '"' in text_content and ':' in text_content:
                    signatures.append(("JSON Data File (heuristic)", "json", "heuristic", 60))
                
                # XML detection
                if text_content.strip().startswith('<') and '>' in text_content:
                    signatures.append(("XML Document (heuristic)", "xml", "heuristic", 45))
                
                # SQL detection
                sql_indicators = ['select ', 'insert ', 'update ', 'delete ', 'create table', 'drop table']
                if any(indicator in text_content for indicator in sql_indicators):
                    signatures.append(("SQL Script (heuristic)", "sql", "heuristic", 55))
                
                # Configuration file detection
                if text_content.startswith('[') and ']' in text_content and '=' in text_content:
                    signatures.append(("INI Configuration File (heuristic)", "ini", "heuristic", 60))
                
                # Dockerfile detection
                if any(line.strip().startswith(cmd) for cmd in ['from ', 'run ', 'copy ', 'add '] 
                       for line in text_content.split('\n')[:10]):
                    signatures.append(("Docker File (heuristic)", "dockerfile", "heuristic", 70))
                
                # YAML detection
                yaml_indicators = ['---', 'version:', 'name:', 'apiversion:', '- name:']
                if any(indicator in text_content for indicator in yaml_indicators):
                    signatures.append(("YAML Configuration (heuristic)", "yml", "heuristic", 55))
            
            # File extension hints (lower priority)
            file_ext = os.path.splitext(file_path)[1].lower().lstrip('.')
            if file_ext and not signatures:
                ext_mapping = {
                    'py': "Python Source File (extension)",
                    'js': "JavaScript Source File (extension)",
                    'ts': "TypeScript Source File (extension)",
                    'html': "HTML Document (extension)",
                    'css': "CSS Stylesheet (extension)",
                    'json': "JSON Data File (extension)",
                    'xml': "XML Document (extension)",
                    'sql': "SQL Script (extension)",
                    'ini': "INI Configuration File (extension)",
                    'cfg': "Configuration File (extension)",
                    'conf': "Configuration File (extension)",
                    'yml': "YAML Configuration (extension)",
                    'yaml': "YAML Configuration (extension)",
                    'md': "Markdown Document (extension)",
                    'txt': "Text File (extension)",
                    'log': "Log File (extension)",
                    'csv': "CSV Data File (extension)",
                }
                if file_ext in ext_mapping:
                    signatures.append((ext_mapping[file_ext], file_ext, "extension", 30))
                    
        except Exception as e:
            logger.debug(f"Text-based signature detection failed: {e}")
        
        return signatures
    
    def _init_windows_api(self):
        """Initialize Windows API functions for file access."""
        try:
            self.kernel32 = WinDLL('kernel32', use_last_error=True)
            self.shell32 = WinDLL('shell32', use_last_error=True)
            
            # Define function prototypes
            self.kernel32.GetLastError.restype = wintypes.DWORD
            
        except Exception as e:
            logger.warning(f"Failed to initialize Windows API: {e}")
    
    def _read_file_with_windows_api(self, file_path: str, max_bytes: int = None) -> Optional[bytes]:
        """
        Read file using Windows API to handle special characters in paths.
        
        Args:
            file_path (str): Path to the file to read
            max_bytes (int, optional): Maximum bytes to read. If None, reads entire file.
            
        Returns:
            Optional[bytes]: File content or None if failed
        """
        try:
            # Use PowerShell as fallback since Windows API is complex with $ characters
            return self._read_file_with_powershell(file_path, max_bytes)
                
        except Exception as e:
            logger.error(f"Windows API read failed for {os.path.basename(file_path)}: {e}")
            return None
    
    def _read_file_with_powershell(self, file_path: str, max_bytes: int = None) -> Optional[bytes]:
        """
        Read file using PowerShell to handle special characters in paths.
        
        Args:
            file_path (str): Path to the file to read
            max_bytes (int, optional): Maximum bytes to read. If None, reads entire file.
            
        Returns:
            Optional[bytes]: File content or None if failed
        """
        try:
            # Escape the file path for PowerShell
            escaped_path = file_path.replace("'", "''")
            
            if max_bytes:
                # Read only specified number of bytes
                ps_command = f"[System.IO.File]::ReadAllBytes('{escaped_path}')[0..{max_bytes-1}]"
            else:
                # Read entire file
                ps_command = f"[System.IO.File]::ReadAllBytes('{escaped_path}')"
            
            # Execute PowerShell command
            result = subprocess.run(
                ['powershell', '-Command', ps_command],
                capture_output=True,
                text=False,
                timeout=10
            )
            
            if result.returncode == 0 and result.stdout:
                # Convert PowerShell output to bytes
                byte_values = result.stdout.decode('utf-8').strip().split()
                return bytes([int(b) for b in byte_values if b.isdigit()])
            
            return None
            
        except Exception as e:
            logger.error(f"PowerShell read failed for {os.path.basename(file_path)}: {e}")
            return None
    
    def get_signature_info(self, signature_bytes: bytes) -> Optional[dict]:
        """
        Get information about a specific signature.
        
        Args:
            signature_bytes (bytes): The signature bytes to look up
            
        Returns:
            Optional[dict]: Signature information or None if not found
        """
        return FILE_SIGNATURES.get(signature_bytes)
    
    def list_supported_signatures(self) -> List[dict]:
        """
        Get a list of all supported file signatures.
        
        Returns:
            List[dict]: List of signature information dictionaries
        """
        signatures = []
        for sig_bytes, info in FILE_SIGNATURES.items():
            signatures.append({
                'signature': sig_bytes.hex().upper(),
                'description': info['desc'],
                'extensions': info['ext'],
                'signature_length': len(sig_bytes)
            })
        
        return sorted(signatures, key=lambda x: x['description'])


# Convenience function for direct usage
def detect_file_signature(file_path: str) -> Tuple[str, str]:
    """
    Convenience function to detect file signature without creating a detector instance.
    
    Args:
        file_path (str): Path to the file to analyze
        
    Returns:
        Tuple[str, str]: (Signature description, File extension)
    """
    detector = FileSignatureDetector()
    return detector.detect_file_signature(file_path)


# Module-level detector instance for performance
_global_detector = None

def get_detector() -> FileSignatureDetector:
    """
    Get a global detector instance for performance optimization.
    
    Returns:
        FileSignatureDetector: Global detector instance
    """
    global _global_detector
    if _global_detector is None:
        _global_detector = FileSignatureDetector()
    return _global_detector


if __name__ == "__main__":
    # Example usage and testing
    import sys
    
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        signature, extension = detect_file_signature(file_path)
        print(f"File: {file_path}")
        print(f"Signature: {signature}")
        print(f"Extension: {extension}")
    else:
        print("Crow Eye File Signature Detection Utility")
        print("Usage: python file_signature_detector.py <file_path>")
        print(f"Supports {len(FILE_SIGNATURES)} different file signatures")
