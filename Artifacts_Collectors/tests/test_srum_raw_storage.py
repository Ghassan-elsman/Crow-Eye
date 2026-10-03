"""SRUM stores raw numbers; the display layer formats them.

The `format_bytes` / `format_cpu_time` / `format_time_duration` / `format_charge_level` /
`format_number` helpers live in `SRUM_Claw.py` for ONE reason: `ui/virtual_table_widget.py`
imports them and formats raw column values at render time (`DISPLAY_FORMATTERS`). If a parser
ever calls one of them on a value it then INSERTs, a formatted string lands in an INTEGER
column - SQLite keeps it as TEXT, TEXT sorts above every integer, and `SUM()` / `> ` silently
stop meaning anything (this is exactly why the SRUM visualisation's byte/CPU totals were wrong
on an old case DB). These tests freeze the correct split so it cannot regress.

Source-level, so they need no ESE library, no hive and no Windows.
"""
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIVE = os.path.join(REPO, "Artifacts_Collectors", "SRUM_Claw.py")
OFFLINE = os.path.join(REPO, "Artifacts_Collectors", "offline_parsers", "offline_SRUM_Claw.py")
DISPLAY = os.path.join(REPO, "ui", "virtual_table_widget.py")

FORMATTERS = ("format_bytes", "format_cpu_time", "format_time_duration",
              "format_charge_level", "format_number")

# The core money columns whose display formatting must never silently disappear.
CORE_FORMATTED_COLUMNS = ("bytes_sent", "bytes_received", "foreground_bytes_read",
                          "foreground_cycle_time", "background_cycle_time",
                          "connected_time", "charge_level")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _formatter_calls(path):
    """Every `format_X(` in the file that is not the helper's own `def`."""
    src = _read(path)
    bad = []
    for name in FORMATTERS:
        for m in re.finditer(r"\b%s\s*\(" % name, src):
            if src[max(0, m.start() - 4):m.start()] == "def ":
                continue  # the definition itself (only in SRUM_Claw.py)
            line = src[:m.start()].count("\n") + 1
            bad.append("%s:%d %s(" % (os.path.basename(path), line, name))
    return bad


class TestSrumRawStorage(unittest.TestCase):

    def test_parsers_never_call_the_display_formatters(self):
        bad = _formatter_calls(LIVE) + _formatter_calls(OFFLINE)
        self.assertEqual(
            bad, [],
            "a SRUM parser calls a display formatter, so a formatted string would be stored "
            "in an INTEGER column (SUM/ordering then break). Store the raw value and let "
            "ui/virtual_table_widget.py format it:\n  " + "\n  ".join(bad))

    def test_metric_columns_are_declared_integer(self):
        """The columns the display layer formats must have INTEGER affinity."""
        src = _read(LIVE)
        for col in CORE_FORMATTED_COLUMNS:
            self.assertRegex(
                src, r"\b%s\s+INTEGER\b" % col,
                "%s should be declared INTEGER so raw numbers keep numeric affinity" % col)

    def test_display_layer_still_formats_the_core_columns(self):
        """DISPLAY_FORMATTERS must keep mapping the core metrics, or the GUI shows bare ints."""
        disp = _read(DISPLAY)
        for col in CORE_FORMATTED_COLUMNS:
            self.assertIn(
                "'%s'" % col, disp,
                "%s dropped from DISPLAY_FORMATTERS - the GUI would show a raw integer" % col)


if __name__ == "__main__":
    unittest.main()
