"""
Actor attribution — the "who did this" ladder.

Order (first satisfied step wins; if nothing resolves the actor stays
EMPTY — the UI renders an explicit "Unattributed" chip; we never guess):

1. Artifact-borne SID  -> UserProfiles / amcache user map lookup.
   Well-known SIDs (S-1-5-18/19/20, DWM, UMFD...) -> System/Application.
2. Log-borne account name (already-parsed payload fields).
3. Per-user-hive artifacts (UserAssist, Shellbags, RecentDocs, LNK...) are
   inherently user-scoped -> the profile owner, when unambiguous.
4. Path classification (System32 etc. -> System).
5. EMPTY.
"""

import logging
from typing import Dict, Optional, Tuple

from uba.utils import sid_utils

logger = logging.getLogger(__name__)

# Path prefixes that identify OS-owned executables/files (lower-case).
_SYSTEM_PATH_MARKERS = (
    "c:\\windows\\system32", "c:\\windows\\syswow64", "\\systemroot\\",
    "c:\\windows\\winsxs", "c:\\windows\\servicing",
)


class ActorResolver:
    """Resolves (actor_type, actor_name, actor_basis) tuples."""

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self._sid_to_user: Dict[str, str] = {}
        self._load_user_maps()

    # ------------------------------------------------------------------ #
    def _load_user_maps(self):
        """UserProfiles (registry) + amcache InventoryMiscellaneousUser."""
        conn = self.db_pool.get("registry")
        if conn is not None and self.db_pool.has_table("registry", "UserProfiles"):
            try:
                for sid, username in conn.execute(
                        "SELECT user_sid, username FROM UserProfiles"):
                    sid = sid_utils.normalize_sid(sid)
                    if sid and username and sid_utils.classify_sid(sid) == "human_candidate":
                        self._sid_to_user[sid] = str(username)
            except Exception as e:
                logger.warning("UBA: UserProfiles load failed: %s", e)

        conn = self.db_pool.get("amcache")
        if conn is not None and self.db_pool.has_table(
                "amcache", "InventoryMiscellaneousUser"):
            try:
                for username, sid in conn.execute(
                        "SELECT user_name, user_sid FROM InventoryMiscellaneousUser"):
                    sid = sid_utils.normalize_sid(sid)
                    if (sid and username
                            and sid_utils.classify_sid(sid) == "human_candidate"
                            and sid not in self._sid_to_user
                            and sid_utils.is_human_account_name(username)):
                        self._sid_to_user[sid] = str(username)
            except Exception as e:
                logger.warning("UBA: amcache user map load failed: %s", e)

        logger.info("UBA: user map has %d human profiles", len(self._sid_to_user))

    # ------------------------------------------------------------------ #
    @property
    def known_users(self) -> Dict[str, str]:
        return dict(self._sid_to_user)

    def username_for_sid(self, sid) -> Optional[str]:
        return self._sid_to_user.get(sid_utils.normalize_sid(sid))

    # ------------------------------------------------------------------ #
    def from_sid(self, sid, source_label: str) -> Tuple[str, str, str]:
        """Ladder step 1: artifact/log SID."""
        norm = sid_utils.normalize_sid(sid)
        if not norm:
            return "", "", ""
        cls = sid_utils.classify_sid(norm)
        if cls == "system":
            label = sid_utils.well_known_label(norm) or "Windows service"
            return "System", label, "{} is the well-known SID {}".format(source_label, norm)
        if cls == "human_candidate":
            username = self._sid_to_user.get(norm)
            if username:
                return ("User", username,
                        "{} SID {} maps to profile '{}'".format(source_label, norm, username))
            # Human-shaped SID but no profile on this machine: do not guess.
            return "", "", ""
        return "", "", ""

    def from_account_name(self, name, source_label: str) -> Tuple[str, str, str]:
        """Ladder step 2: an account name a parsed event-log payload carried."""
        if not name:
            return "", "", ""
        name = str(name).strip()
        if sid_utils.is_system_account_name(name):
            return "System", "Windows", "{} reports system account '{}'".format(source_label, name)
        known = set(self._sid_to_user.values())
        if name in known:
            return ("User", name,
                    "{} account '{}' matches a user profile on this machine".format(
                        source_label, name))
        # A human-looking name with no matching profile — report the name,
        # it came straight from the OS security log (still evidence-borne).
        return ("User", name, "{} recorded account '{}'".format(source_label, name))

    def from_user_hive(self, artifact_label: str,
                       sid=None) -> Tuple[str, str, str]:
        """Ladder step 3: per-user registry hive / profile artifacts."""
        if sid:
            resolved = self.from_sid(sid, artifact_label)
            if resolved[0]:
                return resolved
        # Single-profile machines: the hive owner is unambiguous.
        if len(self._sid_to_user) == 1:
            username = next(iter(self._sid_to_user.values()))
            return ("User", username,
                    "{} belongs to the only user profile on this machine ('{}')".format(
                        artifact_label, username))
        return "", "", ""

    @staticmethod
    def from_path(path) -> Tuple[str, str, str]:
        """Ladder step 4: OS-owned path -> System."""
        if not path:
            return "", "", ""
        low = str(path).lower()
        for marker in _SYSTEM_PATH_MARKERS:
            if marker in low:
                return ("System", "Windows",
                        "path '{}' is inside the Windows system area".format(path))
        return "", "", ""
