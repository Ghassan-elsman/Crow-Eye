from uba.utils import sid_utils, log_parser


def test_pysid_prefix_stripped():
    assert sid_utils.normalize_sid("PySID:S-1-5-21-1-2-3-1001") == "S-1-5-21-1-2-3-1001"
    assert sid_utils.normalize_sid("  S-1-5-18  ") == "S-1-5-18"
    assert sid_utils.normalize_sid("-") == ""
    assert sid_utils.normalize_sid(None) == ""


def test_wellknown_sids_are_system():
    for sid in ("S-1-5-18", "S-1-5-19", "S-1-5-20", "S-1-5-90-0-1", "S-1-5-96-0-0"):
        assert sid_utils.classify_sid(sid) == "system"


def test_human_sid_shape():
    assert sid_utils.classify_sid("S-1-5-21-111-222-333-1001") == "human_candidate"
    assert sid_utils.classify_sid("S-1-5-21-111-222-333-500") == "human_candidate"


def test_machine_and_pseudo_accounts_are_system():
    assert sid_utils.is_machine_account("DAN$")
    assert sid_utils.is_system_account_name("SYSTEM")
    assert sid_utils.is_system_account_name("LOCAL SERVICE")
    assert sid_utils.is_system_account_name("DWM-1")
    assert sid_utils.is_system_account_name("UMFD-0")
    assert not sid_utils.is_human_account_name("DAN$")
    assert sid_utils.is_human_account_name("Alice")


def test_parse_4624_extracts_interactive_type():
    kw = ("S-1-5-18,PC$,WG,0x3e7,S-1-5-21-111-222-333-1001,Alice,PC,0x5fc1d,2,"
          "User32,Negotiate,-,-,-,-,0,0x0,C:\\Windows\\System32\\winlogon.exe,-,-")
    info = log_parser.parse_4624(kw)
    assert info["target_user"] == "Alice"
    assert info["logon_type"] == "2"
    assert info["logon_id"] == "0x5fc1d"
    assert "2" in log_parser.INTERACTIVE_LOGON_TYPES


def test_parse_4688_recovers_process_and_parent():
    kw = ("S-1-5-21-111-222-333-1001,Alice,PC,0x5fc1d,0x111,C:\\Apps\\notepad.exe,"
          "%%1936,0x30c,,S-1-0-0,-,-,0x0,C:\\Windows\\explorer.exe,S-1-16-8192")
    info = log_parser.parse_4688(kw)
    assert info["new_process_name"] == "C:\\Apps\\notepad.exe"
    assert info["parent_process_name"] == "C:\\Windows\\explorer.exe"
    assert info["subject_user"] == "Alice"


def test_parse_payload_bad_input_returns_empty():
    assert log_parser.parse_payload(4624, "") == {}
    assert log_parser.parse_payload(9999, "a,b,c") == {}
    assert log_parser.parse_payload(4688, "too,few") == {}
