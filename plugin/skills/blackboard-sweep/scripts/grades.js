// Submission + grade status for every graded item. Run with javascript_tool in the SAME tab,
// right after pull.js (it reads window.__bb, which pull.js leaves behind). It returns
// immediately and fills the page body when done: wait ~5 s, then get_page_text. The text
// starts with "GRADES" once it has finished.
// status: Graded / NeedsGrading / InProgress; "no attempt" = nothing submitted yet.
(() => {
  const B = 'https://blackboard.olemiss.edu', bb = window.__bb;
  if (!bb) return 'window.__bb missing: run pull.js in this tab first';
  const U = bb.user;
  const j = async u => { const r = await fetch(B + u, { credentials: 'include' }); return r.ok ? r.json() : { err: r.status }; };
  const jobs = [];
  for (const [cid, c] of Object.entries(bb.courses)) {
    for (const col of c.cols) {
      if (!col.due && !/hw|homework|lab|quiz|check|report|assign|exam|test|project|paper|essay|presentation/i.test(col.n)) continue;
      jobs.push(Promise.all([
        j(`/learn/api/public/v1/courses/${cid}/gradebook/columns/${col.id}/users/${U}`),
        j(`/learn/api/public/v2/courses/${cid}/gradebook/columns/${col.id}/attempts?userId=${U}`),
      ]).then(([u, at]) => {
        const atts = (at.results || []).map(x => (x.status || '') + ' ' + (x.created || '').slice(0, 16));
        const grade = u.displayGrade && u.displayGrade.text;
        return [c.name.slice(0, 40), col.n, col.due || '-', u.status || (atts.length ? 'attempted' : 'no attempt'), grade || '', atts.join(', ')].join(' | ');
      }));
    }
  }
  Promise.all(jobs).then(rows => {
    document.body.innerHTML = '<pre></pre>';
    document.querySelector('pre').textContent = ('GRADES ' + rows.length + ' items (course | item | due UTC | status | grade | attempts)\n' + rows.join('\n')).replace(/\?[^"'\s]*/g, '');
  });
  return 'started ' + jobs.length + ' items; wait ~5 s, then get_page_text';
})();
