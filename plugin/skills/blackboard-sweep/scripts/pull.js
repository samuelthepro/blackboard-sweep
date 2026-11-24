// Blackboard sweep pull. Do not paste this file directly: run
//   python3 -I <scripts>/bbsweep.py script pull
// which prints this file with the LAST / EXTRA / SKIP / KNOWN lines filled in from your
// config and manifest. Paste that output into javascript_tool.
//
// Run it on a LIGHT Blackboard page (https://blackboard.olemiss.edu/learn/api/public/v1/system/version).
// Never on an /ultra/ page: the Ultra app freezes the tab and every browser call times out.
// The result is written into the page body; read it with get_page_text (javascript_tool
// output is cut at ~4 KB and hides anything that looks like a "?query").
//@HEADER@
const B = 'https://blackboard.olemiss.edu';
const iso = t => t ? new Date(typeof t === 'number' ? t : Date.parse(t)).toISOString().slice(0, 16) : '';
const clean = h => (h || '').replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim();
const j = async u => {
  for (let k = 0; ; k++) {
    const r = await fetch(B + u, { credentials: 'include' });
    if (r.status === 429 && k < 4) { await new Promise(s => setTimeout(s, 700 * (k + 1))); continue; } // too many requests at once
    return r.ok ? r.json() : { err: r.status };
  }
};
const show = text => { document.body.innerHTML = '<pre></pre>'; document.querySelector('pre').textContent = text.replace(/\?[^"'\s]*/g, ''); };

const me = await j('/learn/api/public/v1/users/me');
if (me.err) { show('SIGNED OUT (' + me.err + '): do the sign-in step in SKILL.md, then run this again'); throw new Error('signed out'); }
const [mem, terms] = await Promise.all([
  j(`/learn/api/v1/users/${me.id}/memberships?expand=course.effectiveAvailability&limit=200`),
  j('/learn/api/public/v1/terms?limit=200'),
]);
if (mem.err) { show('MEMBERSHIPS FAILED ' + mem.err); throw new Error('memberships'); }

// A course is "current" when its term's date range covers today (or it is listed in EXTRA).
const now = Date.now(), T = {};
for (const t of terms.results || []) {
  const d = (t.availability && t.availability.duration) || {};
  T[t.id] = { n: t.name, s: Date.parse(d.start || ''), e: Date.parse(d.end || '') };
}
const term = c => (c.term && T[c.term.id]) || null;
const active = c => { const t = term(c); return !!t && t.s <= now && now <= t.e; };
const all = (mem.results || []).filter(m => m.course).map(m => m.course);
const courses = all.filter(c => !SKIP.includes(c.id) && (EXTRA.includes(c.id) || active(c)));
const others = all.filter(c => !courses.includes(c) && !SKIP.includes(c.id) && c.effectiveAvailability && !(term(c) && term(c).e < now));

const res = await Promise.all(courses.map(c => Promise.all([
  j(`/learn/api/v1/courses/${c.id}/contents?recursive=true&limit=500`),
  j(`/learn/api/v1/courses/${c.id}/gradebook/columns?limit=200`),
  j(`/learn/api/v1/courses/${c.id}/announcements?limit=50`),
])));

const pulled = new Date().toISOString().slice(0, 16);
const lines = [`PULLED ${pulled} LAST ${LAST || '(first run)'} USER ${me.id} ${me.userName} KNOWN ${KNOWN.size}`];
const data = { pulled, user: me.id, userName: me.userName, courses: [], cal: [], others: [] };
window.__bb = { user: me.id, courses: {} };
courses.forEach((c, i) => {
  const [ct, g, a] = res[i];
  const items = (ct.results || []).map(x => {
    const h = x.contentDetail ? Object.keys(x.contentDetail)[0] : '';
    const cd = x.contentDetail ? x.contentDetail[h] : {};
    return {
      id: x.id, t: x.title, h: h.replace('resource/x-bb-', ''), m: iso(x.modifiedDate), p: x.parentId,
      vis: x.visibility, body: clean(x.body && x.body.rawText).slice(0, 300) || undefined,
      file: cd && cd.file ? (cd.file.fileName || cd.file.name) : undefined,
      url: cd && cd.file && cd.file.permanentUrl ? cd.file.permanentUrl : undefined,
    };
  });
  const fresh = items.filter(x => !KNOWN.has(x.id));
  const changed = items.filter(x => KNOWN.has(x.id) && LAST && x.m > LAST);
  const t = term(c);
  lines.push('', `== ${c.id} | ${c.name} | ${c.courseId} | term ${t ? t.n : '-'} | items ${items.length} | new ${fresh.length} | changed ${changed.length}` + (ct.err ? ` | CONTENTS FAILED ${ct.err}` : ''));
  for (const x of fresh) lines.push('NEW ' + JSON.stringify(x));
  for (const x of changed) lines.push('CHANGED ' + JSON.stringify(x));
  const cols = (g.results || []).map(x => ({ id: x.id, n: x.name || x.columnName, due: iso(x.dueDate), cid: x.contentId }));
  window.__bb.courses[c.id] = { name: c.name, cols };
  const ann = (a.results || []).map(x => ({ id: x.id, t: x.title, c: iso(x.createdDate || x.startDate), m: iso(x.modifiedDate), b: clean(x.body && x.body.rawText).slice(0, 1500) }));
  data.courses.push({ id: c.id, name: c.name, courseId: c.courseId, items, cols, ann, err: ct.err || g.err || a.err || undefined });
  lines.push('COLS ' + cols.map(x => [x.id, x.n, x.due, x.cid || ''].join('|')).join(' ;; '));
  let old = 0;
  for (const x of a.results || []) {
    const cr = iso(x.createdDate || x.startDate), md = iso(x.modifiedDate);
    if (!KNOWN.has('a' + x.id) || (LAST && md > LAST)) lines.push(`ANN-NEW ${x.id} | created ${cr} | modified ${md} | ${x.title} | ${clean(x.body && x.body.rawText).slice(0, 700)}`);
    else old++;
  }
  if (old) lines.push(`ANN-OLD ${old} already seen`);
});

// Every due date Blackboard knows about from a week ago to ~15 weeks out (the API allows 16 weeks max).
const since = new Date(now - 7 * 864e5).toISOString(), until = new Date(now + 104 * 864e5).toISOString();
const cal = await j(`/learn/api/public/v1/calendars/items?since=${since}&until=${until}&limit=200`);
const ids = new Set(courses.map(c => c.id));
data.cal = (cal.results || []).filter(x => ids.has(x.calendarId)).map(x => [x.calendarId, x.title, iso(x.start), x.type]);
lines.push('', 'CAL ' + data.cal.map(x => x.join('|')).join(' ;; '));
for (const c of others) {
  const tn = term(c) ? term(c).n : (c.term ? c.term.id : '-');
  data.others.push({ id: c.id, name: c.name, term: tn });
  lines.push(`OTHER ${c.id} | ${c.name} | term ${tn}`);
}
show(lines.join('\n'));
// Hand the full pull to bbsweep.py: Chrome saves this to ~/Downloads, then `bbsweep.py ingest` picks it up.
// Chrome allows one automatic download per tab, so run this in a fresh tab each sweep.
const dl = document.createElement('a');
dl.href = URL.createObjectURL(new Blob([JSON.stringify(data)], { type: 'application/json' }));
dl.download = 'bbsweep-pull.json';
document.body.appendChild(dl);
dl.click();
`ok ${courses.length} courses; saved bbsweep-pull.json to Downloads. Next: bbsweep.py ingest`;
