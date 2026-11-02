"""
Actor attribution — the "who did this" ladder.

Order (first satisfied step wins; if nothing resolves the actor stays
EMPTY — the UI renders an explicit "Unattributed" chip; we never guess):

1. Artifact-borne SID  -> UserProfiles / amcache user map lookup.
   Well-known SIDs (S-1-5-18/19/20, DWM, UMFD...) -> System/Application.
2. Log-borne account name (already-parsed payload fields).
3. Per-user-hive artifacts (UserAssist, Shellbags, RecentDocs, LNK...) are
   inherently user-scoped -> the hive's owner (the row's user_name, or the
   profile folder the file lives in), else the profile owner when the machine
   has only one profile.
4. Path classification (System32 etc. -> System).
5. EMPTY.

Every answer is an ``Actor``: the familiar (actor_type, actor_name,
actor_basis) triple, plus the SID behind it in ``.sid``. The SID is the
person key - a name is not (``Alice``, ``alice``, ``PC\\alice`` and a
Microsoft-account e-mail are one person). It is filled only when the evidence
binds the name to exactly one profile; an ambiguous name keeps an empty SID.
"""

import logging
import ntpath
import re
from typing import Dict, Optional, Set

from uba.utils import sid_utils

logger = logging.getLogger(__name__)

# Path prefixes that identify OS-owned executables/files (lower-case).
_SYSTEM_PATH_MARKERS = (
    "c:\\windows\\system32", "c:\\windows\\syswow64", "\\systemroot\\",
    "c:\\windows\\winsxs", "c:\\windows\\servicing",
)

# Event-log account names with one well-known SID. Only these three: DWM-n,
# UMFD-n and machine accounts have per-session or per-machine SIDs that a name
# alone does not give.
_SYSTEM_NAME_SIDS = {
    "SYSTEM": "S-1-5-18",
    "LOCAL SERVICE": "S-1-5-19",
    "NETWORK SERVICE": "S-1-5-20",
}

# ...\Users\<profile folder>\... in the path of a file a user's shell wrote
# (a .lnk under Recent, a jump list under AutomaticDestinations).
_PROFILE_DIR_RE = re.compile(r"[\\/]users[\\/]([^\\/]+)[\\/]", re.IGNORECASE)

# Security events whose payload binds an account SID to the name it signed in
# under - including MicrosoftAccount e-mail names - in the same record:
# (event id, SID field index, name field index, domain field index).
_ALIAS_LAYOUTS = (
    (4624, 4, 5, 6),     # TargetUserSid, TargetUserName, TargetDomainName
    (4634, 0, 1, 2),
    (4647, 0, 1, 2),
    (4672, 0, 1, 2),     # SubjectUserSid, SubjectUserName, SubjectDomainName
)


class Actor(tuple):
    """(actor_type, actor_name, actor_basis) with the SID it rests on.

    A tuple so every existing ``a, b, c = actor`` and ``actor[0]`` keeps
    working; the SID rides along as an attribute and is read by the event
    builders with ``getattr(actor, "sid", "")``. Equality and hashing are the
    triple's, so grouping by actor is unchanged.
    """

    def __new__(cls, actor_type="", actor_name="", actor_basis="", sid=""):
        obj = super().__new__(cls, (actor_type or "", actor_name or "",
                                    actor_basis or ""))
        obj.sid = sid or ""
        return obj


EMPTY = Actor()


class ActorResolver:
    """Resolves Actor tuples (type, name, basis, .sid)."""

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self._sid_to_user: Dict[str, str] = {}
        # Profile folder name (lower-case) -> SID, from ProfileList's
        # ProfileImagePath. A profile folder is not always the account name
        # (a Microsoft account's folder is the first five letters of it).
        self._folder_to_sid: Dict[str, Set[str]] = {}
        self._aliases: Optional[Dict[str, Set[str]]] = None
        self._load_user_maps()

    # ------------------------------------------------------------------ #
    def _load_user_maps(self):
        """UserProfiles (registry) + amcache InventoryMiscellaneousUser."""
        conn = self.db_pool.get("registry")
        if conn is not None and self.db_pool.has_table("registry", "UserProfiles"):
            folder_cols = [c for c in ("profile_image_path", "profile_path")
                           if self.db_pool.has_column("registry", "UserProfiles", c)]
            select = ", ".join(["user_sid", "username"] + folder_cols)
            try:
                for row in conn.execute("SELECT {} FROM UserProfiles".format(select)):
                    sid = sid_utils.normalize_sid(row[0])
                    username = row[1]
                    if sid and username and sid_utils.classify_sid(sid) == "human_candidate":
                        self._sid_to_user[sid] = str(username)
                        for folder in row[2:]:
                            name = ntpath.basename(str(folder or "").rstrip("\\/"))
                            if name:
                                self._folder_to_sid.setdefault(name.lower(), set()).add(sid)
            except Exception as e:
                logger.warning("UBA: UserProfiles load failed: %s", e)

        # AmCache's user inventory. The columns are 'original_name' (the account
        # name) and 'user_id' (the SID) — this query used to ask for
        # 'user_name, user_sid', which do not exist, so it raised on every case
        # and the except below swallowed it: the fallback had never once run.
        # has_column is what keeps a schema guess from failing silently again.
        conn = self.db_pool.get("amcache")
        if (conn is not None
                and self.db_pool.has_column("amcache", "InventoryMiscellaneousUser",
                                            "original_name")
                and self.db_pool.has_column("amcache", "InventoryMiscellaneousUser",
                                            "user_id")):
            try:
                for username, sid in conn.execute(
                        "SELECT original_name, user_id FROM InventoryMiscellaneousUser"):
                    sid = sid_utils.normalize_sid(sid)
                    if (sid and username
                            and sid_utils.classify_sid(sid) == "human_candidate"
                            and sid not in self._sid_to_user
                            and sid_utils.is_human_account_name(username)):
                        self._sid_to_user[sid] = str(username)
            except Exception as e:
                logger.warning("UBA: amcache user map load failed: %s", e)

        logger.info("UBA: user map has %d human profiles", len(self._sid_to_user))

    def _load_aliases(self) -> Dict[str, Set[str]]:
        """Other names the Security log shows a profile's SID signing in under.

        A Microsoft account signs in as its e-mail address (domain
        'MicrosoftAccount') and a domain account as DOMAIN\\name. The record
        that carries the name also carries the SID, so the evidence itself
        binds the two - nothing is inferred from the spelling. Built lazily:
        only names that do not match a profile directly ever need it.
        """
        aliases: Dict[str, Set[str]] = {}
        conn = self.db_pool.get("logs")
        if conn is None or not self.db_pool.has_table("logs", "SecurityLogs"):
            return aliases
        layouts = {eid: (s, n, d) for eid, s, n, d in _ALIAS_LAYOUTS}
        marks = ",".join("?" for _ in layouts)
        try:
            rows = conn.execute(
                "SELECT DISTINCT EventID, substr(Keywords, 1, 400) FROM SecurityLogs "
                "WHERE EventID IN ({})".format(marks), list(layouts)).fetchall()
        except Exception as e:
            logger.debug("UBA: alias scan failed: %s", e)
            return aliases
        for eid, keywords in rows:
            parts = [p.strip() for p in str(keywords or "").split(",")]
            s_i, n_i, d_i = layouts.get(eid, (None, None, None))
            if s_i is None or len(parts) <= max(s_i, n_i, d_i):
                continue
            sid = sid_utils.normalize_sid(parts[s_i])
            name, domain = parts[n_i], parts[d_i]
            if sid not in self._sid_to_user or not sid_utils.is_human_account_name(name):
                continue
            aliases.setdefault(name.lower(), set()).add(sid)
            if domain and domain not in ("-",):
                aliases.setdefault("{}\\{}".format(domain, name).lower(), set()).add(sid)
        logger.info("UBA: %d sign-in name alias(es) bound to profile SIDs", len(aliases))
        return aliases

    # ------------------------------------------------------------------ #
    @property
    def known_users(self) -> Dict[str, str]:
        return dict(self._sid_to_user)

    def username_for_sid(self, sid) -> Optional[str]:
        return self._sid_to_user.get(sid_utils.normalize_sid(sid))

    def sid_for_account(self, name) -> str:
        """The profile SID an account name denotes, or '' when not certain.

        Matches, in order: the profile's own name (case-insensitive), a
        DOMAIN\\name or name@domain whose name part is a profile name, and a
        name the Security log recorded signing in with that SID (e-mail,
        DOMAIN\\name). Any step that finds two profiles stops with ''.
        """
        if not name:
            return ""
        text = str(name).strip()
        if not text:
            return ""
        low = text.lower()

        def _one(sids):
            return next(iter(sids)) if len(sids) == 1 else ""

        direct = {s for s, u in self._sid_to_user.items() if u.lower() == low}
        if direct:
            return _one(direct)
        if "\\" in text:
            tail = low.rsplit("\\", 1)[1]
            by_tail = {s for s, u in self._sid_to_user.items() if u.lower() == tail}
            if by_tail:
                return _one(by_tail)
        if self._aliases is None:
            self._aliases = self._load_aliases()
        return _one(self._aliases.get(low, set()))

    def sid_for_profile_owner(self, owner) -> str:
        """SID of the profile an artifact row says it belongs to.

        ``owner`` is a row's user_name (a name, or a SID when the parser could
        not resolve one) or a profile folder name. '' when no single profile
        answers.
        """
        if not owner:
            return ""
        text = str(owner).strip()
        norm = sid_utils.normalize_sid(text)
        if norm in self._sid_to_user:
            return norm
        sid = self.sid_for_account(text)
        if sid:
            return sid
        folder = self._folder_to_sid.get(text.lower(), set())
        return next(iter(folder)) if len(folder) == 1 else ""

    @staticmethod
    def profile_folder_in(path) -> str:
        """'<name>' from a path containing ...\\Users\\<name>\\..., else ''.

        The LAST such segment: a collected copy lives under the examiner's own
        profile (C:\\Users\\<examiner>\\Downloads\\<case>\\...\\Users\\<owner>\\...),
        and the owner is the one nearest the file.
        """
        found = _PROFILE_DIR_RE.findall(str(path or ""))
        return found[-1] if found else ""

    # ------------------------------------------------------------------ #
    def from_sid(self, sid, source_label: str) -> Actor:
        """Ladder step 1: artifact/log SID."""
        norm = sid_utils.normalize_sid(sid)
        if not norm:
            return Actor()
        cls = sid_utils.classify_sid(norm)
        if cls == "system":
            label = sid_utils.well_known_label(norm) or "Windows service"
            return Actor("System", label,
                         "{} is the well-known SID {}".format(source_label, norm), norm)
        if cls == "human_candidate":
            username = self._sid_to_user.get(norm)
            if username:
                return Actor("User", username,
                             "{} SID {} maps to profile '{}'".format(
                                 source_label, norm, username), norm)
            # Human-shaped SID but no profile on this machine: do not guess.
            return Actor()
        return Actor()

    def from_account_name(self, name, source_label: str) -> Actor:
        """Ladder step 2: an account name a parsed event-log payload carried."""
        if not name:
            return Actor()
        name = str(name).strip()
        if sid_utils.is_system_account_name(name):
            return Actor("System", "Windows",
                         "{} reports system account '{}'".format(source_label, name),
                         _SYSTEM_NAME_SIDS.get(name.upper(), ""))
        sid = self.sid_for_account(name)
        if sid:
            profile = self._sid_to_user[sid]
            if profile == name:
                basis = ("{} account '{}' matches a user profile on this machine "
                         "(SID {})".format(source_label, name, sid))
            else:
                basis = ("{} account '{}' is the user profile '{}' on this machine "
                         "(SID {})".format(source_label, name, profile, sid))
            return Actor("User", profile, basis, sid)
        # A human-looking name with no matching profile — report the name,
        # it came straight from the OS security log (still evidence-borne).
        # No SID: a name that matches no profile, or two, binds to nobody.
        return Actor("User", name, "{} recorded account '{}'".format(source_label, name))

    def from_user_hive(self, artifact_label: str, sid=None, owner=None) -> Actor:
        """Ladder step 3: per-user registry hive / profile artifacts.

        ``sid`` is a SID the row carries; ``owner`` is the row's user_name or
        the profile folder its file lives in. When an owner is named and does
        not resolve, the actor stays empty rather than falling back to the
        only profile - the row has said it belongs to someone else.
        """
        if sid:
            resolved = self.from_sid(sid, artifact_label)
            if resolved[0]:
                return resolved
        if owner:
            owner_sid = self.sid_for_profile_owner(owner)
            if owner_sid:
                username = self._sid_to_user[owner_sid]
                return Actor("User", username,
                             "{} belongs to the profile of '{}' (SID {})".format(
                                 artifact_label, username, owner_sid), owner_sid)
            return Actor()
        # Single-profile machines: the hive owner is unambiguous.
        if len(self._sid_to_user) == 1:
            only_sid, username = next(iter(self._sid_to_user.items()))
            return Actor("User", username,
                         "{} belongs to the only user profile on this machine ('{}')".format(
                             artifact_label, username), only_sid)
        return Actor()

    @staticmethod
    def from_path(path) -> Actor:
        """Ladder step 4: OS-owned path -> System."""
        if not path:
            return Actor()
        low = str(path).lower()
        for marker in _SYSTEM_PATH_MARKERS:
            if marker in low:
                return Actor("System", "Windows",
                             "path '{}' is inside the Windows system area".format(path))
        return Actor()
