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
# Everything date-dependent follows the calendar in Golden, Colorado, not the build machine's clock.
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


def course_today():
    return datetime.now(COURSE_TZ).date()


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


def module_span(module):
    """The module's place on the timeline, in lecture units: [start, end)."""
    return module["lectures"][0]["n"] - 1, module["lectures"][-1]["n"]


def module_dates(module):
    start, end = day(module["lectures"][0]["date"]), day(module["lectures"][-1]["date"])
    if module["number"] is None:
        return f"{short_date(start)} and {end.day}" if start.month == end.month else f"{short_date(start)} and {short_date(end)}"
    return f"{short_date(start)} to {short_date(end)}"


def project_state(project, today):
    start, due = project_dates(project)
    if today > due:
        return "done"
    if today >= start:
        return "active"
    return "upcoming"


def project_status(project, today):
    """One line on where a project stands, computed from the calendar on the day of the build."""
    start, due = project_dates(project)
    state = project_state(project, today)
    if project["to"] == len(lectures()):
        return {"done": "Presented at Demo Day",
                "active": "Under way until Demo Day",
                "upcoming": f"{short_date(start)} to Demo Day"}[state]
    return {"done": f"Handed in {short_date(due)}",
            "active": f"Under way, due {short_date(due)}",
            "upcoming": f"{short_date(start)} to {short_date(due)}"}[state]


def position(today):
    """Where today falls on the timeline, in lecture units from 0 to 28, or None before the semester.

    A lecture day sits at the middle of its column, and days between lectures move
    evenly from one lecture's middle to the next.
    """
    days = [day(lec["date"]) for lec in lectures()]
    if today < days[0]:
        return None
    if today >= days[-1]:
        return float(len(days)) if today > days[-1] else len(days) - 0.5
    k = max(i for i, d in enumerate(days) if d <= today)
    return k + 0.5 + (today - days[k]).days / (days[k + 1] - days[k]).days


def status_line(today):
    lecs = lectures()
    first, last = day(lecs[0]["date"]), day(lecs[-1]["date"])
    if today < first:
        return f"The semester starts on {long_date(first, year=True)}."
    if today > last:
        return f"The Fall {last.year} semester ended on {long_date(last)}."
    nxt = next(lec for lec in lecs if day(lec["date"]) >= today)
    when = "today" if day(nxt["date"]) == today else f"on {long_date(day(nxt['date']))}"
    demo = next(m for m in CURRICULUM["modules"] if m["number"] is None)
    if nxt in demo["lectures"]:
        return f"Demo Day is {when}."
    return f"Lecture {nxt['n']} of {len(lecs)}, {nxt['title']}, is {when}."


def timeline(today):
    """The semester as one segmented bar with the four projects beneath it, and a line at today."""
    lecs = lectures()
    total = len(lecs)
    pos = position(today)
    cells = []

    # Month ticks, at the first lecture of each month.
    seen = set()
    for lec in lecs:
        d = day(lec["date"])
        if d.month not in seen:
            seen.add(d.month)
            cells.append(f'<span class="tl-month" style="grid-column: {lec["n"]} / span 3">{MONTHS[d.month - 1][:3]}</span>')

    modules = CURRICULUM["modules"]
    for i, module in enumerate(modules):
        start, end = module_span(module)
        done = 0.0 if pos is None else max(0.0, min(1.0, (pos - start) / (end - start)))
        kind = " tl-seg-final" if module["number"] is None else ""
        cells.append(f'<span class="tl-seg{kind}" style="grid-column: {start + 1} / {end + 1}; --done: {done:.3f}"></span>')
        # Labels alternate between two rows, and each may run on until the next label in its row.
        row = "a" if i % 2 == 0 else "b"
        following = next((module_span(m)[0] for m in modules[i + 2:i + 3]), total)
        last = i == len(modules) - 1
        if i + 2 == len(modules) - 1:
            # The last label is right-aligned over the final three columns; stop short of it.
            following = min(following, total - 3)
        column = f"{following - 3 + 1} / {total + 1}" if last else f"{start + 1} / {following + 1}"
        cells.append(
            f'<span class="tl-label tl-row-{row}{" tl-label-end" if last else ""}" style="grid-column: {column}">'
            f'<span class="tl-name">{e(module["short"])}</span><span class="tl-when">{e(module_dates(module))}</span></span>'
        )

    for k, project in enumerate(CURRICULUM["projects"]):
        state = project_state(project, today)
        cells.append(
            f'<span class="tl-project tl-{state}" style="grid-column: {project["from"]} / {project["to"] + 1}; grid-row: {6 + k}">'
            f'<span class="tl-pid">{e(project["id"])}</span> {e(project["short"])}</span>'
        )

    marker = ""
    if pos is not None and pos < total:
        marker = f'<span class="tl-today" style="--pos: {pos / total:.4f}"><span>Today</span></span>'

    # A plain list carries the same information for screen readers, and replaces the chart on phones.
    items = []
    for module in modules:
        start, end = module_span(module)
        done = 0.0 if pos is None else max(0.0, min(1.0, (pos - start) / (end - start)))
        state = "done" if done >= 1 else "active" if done > 0 else "upcoming"
        label = {"done": "Finished", "active": "In progress", "upcoming": "Upcoming"}[state]
        items.append(
            f'<li class="tl-item tl-{state}" style="--done: {done:.3f}">'
            f'<span class="tl-name">{e(module["name"] if module["number"] else module["short"])}</span>'
            f'<span class="tl-when">{e(module_dates(module))}<span class="visually-hidden">, {label.lower()}</span></span></li>'
        )

    return (
        f'<div class="timeline">'
        f'<div class="tl-chart" aria-hidden="true" style="--n: {total}">{"".join(cells)}{marker}</div>'
        f'<ol class="tl-list">{"".join(items)}</ol>'
        f'</div>'
    )


def projects(today):
    out = []
    for project in CURRICULUM["projects"]:
        state = project_state(project, today)
        out.append(
            f'<li class="project" id="project-{project["id"][1:]}">'
            f'<p class="project-id">Project {project["id"][1:]}, {e(project["format"].lower())}</p>'
            f'<h3>{e(project["name"])}</h3>'
            f'<p class="project-summary">{e(project["summary"])}</p>'
            f'<p class="status status-{state}">{e(project_status(project, today))}</p></li>'
        )
    return f'<ol class="projects">{"".join(out)}</ol>'


def milestones():
    marks = {}
    for project in CURRICULUM["projects"]:
        number = project["id"][1:]
        marks.setdefault(project["from"], []).append(f"Project {number} starts")
        if project["to"] != len(lectures()):
            marks.setdefault(project["to"], []).append(f"Project {number} due")
    return marks


def curriculum(today):
    marks = milestones()
    off = [(day(x["date"]), x["why"]) for x in CURRICULUM["no_class"]]
    upcoming = [lec["n"] for lec in lectures() if day(lec["date"]) >= today]
    next_n = upcoming[0] if upcoming else None
    out = []
    previous = None
    for module in CURRICULUM["modules"]:
        anchor = module["number"] or "demo-day"
        number = f'<span class="module-number">Module {module["number"]}</span>' if module["number"] else ""
        rows = []
        for lec in module["lectures"]:
            d = day(lec["date"])
            for skipped, why in off:
                if previous and previous < skipped < d:
                    rows.append(f'<li class="no-class"><span class="lec-date">{weekday_date(skipped)}</span>'
                                f'<p>No class ({e(why)})</p></li>')
            previous = d
            tags = [f'<li class="tag-next">{"Today" if d == today else "Next"}</li>'] if lec["n"] == next_n else []
            tags += [f"<li>{e(m)}</li>" for m in marks.get(lec["n"], [])]
            tag_html = f'<ul class="tags">{"".join(tags)}</ul>' if tags else ""
            rows.append(
                f'<li class="lecture" id="lecture-{lec["n"]}">'
                f'<span class="lec-number">{lec["n"]}</span>'
                f'<span class="lec-date">{weekday_date(d)}</span>'
                f'<div class="lec-body"><h3>{e(lec["title"])}</h3><p>{e(lec["summary"])}</p>{tag_html}</div></li>'
            )
        out.append(
            f'<section class="module" id="module-{anchor}" aria-labelledby="module-{anchor}-title">'
            f'<header class="module-head">{number}<h3 id="module-{anchor}-title">{e(module["name"])}</h3>'
            f'<p class="module-dates">{e(module_dates(module))}</p></header>'
            f'<ol class="lectures">{"".join(rows)}</ol></section>'
        )
    return "".join(out)


def class_format():
    items = "".join(f'<li><span class="step-when">{e(s["when"])}</span><span>{e(s["what"])}</span></li>'
                    for s in CURRICULUM["class_format"])
    return f'<ol class="steps">{items}</ol>'


def outcomes():
    return '<ol class="outcomes">' + "".join(f"<li>{e(o)}</li>" for o in CURRICULUM["outcomes"]) + "</ol>"


def last_updated():
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cs"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
        return date.fromisoformat(out)
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return course_today()


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


def slots_for(today):
    updated = last_updated()
    return {
        "base": BASE,
        "email": SITE["email"],
        "instructor": SITE["instructor"],
        "source_repo": SITE["source_repo"],
        "timeline": timeline(today),
        "status": e(status_line(today)),
        "projects": projects(today),
        "curriculum": curriculum(today),
        "class_format": class_format(),
        "outcomes": outcomes(),
        "updated": long_date(updated, year=True),
        "refined_after": long_date(day(CURRICULUM["refined_after"])),
    }


def build(today=None):
    today = today or course_today()
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(ROOT / "static", OUT / "static")
    layout = (ROOT / "templates" / "base.html").read_text()
    slots = slots_for(today)
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
    stamp = slots["updated"]
    entries = "".join(f"<url><loc>{u}</loc><lastmod>{last_updated().isoformat()}</lastmod></url>" for u in sitemap)
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>\n'
    )
    print(f"Built {len(sitemap) + 1} pages into {OUT.relative_to(ROOT)}/ (updated {stamp})")


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
    # The preview shows the semester without a today marker, so it never goes stale in a cached post.
    page = fill((ROOT / "tools" / "og.html").read_text(), {"timeline": timeline(date(1900, 1, 1))})
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
