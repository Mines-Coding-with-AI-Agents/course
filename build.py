#!/usr/bin/env python3
"""Build the public course site into _site/.

Usage:
  python3 build.py          build the site into _site/
  python3 build.py serve    build, then serve it at http://localhost:8000/course/
  python3 build.py og       render static/img/og.png (the link preview image) with Chrome

Pages live in pages/*.html. Each starts with an HTML comment holding its metadata
as JSON, and may use {{ slot }} placeholders that this script fills from
content/site.json and content/curriculum.json. Standard library only.
"""
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "_site"
SITE = json.loads((ROOT / "content" / "site.json").read_text())
CURRICULUM = json.loads((ROOT / "content" / "curriculum.json").read_text())
BASE = SITE["base_path"]
# Project status lines follow the calendar in Golden, Colorado, not the build machine's clock.
COURSE_TZ = ZoneInfo("America/Denver")

META_RE = re.compile(r"\A<!--\s*(\{.*?\})\s*-->\s*", re.S)
SLOT_RE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

e = partial(html.escape, quote=True)


def fill(template, slots):
    def replace(match):
        key = match.group(1)
        if key not in slots:
            raise KeyError(f"unknown slot {{{{ {key} }}}}")
        return slots[key]
    return SLOT_RE.sub(replace, template)


def day(iso):
    return date.fromisoformat(iso)


def short_date(d):
    return f"{MONTHS[d.month - 1][:3]} {d.day}"


def long_date(d, year=False):
    text = f"{MONTHS[d.month - 1]} {d.day}"
    return f"{text}, {d.year}" if year else text


def weekday_date(d):
    return f"{d.strftime('%a')}, {short_date(d)}"


def lectures():
    return [lec for module in CURRICULUM["modules"] for lec in module["lectures"]]


def lecture(n):
    return next(lec for lec in lectures() if lec["n"] == n)


def project_dates(project):
    return day(lecture(project["from"])["date"]), day(lecture(project["to"])["date"])


def demo_day():
    """"Demo Day on December 3 and 8", from the dates of the Demo Day lectures."""
    days = [day(lec["date"]) for m in CURRICULUM["modules"] if m["number"] is None for lec in m["lectures"]]
    if all(d.month == days[0].month for d in days):
        return f"Demo Day on {long_date(days[0])} and {' and '.join(str(d.day) for d in days[1:])}"
    return "Demo Day on " + " and ".join(long_date(d) for d in days)


def project_status(project, today):
    """One line on where a project stands, computed from the calendar on the day of the build."""
    start, due = project_dates(project)
    kind = f"{project['format']} project"
    if project["to"] == len(lectures()):
        if today > due:
            return f"{kind}, presented at {demo_day()}."
        if today >= start:
            return f"{kind}, under way until {demo_day()}."
        return f"{kind}, from {long_date(start)} to {demo_day()}."
    if today > due:
        return f"{kind}, handed in {long_date(due)}."
    if today >= start:
        return f"{kind}, under way and due {long_date(due)}."
    return f"{kind}, {long_date(start)} to {long_date(due)}."


def project_lanes():
    """Give each project a lane beside the column so that bars in one lane never overlap."""
    lanes, ends = {}, []
    for project in CURRICULUM["projects"]:
        for i, end in enumerate(ends):
            if project["from"] > end:
                lanes[project["id"]], ends[i] = i, project["to"]
                break
        else:
            lanes[project["id"]] = len(ends)
            ends.append(project["to"])
    return lanes, len(ends)


PROJECT_SHORT = {"P1": "Website", "P2": "RAG", "P3": "Skills", "P4": "Team project"}


def strata(variant):
    """The semester as a stratigraphic column: module 1 at the bottom, Demo Day on top."""
    full = variant == "full"
    total = len(lectures())
    lanes, lane_count = project_lanes()
    link = "#module-{}" if full else BASE + "curriculum/#module-{}"
    items = []
    for i, module in enumerate(CURRICULUM["modules"]):
        first, last = module["lectures"][0], module["lectures"][-1]
        rows = f"grid-row: {total + 1 - last['n']} / {total + 2 - first['n']}"
        anchor = module["number"] or "demo-day"
        start, end = day(first["date"]), day(last["date"])
        when = f"{short_date(start)} to {short_date(end)}" if start != end else short_date(start)
        if module["number"] is None:
            when = f"{short_date(start)} and {short_date(end)}"
        if full:
            # Long names on wide screens; the CSS swaps in the short names on phones.
            name = (f'<span class="name-long">{e(module["name"])}</span>'
                    f'<span class="name-short">{e(module["short"])}</span>')
            lectures_part = f"Lectures {first['n']} to {last['n']}, " if module["number"] else ""
            detail = f'<span class="when-lectures">{lectures_part}</span>{e(when)}' if lectures_part else e(when)
        else:
            name, detail = e(module["short"]), e(when)
        items.append(
            f'<div class="layer rock-{module["rock"]}" style="{rows}; --i: {i}" aria-hidden="true"></div>'
            f'<a class="layer-label" style="{rows}" href="{link.format(anchor)}">'
            f'<span class="layer-name">{name}</span><span class="layer-when">{detail}</span></a>'
        )
    for project in CURRICULUM["projects"]:
        start, due = project_dates(project)
        rows = f"grid-row: {total + 1 - project['to']} / {total + 2 - project['from']}"
        column = f"grid-column: {lane_count - lanes[project['id']]}"
        label = f"{project['id']} {PROJECT_SHORT[project['id']]}"
        items.append(
            f'<div class="project-bar" style="{rows}; {column}">'
            f'<span aria-hidden="true">{e(label)}</span>'
            f'<span class="visually-hidden">Project {project["id"][1:]}, {e(project["name"])}, '
            f'{long_date(start)} to {long_date(due)}.</span></div>'
        )
    caption = ("Read from the bottom up. Each layer is a module, as thick as its number of lectures, "
               "and the bars on the left show when each project runs.")
    return (
        f'<figure class="strata-figure strata-{variant}">'
        f'<div class="strata" style="--lanes: {lane_count}; --rows: {total}">{"".join(items)}</div>'
        f'<figcaption>{caption}</figcaption></figure>'
    )


def projects(today):
    out = []
    for project in CURRICULUM["projects"]:
        number = project["id"][1:]
        out.append(
            f'<article class="project" id="project-{number}">'
            f'<div class="project-head"><p class="project-tag">{e(project["id"])}</p>'
            f'<h3>{e(project["name"])}</h3>'
            f'<p class="project-when">{e(project_status(project, today))}</p></div>'
            f'<div class="project-body"><p>{e(project["built"])}</p>'
            f'<p class="project-evidence">{e(project["evidence"])}</p></div></article>'
        )
    return f'<div class="projects">{"".join(out)}</div>'


def milestones():
    marks = {}
    for project in CURRICULUM["projects"]:
        number = project["id"][1:]
        marks.setdefault(project["from"], []).append(f"Project {number} starts")
        if project["id"] != "P4":
            marks.setdefault(project["to"], []).append(f"Project {number} due")
    return marks


def curriculum():
    marks = milestones()
    off = [(day(x["date"]), x["why"]) for x in CURRICULUM["no_class"]]
    out = []
    previous = None
    for module in CURRICULUM["modules"]:
        anchor = module["number"] or "demo-day"
        heading = (f'<span class="module-number">Module {module["number"]}</span>' if module["number"] else "")
        rows = []
        for lec in module["lectures"]:
            d = day(lec["date"])
            for skipped, why in off:
                if previous and previous < skipped < d:
                    rows.append(f'<li class="no-class"><span class="lec-date">{weekday_date(skipped)}</span>'
                                f'<p>No class ({e(why)}).</p></li>')
            previous = d
            tags = "".join(f'<li>{e(m)}</li>' for m in marks.get(lec["n"], []))
            tags = f'<ul class="milestones">{tags}</ul>' if tags else ""
            rows.append(
                f'<li class="lecture" id="lecture-{lec["n"]}">'
                f'<span class="lec-number">{lec["n"]}</span>'
                f'<span class="lec-date">{weekday_date(d)}</span>'
                f'<div class="lec-body"><h3>{e(lec["title"])}</h3><p>{e(lec["summary"])}</p>{tags}</div></li>'
            )
        out.append(
            f'<section class="module" id="module-{anchor}" aria-labelledby="module-{anchor}-title">'
            f'<div class="module-head"><span class="swatch rock-{module["rock"]}" aria-hidden="true"></span>'
            f'<h2 id="module-{anchor}-title">{heading}{e(module["name"])}</h2></div>'
            f'<ol class="lectures">{"".join(rows)}</ol></section>'
        )
    return "".join(out)


def class_format():
    items = "".join(f'<li><span class="step-when">{e(s["when"])}</span> {e(s["what"])}</li>'
                    for s in CURRICULUM["class_format"])
    return f'<ol class="steps">{items}</ol>'


def outcomes():
    return '<ul class="outcomes">' + "".join(f"<li>{e(o)}</li>" for o in CURRICULUM["outcomes"]) + "</ul>"


def last_updated():
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cs"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
        return date.fromisoformat(out)
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return datetime.now(COURSE_TZ).date()


def asset_version():
    digest = hashlib.sha256()
    for path in sorted((ROOT / "static" / "css").glob("*.css")):
        digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


def read_page(path):
    text = path.read_text()
    match = META_RE.match(text)
    if not match:
        raise ValueError(f"{path.name} must start with an HTML comment holding its metadata as JSON")
    return json.loads(match.group(1)), text[match.end():]


def build(today=None):
    today = today or datetime.now(COURSE_TZ).date()
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(ROOT / "static", OUT / "static")
    layout = (ROOT / "templates" / "base.html").read_text()
    updated = last_updated()
    slots = {
        "base": BASE,
        "site_url": SITE["site_url"],
        "email": SITE["email"],
        "instructor": SITE["instructor"],
        "source_repo": SITE["source_repo"],
        "github_org": SITE["github_org"],
        "strata_compact": strata("compact"),
        "strata_full": strata("full"),
        "projects": projects(today),
        "curriculum": curriculum(),
        "class_format": class_format(),
        "outcomes": outcomes(),
        "updated": long_date(updated, year=True),
        "refined_after": long_date(day(CURRICULUM["refined_after"])),
    }
    sitemap = []
    for source in sorted((ROOT / "pages").glob("*.html")):
        meta, body = read_page(source)
        path = meta["path"]
        target = OUT / (path + "index.html" if path == "" or path.endswith("/") else path)
        target.parent.mkdir(parents=True, exist_ok=True)
        indexable = meta.get("index", True)
        url = SITE["site_url"] + path
        page_slots = dict(slots)
        page_slots.update({
            "content": fill(body, slots),
            "title": e(meta["title"]),
            "description": e(meta["description"]),
            "canonical": url,
            "og_title": e(meta.get("og_title", meta["title"])),
            "og_image": SITE["site_url"] + SITE["og_image"],
            "og_image_alt": e(SITE["og_image_alt"]),
            "robots": "" if indexable else '<meta name="robots" content="noindex">',
            "head_links": (f'<link rel="canonical" href="{url}">' if indexable else ""),
            "page_class": e(meta.get("class", "")),
            "css_version": asset_version(),
        })
        for key in ("home", "curriculum", "built"):
            page_slots[f"current_{key}"] = ' aria-current="page"' if meta.get("nav") == key else ""
        target.write_text(fill(layout, page_slots))
        if indexable:
            sitemap.append(url)
    (OUT / ".nojekyll").write_text("")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE['site_url']}sitemap.xml\n")
    entries = "".join(f"<url><loc>{u}</loc><lastmod>{updated.isoformat()}</lastmod></url>" for u in sitemap)
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>\n'
    )
    print(f"Built {len(sitemap) + 1} pages into {OUT.relative_to(ROOT)}/")


class PrefixHandler(SimpleHTTPRequestHandler):
    """Serve _site/ under the base path, the way GitHub Pages serves a project site."""

    def do_GET(self):
        if not self.redirect_bare_base():
            super().do_GET()

    def do_HEAD(self):
        if not self.redirect_bare_base():
            super().do_HEAD()

    def redirect_bare_base(self):
        """Send /course to /course/, as GitHub Pages does."""
        path, _, query = self.path.partition("?")
        if path != BASE.rstrip("/"):
            return False
        self.send_response(301)
        self.send_header("Location", BASE + (f"?{query}" if query else ""))
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    def translate_path(self, path):
        if path.startswith(BASE):
            path = "/" + path[len(BASE):]
        return super().translate_path(path)

    def send_error(self, code, message=None, explain=None):
        if code == 404 and (OUT / "404.html").is_file():
            body = (OUT / "404.html").read_bytes()
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().send_error(code, message, explain)


def serve(port=8000):
    handler = partial(PrefixHandler, directory=str(OUT))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"Serving at http://localhost:{port}{BASE} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


CHROME = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome", "chromium", "chromium-browser",
]


def render_og():
    """Render the link preview image from tools/og.html with headless Chrome."""
    build()
    work = ROOT / ".og"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(OUT / "static", work / "static")
    page = fill((ROOT / "tools" / "og.html").read_text(), {"strata_compact": strata("compact")})
    (work / "og.html").write_text(page)
    chrome = next((c for c in CHROME if shutil.which(c) or Path(c).is_file()), None)
    if not chrome:
        sys.exit("Chrome was not found; install it or render tools/og.html by hand at 1200x630.")
    target = ROOT / "static" / "img" / "og.png"
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", "--window-size=1200,630",
                    "--virtual-time-budget=3000", f"--screenshot={target}",
                    (work / "og.html").as_uri()], check=True, capture_output=True)
    shutil.rmtree(work)
    print(f"Rendered {target.relative_to(ROOT)}")
    build()


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "build"
    if command == "build":
        build()
    elif command == "serve":
        build()
        serve(int(os.environ.get("PORT", "8000")))
    elif command == "og":
        render_og()
    else:
        sys.exit(__doc__)
