# Coding with AI Agents: the public course site

This repository builds the public website for CSCI 498E and CSCI 598E, "Coding with AI Agents", at Colorado School of Mines.
It is live at <https://mines-coding-with-ai-agents.github.io/course/>.

The site is a showcase for people outside the class: what the course teaches, what students build, and how the course itself was built with coding agents.
Course materials for enrolled students live in the private `student` repository, and nothing here replaces them.

## Build and preview

You need Python 3.11 or later and nothing else.

```bash
python3 build.py          # build the site into _site/
python3 check.py          # verify the build: one PASS or FAIL line per fact
python3 build.py serve    # build, then preview at http://localhost:8000/course/
```

`build.py serve` serves the site under `/course/`, the same path GitHub Pages uses, so links behave exactly as they will live.
Set `PORT=8766` (or any free port) if 8000 is taken.

## How it deploys

Every push to `main` runs `.github/workflows/pages.yml`, which builds the site, runs `check.py`, and deploys to GitHub Pages only when every check passes.
The same workflow also runs once a day, so each project's status line on the home page ("under way", "handed in") follows the calendar without anyone pushing.

## What lives where

| Path | What it is |
|---|---|
| `content/curriculum.json` | The single source for the lectures, modules, projects, class format, and outcomes. The stratigraphic column, the project list, and the curriculum page are all generated from it. |
| `content/site.json` | Site-wide facts: title, URL, base path, instructor, contact. |
| `pages/*.html` | One file per page. Each starts with an HTML comment holding its metadata as JSON, and may use `{{ slot }}` placeholders that `build.py` fills. |
| `templates/base.html` | The shared page shell: head, share-preview tags, header, footer. |
| `static/` | The stylesheet, the self-hosted fonts, the favicon, and the share image `img/og.png`. |
| `tools/og.html` | The template for the share image. |
| `DECISIONS.md` | Why the site is built the way it is. |

## Common changes

- **A lecture's title, summary, or date changed.** Edit `content/curriculum.json`, then build and check. The column, the project runways, and the curriculum page all update from that one file.
- **The share image needs updating** (after a design or title change). Run `python3 build.py og`, which renders `tools/og.html` with Chrome into `static/img/og.png`, then commit the PNG. LinkedIn caches previews, so use the LinkedIn Post Inspector to refresh a link that was already shared.
- **Demo Day projects are ready to show.** Add them only for teams that opted in, in writing. See `DECISIONS.md` for the rule.

## What may be published here

This repository is public, and its full history is public too, so deleting a file later does not unpublish it.
Before anything lands here, it must pass these rules:

- Never publish answer keys, quizzes, lesson plans (`plan.md`), teaching notes, rubrics, or grading internals from the private repositories.
- Never publish a student's name, site, or project without that student's written opt-in.
- Keep claims about other universities' courses off the site, and keep outcome claims until they are true.

`check.py` fails the build if a private file name from the instructor repository appears in the output, but a human review of every change is the real gate.
