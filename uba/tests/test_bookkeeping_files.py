"""Files Windows and applications write and delete on their own are not a
person's file activity.

On one real case a game launcher's cache inside OneDrive\\Documents (folder
settings files and Chromium's ~RF<hex>.TMP save copies) read as "146 files
were permanently deleted in the OneDrive folder", and a git repository's
lock files as a deletion burst in Downloads. The Mass File Deletion Wing
fired on both.
"""
import pytest

from uba.engine.extractors.files import _is_bookkeeping


@pytest.mark.parametrize("name", [
    "desktop.ini", "Desktop.ini", "Thumbs.db", "ehthumbs.db", ".DS_Store",
    "TransportSecurity~RF87dde41.TMP", "the-real-index~RF87a834e.TMP",
    "config.lock", "HEAD.lock", "~$Quarterly report.docx",
])
def test_bookkeeping_files_are_recognised(name):
    assert _is_bookkeeping(name)


@pytest.mark.parametrize("name", [
    "Quarterly report.docx", "lock.txt", "evidence.log", "RFC.tmp",
    "notes~draft.txt", "config", "HEAD", "photo.jpg", "", None,
])
def test_real_files_are_kept(name):
    assert not _is_bookkeeping(name)
