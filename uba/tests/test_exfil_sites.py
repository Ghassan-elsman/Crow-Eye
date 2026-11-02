"""The upload endpoints data is posted to are file-sharing sites here.

A Discord or Slack webhook, a Telegram bot's API, webhook.site and the
temporary file drops take a file with one request, so a browser visit to one
is asked about (2026-11-01, with Sentinel's site targets). Discord itself is
ordinary chat and stays unlisted: only its webhook path is a drop.
"""
from uba.engine import site_categories as S


def test_webhook_and_drop_endpoints_are_file_sharing():
    for url in ("https://discord.com/api/webhooks/1/abc",
                "https://discordapp.com/api/webhooks/1/abc",
                "https://hooks.slack.com/services/T0/B0/x",
                "https://api.telegram.org/bot1:x/sendDocument",
                "https://webhook.site/0000", "https://eo1.m.pipedream.net/",
                "https://tmpfiles.org/dl/1/x.zip", "https://uploadfiles.io/x"):
        assert S.categorize(url) == "file_sharing", url


def test_ordinary_chat_is_not():
    assert S.categorize("https://discord.com/channels/1/2") is None
    assert S.categorize("https://app.slack.com/client/T0") is None


def test_a_tunnel_host_is_remote_access():
    assert S.categorize("https://abc.loclx.io/") == "remote_access"


def test_the_list_still_validates():
    assert S.validate(S.load()) == []
