#!/usr/bin/env python3
"""Verify the built site in _site/ before it is deployed.

Usage:  python3 build.py && python3 check.py

Prints one PASS or FAIL line per fact and a summary line, and exits 0 only
when every check passes. Standard library only, read-only, offline.
"""
import json
import struct
import sys
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urlparse

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "_site"
SITE = json.loads((ROOT / "content" / "site.json").read_text())
CURRICULUM = json.loads((ROOT / "content" / "curriculum.json").read_text())
BASE = SITE["base_path"]

PAGES = {
    "index.html": "",
    "curriculum/index.html": "curriculum/",
    "how-it-was-built/index.html": "how-it-was-built/",
}
NOT_FOUND = "404.html"
ASSETS = ["static/img/og.png", "static/img/favicon.svg", "robots.txt", "sitemap.xml"]

# Internal file names from the private instructor repository. None of them
# ever needs to appear on the public site, so any match is a leak.
FORBIDDEN = ["plan.md", "quiz.md", "quiz-qti", "note.md", "teaching-notes",
             "teaching-script", "answer-key", "canvas.html", "staging/"]
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "source", "track", "wbr"}

results = []


def check(ok, message):
    results.append((bool(ok), message))


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.errors = [], []
        self.meta, self.links, self.ids = {}, [], set()
        self.lang = None
        self.title = ""
        self.h1 = 0
        self.imgs_without_alt = 0
        self.canonical = None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang")
        if tag not in VOID:
            self.stack.append(tag)
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "title":
            self._in_title = True
        if tag == "h1":
            self.h1 += 1
        if tag == "meta":
            key = a.get("property") or a.get("name")
            if key:
                self.meta[key] = a.get("content", "")
        if tag == "link" and a.get("rel") == "canonical":
            self.canonical = a.get("href")
        if tag == "img" and "alt" not in a:
            self.imgs_without_alt += 1
        for attr in ("href", "src"):
            if attr in a:
                self.links.append(a[attr])

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack and self.stack[-1] == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}> (open: {self.stack[-3:]})")
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
            return
        self.stack.pop()

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def parse(rel):
    page = Page()
    page.feed((OUT / rel).read_text())
    page.close()
    return page


def target_file(url_path):
    """Map a URL path under the base path to a file in _site, or None."""
    if not url_path.startswith(BASE):
        return None
    rel = url_path[len(BASE):]
    if rel == "" or rel.endswith("/"):
        rel += "index.html"
    return OUT / rel


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])


def check_curriculum():
    lectures = [lec for m in CURRICULUM["modules"] for lec in m["lectures"]]
    numbers = [lec["n"] for lec in lectures]
    check(numbers == list(range(1, 29)), "curriculum: lectures are numbered 1 to 28 in order")
    days = [date.fromisoformat(lec["date"]) for lec in lectures]
    check(all(a < b for a, b in zip(days, days[1:])), "curriculum: lecture dates strictly increase")
    first = date.fromisoformat(CURRICULUM["first_day"])
    last = date.fromisoformat(CURRICULUM["last_day"])
    check(days[0] == first and days[-1] == last, "curriculum: first and last lecture match the semester dates")
    check(all(d.weekday() in (1, 3) for d in days), "curriculum: every lecture falls on a Tuesday or Thursday")
    off = {date.fromisoformat(x["date"]) for x in CURRICULUM["no_class"]}
    check(not off & set(days), "curriculum: no lecture is scheduled on a no-class day")
    spans = all(1 <= p["from"] < p["to"] <= 28 for p in CURRICULUM["projects"])
    check(spans, "curriculum: every project runs between two real lectures")


def check_timeline():
    import build
    from datetime import timedelta
    first = date.fromisoformat(CURRICULUM["first_day"])
    last = date.fromisoformat(CURRICULUM["last_day"])
    days = [first + timedelta(days=i) for i in range((last - first).days + 2)]
    spots = [build.position(d) for d in days]
    check(build.position(first - timedelta(days=1)) is None, "timeline: no today line before the semester starts")
    check(all(0 <= p <= 28 for p in spots) and all(a <= b for a, b in zip(spots, spots[1:])),
          "timeline: the today line moves forward every day of the semester and stays on the chart")
    home = (OUT / "index.html").read_text() if (OUT / "index.html").is_file() else ""
    modules = len(CURRICULUM["modules"])
    check(home.count('class="tl-seg') == modules and home.count('class="tl-item') == modules,
          f"timeline: the chart and the list each show all {modules} modules")
    check(home.count('class="tl-project') == len(CURRICULUM["projects"]), "timeline: the chart shows every project")
    check('class="live"' in home, "timeline: the home page carries the next-lecture status line")


def check_page(rel, path):
    page = parse(rel)
    where = rel
    check(not page.errors and not page.stack,
          f"{where}: tags are balanced" + (f" ({page.errors[:2]} {page.stack[-3:]})" if page.errors or page.stack else ""))
    check(page.lang == "en", f"{where}: <html lang=\"en\">")
    check(page.h1 == 1, f"{where}: exactly one <h1> (found {page.h1})")
    check(page.title.strip(), f"{where}: has a <title>")
    check(page.meta.get("viewport"), f"{where}: has a viewport meta tag")
    check(page.meta.get("description"), f"{where}: has a meta description")
    check(page.imgs_without_alt == 0, f"{where}: every <img> has alt text")
    if path is None:
        check(page.meta.get("robots") == "noindex", f"{where}: is marked noindex")
        return page
    url = SITE["site_url"] + path
    check(page.canonical == url, f"{where}: canonical URL is {url}")
    check(page.meta.get("og:url") == url, f"{where}: og:url matches the canonical URL")
    for key in ("og:title", "og:description", "og:type", "og:site_name", "og:image:alt"):
        check(page.meta.get(key), f"{where}: has {key}")
    image = page.meta.get("og:image", "")
    check(image.startswith("https://") and image.endswith(".png"), f"{where}: og:image is an absolute https PNG URL")
    check(page.meta.get("og:image:width") == "1200" and page.meta.get("og:image:height") == "630",
          f"{where}: og:image is declared as 1200x630")
    check(page.meta.get("twitter:card") == "summary_large_image", f"{where}: twitter:card is summary_large_image")
    return page


def check_links(pages):
    bad = []
    for rel, page in pages.items():
        for link in page.links:
            scheme = urlparse(link).scheme
            if scheme in ("https", "mailto"):
                continue
            if scheme:
                bad.append(f"{rel}: {link} (use https)")
                continue
            if link.startswith("#"):
                if link[1:] and link[1:] not in page.ids:
                    bad.append(f"{rel}: {link} (no such id)")
                continue
            path, fragment = urldefrag(link)
            target = target_file(urlparse(path).path)
            if target is None:
                bad.append(f"{rel}: {link} (internal links must start with {BASE})")
            elif not target.is_file():
                bad.append(f"{rel}: {link} (no file at {target.relative_to(OUT)})")
            elif fragment:
                other = pages.get(str(target.relative_to(OUT))) or parse(target.relative_to(OUT))
                if fragment not in other.ids:
                    bad.append(f"{rel}: {link} (no such id on that page)")
    check(not bad, "links: every internal link and anchor resolves" + (f" ({'; '.join(bad[:4])})" if bad else ""))


def check_text():
    built = [p for p in OUT.rglob("*") if p.suffix in (".html", ".xml", ".txt", ".css")]
    sources = [p for p in ROOT.glob("content/*.json")] + list(ROOT.glob("pages/*.html")) + list(ROOT.glob("templates/*.html"))
    dashes = [str(p.relative_to(ROOT)) for p in built + sources if "—" in p.read_text()]
    check(not dashes, "text: no em dash anywhere" + (f" ({', '.join(dashes)})" if dashes else ""))
    leaks = sorted({f"{p.relative_to(ROOT)}: {w}" for p in built + sources for w in FORBIDDEN if w in p.read_text().lower()})
    check(not leaks, "text: no private instructor-repo file names" + (f" ({'; '.join(leaks[:4])})" if leaks else ""))


def main():
    if not OUT.is_dir():
        print("FAIL _site/ does not exist: run python3 build.py first")
        return 1
    check_curriculum()
    check_timeline()
    for rel in list(PAGES) + [NOT_FOUND] + ASSETS:
        check((OUT / rel).is_file(), f"built: {rel} exists")
    pages = {}
    for rel, path in PAGES.items():
        if (OUT / rel).is_file():
            pages[rel] = check_page(rel, path)
    if (OUT / NOT_FOUND).is_file():
        pages[NOT_FOUND] = check_page(NOT_FOUND, None)
    check_links(pages)
    og = OUT / "static/img/og.png"
    check(og.is_file() and png_size(og) == (1200, 630), "share image: og.png is 1200x630")
    sitemap = (OUT / "sitemap.xml").read_text() if (OUT / "sitemap.xml").is_file() else ""
    check(all(f"<loc>{SITE['site_url'] + p}</loc>" in sitemap for p in PAGES.values()),
          "sitemap: lists every public page")
    check_text()

    for ok, message in results:
        print(("PASS " if ok else "FAIL ") + message)
    failed = sum(1 for ok, _ in results if not ok)
    print(f"{len(results) - failed} of {len(results)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
