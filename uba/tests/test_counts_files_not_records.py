"""UBA counts files, names unknown folders honestly, reads times correctly.

Measured on a real case: NTFS writes several journal records for one change
of one file, and every record was counted - "5000 files were created" was
about 1,500 files, edits were overstated ~19x. 141,398 records whose folder
had not been read were said to be "in the drive root". A bare "6" became
2001-01-01 00:00:06, and '+03:00' was dropped without converting.
"""
from uba.engine import aggregation, description
from uba.engine.extractors import files as F
from uba.utils.timeparse import normalize_ts


def _row(i, frn, reason="FILE_CREATE", path="./Users/a/Desktop/x.txt"):
    return aggregation.usn_row_from_db(i, "C", "f%d.txt" % i, i, frn, "5",
                                       "2026-10-08 10:00:%02d" % (i % 60), reason, path)


def test_a_burst_counts_distinct_files():
    rows = [_row(1, "100"), _row(2, "100", "DATA_EXTEND | FILE_CREATE"),
            _row(3, "100", "DATA_EXTEND | FILE_CREATE | CLOSE"), _row(4, "200")]
    burst = aggregation.Burst(volume="C", folder_bucket="Desktop", op=aggregation.OP_CREATE,
                              rows=rows)
    assert burst.file_count() == 2


def test_burst_text_says_files_and_records():
    rows = [_row(i, str(100 + i // 3)) for i in range(9)]
    burst = aggregation.Burst(volume="C", folder_bucket="Alice's Desktop",
                              op=aggregation.OP_CREATE, rows=rows)

    class Ctx:
        resolver = type("R", (), {"known_users": {}})()

        def session_context(self, ts):
            return ""
    rule = {"id": "file_created", "behavior_class": "file", "activity": "file_created",
            "severity": "info"}
    ev = F._burst_event(Ctx(), {"file_created": rule}, burst)
    assert ev.description.startswith("3 files were created in Alice's Desktop")
    assert "(9 journal records)" in ev.description
    assert ev.aggregate_count == 3


def test_an_unknown_folder_is_not_the_drive_root():
    assert description.folder_label(None) == "an unknown folder"
    assert description.folder_label("report.docx") == "an unknown folder"
    assert description.folder_label("[Unknown Parent: 4711]/x.txt") == "an unknown folder"
    assert description.folder_label("./x.txt") == "the drive root"
    assert description.folder_label(".") == "the drive root"


def test_frn_reference_decodes_v2_and_v3():
    ref = (7 << 48) | 123456
    assert F._mft_ref(str(ref)) == (123456, 7)
    assert F._mft_ref("%016x%016x" % (0, ref)) == (123456, 7)
    assert F._mft_ref("") is None


def test_small_numbers_are_not_cocoa_times():
    assert normalize_ts("6") is None
    assert normalize_ts(0.5) is None


def test_offsets_are_converted_to_utc():
    assert normalize_ts("2026-10-08T09:25:00+03:00") == "2026-10-08 06:25:00"
