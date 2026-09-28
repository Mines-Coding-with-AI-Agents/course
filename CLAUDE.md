# CLAUDE.md - the public course site

This repository builds the public showcase site for "Coding with AI Agents" (CSCI 498E/598E, Colorado School of Mines).
It is public, and so is its whole history: anything committed here is published and cannot be taken back.

## Publishing boundary

- Never copy anything from the private `development` or `student` repositories verbatim. Write for a public reader instead.
- Never publish answer keys, quizzes, `plan.md` content, teaching notes, rubrics, or grading internals.
- Never publish a student's name, site, or project unless that student opted in, in writing. Ask the instructor if unsure.
- No claims about other universities' courses, and no outcome claims before they are true.

## Sources of truth

- `content/curriculum.json` mirrors the dated schedule in the private repos (`development/calendar.md`, `student/SCHEDULE.md`). When a lecture date, title, or project date changes there, update it here in the same sitting.
- Lecture summaries are one public-facing sentence each, derived from each lecture's objectives, never copied from a lesson plan.

## Writing

- Never use the em dash. `check.py` fails the build if one appears.
- Headings are full sentences or plain names, never slogan fragments. Explanations say what was done, with numbers where there are numbers.
- The home and curriculum pages speak about the course. The "How it was built" page is the instructor's first-person note, in the instructor's own voice: warm, direct, no hype, no exclamation marks.

## Verify before you say it is done

1. `python3 build.py && python3 check.py` must end with every check passing.
2. Preview with `PORT=8766 python3 build.py serve` and look at every changed page at 1440px and 390px wide. Check that nothing overflows horizontally and that the timeline labels do not collide with each other or with the today line.
3. After a design or title change, re-render the share image with `python3 build.py og` and look at `static/img/og.png`.
