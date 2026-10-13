"""Turn a class file into a plain-text .md next to it, using only what ships with macOS.

pdf            pdftotext -layout if Homebrew poppler is installed, otherwise macOS PDFKit
docx doc rtf   textutil (built into macOS)
odt html htm
pptx           slide text in presentation order + speaker notes (zip/XML)
ppt            legacy binary PowerPoint (OLE stream walk)
xlsx           every sheet as tab-separated rows (zip/XML)
txt md csv py  copied as-is (and most other plain-text code files)
"""
import html
import os
import re
import shutil
import struct
import subprocess
import zipfile

TEXT_EXT = {'.txt', '.md', '.csv', '.tsv', '.py', '.c', '.h', '.cpp', '.java', '.js', '.json',
            '.m', '.r', '.sql', '.v', '.vhd', '.asm', '.ino', '.tex', '.xml', '.yaml', '.yml'}


def extract(src, dst, title=None):
    ext = os.path.splitext(src)[1].lower()
    title = title or os.path.splitext(os.path.basename(src))[0]
    if ext == '.pdf':
        body = pdf_text(src)
    elif ext in ('.docx', '.doc', '.rtf', '.odt', '.html', '.htm', '.webarchive'):
        body = run(['textutil', '-convert', 'txt', '-stdout', src])
    elif ext == '.pptx':
        body = pptx_text(src)
    elif ext == '.ppt':
        body = ppt_text(src)
    elif ext in ('.xlsx', '.xlsm'):
        body = xlsx_text(src)
    elif ext in TEXT_EXT:
        body = open(src, encoding='utf-8', errors='replace').read()
    else:
        raise SystemExit('no extractor for %s files' % ext)
    body = body.strip()
    out = '# %s\n\nSource: %s\n\n%s\n' % (title, os.path.basename(src), body or '(no text found: scanned or image-only file)')
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(out)
    return len(body)


def run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def pdf_text(src):
    if shutil.which('pdftotext'):
        return run(['pdftotext', '-layout', src, '-'])
    jxa = ('ObjC.import("PDFKit");function run(a){var d=$.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(a[0]));'
           'if(!d)return "";var o=[];for(var i=0;i<d.pageCount;i++){var p=d.pageAtIndex(i).string;'
           'o.push("--- page "+(i+1)+" ---\\n"+(p.isNil()?"":p.js))}return o.join("\\n\\n")}')
    return run(['osascript', '-l', 'JavaScript', '-e', jxa, src])


def _runs(xml):
    paras = []
    for p in re.findall(r'<a:p>.*?</a:p>|<a:p .*?</a:p>', xml, flags=re.S):
        t = html.unescape(''.join(re.findall(r'<a:t>(.*?)</a:t>', p, flags=re.S))).strip()
        if t:
            paras.append(t)
    return paras


def pptx_text(src):
    z = zipfile.ZipFile(src)
    names = z.namelist()
    slides = sorted([n for n in names if re.fullmatch(r'ppt/slides/slide\d+\.xml', n)],
                    key=lambda n: int(re.search(r'(\d+)\.xml$', n).group(1)))
    try:  # presentation order, not file-number order
        pres = z.read('ppt/presentation.xml').decode('utf8')
        rels = z.read('ppt/_rels/presentation.xml.rels').decode('utf8')
        rmap = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="(slides/slide\d+\.xml)"', rels))
        rmap.update({a: b for b, a in re.findall(r'Target="(slides/slide\d+\.xml)"[^>]*Id="(rId\d+)"', rels)})
        order = ['ppt/' + rmap[r] for r in re.findall(r'<p:sldId [^>]*r:id="(rId\d+)"', pres) if r in rmap]
        if order:
            slides = order
    except Exception:
        pass
    out = []
    for i, s in enumerate(slides, 1):
        out.append('## Slide %d' % i)
        out.extend(_runs(z.read(s).decode('utf8')))
        num = re.search(r'(\d+)\.xml$', s).group(1)
        nn, relp = 'ppt/notesSlides/notesSlide%s.xml' % num, 'ppt/slides/_rels/slide%s.xml.rels' % num
        if relp in names:
            m = re.search(r'Target="\.\./notesSlides/(notesSlide\d+\.xml)"', z.read(relp).decode('utf8'))
            nn = 'ppt/notesSlides/' + m.group(1) if m else None
        if nn and nn in names:
            notes = [p for p in _runs(z.read(nn).decode('utf8')) if not p.isdigit()]
            if notes:
                out += ['', 'Notes: ' + ' '.join(notes)]
        out.append('')
    return '\n'.join(out)


def xlsx_text(src):
    z = zipfile.ZipFile(src)
    names = z.namelist()
    shared = []
    if 'xl/sharedStrings.xml' in names:
        for si in re.findall(r'<si>(.*?)</si>', z.read('xl/sharedStrings.xml').decode('utf8'), flags=re.S):
            shared.append(html.unescape(''.join(re.findall(r'<t[^>]*>(.*?)</t>', si, flags=re.S))))
    wb = z.read('xl/workbook.xml').decode('utf8')
    rels = z.read('xl/_rels/workbook.xml.rels').decode('utf8')
    rmap = {}
    for rel in re.findall(r'<Relationship [^>]*>', rels):
        i, t = re.search(r'Id="([^"]+)"', rel), re.search(r'Target="([^"]+)"', rel)
        if i and t:
            rmap[i.group(1)] = t.group(1).lstrip('/').replace('xl/', '', 1)
    out = []
    for sheet in re.findall(r'<sheet [^>]*>', wb):
        name = html.unescape(re.search(r'name="([^"]*)"', sheet).group(1))
        rid = re.search(r'r:id="([^"]+)"', sheet).group(1)
        path = 'xl/' + rmap.get(rid, '')
        if path not in names:
            continue
        out.append('## Sheet: %s' % name)
        for row in re.findall(r'<row[^>]*>(.*?)</row>', z.read(path).decode('utf8'), flags=re.S):
            cells = []
            for attrs, inner in re.findall(r'<c([^>]*?)(?:/>|>(.*?)</c>)', row, flags=re.S):
                col = re.search(r'r="([A-Z]+)', attrs)
                idx = _col_index(col.group(1)) if col else len(cells)
                while len(cells) < idx:
                    cells.append('')
                v = re.search(r'<v>(.*?)</v>', inner or '', flags=re.S)
                typ = re.search(r't="(\w+)"', attrs)
                if typ and typ.group(1) == 's' and v:
                    val = shared[int(v.group(1))]
                elif typ and typ.group(1) == 'inlineStr':
                    val = html.unescape(''.join(re.findall(r'<t[^>]*>(.*?)</t>', inner or '', flags=re.S)))
                else:
                    val = html.unescape(v.group(1)) if v else ''
                cells.append(val.replace('\t', ' ').replace('\n', ' '))
            if any(cells):
                out.append('\t'.join(cells).rstrip())
        out.append('')
    return '\n'.join(out)


def _col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def ppt_text(src):
    s = _cfb_stream(src, 'PowerPoint Document')
    items, ctx = [], {'slide': 0}
    _walk(s, 0, len(s), items, ctx)
    lines = []
    for kind, v in items:
        if kind == 'slide':
            lines.append('\n## Slide %d\n' % v)
        elif kind == 'notes':
            lines.append('\n### Notes page\n')
        else:
            t = v.replace('\r', '\n').replace('\x0b', '\n').strip()
            if t and t != '*':
                lines.append(t)
    return '\n'.join(lines)


def _cfb_stream(path, want):
    d = open(path, 'rb').read()
    ssz = 1 << struct.unpack_from('<H', d, 30)[0]
    mssz = 1 << struct.unpack_from('<H', d, 32)[0]
    ndifat_fat = struct.unpack_from('<I', d, 44)[0]
    dir_start = struct.unpack_from('<I', d, 48)[0]
    mini_cut = struct.unpack_from('<I', d, 56)[0]
    minifat_start = struct.unpack_from('<I', d, 60)[0]
    difat_start = struct.unpack_from('<I', d, 68)[0]
    sec = lambda n: d[(n + 1) * ssz:(n + 2) * ssz]
    difat = list(struct.unpack_from('<109I', d, 76))
    n = difat_start
    while n < 0xFFFFFFFA:
        s = sec(n)
        difat += struct.unpack_from('<%dI' % (ssz // 4 - 1), s)
        n = struct.unpack_from('<I', s, ssz - 4)[0]
    fat = []
    for f in difat[:ndifat_fat]:
        fat += struct.unpack('<%dI' % (ssz // 4), sec(f))

    def chain(n):
        out = []
        while n < 0xFFFFFFFA:
            out.append(sec(n))
            n = fat[n]
        return b''.join(out)

    dirs = chain(dir_start)
    entries = []
    for i in range(0, len(dirs), 128):
        e = dirs[i:i + 128]
        nl = struct.unpack_from('<H', e, 64)[0]
        name = e[:max(nl - 2, 0)].decode('utf-16le', 'ignore')
        start, size = struct.unpack_from('<IQ', e, 116)
        entries.append((name, start, size))
    root = entries[0]
    for name, start, size in entries:
        if name == want:
            if size < mini_cut:
                ministream = chain(root[1])
                mf = chain(minifat_start)
                minifat = struct.unpack('<%dI' % (len(mf) // 4), mf)
                out, n = [], start
                while n < 0xFFFFFFFA:
                    out.append(ministream[n * mssz:(n + 1) * mssz])
                    n = minifat[n]
                return b''.join(out)[:size]
            return chain(start)[:size]
    raise SystemExit('stream %r not found' % want)


def _walk(buf, pos, end, out, ctx):
    while pos + 8 <= end:
        verinst, typ, ln = struct.unpack_from('<HHI', buf, pos)
        body = pos + 8
        if body + ln > end:
            break
        if verinst & 0xF == 0xF:  # container record
            if typ == 0x03EE:
                ctx['slide'] += 1
                out.append(('slide', ctx['slide']))
            elif typ == 0x03F0:
                out.append(('notes', None))
            _walk(buf, body, body + ln, out, ctx)
        elif typ == 0x0FA0:  # TextCharsAtom (UTF-16)
            out.append(('text', buf[body:body + ln].decode('utf-16le', 'ignore')))
        elif typ == 0x0FA8:  # TextBytesAtom (Latin-1)
            out.append(('text', buf[body:body + ln].decode('latin-1', 'ignore')))
        pos = body + ln
