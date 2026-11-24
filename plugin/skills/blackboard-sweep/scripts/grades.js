// Submission + grade status for every graded item. Run with javascript_tool in the SAME tab,
// right after pull.js (it reads window.__bb, which pull.js leaves behind). It returns
// immediately and fills the page body when done: wait ~15 s, then get_page_text. The text
// starts with "GRADES" once it has finished (before that the page still shows the pull).
//
// Blackboard answers 429 when too many requests run at once, so at most 6 run together and a
// 429 is retried. A request that still fails is reported as "check failed", never as "no attempt".
(() => {
  const bb = window.__bb;
  if (!bb) return 'window.__bb missing: run pull.js in this tab first';
  const U = bb.user;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  let active = 0;
  const queue = [];
  const take = () => new Promise(r => { if (active < 6) { active++; r(); } else queue.push(r); });
  const give = () => { const next = queue.shift(); if (next) next(); else active--; };
  const j = async u => {
    await take();
    try {
      for (let k = 0; k < 5; k++) {
        const r = await fetch(u, { credentials: 'include' });
        if (r.status === 429) { await sleep(700 * (k + 1)); continue; }
        return r.ok ? await r.json() : { err: r.status };
      }
      return { err: 429 };
    } catch (e) {
      return { err: 'network' };
    } finally {
      give();
    }
  };
  const round = n => Math.round(n * 100) / 100;
  const recent = due => due && Date.parse(due + 'Z') > Date.now() - 14 * 864e5;
  const wanted = col => col.due || /hw|homework|lab|quiz|check|report|assign|exam|test|project|paper|essay|presentation|midterm|final/i.test(col.n);

  const rowFor = async (cid, c, col, possible) => {
    const v2 = `/learn/api/public/v2/courses/${cid}/gradebook/columns/${col.id}/attempts`;
    const [u, at] = await Promise.all([
      j(`/learn/api/public/v1/courses/${cid}/gradebook/columns/${col.id}/users/${U}`),
      j(`${v2}?userId=${U}`),
    ]);
    const failed = [u.err, at.err].find(e => e && e !== 404); // 404 = no record, which is normal
    const atts = at.results || [];
    const sent = atts.filter(x => x.status !== 'InProgress');
    const drafts = atts.length - sent.length;
    // Team items can say NeedsGrading with zero attempts: that means nothing was submitted.
    let status;
    if (failed) status = failed === 403 ? 'hidden right now (403), often while being graded' : `check failed (${failed}), run again`;
    else if (u.exempt) status = 'exempt';
    else if (sent.length || u.score != null) status = (u.status || 'attempted') + (drafts ? ' + open draft' : '');
    else if (drafts) status = 'draft open, NOT submitted';
    else status = 'no attempt';
    // An attempt's "created" is when it was opened. The real submit time is on its receipt.
    let submitted = '';
    if (sent.length && recent(col.due)) {
      const one = await j(`${v2}/${sent[sent.length - 1].id}`);
      submitted = ((one.attemptReceipt && one.attemptReceipt.submissionDate) || '').slice(0, 16);
    }
    const grade = u.score != null ? round(u.score) + (possible != null ? '/' + round(possible) : '') : '';
    const due = col.due ? col.due + (col.cid ? '' : ' (gradebook-only item, may just be its creation time)') : '-';
    return [c.name.slice(0, 40), col.n, due, status, grade,
      atts.map(x => (x.status || '') + ' opened ' + (x.created || '').slice(0, 16)).join(', '),
      submitted && 'submitted ' + submitted,
      u.overridden && 'grade changed ' + u.overridden.slice(0, 16),
    ].filter((x, i) => i < 5 || x).join(' | ');
  };

  window.__grades = 'pending';
  Promise.all(Object.entries(bb.courses).map(async ([cid, c]) => {
    const list = await j(`/learn/api/public/v2/courses/${cid}/gradebook/columns?limit=200`);
    const possible = {};
    for (const x of list.results || []) possible[x.id] = x.score && x.score.possible;
    return Promise.all(c.cols.filter(wanted).map(col => rowFor(cid, c, col, possible[col.id])));
  })).then(groups => {
    const rows = groups.flat();
    document.body.innerHTML = '<pre></pre>';
    document.querySelector('pre').textContent = ('GRADES ' + rows.length + ' items (course | item | due UTC | status | grade | attempts)\n' + rows.join('\n')).replace(/\?[^"'\s]*/g, '');
    window.__grades = 'done ' + rows.length;
  }).catch(e => {
    document.body.innerHTML = '<pre></pre>';
    document.querySelector('pre').textContent = 'GRADES FAILED ' + e;
    window.__grades = 'failed';
  });
  return 'started; wait ~15 s, then get_page_text';
})();
