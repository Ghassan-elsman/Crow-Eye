"""Where an acquisition reads from: the live machine or a forensic image.

Both sources take paths relative to the volume root in Windows form
(``Users\\bob\\AppData\\Roaming\\Foo``), so the catalog, the footprint and the
collector are written once and work on either.

LiveSource copies through Crow-Claw's FileAccessor (standard copy, then a
shadow copy, then a raw cluster read), so a database a running program holds
open still comes. ImageSource reads through the image collector's
FileSystemAccessor, which keeps the file's own timestamps on the copy.
"""
from __future__ import annotations

import ctypes
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

# The file system's own bookkeeping at the volume root - not anyone's files.
# Only these: $Recycle.Bin and $WinREAgent are folders like any other, and the
# Recycle Bin is evidence.
NTFS_METAFILES = {"$MFT", "$MFTMirr", "$LogFile", "$Volume", "$AttrDef", "$Bitmap", "$Boot",
                  "$BadClus", "$Secure", "$UpCase", "$Extend", "$Quota", "$ObjId", "$Reparse"}

# Profiles that hold no one's data of their own.
_SKIP_PROFILES = {"public", "default", "default user", "all users", "defaultapppool"}


def _rel(path: str) -> str:
    """``Users/bob`` / ``\\Users\\bob\\`` -> ``Users\\bob``."""
    return path.replace("/", "\\").strip("\\")


class Source:
    """What the catalog, footprint and collector need from a source."""

    kind = "source"

    @property
    def tag(self) -> str:
        """Folder name under the acquisition: ``live`` or the image's volume."""
        raise NotImplementedError

    def describe(self) -> str:
        raise NotImplementedError

    def isdir(self, rel: str) -> bool:
        raise NotImplementedError

    def isfile(self, rel: str) -> bool:
        raise NotImplementedError

    def listdir(self, rel: str) -> List[Tuple[str, bool]]:
        """[(name, is_dir)] of one folder; [] when it cannot be read."""
        raise NotImplementedError

    def size(self, rel: str) -> int:
        raise NotImplementedError

    can_copy = True

    def entries(self, rel: str) -> List[dict]:
        """One folder, for a file browser: [{name, is_dir, size, modified,
        created, deleted}] - times as UTC ISO text, or None."""
        return [{"name": n, "is_dir": d, "size": None if d else self.size(rel + "\\" + n if rel else n),
                 "modified": None, "created": None, "deleted": False} for n, d in self.listdir(rel)]

    def walk_files(self, rel: str) -> Iterator[Tuple[str, int]]:
        """Every file below ``rel`` (or ``rel`` itself) as (rel_path, size).
        Links and junctions are not followed."""
        if self.isfile(rel):
            yield rel, self.size(rel)
            return
        stack = [rel]
        while stack:
            cur = stack.pop()
            for name, is_dir in self.listdir(cur):
                child = cur + "\\" + name if cur else name
                if is_dir:
                    stack.append(child)
                else:
                    yield child, self.size(child)

    def user_profiles(self) -> List[Tuple[str, str]]:
        """[(user name, profile folder rel)] for every real profile."""
        out = []
        for name, is_dir in self.listdir("Users"):
            if is_dir and name.lower() not in _SKIP_PROFILES:
                out.append((name, "Users\\" + name))
        return out

    def copy_file(self, rel: str, dest: str):
        """Copy one file to ``dest``. Returns (ok, method, detail) where detail
        carries what custody needs (times, read_from, shadow copy)."""
        raise NotImplementedError

    def hive_file(self, rel: str) -> Optional[str]:
        """A local copy of a registry hive file, for python-registry (image)."""
        return None

    def close(self):
        pass


class LiveSource(Source):
    """The running machine's system volume."""

    kind = "live"

    def __init__(self, volume: str = None):
        self.volume = (volume or os.environ.get("SystemDrive", "C:")).rstrip("\\/") + "\\"
        self._accessor = None
        try:
            self.is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            self.is_admin = False

    @property
    def tag(self) -> str:
        return "live"

    def describe(self) -> str:
        return "this machine (%s)" % self.volume.rstrip("\\")

    def abspath(self, rel: str) -> str:
        return os.path.join(self.volume, _rel(rel))

    def isdir(self, rel):
        return os.path.isdir(self.abspath(rel))

    def isfile(self, rel):
        return os.path.isfile(self.abspath(rel))

    def size(self, rel):
        try:
            return os.path.getsize(self.abspath(rel))
        except OSError:
            return 0

    def listdir(self, rel):
        path = self.abspath(rel)
        out = []
        try:
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        is_dir = entry.is_dir(follow_symlinks=False)
                        if is_dir and _entry_is_junction(entry):
                            continue
                        out.append((entry.name, is_dir))
                    except OSError:
                        continue
        except OSError:
            return []
        return out

    def entries(self, rel):
        path = self.abspath(rel)
        out = []
        try:
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        is_dir = entry.is_dir(follow_symlinks=False)
                        if is_dir and _entry_is_junction(entry):
                            continue
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    out.append({"name": entry.name, "is_dir": is_dir, "size": None if is_dir else st.st_size,
                                "modified": _iso(st.st_mtime),
                                "created": _iso(getattr(st, "st_birthtime", None) or st.st_ctime),
                                "deleted": False})
        except OSError:
            return []
        return out

    @staticmethod
    def drives() -> List[str]:
        """Fixed drives of this machine, and removable ones with media in them, for the browser's
        picker. os.listdrives() also lists network drives and empty card readers, and asking
        one of those for its size or label (each chip does) can hold the window for seconds."""
        try:
            letters = [d.rstrip("\\") for d in os.listdrives()]
        except Exception:
            import string
            letters = ["%s:" % c for c in string.ascii_uppercase if os.path.exists("%s:\\" % c)]
        if os.name != "nt":
            return letters
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            # No "There is no disk in the drive" box while an empty reader is asked.
            old = k32.SetErrorMode(0x0001 | 0x8000)
            try:
                out = []
                for d in letters:
                    kind = k32.GetDriveTypeW(ctypes.c_wchar_p(d + "\\"))
                    if kind == 3:                                   # DRIVE_FIXED
                        out.append(d)
                    elif kind == 2 and k32.GetVolumeInformationW(   # DRIVE_REMOVABLE, media in
                            ctypes.c_wchar_p(d + "\\"), None, 0, None, None, None, None, 0):
                        out.append(d)
                return out or letters
            finally:
                k32.SetErrorMode(old)
        except Exception:
            return letters

    def user_profiles(self):
        out, seen = [], set()
        try:
            from Artifacts_Collectors.user_identity import _profile_list_live
            for _sid, path in _profile_list_live().items():
                if not path or not os.path.isdir(path):
                    continue
                name = os.path.basename(path.rstrip("\\/"))
                if name.lower() in _SKIP_PROFILES:
                    continue
                if os.path.splitdrive(path)[0].upper() + "\\" != self.volume.upper():
                    continue
                rel = _rel(os.path.splitdrive(path)[1])
                if rel.lower() not in seen:
                    seen.add(rel.lower())
                    out.append((name, rel))
        except Exception as exc:
            logger.debug("ProfileList unavailable: %s", exc)
        for name, rel in super().user_profiles():
            if rel.lower() not in seen:
                seen.add(rel.lower())
                out.append((name, rel))
        return out

    def _file_accessor(self):
        if self._accessor is None:
            from Artifacts_Collectors.crow_claw.core.file_accessor import FileAccessor
            acc = FileAccessor(is_admin=self.is_admin)
            try:
                # The same setting every parser honours: no new shadow copy on
                # the target unless the examiner allowed it.
                from Artifacts_Collectors.SRUM_Claw import _parser_allows_snapshot_creation
                if not _parser_allows_snapshot_creation():
                    for strategy in getattr(acc, "strategies", []):
                        if type(strategy).__name__ == "VSSAccessStrategy":
                            strategy.allow_snapshot_creation = False
            except Exception:
                pass
            self._accessor = acc
        return self._accessor

    def copy_file(self, rel, dest):
        src = self.abspath(rel)
        detail = {"source": src}
        try:
            from utils import custody
            detail["times"] = custody.file_times(src)
        except Exception:
            pass
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            res = self._file_accessor().access_file_with_retry(src, dest, "Application", max_retries=1)
        except Exception as exc:
            return False, None, dict(detail, error=str(exc))
        method = (getattr(res, "strategy_used", "") or "standard").lower()
        detail.update(read_from=getattr(res, "read_path", None),
                      shadow_copy_id=getattr(res, "vss_shadow_copy_id", None),
                      shadow_copy_created_utc=getattr(res, "vss_shadow_copy_created", None))
        if getattr(res, "success", False) and os.path.exists(dest):
            return True, method, detail
        return False, method, dict(detail, error=getattr(res, "error", None) or "copy failed")


def _iso(ts) -> Optional[str]:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat() if ts else None
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _is_junction(path: str) -> bool:
    try:
        return bool(getattr(os.path, "isjunction", lambda _p: False)(path))
    except OSError:
        return True


def _entry_is_junction(entry) -> bool:
    """A directory entry that is a junction. Python 3.12's DirEntry answers from the reparse tag the
    directory scan already returned; os.path.isjunction made one lstat per entry, 26,805 of them
    (2 s) to work out one program's footprint."""
    check = getattr(entry, "is_junction", None)
    if check is not None:
        try:
            return bool(check())
        except OSError:
            return True
    return _is_junction(entry.path)


class ImageSource(Source):
    """One NTFS partition inside a forensic image (E01, VHD(X), VMDK, raw...)."""

    kind = "image"

    def __init__(self, image_path, partition_number: int):
        from Artifacts_Collectors.Forensics_Image_parsing.image_parser import ImageParser
        from Artifacts_Collectors.Forensics_Image_parsing.file_system_accessor import FileSystemAccessor
        self.image_path = image_path[0] if isinstance(image_path, list) else image_path
        self.partition_number = partition_number
        parser = ImageParser()
        strategy = parser.get_strategy(file_source=image_path)
        if not strategy:
            raise ValueError("Unsupported forensic image format: %s" % self.image_path)
        if hasattr(strategy, "_open_image") and not strategy._open_image(image_path):
            raise ValueError("Could not open the image: %s" % self.image_path)
        img_info = strategy.get_img_info() if hasattr(strategy, "get_img_info") else None
        if not img_info:
            raise ValueError("No image information for: %s" % self.image_path)
        partitions = strategy.list_partitions() if hasattr(strategy, "list_partitions") else []
        offset = next((p.start_offset for p in partitions if p.partition_number == partition_number), 0)
        self._strategy = strategy
        self.accessor = FileSystemAccessor(img_info)
        if not self.accessor.open_partition(offset):
            raise ValueError("Partition %s of %s has no readable file system"
                             % (partition_number, os.path.basename(self.image_path)))
        self._tmp = tempfile.mkdtemp(prefix="crow_app_hives_")

    @staticmethod
    def partitions(image_path):
        """[(partition_number, label)] of an image, for the picker."""
        from Artifacts_Collectors.Forensics_Image_parsing.image_parser import ImageParser
        out = []
        for p in ImageParser().list_partitions(image_path) or []:
            label = str(p)
            if getattr(p, "has_windows", None):
                label += "  - Windows"
            out.append((p.partition_number, label))
        # The Windows partition first: that is where the applications are.
        return sorted(out, key=lambda item: "- Windows" not in item[1])

    @property
    def tag(self) -> str:
        stem = os.path.splitext(os.path.basename(self.image_path))[0] or "image"
        return "%s_p%s" % (stem, self.partition_number)

    def describe(self) -> str:
        return "%s, partition %s" % (os.path.basename(self.image_path), self.partition_number)

    @staticmethod
    def _img(rel: str) -> str:
        return "/" + _rel(rel).replace("\\", "/")

    def _node(self, rel):
        try:
            return self.accessor.fs_info.get(self._img(rel))
        except Exception:
            return None

    def isdir(self, rel):
        node = self._node(rel)
        try:
            return bool(node is not None and node.is_dir())
        except Exception:
            return False

    def isfile(self, rel):
        node = self._node(rel)
        try:
            return bool(node is not None and not node.is_dir())
        except Exception:
            return False

    def size(self, rel):
        node = self._node(rel)
        try:
            return int(node.stat().st_size) if node is not None else 0
        except Exception:
            return 0

    def listdir(self, rel):
        node = self._node(rel)
        if node is None:
            return []
        out = []
        try:
            for entry in node.scandir():
                name = getattr(entry, "name", "")
                if name in (".", "..", "") or name in NTFS_METAFILES:
                    continue
                try:
                    if entry.is_symlink():
                        continue
                except Exception:
                    pass
                try:
                    out.append((name, bool(entry.is_dir())))
                except Exception:
                    continue
        except Exception:
            return []
        return out

    def entries(self, rel):
        node = self._node(rel)
        if node is None:
            return []
        out = []
        try:
            for entry in node.scandir():
                name = getattr(entry, "name", "")
                if name in (".", "..", "") or name in NTFS_METAFILES:
                    continue
                try:
                    if entry.is_symlink():
                        continue
                    is_dir = bool(entry.is_dir())
                    st = entry.stat()
                except Exception:
                    continue
                out.append({"name": name, "is_dir": is_dir,
                            "size": None if is_dir else getattr(st, "st_size", None),
                            "modified": _iso(getattr(st, "st_mtime", None)),
                            "created": _iso(getattr(st, "st_birthtime", None)), "deleted": False})
        except Exception:
            return out
        return out

    def _times(self, rel):
        node = self._node(rel)
        try:
            st = node.stat()
        except Exception:
            return None

        def iso(v):
            try:
                return datetime.fromtimestamp(float(v), tz=timezone.utc).isoformat()
            except Exception:
                return None
        return {"modified": iso(getattr(st, "st_mtime", None)),
                "accessed": iso(getattr(st, "st_atime", None)),
                "changed": iso(getattr(st, "st_ctime", None)),
                "born": iso(getattr(st, "st_birthtime", None)),
                "size": getattr(st, "st_size", None)}

    def copy_file(self, rel, dest):
        detail = {"source": "image:%s/%s" % (self.tag, _rel(rel).replace("\\", "/")),
                  "times": self._times(rel)}
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            # Byte for byte: compact (zero-skipping) would shift offsets.
            self.accessor.read_file_streaming(self._img(rel), dest, compact=False)
        except Exception as exc:
            return False, "image", dict(detail, error=str(exc))
        if os.path.exists(dest):
            return True, "image", detail
        return False, "image", dict(detail, error="nothing was written")

    def hive_file(self, rel):
        dest = os.path.join(self._tmp, _rel(rel).replace("\\", "_"))
        if os.path.exists(dest):
            return dest
        try:
            self.accessor.read_file_streaming(self._img(rel), dest, compact=False)
        except Exception as exc:
            logger.debug("Hive %s not read from the image: %s", rel, exc)
            return None
        return dest if os.path.exists(dest) else None

    def close(self):
        try:
            self.accessor.close()
        except Exception:
            pass
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)


class ShadowSource(LiveSource):
    """One shadow copy of this machine's volume, browsed through its own device
    (\\\\?\\GLOBALROOT\\Device\\HarddiskVolumeShadowCopyN\\): the volume exactly as it
    was when the copy was made. Read-only by nature, and nothing in it is locked,
    so a plain copy is the copy; its registry hives are read where they lie."""

    kind = "shadow"

    def __new__(cls, copy: dict):
        # A copy Windows lists in the volume's catalog but exposes as no device
        # is rebuilt from its store over the raw volume instead.
        if cls is ShadowSource and not copy.get("device"):
            return HiddenShadowSource(copy)
        return super().__new__(cls)

    def __init__(self, copy: dict):
        LiveSource.__init__(self, (copy.get("volume") or "C") + ":")
        self.copy = copy
        self.volume = copy["device"].rstrip("\\") + "\\"

    @property
    def tag(self) -> str:
        return "shadow%s_%s" % (self.copy.get("number") or "", self.copy.get("volume") or "")

    def describe(self) -> str:
        when = (self.copy.get("created") or "").replace("T", " ").rstrip("Z")
        return "shadow copy #%s of %s: (%s UTC)" % (self.copy.get("number"), self.copy.get("volume"), when)

    def user_profiles(self):
        return Source.user_profiles(self)

    def copy_file(self, rel, dest):
        import shutil
        src = self.abspath(rel)
        detail = {"source": src, "shadow_copy_id": self.copy.get("shadow_id"),
                  "shadow_copy_created_utc": self.copy.get("created"), "read_from": src}
        try:
            from utils import custody
            detail["times"] = custody.file_times(src)
        except Exception:
            pass
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            shutil.copy2(src, dest)
        except OSError as exc:
            return False, "shadow_copy", dict(detail, error=str(exc))
        return True, "shadow_copy", detail

    def hive_file(self, rel):
        path = self.abspath(rel)
        return path if os.path.isfile(path) else None

    @staticmethod
    def copies(volume: str = None) -> List[dict]:
        """This machine's shadow copies (Artifacts_Collectors.shadow_copies.live_copies)."""
        from Artifacts_Collectors.shadow_copies import live_copies
        return live_copies(volume)


def _open_store_fs(store):
    """A FileSystemAccessor over a shadow copy rebuilt by Crow-Eye's own VSS reader. The NTFS on
    it opens through the same file system layer as every image partition's."""
    from dissect.target.filesystem import open as open_fs
    from Artifacts_Collectors.Forensics_Image_parsing.file_system_accessor import FileSystemAccessor
    from Artifacts_Collectors.shadow_copies import snapshot_stream
    accessor = FileSystemAccessor(None)
    accessor.fs_info = open_fs(snapshot_stream(store))
    return accessor


class ImageShadowSource(ImageSource):
    """One shadow copy inside a partition of a forensic image: the partition's
    VSS catalog read and the copy rebuilt from its store chain by Crow-Eye's own
    VSS reader (vss_reader), and its NTFS opened like any other partition's."""

    kind = "image_shadow"

    def __init__(self, image_path, partition_number: int, store_index: int):
        from Artifacts_Collectors.shadow_copies import open_image_volume, find_store
        self.image_path = image_path[0] if isinstance(image_path, list) else image_path
        self.partition_number = partition_number
        self.store_index = store_index
        self._strategy, vol = open_image_volume(self.image_path, partition_number)
        self.store = find_store(vol, index=store_index)
        self.accessor = _open_store_fs(self.store)
        self._tmp = tempfile.mkdtemp(prefix="crow_app_hives_")

    @property
    def tag(self) -> str:
        return "%s_vss%d" % (ImageSource.tag.fget(self), self.store_index + 1)

    def describe(self) -> str:
        return "%s, shadow copy %d" % (ImageSource.describe(self), self.store_index + 1)

    def copy_file(self, rel, dest):
        ok, _method, detail = ImageSource.copy_file(self, rel, dest)
        detail["shadow_copy_id"] = self.store.copy_id
        created = getattr(self, "copy", None) and self.copy.get("created")
        detail["shadow_copy_created_utc"] = created or getattr(self.store, "created", None)
        return ok, "image_shadow_copy", detail


class HiddenShadowSource(ImageShadowSource):
    """A live shadow copy Windows keeps in the volume's catalog but exposes as no
    device: rebuilt from its store chain over this machine's raw volume
    (administrator). Checked against exposed copies' own devices: identical but
    for the few blocks the running system writes during the read."""

    kind = "hidden_shadow"

    def __init__(self, copy: dict):
        from Artifacts_Collectors.shadow_copies import raw_volume, find_store
        self.copy = copy
        self.image_path = "\\\\.\\%s:" % (copy.get("volume") or "C")
        self.partition_number = 0
        self.store_index = -1
        self._raw = raw_volume(copy.get("volume") or "C")
        self.store = find_store(self._raw, shadow_id=copy.get("shadow_id"))
        self.accessor = _open_store_fs(self.store)
        self._tmp = tempfile.mkdtemp(prefix="crow_app_hives_")

    @property
    def tag(self) -> str:
        return "hidden_shadow_%s_%s" % ((self.copy.get("created") or "").replace(":", "")[:15],
                                        self.copy.get("volume") or "")

    def describe(self) -> str:
        when = (self.copy.get("created") or "").replace("T", " ").rstrip("Z")
        return "hidden shadow copy of %s: (%s UTC, in the catalog, not exposed by Windows)" % (
            self.copy.get("volume"), when)

    def close(self):
        ImageSource.close(self)
        try:
            self._raw.close()
        except Exception:
            pass


class SavedSource(Source):
    """A machine's file system as the case saved it when its MFT was parsed.

    No access to the machine is needed: the listing is the parsed $MFT
    (Target_Artifacts/mft_claw_analysis.db) - every name with its parent, size,
    times and whether the record is still in use, so deleted entries the MFT
    still holds are listed too (marked). It holds names and times, not file
    contents: nothing can be copied from it.
    """

    kind = "saved"
    can_copy = False
    _ROOT = 5                      # the volume's root folder record
    _MAX_ROWS = 20000

    def __init__(self, artifacts_dir: str, volume_letter: Optional[str] = None):
        import sqlite3
        path = os.path.join(artifacts_dir, "mft_claw_analysis.db")
        if not os.path.isfile(path):
            raise ValueError("This case has no parsed MFT: parse the MFT to save the file listing.")
        self._conn = sqlite3.connect("file:%s?mode=ro" % path.replace("?", "%3f"), uri=True,
                                     check_same_thread=False, timeout=10)
        self.volume = (volume_letter or (self.volumes(artifacts_dir) or ["C"])[0]).rstrip(":\\")
        self._records: Dict[str, int] = {"": self._ROOT}

    @staticmethod
    def volumes(artifacts_dir: str) -> List[str]:
        import sqlite3
        path = os.path.join(artifacts_dir, "mft_claw_analysis.db")
        if not os.path.isfile(path):
            return []
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % path.replace("?", "%3f"), uri=True, timeout=10)
            with conn:
                # Every NTFS volume holds records 0-15 (the system files), and the primary key
                # leads with record_number: 4 ms. DISTINCT over the whole table had no index
                # to use - 2.4 s on 3.3M rows, before the File Browser could show.
                vols = [r[0] for r in conn.execute(
                    "SELECT DISTINCT volume_letter FROM mft_records WHERE record_number BETWEEN 0 AND 15 "
                    "AND volume_letter IS NOT NULL ORDER BY 1")]
                return vols or [r[0] for r in conn.execute("SELECT DISTINCT volume_letter FROM mft_records "
                                                           "WHERE volume_letter IS NOT NULL ORDER BY 1")]
        except Exception:
            return []

    @property
    def tag(self) -> str:
        return "saved_%s" % self.volume

    def describe(self) -> str:
        return "the saved listing of %s: (this case's parsed MFT)" % self.volume

    def _children(self, record: int) -> List[dict]:
        rows = self._conn.execute(
            "SELECT fn.record_number, fn.file_name, fn.namespace, r.is_directory, r.in_use, "
            "COALESCE(NULLIF(r.file_size, 0), fn.real_size), r.modified_time, r.created_time, "
            "r.mft_sequence_number "
            "FROM mft_file_names fn LEFT JOIN mft_records r "
            "ON r.record_number = fn.record_number AND r.volume_letter = fn.volume_letter "
            "WHERE fn.parent_record = ? AND fn.volume_letter = ? AND fn.record_number != ? "
            "LIMIT ?", (record, self.volume, record, self._MAX_ROWS * 3)).fetchall()
        best: Dict[int, tuple] = {}
        for row in rows:
            # One name per record: the long (Win32 / POSIX) one, never the 8.3 DOS alias.
            if row[2] == 2:
                continue
            if row[0] not in best or best[row[0]][2] == 0 and row[2] in (1, 3):
                best[row[0]] = row
        out = []
        for rec, name, _ns, is_dir, in_use, size, modified, created, seq in best.values():
            if not name or name in NTFS_METAFILES:
                continue
            out.append({"record": rec, "name": name, "is_dir": bool(is_dir),
                        "size": None if is_dir else size, "modified": modified, "created": created,
                        "deleted": in_use == 0, "sequence": seq})
        return sorted(out, key=lambda e: (not e["is_dir"], e["name"].lower()))[:self._MAX_ROWS]

    def _record_of(self, rel: str) -> Optional[int]:
        rel = _rel(rel)
        key = rel.lower()
        if key in self._records:
            return self._records[key]
        parent, _, leaf = rel.rpartition("\\")
        parent_rec = self._record_of(parent)
        if parent_rec is None:
            return None
        for e in self._children(parent_rec):
            if e["name"].lower() == leaf.lower():
                self._records[key] = e["record"]
                return e["record"]
        return None

    def entries(self, rel):
        rec = self._record_of(rel)
        return [] if rec is None else self._children(rec)

    def listdir(self, rel):
        return [(e["name"], e["is_dir"]) for e in self.entries(rel)]

    def _entry(self, rel):
        parent, _, leaf = _rel(rel).rpartition("\\")
        return next((e for e in self.entries(parent) if e["name"].lower() == leaf.lower()), None)

    def isdir(self, rel):
        e = self._entry(rel) if _rel(rel) else {"is_dir": True}
        return bool(e and e["is_dir"])

    def isfile(self, rel):
        e = self._entry(rel)
        return bool(e and not e["is_dir"])

    def size(self, rel):
        e = self._entry(rel)
        return int(e["size"] or 0) if e else 0

    def user_profiles(self):
        return []

    def copy_file(self, rel, dest):
        return False, "saved", {"source": rel, "error": "a saved listing holds no file contents"}

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
