#!/usr/bin/env python3
"""Local half of the Blackboard sweep: settings, the pulled-content manifest, text extraction,
Apple Reminders and Calendar. Python standard library only.

  bbsweep.py show                         settings, folders, last sweep, recent log
  bbsweep.py setup --root DIR [--reminders LIST|none] [--calendar NAME|none]
  bbsweep.py course ID --folder NAME [--short CODE]  |  course ID --extra  |  course ID --skip
  bbsweep.py script pull|grades           print the JavaScript to paste into javascript_tool
  bbsweep.py ingest [--file F]            pick up bbsweep-pull.json from ~/Downloads, report what is new
  bbsweep.py grab ITEM_ID --to info|lectures|assignments   file Chrome just downloaded -> class folder + .md + manifest
  bbsweep.py record ITEM_ID PATH... | record ITEM_ID --skip
  bbsweep.py finish [--baseline]          mark the rest of the pull as seen, save the sweep time
                                          (--baseline: also treat files not downloaded as seen)
  bbsweep.py log "text"                   append a line to the sweep log
  bbsweep.py extract IN OUT.md [--title T]
  bbsweep.py reminders list [--all]  |  reminders add --name N (--due "YYYY-MM-DD HH:MM" | --due-utc ISO) [--notes T] [--dry-run]
  bbsweep.py calendar list [--days N] |  calendar add --title T (--start ... | --start-utc ISO) [--minutes M] [--location L] [--notes T] [--dry-run]

Settings live in ~/.claude/blackboard-sweep/config.json (override with BBSWEEP_CONFIG), outside the
plugin folder so plugin updates never wipe them. The manifest, last pull and sweep log live in the
class root folder.
"""
import argparse
import datetime as dt
import filecmp
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import extract as _extract  # noqa: E402

CONFIG = os.path.expanduser(os.environ.get('BBSWEEP_CONFIG', '~/.claude/blackboard-sweep/config.json'))
CATEGORIES = ['01 Course Info', '02 Lectures & Readings', '03 Assignments & Tests']
DOWNLOADS = os.path.expanduser('~/Downloads')
CATEGORY_ALIASES = {'info': CATEGORIES[0], 'course-info': CATEGORIES[0], 'lectures': CATEGORIES[1],
                    'readings': CATEGORIES[1], 'assignments': CATEGORIES[2], 'tests': CATEGORIES[2]}


# ---------- storage ----------

def load_config(required=True):
    if not os.path.exists(CONFIG):
        if required:
            sys.exit('Not set up yet: run  bbsweep.py setup --root "<folder for class files>"')
        return {}
    with open(CONFIG) as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def root_dir(cfg):
    return os.path.expanduser(cfg['root'])


def manifest_path(cfg):
    return os.path.join(root_dir(cfg), '_blackboard_manifest.json')


def load_manifest(cfg):
    p = manifest_path(cfg)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {'note': 'Blackboard content id -> local file(s), relative to the class folder. '
                    'local null = seen, nothing to download. m = Blackboard modified time (UTC).',
            'courses': {}}


def last_pull_path(cfg):
    return os.path.join(root_dir(cfg), '_last_pull.json')


def load_last_pull(cfg):
    p = last_pull_path(cfg)
    if not os.path.exists(p):
        sys.exit('No pull on file: run pull.js, then  bbsweep.py ingest')
    with open(p) as f:
        return json.load(f)


def known_ids(man):
    ids = []
    for c in man['courses'].values():
        ids += list(c.get('items', {}))
        ids += ['a' + a for a in c.get('ann', {})]
    return ids


def to_local(utc_iso):
    """'2026-10-21T18:00' (UTC) -> local datetime."""
    if not utc_iso:
        return None
    d = dt.datetime.fromisoformat(utc_iso.replace('Z', '')[:16])
    return d.replace(tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None)


def fmt(d):
    return d.strftime('%a %b %-d %-I:%M %p') if d else '-'


# ---------- commands ----------

def cmd_setup(a):
    cfg = load_config(required=False)
    if a.root:
        cfg['root'] = a.root
    if 'root' not in cfg:
        sys.exit('--root is required the first time')
    if a.reminders is not None:
        cfg['reminders_list'] = None if a.reminders.lower() == 'none' else a.reminders
    if a.calendar is not None:
        cfg['calendar'] = None if a.calendar.lower() == 'none' else a.calendar
    cfg.setdefault('reminders_list', None)
    cfg.setdefault('calendar', None)
    cfg.setdefault('extra_course_ids', [])
    cfg.setdefault('skip_course_ids', [])
    cfg.setdefault('courses', {})
    cfg.setdefault('last_sweep', '')
    os.makedirs(root_dir(cfg), exist_ok=True)
    save_json(CONFIG, cfg)
    if not os.path.exists(manifest_path(cfg)):
        save_json(manifest_path(cfg), load_manifest(cfg))
    print('Saved', CONFIG)
    print(json.dumps(cfg, indent=1))


def cmd_show(a):
    cfg = load_config()
    print('config:', CONFIG)
    print(json.dumps({k: v for k, v in cfg.items() if k != 'courses'}, indent=1))
    man = load_manifest(cfg)
    print('\nclasses:')
    for cid, c in cfg.get('courses', {}).items():
        n = len(man['courses'].get(cid, {}).get('items', {}))
        print('  %s  %s  ->  %s  (%d items known)' % (cid, c.get('short', ''), os.path.join(root_dir(cfg), c['folder']), n))
    log = os.path.join(root_dir(cfg), '_sweep_log.md')
    if os.path.exists(log):
        print('\nrecent log (%s):' % log)
        print(''.join(open(log).readlines()[-30:]))


def cmd_course(a):
    cfg = load_config()
    if a.extra or a.skip:
        key = 'extra_course_ids' if a.extra else 'skip_course_ids'
        if a.id not in cfg[key]:
            cfg[key].append(a.id)
        save_json(CONFIG, cfg)
        print('%s now: %s' % (key, cfg[key]))
        if not a.folder:
            return
    if not a.folder:
        sys.exit('--folder is required')
    entry = cfg['courses'].setdefault(a.id, {})
    entry['folder'] = a.folder
    if a.short:
        entry['short'] = a.short
    if a.name:
        entry['name'] = a.name
    base = os.path.join(root_dir(cfg), a.folder)
    for cat in CATEGORIES:
        os.makedirs(os.path.join(base, cat), exist_ok=True)
    save_json(CONFIG, cfg)
    print('OK %s -> %s' % (a.id, base))


def cmd_script(a):
    src = open(os.path.join(HERE, a.which + '.js')).read()
    if a.which == 'pull':
        cfg = load_config()
        man = load_manifest(cfg)
        header = '\n'.join([
            'const LAST = %s;' % json.dumps(cfg.get('last_sweep', '')),
            'const EXTRA = %s;' % json.dumps(cfg.get('extra_course_ids', [])),
            'const SKIP = %s;' % json.dumps(cfg.get('skip_course_ids', [])),
            'const KNOWN = new Set(%s);' % json.dumps(known_ids(man), separators=(',', ':')),
        ])
        src = src.replace('//@HEADER@', header)
    print(src)


def classify(x, kids):
    h = (x.get('h') or '').lower()
    if x.get('url'):
        return 'FILE'
    if x.get('t') == 'ultraDocumentBody':
        return 'DOC-BODY'
    if 'asmt' in h or 'assignment' in h or 'test' in h:
        return 'ASSIGNMENT'
    if h == 'folder' and any(k.get('t') == 'ultraDocumentBody' for k in kids.get(x['id'], [])):
        return 'DOC'
    if h in ('', 'document', 'blankpage'):
        return 'DOC'
    if 'link' in h or 'lti' in h:
        return 'LINK'
    if h in ('folder', 'lesson'):
        return 'FOLDER'
    return 'OTHER:' + h


def cmd_ingest(a):
    cfg = load_config()
    src = a.file
    if not src:
        deadline = time.time() + a.wait
        while True:
            hits = sorted(glob.glob(os.path.join(DOWNLOADS, 'bbsweep-pull*.json')), key=os.path.getmtime)
            if hits and time.time() - os.path.getmtime(hits[-1]) < 1800:
                src = hits[-1]
                break
            if time.time() > deadline:
                sys.exit('No bbsweep-pull.json in ~/Downloads from the last 30 min. Fall back to get_page_text '
                         '(see SKILL.md), or check that Chrome saves downloads to ~/Downloads without asking.')
            time.sleep(1)
    with open(src) as f:
        pull = json.load(f)
    shutil.copyfile(src, last_pull_path(cfg))
    if not a.file:
        for p in glob.glob(os.path.join(DOWNLOADS, 'bbsweep-pull*.json')):
            os.remove(p)
    man = load_manifest(cfg)
    summary = ['Pulled %s (UTC) as %s. Last sweep: %s' % (pull['pulled'], pull['userName'], cfg.get('last_sweep') or 'never (first run)')]
    details, unmapped = [], []
    for c in pull['courses']:
        mc = man['courses'].get(c['id'], {})
        seen, seen_ann = mc.get('items', {}), mc.get('ann', {})
        conf = cfg['courses'].get(c['id'])
        folder = os.path.join(root_dir(cfg), conf['folder']) if conf else None
        if not conf:
            unmapped.append(c)
        kids = {}
        for x in c['items']:
            kids.setdefault(x.get('p'), []).append(x)
        rows = []
        for x in c['items']:
            kind = classify(x, kids)
            if kind == 'DOC-BODY':
                continue
            prev = seen.get(x['id'])
            if prev is None:
                tag = 'NEW'
            elif x.get('m') and x['m'] > (prev.get('m') or ''):
                tag = 'CHANGED'
            else:
                continue
            if kind == 'FOLDER' and tag == 'CHANGED':
                continue  # a folder's own timestamp moves whenever anything inside it changes
            line = '  %s %s %s "%s"' % (tag, kind, x['id'], x.get('t'))
            if x.get('file'):
                line += ' file=%s' % x['file']
            if x.get('url'):
                line += ' url=%s' % x['url']
            if kind == 'DOC':
                body_child = next((k for k in kids.get(x['id'], []) if k.get('t') == 'ultraDocumentBody'), None)
                body = x.get('body') or (body_child or {}).get('body') or ''
                line += ' body_id=%s' % (body_child['id'] if body_child else x['id'])
                line += (' text="%s"' % body[:300]) if body else ' text=(empty: body is an embedded page, fetch it)'
            elif x.get('body'):
                line += ' text="%s"' % x['body'][:200]
            line += ' modified=%s parent=%s' % (x.get('m'), x.get('p'))
            rows.append(line)
        anns = []
        for n in c['ann']:
            prev = seen_ann.get(n['id'])
            if prev is None or (n.get('m') and n['m'] > (prev.get('m') or '')):
                anns.append('  ANNOUNCEMENT %s %s "%s": %s' % (n['id'], fmt(to_local(n.get('c'))), n['t'], n.get('b', '')[:600]))
        files = sum(1 for r in rows if ' FILE ' in r)
        summary.append('  %s %s: %d new/changed (%d files), %d new announcements | %s' % (
            c['id'], (conf or {}).get('short') or c['name'][:45], len(rows), files, len(anns),
            folder or 'NO FOLDER YET'))
        if c.get('err'):
            summary.append('    (some requests failed for this class: %s)' % c['err'])
        details.append('\n== %s %s' % (c['id'], c['name']))
        details += (rows + anns) or ['  nothing new']
    now = dt.datetime.now()
    due = []
    for c in pull['courses']:
        short = cfg['courses'].get(c['id'], {}).get('short') or suggest_short(c) or c['name'][:30]
        for col in c['cols']:
            d = to_local(col.get('due'))
            if d and d > now - dt.timedelta(days=1):
                # a gradebook-only column (no content id) often carries its creation time as the due date
                due.append((d, '%s: %s' % (short, col['n']), '' if col.get('cid') else '  (gradebook-only item: may just be its creation time)'))
        for e in pull.get('cal', []):
            if e[0] == c['id']:
                d = to_local(e[2])
                key = '%s: %s' % (short, e[1])
                if d and d > now - dt.timedelta(days=1) and not any(x[1] == key and abs((x[0] - d).total_seconds()) < 3600 for x in due):
                    due.append((d, key + ' (calendar)', ''))
    summary.append('\nUPCOMING DUE DATES ON BLACKBOARD (local time):')
    summary += ['  %s  %s%s' % (fmt(d), t, note) for d, t, note in sorted(due)] or ['  (none)']
    if unmapped:
        summary.append('\nCLASSES WITHOUT A FOLDER YET (suggested commands; adjust names if you like):')
        for c in unmapped:
            summary.append('  bbsweep.py course %s --folder "%s" --short "%s" --name "%s"' % (
                c['id'], suggest_folder(c), suggest_short(c), c['name'].replace('"', "'")))
    if pull.get('others'):
        summary.append('\nOTHER COURSES/ORGS ON BLACKBOARD, NOT IN THE SWEEP (include: course ID --extra; hide: course ID --skip):')
        summary += ['  %s %s (term: %s)' % (o['id'], o['name'], o.get('term') or '-') for o in pull['others']]
    summary.append('\nDETAILS:')
    report = '\n'.join(summary + details)
    full = os.path.join(root_dir(cfg), '_last_pull.md')
    with open(full, 'w') as f:
        f.write(report + '\n')
    if len(report) > 25000:
        print(report[:25000] + '\n... (cut here; the full report is in %s, read the rest from there)' % full)
    else:
        print(report)


def suggest_folder(c):
    name = re.sub(r'(Fall|Spring|Summer|Winter)\s+(Semester\s+)?\d{4}(-\d{4})?', '', c['name'])
    parts = [p.strip(' -') for p in re.split(r'\s+-\s+', name) if p.strip(' -')]
    best = max(parts, key=lambda p: len(re.sub(r'[^A-Za-z ]', '', p))) if parts else c['name']
    best = re.sub(r'^[A-Z_]{2,9}\s*\d{3,4}(\.\d+)?\s*', '', best)
    best = re.sub(r'\s*\([^)]*\)?\s*$', '', best)
    best = re.sub(r'\bSection\s+\w+.*$', '', best).strip(' -_.')
    best = re.sub(r'\s*:\s*', ' - ', best)
    return re.sub(r'/', '-', best) or c['id']


def suggest_short(c):
    m = re.search(r'([A-Z]{2,4})[ _]?(\d{3,4})', (c.get('courseId') or '') + ' ' + c['name'])
    return '%s %s' % (m.group(1), m.group(2)) if m else ''


def find_item(pull, item_id):
    for c in pull['courses']:
        for x in c['items']:
            if x['id'] == item_id:
                return c, x
    sys.exit('%s is not in the last pull' % item_id)


def cmd_record(a):
    cfg = load_config()
    pull = load_last_pull(cfg)
    c, x = find_item(pull, a.id)
    man = load_manifest(cfg)
    folder = os.path.join(root_dir(cfg), cfg['courses'].get(c['id'], {}).get('folder', ''))
    local = []
    for p in a.paths:
        p = os.path.expanduser(p)
        if os.path.isabs(p):
            p = os.path.relpath(p, folder)
        if not os.path.exists(os.path.join(folder, p)):
            sys.exit('Not found: %s (paths are relative to %s)' % (p, folder))
        local.append(p)
    if not local and not a.skip:
        sys.exit('Give the saved file path(s), or --skip to mark it as intentionally not downloaded')
    items = man['courses'].setdefault(c['id'], {'name': c['name']}).setdefault('items', {})
    items[a.id] = {'t': x.get('t'), 'm': x.get('m'), 'local': ' + '.join(local) if local else None}
    save_json(manifest_path(cfg), man)
    print('recorded %s -> %s' % (a.id, items[a.id]['local']))


def _norm(name):
    stem = os.path.splitext(os.path.basename(name))[0]
    stem = re.sub(r' \(\d+\)$', '', stem)
    return re.sub(r'[^a-z0-9]', '', stem.lower())


def wait_for_download(server_name, since, wait):
    deadline = time.time() + wait
    want = _norm(server_name) if server_name else ''
    while True:
        cands = []
        for p in glob.glob(os.path.join(DOWNLOADS, '*')):
            b = os.path.basename(p)
            if b.startswith('.') or b.endswith(('.crdownload', '.download', '.part')) or b.startswith('bbsweep-pull') or not os.path.isfile(p):
                continue
            if os.path.getmtime(p) >= since:
                cands.append(p)
        busy = glob.glob(os.path.join(DOWNLOADS, '*.crdownload'))
        match = [p for p in cands if want and _norm(p) == want]
        if match and not busy:
            return max(match, key=os.path.getmtime)
        if not want and len(cands) == 1 and not busy:
            return cands[0]
        if time.time() > deadline:
            names = ', '.join(os.path.basename(p) for p in cands) or 'none'
            sys.exit('Download not found in ~/Downloads (looking for "%s"; recent files: %s). '
                     'If it is there under another name, rerun with --file PATH.' % (server_name, names))
        time.sleep(1)


def cmd_grab(a):
    cfg = load_config()
    pull = load_last_pull(cfg)
    c, x = find_item(pull, a.id)
    conf = cfg['courses'].get(c['id'])
    if not conf:
        sys.exit('Set up a folder for this class first:  bbsweep.py course %s --folder "<name>"' % c['id'])
    class_dir = os.path.join(root_dir(cfg), conf['folder'])
    dest_dir = os.path.join(class_dir, CATEGORY_ALIASES.get(a.to, a.to))
    os.makedirs(dest_dir, exist_ok=True)
    src = os.path.expanduser(a.file) if a.file else wait_for_download(x.get('file') or '', time.time() - a.since, a.wait)
    ext = os.path.splitext(src)[1]
    title = re.sub(r'[/:]', '-', a.name or x.get('t') or os.path.basename(src)).strip()
    name = title if ext and title.lower().endswith(ext.lower()) else title + ext
    dest = os.path.join(dest_dir, name)
    if os.path.exists(dest):
        if filecmp.cmp(src, dest, shallow=False):
            os.remove(src)
            print('identical copy already saved:', dest)
        else:
            dest = os.path.splitext(dest)[0] + ' (updated %s)' % dt.date.today().isoformat() + ext
    if os.path.exists(src):
        shutil.move(src, dest)
    local = [os.path.relpath(dest, class_dir)]
    if ext.lower() == '.zip':
        out_dir = os.path.splitext(dest)[0]
        subprocess.run(['ditto', '-x', '-k', dest, out_dir], check=True)
        local.append(os.path.relpath(out_dir, class_dir) + '/')
    else:
        md = os.path.splitext(dest)[0] + '.md'
        try:
            n = _extract.extract(dest, md, title=os.path.splitext(name)[0])
            local.append(os.path.relpath(md, class_dir))
            if n == 0:
                print('note: no text found (scanned or image-only file)')
        except SystemExit as e:
            print('no text copy:', e)
        except Exception as e:  # a broken file should not stop the sweep
            print('text extraction failed:', e)
    man = load_manifest(cfg)
    items = man['courses'].setdefault(c['id'], {'name': c['name']}).setdefault('items', {})
    items[a.id] = {'t': x.get('t'), 'm': x.get('m'), 'local': ' + '.join(local)}
    save_json(manifest_path(cfg), man)
    print('saved', ' + '.join(os.path.join(conf['folder'], l) for l in local))


def cmd_finish(a):
    cfg = load_config()
    pull = load_last_pull(cfg)
    man = load_manifest(cfg)
    missing = []
    for c in pull['courses']:
        mc = man['courses'].setdefault(c['id'], {'name': c['name']})
        items, anns = mc.setdefault('items', {}), mc.setdefault('ann', {})
        for x in c['items']:
            prev = items.get(x['id'])
            if x.get('url') and not a.baseline:  # files only count once they are recorded
                if prev is None or (x.get('m') and x['m'] > (prev.get('m') or '') and prev.get('local') is not None):
                    missing.append('%s %s "%s"' % (c['name'][:30], x['id'], x.get('t')))
                continue
            items[x['id']] = {'t': x.get('t'), 'm': x.get('m'), 'local': prev.get('local') if prev else None}
        for n in c['ann']:
            anns[n['id']] = {'t': n['t'], 'm': n.get('m')}
    save_json(manifest_path(cfg), man)
    cfg['last_sweep'] = pull['pulled']
    save_json(CONFIG, cfg)
    print('Sweep saved (last_sweep = %s UTC).' % pull['pulled'])
    if missing:
        print('These files are still not recorded and will show up as new next time:')
        print('\n'.join('  ' + m for m in missing))


def cmd_log(a):
    cfg = load_config()
    p = os.path.join(root_dir(cfg), '_sweep_log.md')
    with open(p, 'a') as f:
        f.write('- %s: %s\n' % (dt.datetime.now().strftime('%Y-%m-%d %-I:%M %p'), a.text))
    print('logged to', p)


def cmd_extract(a):
    n = _extract.extract(os.path.expanduser(a.src), os.path.expanduser(a.dst), a.title)
    print('wrote %s (%d characters of text)' % (a.dst, n))


# ---------- Reminders / Calendar (AppleScript) ----------

AS_HELPERS = '''
on pad(n)
	set s to (n as integer) as string
	if length of s < 2 then set s to "0" & s
	return s
end pad
on isod(d)
	return ((year of d) as string) & "-" & pad(month of d as integer) & "-" & pad(day of d) & " " & pad(hours of d) & ":" & pad(minutes of d)
end isod
on mkdate(y, mo, dd, hh, mi)
	set t to current date
	set day of t to 1
	set year of t to y
	set month of t to mo
	set day of t to dd
	set time of t to (hh * 3600 + mi * 60)
	return t
end mkdate
'''

AS_REM_LIST = AS_HELPERS + '''
on run argv
	set ln to item 1 of argv
	tell application "Reminders"
		if not (exists list ln) then return "NO LIST"
		set L to list ln
		set ns to name of every reminder of L
		set cs to completed of every reminder of L
		set ds to due date of every reminder of L
	end tell
	set out to ""
	repeat with i from 1 to count of ns
		set d to item i of ds
		set dtxt to ""
		if d is not missing value then set dtxt to my isod(d)
		set out to out & (item i of cs) & tab & dtxt & tab & (item i of ns) & linefeed
	end repeat
	return out
end run
'''

AS_REM_ADD = AS_HELPERS + '''
on run argv
	set ln to item 1 of argv
	set t to my mkdate((item 3 of argv) as integer, (item 4 of argv) as integer, (item 5 of argv) as integer, (item 6 of argv) as integer, (item 7 of argv) as integer)
	if item 9 of argv is "1" then return "DRY RUN due " & my isod(t)
	tell application "Reminders"
		if not (exists list ln) then make new list with properties {name:ln}
		set r to make new reminder in list ln with properties {name:(item 2 of argv), body:(item 8 of argv), due date:t}
		return "ADDED due " & my isod(due date of r)
	end tell
end run
'''

AS_CAL_LIST = AS_HELPERS + '''
on run argv
	set cn to item 1 of argv
	set d1 to (current date) - 7 * days
	set d2 to (current date) + ((item 2 of argv) as integer) * days
	tell application "Calendar"
		if not (exists calendar cn) then return "NO CALENDAR"
		set evs to every event of calendar cn whose start date >= d1 and start date <= d2
		set out to ""
		repeat with e in evs
			set out to out & my isod(start date of e) & tab & (summary of e) & linefeed
		end repeat
	end tell
	return out
end run
'''

AS_CAL_ADD = AS_HELPERS + '''
on run argv
	set cn to item 1 of argv
	set t to my mkdate((item 3 of argv) as integer, (item 4 of argv) as integer, (item 5 of argv) as integer, (item 6 of argv) as integer, (item 7 of argv) as integer)
	set t2 to t + ((item 8 of argv) as integer) * minutes
	if item 11 of argv is "1" then return "DRY RUN " & my isod(t) & " to " & my isod(t2)
	tell application "Calendar"
		if not (exists calendar cn) then
			try
				make new calendar with properties {name:cn}
			on error
				return "NO CALENDAR: create a calendar named " & cn & " in the Calendar app, then rerun"
			end try
		end if
		tell calendar cn to make new event with properties {summary:(item 2 of argv), start date:t, end date:t2, location:(item 9 of argv), description:(item 10 of argv)}
		return "ADDED " & my isod(t) & " to " & my isod(t2)
	end tell
end run
'''


def osa(src, *args):
    r = subprocess.run(['osascript', '-', *[str(x) for x in args]], input=src, text=True, capture_output=True)
    if r.returncode:
        sys.exit('AppleScript failed: ' + r.stderr.strip())
    return r.stdout.rstrip('\n')


def when(local, utc):
    try:
        return to_local(utc) if utc else dt.datetime.strptime(local, '%Y-%m-%d %H:%M')
    except ValueError as e:
        sys.exit('Bad date %r (%s). Use "YYYY-MM-DD HH:MM" local time, or --due-utc/--start-utc with the Blackboard UTC time.' % (utc or local, e))


def cmd_reminders(a):
    cfg = load_config()
    ln = cfg.get('reminders_list')
    if not ln:
        sys.exit('Reminders are turned off (setup --reminders "<list name>" to turn them on)')
    if a.action == 'list':
        out = osa(AS_REM_LIST, ln)
        if out == 'NO LIST':
            print('(list "%s" does not exist yet; the first add creates it)' % ln)
            return
        rows = [r.split('\t', 2) for r in out.splitlines() if r]
        rows = [r for r in rows if a.all or r[0] == 'false']
        for done, due, name in sorted(rows, key=lambda r: r[1] or '9'):
            print('%s %s  %s' % ('[x]' if done == 'true' else '[ ]', due or '(no date)     ', name))
        print('(%d shown; nested subtasks are invisible to AppleScript)' % len(rows))
        return
    if not a.name or not (a.due or a.due_utc):
        sys.exit('add needs --name and --due or --due-utc')
    if not a.force:
        for r in osa(AS_REM_LIST, ln).splitlines():
            parts = r.split('\t', 2)
            if len(parts) == 3 and parts[0] == 'false' and parts[2].strip().lower() == a.name.strip().lower():
                sys.exit('An open reminder with that name already exists (use --force to add anyway)')
    d = when(a.due, a.due_utc)
    print(osa(AS_REM_ADD, ln, a.name, d.year, d.month, d.day, d.hour, d.minute, a.notes or '', '1' if a.dry_run else '0'))


def cmd_calendar(a):
    cfg = load_config()
    cn = cfg.get('calendar')
    if not cn:
        sys.exit('No exam calendar set (setup --calendar "<calendar name>"); put exams in Reminders instead')
    if a.action == 'list':
        out = osa(AS_CAL_LIST, cn, a.days)
        print('\n'.join(sorted(set(out.splitlines()))) if out else '(no events in that window)')
        return
    if not a.title or not (a.start or a.start_utc):
        sys.exit('add needs --title and --start or --start-utc')
    d = when(a.start, a.start_utc)
    if not a.force and not a.dry_run:
        out = osa(AS_CAL_LIST, cn, 400)
        if out.startswith('NO CALENDAR'):
            out = ''
        for r in out.splitlines():
            day, _, title = r.partition('\t')
            if day[:10] == d.strftime('%Y-%m-%d') and title.strip().lower() == a.title.strip().lower():
                sys.exit('That event is already on the calendar (use --force to add anyway)')
    print(osa(AS_CAL_ADD, cn, a.title, d.year, d.month, d.day, d.hour, d.minute, a.minutes,
              a.location or '', a.notes or '', '1' if a.dry_run else '0'))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('setup'); p.add_argument('--root'); p.add_argument('--reminders'); p.add_argument('--calendar'); p.set_defaults(fn=cmd_setup)
    p = sp.add_parser('show'); p.set_defaults(fn=cmd_show)
    p = sp.add_parser('course'); p.add_argument('id'); p.add_argument('--folder'); p.add_argument('--short'); p.add_argument('--name')
    p.add_argument('--extra', action='store_true'); p.add_argument('--skip', action='store_true'); p.set_defaults(fn=cmd_course)
    p = sp.add_parser('script'); p.add_argument('which', choices=['pull', 'grades']); p.set_defaults(fn=cmd_script)
    p = sp.add_parser('ingest'); p.add_argument('--file'); p.add_argument('--wait', type=int, default=15); p.set_defaults(fn=cmd_ingest)
    p = sp.add_parser('record'); p.add_argument('id'); p.add_argument('paths', nargs='*'); p.add_argument('--skip', action='store_true'); p.set_defaults(fn=cmd_record)
    p = sp.add_parser('grab'); p.add_argument('id'); p.add_argument('--to', required=True); p.add_argument('--name'); p.add_argument('--file')
    p.add_argument('--since', type=int, default=120); p.add_argument('--wait', type=int, default=30); p.set_defaults(fn=cmd_grab)
    p = sp.add_parser('finish'); p.add_argument('--baseline', action='store_true'); p.set_defaults(fn=cmd_finish)
    p = sp.add_parser('log'); p.add_argument('text'); p.set_defaults(fn=cmd_log)
    p = sp.add_parser('extract'); p.add_argument('src'); p.add_argument('dst'); p.add_argument('--title'); p.set_defaults(fn=cmd_extract)
    p = sp.add_parser('reminders'); p.add_argument('action', choices=['list', 'add']); p.add_argument('--all', action='store_true')
    p.add_argument('--name'); p.add_argument('--due'); p.add_argument('--due-utc'); p.add_argument('--notes')
    p.add_argument('--dry-run', action='store_true'); p.add_argument('--force', action='store_true'); p.set_defaults(fn=cmd_reminders)
    p = sp.add_parser('calendar'); p.add_argument('action', choices=['list', 'add']); p.add_argument('--days', type=int, default=150)
    p.add_argument('--title'); p.add_argument('--start'); p.add_argument('--start-utc'); p.add_argument('--minutes', type=int, default=60)
    p.add_argument('--location'); p.add_argument('--notes'); p.add_argument('--dry-run', action='store_true'); p.add_argument('--force', action='store_true')
    p.set_defaults(fn=cmd_calendar)
    a = ap.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
