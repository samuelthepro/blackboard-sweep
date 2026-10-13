# Blackboard Sweep

A Claude Code plugin for Ole Miss students. Say "check Blackboard" and Claude:

- downloads every new file your classes post (slides, PDFs, Word docs, zips) into one folder per
  class, sorted into Course Info / Lectures & Readings / Assignments & Tests, each with a
  searchable `.md` text copy
- reads new announcements and Ultra documents and keeps a short note per class
- checks what you have submitted and what has been graded
- adds deadlines to an Apple Reminders list and exams to an Apple Calendar
- ends with a short report: what is new, what is due in the next two weeks, what still needs you

It only reads. It never submits, starts an attempt, or posts anything, and it does not do graded
work for you (many departments ban AI help on graded work; check your syllabi).

## What you need

- A Mac
- A Claude Pro plan (or higher) and Claude Code (the `claude` terminal app, or the Code tab in the
  Claude desktop app)
- Google Chrome with the [Claude in Chrome](https://claude.com/chrome) extension connected
- You signed in to [Blackboard](https://blackboard.olemiss.edu) in that Chrome

In Chrome, open Settings > Downloads and turn OFF "Ask where to save each file before
downloading". Optional but faster: Settings > Privacy and security > Site settings > Additional
content settings > PDF documents > "Download PDFs".

## Install

Run these in the Terminal app.

1. If you do not have the `claude` command yet, install it (Anthropic's installer), then open a
   new Terminal window:

   ```bash
   curl -fsSL https://claude.ai/install.sh | bash
   ```

2. Add this plugin:

   ```bash
   claude plugin marketplace add samuelthepro/blackboard-sweep
   ```

   ```bash
   claude plugin install blackboard-sweep@blackboard-sweep
   ```

3. Quit and reopen Claude (the desktop app, or any open `claude` session). In the desktop app it
   shows up in the Code tab under + > Plugins.

Already inside a `claude` session? `/plugin marketplace add samuelthepro/blackboard-sweep` and
`/plugin install blackboard-sweep@blackboard-sweep` do the same thing.

## First run

Start a new Claude Code session and say "check Blackboard" (or type `/blackboard-sweep:blackboard-sweep`).
The first time, Claude asks three things:

1. Where to keep your class files (default `~/Documents/Ole Miss Fall 2026` or similar)
2. Which Reminders list to use for assignments (or none)
3. Which calendar to use for exams (or none)

Then it finds your current classes, sets up a folder for each, and asks whether to download
everything already posted this semester or only what gets posted from now on. macOS will ask
once whether Claude may use Reminders and Calendar.

After that, run it whenever you want ("am I up to date on my classes?", "what's due?"). Each sweep
takes a few minutes and only downloads what changed.

## Where things live

- Your class files, plus `_blackboard_manifest.json` (what has been saved), `_last_pull.md`
  (the latest report) and `_sweep_log.md`, all in the folder you picked
- Settings: `~/.claude/blackboard-sweep/config.json`

Everything stays on your Mac. The plugin talks only to Blackboard, through your own Chrome
session, and never sees or types your password.

## Update or remove

Get the latest version:

```bash
claude plugin marketplace update blackboard-sweep
```

```bash
claude plugin update blackboard-sweep@blackboard-sweep
```

Or turn on automatic updates once: in a `claude` session, `/plugin` > Marketplaces >
blackboard-sweep > Enable auto-update.

Remove it with `claude plugin uninstall blackboard-sweep@blackboard-sweep`. Your class files and
settings stay where they are.
