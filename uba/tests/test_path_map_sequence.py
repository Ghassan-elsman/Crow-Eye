"""A reused MFT record must not lend its current file's path to the journal
events of an earlier occupant.

Older cases' mft_usn_correlated has mft_sequence_number but no volume_letter.
The path map was keyed by the record alone there, so on one real case 88,281
of 160,530 journal events took another file's path (Brave temp files read as
Epic Games files under Program Files), and every folder label built on them
was wrong.
"""
import sqlite3
from types import SimpleNamespace

from uba.engine.extractors import files


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def get(self, name):
        return self.conn

    def has_table(self, db, table):
        return True


def _ctx(columns, rows):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE mft_usn_correlated ({})".format(", ".join(columns)))
    marks = ", ".join("?" for _ in columns)
    conn.executemany("INSERT INTO mft_usn_correlated VALUES ({})".format(marks), rows)
    return SimpleNamespace(pool=_Pool(conn))


def test_sequence_without_volume_keys_by_record_and_sequence():
    # Record 56065 held a Brave temp file at sequence 19; it now holds a game
    # file at sequence 54. Only the current occupant is in the table.
    ctx = _ctx(["mft_record_number", "mft_sequence_number", "reconstructed_path"],
               [(56065, 54, "./Program Files/Epic Games/dlc.rpf")])
    path_map = files._build_path_map(ctx)
    assert ctx.corr_key_mode == "seq"
    old = files._path_key(ctx.corr_key_mode, "C", 56065, 19)
    new = files._path_key(ctx.corr_key_mode, "C", 56065, 54)
    assert path_map.get(old) is None
    assert path_map.get(new) == "./Program Files/Epic Games/dlc.rpf"


def test_full_key_when_the_volume_is_recorded():
    ctx = _ctx(["volume_letter", "mft_record_number", "mft_sequence_number",
                "reconstructed_path"],
               [("C", 5000, 3, "./Users/a/x.txt"), ("D", 5000, 3, "./data/y.txt")])
    path_map = files._build_path_map(ctx)
    assert ctx.corr_key_mode == "vol_seq"
    assert path_map[files._path_key("vol_seq", "C", 5000, 3)] == "./Users/a/x.txt"
    assert path_map[files._path_key("vol_seq", "D", 5000, 3)] == "./data/y.txt"


def test_record_only_tables_still_resolve():
    ctx = _ctx(["mft_record_number", "reconstructed_path"], [(77, "./Users/a/z.txt")])
    path_map = files._build_path_map(ctx)
    assert ctx.corr_key_mode == "rec"
    assert path_map[files._path_key("rec", None, 77, None)] == "./Users/a/z.txt"
