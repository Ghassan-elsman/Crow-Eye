"""
The Narrative Map seed (build_evidence_map.py) must NOT turn the triage's
"System Identity" / "Immediate Technical Observations" report blocks into
verdict-linked narratives — they are surfaced as floating GLOBAL cards instead,
so they don't appear twice on the map.
"""

import json
import tempfile
import shutil
import unittest
from pathlib import Path

from eye.ui.react.src.build_evidence_map import build


class TestSeedSkipsTriageGlobals(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        logs = Path(self.dir) / "EYE_Logs"
        logs.mkdir(parents=True)
        workspace = {
            "blocks": [
                {"block_id": "b1", "title": "System Identity",
                 "markdown_content": "Host: PC1\nOS: Windows 11"},
                {"block_id": "b2", "title": "Immediate Technical Observations",
                 "markdown_content": "High SRUM egress observed."},
                {"block_id": "b3", "title": "Discord Exfiltration",
                 "markdown_content": "Discord sent 4.2 MB outbound."},
            ]
        }
        (logs / "eye_report_workspace.json").write_text(json.dumps(workspace), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_triage_global_blocks_are_not_narratives(self):
        graph = build(Path(self.dir))
        # The seed renames the block title to the node's `data` field.
        titles = [n.get("data") for n in graph["narratives"]]
        self.assertNotIn("System Identity", titles)
        self.assertNotIn("Immediate Technical Observations", titles)
        # The real finding IS kept.
        self.assertIn("Discord Exfiltration", titles)


if __name__ == "__main__":
    unittest.main()
