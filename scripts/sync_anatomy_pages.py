"""Copy the Eye-Describe anatomy pages into the app, so Anatomy buttons work offline.

The site folder is the one source of truth. This copies every page an
Anatomy button points at (ui/anatomy_links.py), with the stylesheets and
scripts those pages load, into docs/anatomy/ - and rewrites links so the copy
works from disk:

  /Eye-Describe/<bundled page>#x   ->  <page>.html#x       (stays in the app)
  /Eye-Describe/<other page>       ->  https://crow-eye.com/Eye-Describe/<page>
  /anything-else                   ->  https://crow-eye.com/anything-else
  anatomy.css?v=...                ->  anatomy.css         (a query string on a
                                                            file: URL is noise)

The favicon and web-manifest links are dropped: a manifest fetched from file:
is an error in the console and nothing else.

Run after editing a page on the site:

    python scripts/sync_anatomy_pages.py            # site beside the engine
    python scripts/sync_anatomy_pages.py --check    # exit 1 when out of date

`correlation_engine/tests/test_anatomy_bundle.py` runs the --check logic, so a
page edited on the site and not synced fails a test rather than shipping stale.
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(os.path.dirname(ROOT), "Crow Eye Site")
OUT = os.path.join(ROOT, "docs", "anatomy")
SITE_URL = "https://crow-eye.com"

# Files every page loads, relative to the site root.
SHARED = ["style.css", "main.js",
          "Eye-Describe/anatomy.css", "Eye-Describe/anatomy.js", "Eye-Describe/bytemap.js"]


def bundled_pages():
    """Every page an Anatomy button points at."""
    sys.path.insert(0, ROOT)
    from ui.anatomy_links import ANATOMY_LINKS
    return sorted({page for page, _anchor, _tip in ANATOMY_LINKS.values()})


def transform_page(html, pages):
    """The page as it is served from docs/anatomy/Eye-Describe/."""
    keep = set(pages)

    def site_link(m):
        attr, path, rest = m.group(1), m.group(2), m.group(3) or ""
        if path.startswith("/Eye-Describe/"):
            slug = path[len("/Eye-Describe/"):].rstrip("/")
            if slug.endswith(".html"):
                slug = slug[:-5]
            if slug in keep:
                return '%s="%s.html%s"' % (attr, slug, rest)
        return '%s="%s%s%s"' % (attr, SITE_URL, path, rest)

    html = re.sub(r'(href|src)="(/[^"#?]*)([?#][^"]*)?"', site_link, html)
    # Local assets: drop the cache-busting stamp.
    html = re.sub(r'(href|src)="((?:\.\./)?[\w./-]+\.(?:css|js))\?v=[^"]*"', r'\1="\2"', html)
    # Favicon and manifest links mean nothing from disk.
    html = re.sub(r'[ \t]*<link rel="(?:apple-touch-icon|icon|manifest)"[^>]*>\r?\n', "", html)
    # Remote stylesheets (Google Fonts, Font Awesome) must not block the first
    # paint: on an offline workstation they only fail after a network timeout,
    # and until then the viewer shows an empty page. Loaded as print media and
    # switched on when they arrive - the page paints at once in local fonts.
    def _non_blocking(m):
        tag = m.group(0)
        if 'media=' in tag:
            return tag
        return tag[:-1].rstrip("/ ") + ' media="print" onload="this.media=\'all\'">'
    html = re.sub(r'<link\b[^>]*href="https?://[^"]+"[^>]*rel="stylesheet"[^>]*>', _non_blocking, html)
    html = re.sub(r'<link\b[^>]*rel="stylesheet"[^>]*href="https?://[^"]+"[^>]*>', _non_blocking, html)
    return html


def build(site=SITE):
    """{relative path under docs/anatomy: bytes} - what the bundle should hold."""
    pages = bundled_pages()
    files = {}
    for page in pages:
        src = os.path.join(site, "Eye-Describe", page + ".html")
        html = io.open(src, encoding="utf-8", newline="").read()
        files["Eye-Describe/%s.html" % page] = transform_page(html, pages).encode("utf-8")
    for rel in SHARED:
        with open(os.path.join(site, *rel.split("/")), "rb") as fh:
            files[rel] = fh.read()
    manifest = {
        "source": "Crow Eye Site (synced by scripts/sync_anatomy_pages.py)",
        "pages": pages,
        "sha256": {rel: hashlib.sha256(data).hexdigest() for rel, data in sorted(files.items())},
    }
    files["manifest.json"] = (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode("utf-8")
    return files


def stale(files, out=OUT):
    """Paths whose bundled copy differs from what the site would produce."""
    bad = []
    for rel, data in files.items():
        path = os.path.join(out, *rel.split("/"))
        try:
            with open(path, "rb") as fh:
                if fh.read() != data:
                    bad.append(rel)
        except OSError:
            bad.append(rel)
    return sorted(bad)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--site", default=SITE)
    ap.add_argument("--check", action="store_true", help="report, do not write")
    args = ap.parse_args(argv)
    if not os.path.isdir(os.path.join(args.site, "Eye-Describe")):
        print("[FAIL] site tree not found: %s" % args.site)
        return 2
    files = build(args.site)
    bad = stale(files)
    if args.check:
        for rel in bad:
            print("[STALE] %s" % rel)
        print("[OK] bundle is current" if not bad else "[FAIL] %d file(s) out of date" % len(bad))
        return 1 if bad else 0
    for rel in bad:
        path = os.path.join(OUT, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(files[rel])
    print("[OK] %d page(s), %d file(s) written to %s"
          % (len(json.loads(files["manifest.json"])["pages"]), len(bad), OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
