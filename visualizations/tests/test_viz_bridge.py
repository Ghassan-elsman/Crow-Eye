"""Tests for the SRUM visualization bridge queries.

Builds a tiny srum_data.db fixture and checks that the contribution aggregation,
the multi-term AND/OR search, and the day-detail shape are correct.
"""
import os
import json
import sqlite3
import tempfile
import unittest


def _make_db(path):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("""CREATE TABLE srum_application_usage (
        id INTEGER PRIMARY KEY, timestamp TEXT, app_name TEXT, app_path TEXT,
        user_name TEXT, user_sid TEXT, foreground_cycle_time INTEGER,
        background_cycle_time INTEGER)""")
    c.execute("""CREATE TABLE srum_network_data_usage (
        id INTEGER PRIMARY KEY, timestamp TEXT, app_name TEXT, app_path TEXT,
        user_name TEXT, user_sid TEXT, bytes_sent INTEGER, bytes_received INTEGER)""")
    c.execute("""CREATE TABLE srum_app_timeline (
        id INTEGER PRIMARY KEY, timestamp TEXT, app_name TEXT, app_path TEXT,
        user_name TEXT, user_sid TEXT, keyboard_input_s INTEGER,
        mouse_input_s INTEGER, in_focus_s INTEGER)""")
    # Day 1: 3 app rows (2 chrome, 1 powershell), 2 net rows, 1 timeline w/ input.
    au = [
        ("2026-01-01 09:00:00", "chrome.exe", r"C:\chrome.exe", "PC\\a", "S-1-1", 10, 1),
        ("2026-01-01 10:00:00", "chrome.exe", r"C:\chrome.exe", "PC\\a", "S-1-1", 20, 2),
        ("2026-01-01 11:00:00", "powershell.exe", r"C:\ps.exe", "PC\\a", "S-1-1", 5, 0),
        ("2026-01-02 09:00:00", "svchost.exe", r"C:\svchost.exe", "PC\\b", "S-1-2", 1, 1),
    ]
    c.executemany("INSERT INTO srum_application_usage "
                  "(timestamp,app_name,app_path,user_name,user_sid,foreground_cycle_time,background_cycle_time) "
                  "VALUES (?,?,?,?,?,?,?)", au)
    nd = [
        ("2026-01-01 09:00:00", "chrome.exe", r"C:\chrome.exe", "PC\\a", "S-1-1", 1000, 2000),
        ("2026-01-01 10:00:00", "chrome.exe", r"C:\chrome.exe", "PC\\a", "S-1-1", 500, 500),
    ]
    c.executemany("INSERT INTO srum_network_data_usage "
                  "(timestamp,app_name,app_path,user_name,user_sid,bytes_sent,bytes_received) "
                  "VALUES (?,?,?,?,?,?,?)", nd)
    c.execute("INSERT INTO srum_app_timeline "
              "(timestamp,app_name,app_path,user_name,user_sid,keyboard_input_s,mouse_input_s,in_focus_s) "
              "VALUES ('2026-01-01 09:00:00','chrome.exe',?,?,?,30,10,120)",
              (r"C:\chrome.exe", "PC\\a", "S-1-1"))
    conn.commit()
    conn.close()


class VizBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # QObject needs a QApplication.
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        from visualizations.viz_bridge import VizBridge
        cls.VizBridge = VizBridge

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="vizt_")
        _make_db(os.path.join(self.dir, "srum_data.db"))
        self.b = self.VizBridge(self.dir)

    def test_bounds(self):
        r = json.loads(self.b.getSrumBounds())
        self.assertTrue(r["hasData"])
        self.assertEqual(r["minDate"], "2026-01-01")
        self.assertEqual(r["maxDate"], "2026-01-02")
        self.assertEqual(r["providers"]["application_usage"], 4)

    def test_heatmaps(self):
        r = json.loads(self.b.getSrumHeatmaps(json.dumps({})))
        au = {d["day"]: d["value"] for d in r["providers"]["application_usage"]["days"]}
        self.assertEqual(au["2026-01-01"], 3)     # 3 app_usage rows on day 1
        self.assertEqual(au["2026-01-02"], 1)
        self.assertEqual(r["providers"]["application_usage"]["max"], 3)
        nd = {d["day"]: d["value"] for d in r["providers"]["network_data"]["days"]}
        self.assertEqual(nd["2026-01-01"], 2)     # 2 network rows on day 1
        combined = {d["day"]: d["value"] for d in r["combined"]}
        self.assertEqual(combined["2026-01-01"], 3 + 2 + 1)   # app + net + timeline
        # search narrows every provider
        r2 = json.loads(self.b.getSrumHeatmaps(json.dumps({"terms": ["powershell"], "mode": "or"})))
        au2 = {d["day"]: d["value"] for d in r2["providers"]["application_usage"]["days"]}
        self.assertEqual(au2.get("2026-01-01"), 1)

    def test_day_detail(self):
        r = json.loads(self.b.getSrumDayDetail(json.dumps({"day": "2026-01-01"})))
        self.assertEqual(sum(r["hourly"]), 3)
        self.assertEqual(r["hourly"][9], 1)
        self.assertEqual(r["perProvider"]["application_usage"], 3)
        self.assertEqual(r["presence"], {"keyboard": 30, "mouse": 10, "focus": 120})
        apps = {a["app"]: a["windows"] for a in r["topApps"]}
        self.assertEqual(apps["chrome.exe"], 2)
        # per-provider hourly + top-apps splits
        self.assertEqual(r["hourlyByProvider"]["application_usage"][9], 1)
        self.assertEqual(r["hourlyByProvider"]["network_data"][9], 1)
        chrome = [a for a in r["topAppsByProvider"] if a["app"] == "chrome.exe"][0]
        self.assertEqual(chrome["counts"]["application_usage"], 2)
        self.assertEqual(chrome["counts"]["network_data"], 2)

    def test_day_activity_merges_and_hours(self):
        r = json.loads(self.b.getSrumDayActivity(json.dumps({"day": "2026-01-01", "topN": 10})))
        self.assertEqual(r["day"], "2026-01-01")
        self.assertIn("chrome.exe", r["apps"])
        # chrome ran at hours 9 and 10 that day; hour 9 carries all three providers
        h9 = [p for p in r["points"] if p["app"] == "chrome.exe" and p["h"] == 9]
        self.assertTrue(h9)
        p = h9[0]
        self.assertEqual(p["bytesSent"], 1000)
        self.assertEqual(p["bytesReceived"], 2000)
        self.assertEqual(p["cpu"], 11)                # 10 + 1
        self.assertEqual(p["focusS"], 120)
        hours = sorted({p["h"] for p in r["points"] if p["app"] == "chrome.exe"})
        self.assertEqual(hours, [9, 10])
        self.assertIn("chrome.exe", r["ranges"])

    def test_day_activity_topn_and_search(self):
        r = json.loads(self.b.getSrumDayActivity(json.dumps({"day": "2026-01-01", "topN": 1})))
        self.assertEqual(len(r["apps"]), 1)           # capped
        r2 = json.loads(self.b.getSrumDayActivity(json.dumps({"day": "2026-01-01", "topN": 10, "terms": ["powershell"], "mode": "or"})))
        self.assertEqual(set(r2["apps"]), {"powershell.exe"})

    def test_overview(self):
        r = json.loads(self.b.getSrumOverview(json.dumps({})))
        t = r["totals"]
        self.assertEqual(t["bytesSent"], 1500)        # only chrome sent, both days
        self.assertEqual(t["bytesReceived"], 2500)
        self.assertEqual(t["cpu"], 33 + 5 + 2)        # chrome(33) + powershell(5) + svchost(2)
        self.assertEqual(t["activeDays"], 2)
        self.assertEqual(t["apps"], 3)                # chrome, powershell, svchost
        self.assertEqual(r["providerTotals"]["application_usage"], 4)
        apps = {a["app"]: a for a in r["topApps"]}
        self.assertTrue({"chrome.exe", "powershell.exe", "svchost.exe"} <= set(apps))
        # per-provider counts attached for the stacked bars
        self.assertEqual(apps["chrome.exe"]["counts"]["application_usage"], 2)
        self.assertEqual(apps["chrome.exe"]["counts"]["network_data"], 2)
        users = {u["user"] for u in r["byUser"]}
        self.assertTrue({"PC\\a", "PC\\b"} <= users)
        # network activity: per-day sent/received + top network apps
        nbd = {d["day"]: d for d in r["networkByDay"]}
        self.assertEqual(sum(d["sent"] for d in r["networkByDay"]), 1500)
        self.assertEqual(sum(d["received"] for d in r["networkByDay"]), 2500)
        tna = {a["app"]: a for a in r["topNetworkApps"]}
        self.assertIn("chrome.exe", tna)
        self.assertEqual(tna["chrome.exe"]["sent"], 1500)
        self.assertEqual(tna["chrome.exe"]["received"], 2500)

    def test_app_detail(self):
        r = json.loads(self.b.getSrumAppDetail(json.dumps({"app": "chrome.exe"})))
        self.assertEqual(r["app"], "chrome.exe")
        self.assertEqual(r["totals"]["bytesSent"], 1500)
        self.assertEqual(r["totals"]["bytesReceived"], 2500)
        self.assertEqual(r["totals"]["cpu"], 33)
        # radar is share-of-total; chrome is the only net sender so netOut share = 100
        self.assertEqual(r["radar"]["netOut"], 100.0)
        users = {u["user"] for u in r["byUser"]}
        self.assertIn("PC\\a", users)


if __name__ == "__main__":
    unittest.main()
