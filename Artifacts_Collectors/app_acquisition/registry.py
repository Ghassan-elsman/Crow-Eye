"""Registry reads for an acquisition, live or from an image.

Two hives matter: the machine's SOFTWARE hive and each user's NTUSER.DAT.
Live, they are read through winreg (HKLM, and HKEY_USERS\\<SID> for profiles
whose hive is loaded); in an image, the hive files are read out of the image
and opened with python-registry. Either way the caller names a hive as
``"SOFTWARE"`` or ``"USER:<profile name>"`` and a key path inside it.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

SOFTWARE = "SOFTWARE"
_MAX_EXPORT_KEYS = 2000
_MAX_VALUE_CHARS = 4096


def _value_text(value) -> object:
    """A value as JSON can hold it: bytes as hex, long text cut."""
    if isinstance(value, (bytes, bytearray)):
        text = bytes(value[:_MAX_VALUE_CHARS // 2]).hex()
        return {"hex": text, "length": len(value)}
    if isinstance(value, (list, tuple)):
        return [_value_text(v) for v in value]
    if isinstance(value, str) and len(value) > _MAX_VALUE_CHARS:
        return value[:_MAX_VALUE_CHARS] + "...(%d chars)" % len(value)
    return value


class RegistryView:
    """subkeys / values / export over the source's SOFTWARE and user hives."""

    def __init__(self, source):
        self.source = source
        self._hives: Dict[str, object] = {}   # image: hive name -> python-registry Registry
        self._sids: Optional[Dict[str, str]] = None
        self.unavailable: Dict[str, str] = {}  # hive -> why it could not be read

    # -- hive access --------------------------------------------------
    def user_hives(self) -> List[str]:
        return ["USER:%s" % name for name, _rel in self.source.user_profiles()]

    def _live_sid(self, user: str) -> Optional[str]:
        if self._sids is None:
            self._sids = {}
            try:
                import os
                from Artifacts_Collectors.user_identity import _profile_list_live
                for sid, path in _profile_list_live().items():
                    if path:
                        self._sids[os.path.basename(path.rstrip("\\/")).lower()] = sid
            except Exception as exc:
                logger.debug("ProfileList unavailable: %s", exc)
        return self._sids.get(user.lower())

    def _image_hive(self, hive: str):
        if hive in self._hives:
            return self._hives[hive]
        reg = None
        if hive == SOFTWARE:
            rel = "Windows\\System32\\config\\SOFTWARE"
        else:
            rel = "Users\\%s\\NTUSER.DAT" % hive.split(":", 1)[1]
        path = self.source.hive_file(rel)
        if path:
            try:
                from Registry import Registry
                reg = Registry.Registry(path)
            except Exception as exc:
                self.unavailable[hive] = "hive could not be opened: %s" % exc
        else:
            self.unavailable[hive] = "hive file not found in the image"
        self._hives[hive] = reg
        return reg

    def _live_open(self, hive: str, path: str):
        import winreg
        if hive == SOFTWARE:
            root, sub = winreg.HKEY_LOCAL_MACHINE, ("SOFTWARE\\" + path) if path else "SOFTWARE"
        else:
            sid = self._live_sid(hive.split(":", 1)[1])
            if not sid:
                self.unavailable[hive] = "no SID for this profile"
                return None
            root, sub = winreg.HKEY_USERS, sid + ("\\" + path if path else "")
        try:
            return winreg.OpenKey(root, sub, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        except FileNotFoundError:
            if hive != SOFTWARE and not path:
                # The profile's hive is not loaded (the user is not signed in).
                self.unavailable[hive] = "hive not loaded (user not signed in)"
            return None
        except OSError:
            return None

    def _image_key(self, hive: str, path: str):
        reg = self._image_hive(hive)
        if reg is None:
            return None
        try:
            return reg.open(path) if path else reg.root()
        except Exception:
            return None

    # -- reads --------------------------------------------------------
    def subkeys(self, hive: str, path: str) -> List[str]:
        if self.source.kind == "live":
            import winreg
            key = self._live_open(hive, path)
            if key is None:
                return []
            out = []
            with key:
                i = 0
                while True:
                    try:
                        out.append(winreg.EnumKey(key, i))
                    except OSError:
                        break
                    i += 1
            return out
        key = self._image_key(hive, path)
        try:
            return [k.name() for k in key.subkeys()] if key is not None else []
        except Exception:
            return []

    def values(self, hive: str, path: str) -> Dict[str, object]:
        """{value name: data}; the default value is named ``""``."""
        if self.source.kind == "live":
            import winreg
            key = self._live_open(hive, path)
            if key is None:
                return {}
            out = {}
            with key:
                i = 0
                while True:
                    try:
                        name, data, _type = winreg.EnumValue(key, i)
                    except OSError:
                        break
                    out[name] = data
                    i += 1
            return out
        key = self._image_key(hive, path)
        out = {}
        try:
            for v in (key.values() if key is not None else []):
                name = v.name()
                # python-registry names the default value "(default)"; winreg "".
                out["" if name == "(default)" else name] = v.value()
        except Exception:
            pass
        return out

    def last_written(self, hive: str, path: str) -> Optional[str]:
        if self.source.kind == "live":
            import winreg
            key = self._live_open(hive, path)
            if key is None:
                return None
            with key:
                try:
                    ft = winreg.QueryInfoKey(key)[2]
                    from utils.time_utils import filetime_to_datetime
                    dt = filetime_to_datetime(ft)
                    return dt.isoformat() if dt else None
                except Exception:
                    return None
        key = self._image_key(hive, path)
        try:
            ts = key.timestamp() if key is not None else None
            return ts.isoformat() if ts else None
        except Exception:
            return None

    def exists(self, hive: str, path: str) -> bool:
        if self.source.kind == "live":
            key = self._live_open(hive, path)
            if key is None:
                return False
            key.Close()
            return True
        return self._image_key(hive, path) is not None

    def export(self, hive: str, path: str) -> Dict[str, object]:
        """The key, its values and every subkey below it, as JSON-able data.
        Stops after _MAX_EXPORT_KEYS keys and says so."""
        count = [0]

        def one(p):
            count[0] += 1
            node = {"path": p, "last_written": self.last_written(hive, p),
                    "values": {k: _value_text(v) for k, v in self.values(hive, p).items()},
                    "subkeys": []}
            for name in self.subkeys(hive, p):
                if count[0] >= _MAX_EXPORT_KEYS:
                    node["truncated"] = True
                    break
                node["subkeys"].append(one(p + "\\" + name))
            return node
        root_name = "HKLM\\SOFTWARE" if hive == SOFTWARE else "HKU\\%s (NTUSER.DAT)" % hive.split(":", 1)[1]
        return {"hive": root_name, "key": one(path), "keys_exported": count[0]}
