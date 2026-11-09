"""AI agent session records through the OFFLINE and IMAGE chains.

Driven through Crow-Eye's own pipeline, never around it:

    CollectionCoordinator / ImageArtifactCollector
        -> ArtifactTypeDetector ('AIAgents', by path)
        -> live_acquisition/AIAgents/<source>/Users/<name>/...
        -> ParserInvoker ('AIAgents') -> offline_AIAgentClaw -> ai_agents.db

Pinned: only the session records are typed AIAgents (never a credential file
or anything else in the agents' folders), the tree keeps its owner, one result
per user, the rows equal a direct parse of the source, and a second run adds
nothing.
"""
import glob
import hashlib
import os
import re
import shutil
import sqlite3

from Artifacts_Collectors.AI_Agent_Claw import parse_users_root
from Artifacts_Collectors.ai_agent_paths import ai_agent_path_info, ai_agent_relative_path
from Artifacts_Collectors.Offline_Importer.artifact_type_detector import ArtifactTypeDetector
from Artifacts_Collectors.tests.ai_agent_transcripts import PLANTED_SECRETS, write_users

CREDENTIALS = (os.path.join(".claude", ".credentials.json"), os.path.join(".codex", "auth.json"),
               os.path.join(".gemini", "oauth_creds.json"))
COUNT_SQL = "SELECT agent, role, kind, count(*) FROM ai_agent_steps GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"


def _source(root):
    """write_users() plus the other files an agent keeps beside its records."""
    users = write_users(root)
    home = os.path.join(users, "Alice")
    for rel, body in ((CREDENTIALS[0], '{"claudeAiOauth": "%s"}' % PLANTED_SECRETS[0]),
                      (CREDENTIALS[2], '{"refresh_token": "%s"}' % PLANTED_SECRETS[1]),
                      (os.path.join(".claude", "settings.json"), "{}"),
                      (os.path.join(".claude", "history.jsonl"), "{}\n"),
                      (os.path.join(".gemini", "settings.json"), "{}"),
                      (os.path.join(".codex", "config.toml"), "model = 'x'\n")):
        path = os.path.join(home, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
    # The Codex state database the titles come from.
    con = sqlite3.connect(os.path.join(home, ".codex", "state_5.sqlite"))
    con.execute("CREATE TABLE threads (id TEXT, title TEXT)")
    con.execute("INSERT INTO threads VALUES ('cdx-1', 'List the large files')")
    con.commit()
    con.close()
    return users


def _counts(db):
    con = sqlite3.connect(db)
    try:
        return con.execute(COUNT_SQL).fetchall(), con.execute(
            "SELECT count(*) FROM ai_agent_steps").fetchone()[0]
    finally:
        con.close()


def _direct(tmp_path, users):
    db = os.path.join(str(tmp_path), "direct", "ai_agents.db")
    parse_users_root(users, db)
    return _counts(db)


def _tree_files(case):
    base = os.path.join(case, "live_acquisition", "AIAgents")
    out = []
    for r, _d, fs in os.walk(base):
        out += [os.path.relpath(os.path.join(r, f), base).replace("\\", "/") for f in fs]
    return sorted(out)


def _parse_case(case, artifacts):
    from Artifacts_Collectors.Offline_Importer.artifact_scan_index import ScannedArtifact
    from Artifacts_Collectors.Offline_Importer.parser_invoker import ParserInvoker
    scanned = [ScannedArtifact(artifact_id=hashlib.md5(a.source_path.encode()).hexdigest()[:16],
                               artifact_type=a.artifact_type, original_path=a.source_path,
                               current_path=a.destination_path or a.source_path,
                               file_size=a.file_size, collected=bool(a.destination_path))
               for a in artifacts]
    return ParserInvoker(case).parse_artifacts_batch(scanned)


# ---------------------------------------------------------------- detection
def test_only_session_records_are_typed_ai_agents():
    det = ArtifactTypeDetector()
    home = r"E:\export\C\Users\Ann"
    typed = {
        r"\.claude\projects\C--work\1111.jsonl": "AIAgents",
        r"\.claude\projects\C--work\1111\subagents\agent-a.jsonl": "AIAgents",
        r"\.gemini\tmp\abc\chats\session-2026-01-01T00-00-x.json": "AIAgents",
        r"\.codex\sessions\2026\01\01\rollout-2026-01-01T00-00-00-x.jsonl": "AIAgents",
        r"\.codex\archived_sessions\rollout-x.jsonl.zst": "AIAgents",
        r"\.codex\state_5.sqlite": "AIAgents",
        r"\.codex\state_5.sqlite-wal": "AIAgents",
        # what the agent was allowed to do, the prompts typed, Codex's MCP
        # config, Gemini prompts with no chat file (read since 2026-11-04)
        r"\.claude\settings.json": "AIAgents",
        r"\.claude\history.jsonl": "AIAgents",
        r"\.codex\config.toml": "AIAgents",
        r"\.gemini\tmp\abc\logs.json": "AIAgents",
    }
    for rel, want in typed.items():
        assert det.detect_artifact_type(home + rel).artifact_type == want, rel
    for rel in (r"\.codex\auth.json", r"\.claude\.credentials.json", r"\.gemini\oauth_creds.json",
                r"\.gemini\settings.json", r"\.claude\projects\C--work\1111\tool-results\a.txt"):
        assert det.detect_artifact_type(home + rel).artifact_type != "AIAgents", rel
    assert ai_agent_relative_path(home + r"\.codex\auth.json") is None


def test_owner_is_the_evidence_user_never_the_analyst():
    p = r"C:\Users\Analyst\AppData\Local\Temp\kape\C\Users\Ann\.codex\sessions\rollout-x.jsonl"
    rel, root, vol = ai_agent_path_info(p, r"C:\Users\Analyst\AppData\Local\Temp\kape")
    assert rel.split("\\")[0] == "Ann" and vol.endswith(r"kape\C")
    # A profile ABOVE the imported folder is the analyst's: not attributed to it.
    base = r"C:\Users\Analyst\.claude"
    rel, root, _vol = ai_agent_path_info(base + r"\projects\x\1.jsonl", base)
    assert rel.startswith("_unattributed_") and root == base


# ---------------------------------------------------------------- offline folder
def test_offline_import_collects_tree_without_credentials_and_parses(tmp_path):
    from Artifacts_Collectors.Offline_Importer.collection_coordinator import CollectionCoordinator
    src = os.path.join(str(tmp_path), "evidence")
    users = _source(src)
    case = os.path.join(str(tmp_path), "case")
    os.makedirs(case)

    summary = CollectionCoordinator(case, calculate_hashes=True).collect_artifacts(src)
    ai = [a for a in summary.artifacts if a.artifact_type == "AIAgents"]
    # One result per user, pointing at the user's folder in the case tree.
    assert len(ai) == 1 and ai[0].collection_status == "success"
    assert re.search(r"[\\/]AIAgents[\\/]src_evidence_[0-9a-f]{8}[\\/]Users[\\/]Alice$",
                     ai[0].destination_path), ai[0].destination_path
    files = _tree_files(case)
    assert files and all(re.match(r"src_evidence_[0-9a-f]{8}/Users/Alice/\.(claude|gemini|codex)/", f)
                         for f in files), files
    names = {f.rsplit("/", 1)[-1] for f in files}
    assert not names & {"auth.json", ".credentials.json", "oauth_creds.json"}, names
    assert {"history.jsonl", "config.toml"} <= names, names
    assert "state_5.sqlite" in names
    # Nothing from the agents' folders went anywhere else in the case either.
    everywhere = [os.path.basename(p) for p in glob.glob(
        os.path.join(case, "live_acquisition", "**", "*"), recursive=True)]
    assert not set(everywhere) & {"auth.json", ".credentials.json", "oauth_creds.json"}

    results = _parse_case(case, summary.artifacts)
    assert [r.success for r in results if r.artifact_type == "AIAgents"] == [True]
    db = os.path.join(case, "Target_Artifacts", "ai_agents.db")
    got, total = _counts(db)
    want, want_total = _direct(tmp_path, users)
    assert got == want and total == want_total > 0
    # The secrets planted in the records never reach a row.
    con = sqlite3.connect(db)
    blob = " ".join(str(v) for row in con.execute("SELECT * FROM ai_agent_steps") for v in row)
    con.close()
    assert not any(s in blob for s in PLANTED_SECRETS)

    # Second run: collection keeps the same tree, the parse adds nothing.
    summary2 = CollectionCoordinator(case, calculate_hashes=True).collect_artifacts(src)
    assert _tree_files(case) == files
    _parse_case(case, summary2.artifacts)
    assert _counts(db) == (got, total)


def test_parse_status_finds_the_collected_tree(tmp_path):
    from Artifacts_Collectors.Offline_Importer.artifact_collector import ArtifactCollector
    from utils.parse_status import canonical_artifact, probe_sources
    assert canonical_artifact("AIAgents") == "ai_agents"
    case = os.path.join(str(tmp_path), "case")
    os.makedirs(case)
    empty = probe_sources("ai_agents", "offline", case_root=case, scanned_paths=[])
    assert empty["status"] is not None and not empty["sources"]
    _source(os.path.join(str(tmp_path), "ev"))
    ArtifactCollector(case).collect_from_directory(os.path.join(str(tmp_path), "ev"))
    found = probe_sources("ai_agents", "offline", case_root=case, scanned_paths=[])
    assert found["status"] is None and found["sources"]


# ---------------------------------------------------------------- forensic image
class _Node:
    """A folder or file of the fake image: a local tree read through the same
    calls the image collector makes on a dissect file system."""

    def __init__(self, real):
        self.real = real
        self.name = os.path.basename(real)

    def is_dir(self):
        return os.path.isdir(self.real)

    def scandir(self):
        return [_Node(os.path.join(self.real, n)) for n in sorted(os.listdir(self.real))]

    def get(self, name):
        path = os.path.join(self.real, name)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        return _Node(path)

    def stat(self):
        return os.stat(self.real)


class _FakeImage:
    def __init__(self, root):
        root_dir = root

        class _FS:
            def get(self, path):
                real = os.path.join(root_dir, *[p for p in path.split("/") if p])
                if not os.path.exists(real):
                    raise FileNotFoundError(path)
                return _Node(real)
        self.fs_info = _FS()

    def read_file_streaming(self, src, dest, compact=False):
        real = self.fs_info.get(src).real
        shutil.copyfile(real, dest)
        return os.path.getsize(dest)


def test_image_extraction_keeps_the_tree_per_partition_and_parses(tmp_path):
    from Artifacts_Collectors.crow_claw.core.artifacts import ArtifactType, get_all_artifacts
    from Artifacts_Collectors.Forensics_Image_parsing.image_collection_wrapper import ImageArtifactCollector
    img = os.path.join(str(tmp_path), "image_root")
    users = _source(img)
    case = os.path.join(str(tmp_path), "case")
    os.makedirs(case)
    art_def = [a for a in get_all_artifacts() if a.artifact_type == ArtifactType.AI_AGENTS][0]
    assert art_def.preserve_tree

    col = ImageArtifactCollector(case, False, False, False)
    col._image_path = os.path.join(str(tmp_path), "disk.e01")
    results = col._collect_preserved_tree(_FakeImage(img), art_def, 2)
    assert [(r.artifact_type, os.path.basename(r.destination_path)) for r in results] == [("AIAgents", "Alice")]
    files = _tree_files(case)
    assert files and all(re.match(r"vol_2_[0-9a-f]{8}/Users/Alice/\.(claude|gemini|codex)/", f)
                         for f in files), files
    names = {f.rsplit("/", 1)[-1] for f in files}
    assert not names & {"auth.json", ".credentials.json", "oauth_creds.json"}, names

    _parse_case(case, results)
    db = os.path.join(case, "Target_Artifacts", "ai_agents.db")
    got = _counts(db)
    assert got == _direct(tmp_path, users)
    # A second extraction + parse of the same partition adds nothing.
    col._collect_preserved_tree(_FakeImage(img), art_def, 2)
    assert _tree_files(case) == files
    _parse_case(case, results)
    assert _counts(db) == got
