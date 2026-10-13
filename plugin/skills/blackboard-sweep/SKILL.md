---
name: blackboard-sweep
description: Sweep an Ole Miss Blackboard (blackboard.olemiss.edu) account. Downloads every new class file into local class folders with searchable text copies, tracks announcements and due dates, checks what has been submitted or graded, and adds deadlines to Apple Reminders and exams to Apple Calendar. Works through Claude in Chrome with the student's own Blackboard login. Trigger on "/blackboard-sweep", "check Blackboard", "sweep Blackboard", "am I up to date on my classes", "download my class files", "what's due".
---

# Blackboard sweep

Goal: after a sweep, every file Blackboard offers for the student's current classes is saved
locally (with a `.md` text copy), every deadline is a Reminder, every exam is on the calendar,
and the student gets a short report of what changed and what is due next.

Run the helper as `python3 "${CLAUDE_SKILL_DIR}/scripts/bbsweep.py" <command>`, written
`bbsweep` below. (If that path shows up unexpanded, use the base directory shown when this skill
loaded: the scripts are in its `scripts/` folder.) `bbsweep --help` lists every command.

## 0. Ground rules

- **Read only.** Never submit anything, never click "Start attempt", "Submit", "Post" or anything
  similar, never open an assignment attempt page, never post to discussions. Downloading course
  materials is what the student installed this for, so no per-file OK is needed.
- **No graded work.** Many Ole Miss departments ban AI help on graded work, and some syllabi say
  so outright. This skill organizes, summarizes and reminds. If the student asks for help with a
  graded item, point out the course policy first.
- **Never run `javascript_tool`, `get_page_text` or `read_page` on an `/ultra/...` page.** The
  Ultra app freezes the tab and every browser call then times out for 45 s. Do all API work
  from the light page `https://blackboard.olemiss.edu/learn/api/public/v1/system/version`.
- Never type the student's password. If Blackboard needs a real sign-in, ask the student to do it.
- Blackboard times are UTC. `bbsweep` converts to the Mac's local time (Oxford = Central) in its
  report; pass Blackboard's UTC times straight to `--due-utc` / `--start-utc`.
- Keep the final report short. No em dashes in anything written for the student.

## 1. First run

Run `bbsweep show`. If it says "Not set up yet":

1. Check the basics, and tell the student what to fix if anything is off:
   - Claude in Chrome is connected, and the student is signed in to Blackboard in Chrome.
   - Chrome Settings > Downloads: location is the Downloads folder and **"Ask where to save each
     file before downloading" is OFF** (otherwise every download stops at a save dialog).
   - Optional but faster: Chrome Settings > Privacy and security > Site settings > Additional
     content settings > PDF documents > "Download PDFs". Then PDFs download like any other file
     instead of opening in Chrome's viewer (see §4).
2. Ask the student three things (one question each, offer the defaults):
   - Where to keep class files. Default `~/Documents/Ole Miss <Fall|Spring> <year>`.
   - Apple Reminders list for assignments. Default `Ole Miss <Fall|Spring> <year>`, or none.
   - Calendar for exams. Default none (exams then go to Reminders too), or an existing calendar's name.
3. `bbsweep setup --root "<folder>" --reminders "<list or none>" --calendar "<calendar or none>"`
4. Do the pull (§2) and `bbsweep ingest`. The report ends with one suggested
   `bbsweep course ...` command per class. Run them (shorten folder names if the student wants).
   Each class gets `01 Course Info/`, `02 Lectures & Readings/`, `03 Assignments & Tests/`.
5. The report also lists OTHER courses and orgs that are not in the current term (for example the
   Honors College capstone org). Ask whether to include any: `bbsweep course <id> --extra`, then
   map a folder for it. `--skip` hides one for good.
6. Ask: download every file already posted this semester now (it can be 50 to 100 files and take a
   while), or start fresh and only download what gets posted from now on? For "start fresh", do
   §5 and §6 only, then `bbsweep finish --baseline`.
7. Create a class note for each class: `<class folder>/01 Course Info/Blackboard - <short name>.md`
   with sections `## Due dates`, `## Announcements` (newest first) and `## Documents`.

## 2. Pull (every sweep)

1. `tabs_context_mcp`, then `tabs_create_mcp`. Use a **fresh tab every sweep**: Chrome allows only
   one script-started download per tab, and the pull uses it.
2. `navigate` that tab to `https://blackboard.olemiss.edu/learn/api/public/v1/system/version`.
3. Run `bbsweep script pull` and paste its **entire output** as the `javascript_tool` text.
   It answers `ok N courses; saved bbsweep-pull.json to Downloads`.
   - `SIGNED OUT (401)`: the Blackboard session expired (normal overnight), but the Ole Miss
     single sign-on usually is still live. `navigate` the tab to
     `https://blackboard.olemiss.edu/auth-saml/saml/login?apId=_122_1&redirectUrl=https%3A%2F%2Folemiss.blackboard.com%2Fwebapps%2Fportal%2Fexecute%2FdefaultTab`,
     wait ~5 s, then `tabs_context_mcp`. If the tab is now on `/ultra/...`, you are signed in:
     `navigate` it straight back to the light page and run the pull again (do not run anything
     on the `/ultra/` page). If it shows a WebID / Okta sign-in form instead, stop and ask the
     student to sign in to Blackboard in Chrome.
4. `bbsweep ingest`. It picks up `bbsweep-pull.json` from Downloads, compares it with what is
   already saved, and prints: per-class counts, upcoming due dates, then every NEW or CHANGED
   item with its id and type. If it cannot find the file, Chrome probably asked where to save it:
   fix the download setting from §1 and redo §2 in a fresh tab. (`get_page_text` on the pull tab
   shows the same information as text if you only need a report.)

## 3. Work through what is new

Item types in the report:

- **FILE**: download it (§4).
- **DOC** (an Ultra document): if the report shows `text="..."`, that is the document. Summarize
  anything useful into the class note's `## Documents` section. If it says
  `text=(empty: body is an embedded page, fetch it)`, run this on the light tab, filling in the
  course id and `body_id` from the report:
  ```js
  const r = await (await fetch('https://blackboard.olemiss.edu/learn/api/public/v1/courses/COURSE/contents/BODY_ID', {credentials: 'include'})).json();
  ((r.body || '').match(/\/bbcswebdav\/[^"'\s?]+/g) || []).join('\n') || (r.body || '').replace(/<[^>]+>/g, ' ').slice(0, 3000)
  ```
  Each link it returns is either the document's page (`navigate` a tab there, then
  `get_page_text`; these are not `/ultra/` pages, so that is safe) or a file embedded in the
  document (download it like a FILE, then `bbsweep grab <the DOC's id> --to ...`).
- **ASSIGNMENT** (assignments, tests, quizzes): note the due date (it is in the UPCOMING list
  when the gradebook has one). The instructions live on the assignment page; do not open
  attempt pages.
- **LINK / FOLDER**: nothing to download. Mention useful links in the class note.
- **ANNOUNCEMENT**: add it to the class note (date, title, one to three lines). If it announces a
  test, quiz, deadline, room change or cancelled class, act on it in §6 and the report.
- A CHANGED file has a newer version on Blackboard: download it again. `grab` keeps the old copy
  and saves the new one as `<name> (updated <date>)`.

## 4. Download files

Use one more fresh tab for downloads (not the pull tab). For each FILE:

1. `navigate` the tab to `https://blackboard.olemiss.edu` + the item's `url`.
2. `bbsweep grab <item id> --to info|lectures|assignments`
   It waits for the download, renames it to the Blackboard title, moves it into the class
   folder, unzips zips, writes the `.md` text copy, and records it as saved.
   - `info`: syllabus, schedule, course rules, team assignments, forms and templates about the course.
   - `lectures`: slides, chapters, readings, references, simulators, demo videos.
   - `assignments`: homework, labs, quizzes, tests, solutions, project instructions, rubrics.

Several plain navigates in the same tab are fine. Ask before downloading anything over ~200 MB.

**PDF opened in Chrome's viewer instead of downloading** (the tab now shows the PDF on a
`*.blackboardcdn.com` address): open a NEW tab, `navigate` it to the same file URL, wait ~5 s
(10 s for big files; the viewer freezes the tab while it loads), then run this without `await`:
```js
window.__st='pending';fetch(location.href).then(r=>r.blob().then(b=>{const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='file.pdf';document.body.appendChild(a);a.click();window.__st=r.status+' '+b.size;}));'started'
```
then `bbsweep grab <id> --to ...`. That trick works once per tab: close the tab and use a new one
for the next PDF. Do not try `<a download>` links or `fetch()` of `bbcswebdav` URLs from a
Blackboard page; those are blocked. Turning on "Download PDFs" in Chrome (§1) avoids all this.

If a file will not download (403, 404, removed), `bbsweep record <id> --skip` and mention it.
If the file is in Downloads under a different name, `bbsweep grab <id> --to ... --file "<path>"`.

## 5. Submission and grade status (quick)

In the **pull tab** (it still holds the pulled data): run `bbsweep script grades` as
`javascript_tool` text, wait ~5 s, then `get_page_text`. Each line is
`course | item | due (UTC) | status | grade | attempts`; status `no attempt` means nothing has been
submitted. Use it to mark "submitted / not yet" for everything due in the next 14 days, and to
mention newly graded items in one line each.

## 6. Reminders and calendar

- `bbsweep reminders list` shows open reminders. For every upcoming deadline (the UPCOMING list,
  new ASSIGNMENT items, dates in announcements or documents) with no matching reminder, add one:
  `bbsweep reminders add --name "<short>: <task>" --due-utc <Blackboard UTC time> --notes "<how or where to submit>"`
  Example name: `CSCI 2056: Lab 7 (in lab, LockDown Browser)`. Use `--due "YYYY-MM-DD HH:MM"`
  (local time) for dates that came from text instead of Blackboard. The helper refuses an exact
  duplicate name; also check by eye for near-duplicates before adding.
- Exams (midterms, finals, in-class tests) go on the calendar when one is set up:
  `bbsweep calendar list`, then
  `bbsweep calendar add --title "MIDTERM: <class>" --start "YYYY-MM-DD HH:MM" --minutes 75 --location "<room>"`.
  Final exam times come from the syllabus or the registrar's finals schedule. No calendar set up:
  add the exam as a reminder instead.
- If Blackboard moves a deadline, say so in the report and let the student fix the existing
  reminder (the helper only adds). Do not add reminders for items already past due; if one was
  never submitted, flag it in the report instead.
- AppleScript cannot see reminders nested as subtasks, so keep this list flat.
- The first time, macOS asks whether the app may control Reminders and Calendar. The student
  clicks OK.

## 7. Finish and report

1. `bbsweep finish` (it saves the sweep time and marks everything handled; any file still not
   saved is listed and comes back as NEW next time).
2. `bbsweep log "<one line: what changed, what to watch for next>"`
3. Close the tabs you opened.
4. Report, short: new files by class (count plus notable names), new announcements (one line
   each), changed deadlines, everything due in the next 14 days with submitted / not yet, and
   anything that needs the student's action.

## Troubleshooting

- Every browser call times out: the tab is on an `/ultra/` page or a big PDF is rendering. Close
  it, open a fresh tab, park it on the light page.
- `javascript_tool` output is cut at ~4 KB and hides anything containing `?`. That is why the
  scripts write to the page body or hand off a JSON download.
- New semester: classes switch over by themselves once the new term starts, and `ingest` lists
  them as classes without folders. Ask whether to start a new root folder for the semester
  (`bbsweep setup --root "<new folder>"`). Each root folder has its own manifest.
- Settings live in `~/.claude/blackboard-sweep/config.json`. The manifest
  (`_blackboard_manifest.json`), the last pull (`_last_pull.json`, `_last_pull.md`) and the sweep
  log (`_sweep_log.md`) live in the root class folder.
- The first `python3` on a fresh Mac may ask to install Apple's Command Line Tools. Say yes.
- PDF text uses `pdftotext` if Homebrew poppler is installed, otherwise macOS's own PDF engine.
  Scanned PDFs have no text; the `.md` says so.
