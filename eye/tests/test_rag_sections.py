"""Knowledge goes in by relevant section, not whole file; USB questions get USB
knowledge (2026-11-02 review: no USB keyword existed, and whole files - the
100 KB schema reference among them - went into every step)."""

from eye.services.intent_engine import IntentEngine
from eye.services.rag_service import RAGService, SECTION_BUDGET_CHARS


def _doc():
    parts = ["# Registry knowledge\nIntro about hives.\n"]
    for name in ("UserAssist", "ShellBags", "BAM", "RecentDocs"):
        parts.append("## %s\n%s\n" % (name, ("filler about %s. " % name) * 300))
    parts.append("## USBSTOR\nUSBSTOR lists storage devices by vendor, product and serial.\n")
    return "".join(parts)


def test_small_files_go_in_whole():
    assert RAGService.relevant_sections("# t\nshort", {"usb"}, 1000) == "# t\nshort"


def test_large_files_keep_the_intro_and_the_matching_sections():
    out = RAGService.relevant_sections(_doc(), {"usbstor", "storage"}, 4000)
    assert out.startswith("# Registry knowledge")
    assert "## USBSTOR" in out
    assert "## UserAssist" not in out and "## ShellBags" not in out
    assert "not shown" in out
    assert len(out) <= 4000 + 120


def test_usb_and_other_topics_reach_their_knowledge():
    ie = IntentEngine()
    assert "registry" in ie.detect_keywords("Which USB storage devices were connected?")
    assert "eventlog" in ie.detect_keywords("Were there any failed logon attempts?")
    assert "registry" in ie.detect_keywords("When was this machine last shut down?")
    assert "registry" in ie.detect_keywords("Which Wi-Fi networks did it join?")


def test_the_schema_reference_is_sent_by_section():
    r = RAGService(embedding_client=None)
    ctx = r.retrieve_context(keywords=["Global_schema_database_Reference"],
                             user_query="Which USB storage devices were connected?", max_tokens=48000)
    assert "USBDevices" in ctx
    assert len(ctx) < 30000          # the whole reference is ~100 KB; ranked matches add a little
