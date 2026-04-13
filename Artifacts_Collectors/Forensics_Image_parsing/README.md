# Forensics Image Parsing Module

Welcome to the **Forensics Image Parsing** module. This core component of Crow-eye provides a robust, extensible, and modular architecture designed to parse, analyze, and extract artifacts from various forensic image formats. By abstracting the complexities of underlying file systems and image containers, this module ensures that artifact collection rules can run seamlessly across bit-for-bit raw copies, virtual machine disks, and expert witness formats.

---

## 🏗 Architecture Overview

The module follows a highly decoupled design centered around the **Strategy Design Pattern** and is heavily backed by the **`dissect`** incident response framework (with fallbacks to `pycdlib` for specific formats).

The architecture separates format detection, container parsing, volume enumeration, and file system extraction into distinct components.

### Core Components

#### 1. Image Parser (`image_parser.py`)
Acts as the central coordinator. 
- Automatically detects the correct forensic image format through both **signature verification** and fallback **extension checking**.
- Manages the lifecycle of format-specific strategies, iterating through them in a priority order.
- Provides a unified interface to detect formats, retrieve the appropriate strategy, and enumerate partitions.
- Supports handling split or segmented forensic images (e.g., `.001`, `.E01`).

#### 2. File System Accessor (`file_system_accessor.py`)
A unified abstraction layer over the file system parsing logic (`dissect.target.volume` & `dissect.target.filesystem`).
- Exposes standard, format-agnostic file operations: `open_partition`, `list_directory`, `read_file`, `read_file_streaming`, and `read_directory_recursive`.
- Intelligently handles complex filesystem features such as **NTFS Alternate Data Streams (ADS)**.
- Implements specialized compaction logic for sparse files (like the USN Journal `$J`), significantly optimizing extraction performance.
- Ensures absolute preservation of **forensic MAC times (Modified, Accessed, Created)** on extracted files.

#### 3. Image Extractor (`image_extractor.py`)
The functional bridge between the core artifact definitions and the parsed image.
- Uses `ImageParser` and `FileSystemAccessor` to navigate the parsed volume.
- Translates Windows environment variables (e.g., `%SystemRoot%`, `%UserProfile%`) to internal path representations understood by `dissect`.
- Safely extracts targeted artifacts from the image to the local examiner's system structure, allowing live-system-like analysis over dead-disk images.

#### 4. Partition Detector (`partition_detector.py`)
Responsible for volume discovery.
- Scans containers for Volume Systems (MBR, GPT).
- Gracefully handles "Volume-Only" acquisitions (direct filesystem mounts at offset 0) when no partition table is present.

#### 5. Data Models (`data_models.py`)
Defines structured dataclasses that standardize data representation across the module:
- `ImageInfo`: Comprehensive metadata about the loaded image.
- `PartitionInfo`: Specific details regarding partitions (number, offset, size, bootable flag, filesystem type).
- `FileMetadata`: Details about individual files including MAC timestamps and DOS attributes.
- `ExtractionOptions`: User-defined options handling things like hash calculation, retry attempts, and partition filtering.

#### 6. Strategy Pattern (`strategies/` subdirectory)
The module leverages the **Strategy Pattern** to cleanly separate the parsing logic for different container formats. Each strategy implements a standard interface (via `FileAccessStrategy`) determining if it can handle an image and exposing methods to load it.

---

## 💽 Supported Forensic Formats & Strategies

| Format | Strategy Class | Description / Details |
| :--- | :--- | :--- |
| **E01 / Ex01** | `E01AccessStrategy` | Expert Witness Format. Includes intelligent fallback loaders for logical slices or images with missing segments. |
| **RAW / DD** | `RawAccessStrategy` | Bit-for-bit raw copies (`.dd`, `.raw`, `.img`, `.001`). Contains automated multi-part discovery for split raw images (`.001`, `.002`, etc.). |
| **VHDX / VHD** | `VHDXAccessStrategy` | Hyper-V Virtual Hard Disks. |
| **VMDK** | `VMDKAccessStrategy` | VMware Virtual Disks. |
| **ISO** | `ISOAccessStrategy` | Optical Disc Images (`.iso`). Validates the `CD001` signature at offset 32769 and utilizes `pycdlib` for parsing. |

---

## ⚙️ How the System Works

1. **Initialization & Detection**: The user (or the GUI `image_parsing_dialog.py`) submits an image file path to the `ImageParser`. The parser cascades the request down to its loaded strategies. The first strategy confirming support via `can_handle()` (checking magic bytes and extensions) is elected.
2. **Container Mounting**: The elected strategy uses the appropriate backend (usually `dissect.target.container`) to mount the forensic image, resolving any split segments seamlessly.
3. **Partition Discovery**: `partition_detector.py` attempts to read an MBR/GPT table. If successful, it builds a list of `PartitionInfo` objects. If not, it probes for a raw volume filesystem.
4. **Filesystem Traversal**: The `FileSystemAccessor` acts as the bridge. By mapping offset addresses provided by the `PartitionInfo`, it mounts a specific volume.
5. **Artifact Extraction**: `image_extractor.py` queries the `FileSystemAccessor` for target paths, streams the binary data to the host machine safely avoiding memory exhaustion via chunked reading, and restores the forensic timestamps on the destination files.

---

## 🛠 Dependencies

- Python 3.8+
- `dissect.target`: Core capability for opening forensic containers and volumes.
- `pycdlib`: Used exclusively by the `ISOAccessStrategy` for parsing optical media.
