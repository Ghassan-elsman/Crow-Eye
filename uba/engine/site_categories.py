"""Site categories for the browser rules - data in uba/config/site_categories.json.

``categorize(host)``  -> category key ("file_sharing", "paste", ...) or None
``search_term(url)``  -> (engine name, the words searched) or None
``is_raw_ip(host)``   -> a literal IPv4/IPv6 address instead of a name
``validate(data)``    -> list of problems in a categories file (empty = fine)

Matching is by host: a host is in a category when it IS a listed domain or a
subdomain of one ('drive.google.com' does not put all of google.com in
file-sharing). '*.onion' matches subdomains only. An entry may carry a path
('huggingface.co/chat'), matched as a prefix of the URL's path. 'exclude' wins
over every list.
"""
import ipaddress
import json
import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote_plus, urlsplit

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "config", "site_categories.json")

_DATA = None
_INDEX = None


def load(path: str = None) -> dict:
    global _DATA, _INDEX
    if path is None and _DATA is not None:
        return _DATA
    with open(path or PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if path is None:
        _DATA, _INDEX = data, None
    return data


def reload():
    global _DATA, _INDEX
    _DATA, _INDEX = None, None


def _index():
    """[(category, host, path_prefix, wildcard)], [(category, host)] excludes."""
    global _INDEX
    if _INDEX is None:
        entries, excludes = [], []
        for cat, spec in (load().get("categories") or {}).items():
            for d in spec.get("domains") or []:
                d = d.strip().lower()
                wildcard = d.startswith("*.")
                d = d[2:] if wildcard else d
                host, _, path = d.partition("/")
                entries.append((cat, host, ("/" + path) if path else "", wildcard))
            for d in spec.get("exclude") or []:
                excludes.append((cat, d.strip().lower().lstrip("*.")))
        _INDEX = (entries, excludes)
    return _INDEX


def _split(url_or_host: str) -> Tuple[str, str]:
    text = str(url_or_host or "").strip()
    if not text:
        return "", ""
    if "://" not in text:
        text = "http://" + text
    try:
        parts = urlsplit(text)
        host = (parts.hostname or "").lower().rstrip(".")
        return host, parts.path or "/"
    except ValueError:
        return "", ""


def normalize_host(url_or_host: str) -> str:
    """'https://WWW.Example.com:8443/x' -> 'example.com' ('www.' dropped)."""
    host, _ = _split(url_or_host)
    return host[4:] if host.startswith("www.") else host


def _under(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def categorize(url_or_host: str) -> Optional[str]:
    """The category of a URL or host, or None."""
    host, path = _split(url_or_host)
    if not host:
        return None
    entries, excludes = _index()
    if any(_under(host, d) for _c, d in excludes):
        return None
    best = None
    for cat, domain, prefix, wildcard in entries:
        if wildcard:
            hit = host.endswith("." + domain)
        else:
            hit = _under(host, domain)
        if hit and (not prefix or path.lower().startswith(prefix)):
            # The most specific (longest) domain wins: drive.google.com over google.com.
            if best is None or len(domain) > best[1]:
                best = (cat, len(domain))
    return best[0] if best else None


def category_label(cat: str) -> str:
    spec = (load().get("categories") or {}).get(cat) or {}
    return spec.get("label") or (cat or "").replace("_", " ")


def search_term(url: str) -> Optional[Tuple[str, str]]:
    """(engine, words) when ``url`` is a search on a known engine."""
    text = str(url or "")
    if "?" not in text:
        return None
    host, path = _split(text)
    if not host:
        return None
    try:
        query = parse_qs(urlsplit(text if "://" in text else "http://" + text).query)
    except ValueError:
        return None
    for eng in load().get("search_engines") or []:
        h = eng.get("host", "").lower()
        hit = (host.startswith(h) or (".%s" % h) in ("." + host)) if h.endswith(".") \
            else _under(host, h)
        if not hit:
            continue
        if eng.get("path") and not path.lower().startswith(eng["path"]):
            continue
        for p in eng.get("params") or []:
            vals = query.get(p)
            if vals and vals[0].strip():
                words = re.sub(r"\s+", " ", unquote_plus(vals[0])).strip()
                return eng.get("name") or h, words[:200]
    return None


def is_raw_ip(url_or_host: str) -> bool:
    host, _ = _split(url_or_host)
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def electron_app(name: str) -> Optional[str]:
    """Display name when ``name`` (the parser's browser column) is a chat app."""
    return (load().get("electron_apps") or {}).get(str(name or "").strip().lower())


def wallet_extension(extension_id: str, name: str = "") -> Optional[str]:
    """Wallet display name for an extension, by its id or (fallback) its name."""
    data = load()
    by_id = data.get("wallet_extensions") or {}
    if extension_id and extension_id.lower() in by_id:
        return by_id[extension_id.lower()]
    low = str(name or "").lower()
    for word in data.get("wallet_name_words") or []:
        if word in low:
            return name
    return None


def validate(data: dict) -> List[str]:
    """Problems in a categories document; the rule loader refuses to start on any."""
    problems = []
    if not isinstance(data.get("categories"), dict) or not data["categories"]:
        return ["no categories"]
    seen: Dict[str, str] = {}
    for cat, spec in data["categories"].items():
        if not re.fullmatch(r"[a-z_]+", cat):
            problems.append("bad category key %r" % cat)
        doms = spec.get("domains") or []
        if not doms:
            problems.append("%s: no domains" % cat)
        for d in doms:
            low = d.strip().lower()
            if low != d or " " in d or "://" in d:
                problems.append("%s: %r is not a bare lower-case host" % (cat, d))
            if low in seen:
                problems.append("%r listed in both %s and %s" % (low, seen[low], cat))
            seen[low] = cat
    for eng in data.get("search_engines") or []:
        if not eng.get("host") or not eng.get("params"):
            problems.append("search engine without host or params: %r" % eng)
    for ext_id in (data.get("wallet_extensions") or {}):
        if not re.fullmatch(r"[a-p]{32}", ext_id):
            problems.append("wallet extension id %r is not a 32-letter a-p id" % ext_id)
    return problems
