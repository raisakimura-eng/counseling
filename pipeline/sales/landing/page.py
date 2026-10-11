"""Read / write the 着地予想ダッシュボード HTML.

The page keeps its data in one-line JS constants (`const NAME = <json>;`) at the top of its only
<script>. build.py replaces those lines and the generated sentences in <span data-gen="..."> only;
CSS and the rendering code are left alone.

The page as published until 2026-10 was written for two fixed months (DAYS_SEP / DAYS_OCT and the
words 9月 / 10月 in the code). `migrate()` makes the month generic with a small, checked set of
edits (each old snippet must occur exactly as expected), so that a new month needs no code change:

* the day lists become DAYS_BASE (previous month, the reference month for the model) and DAYS_CUR
  (current month); `const DAYS_SEP = DAYS_BASE, DAYS_OCT = DAYS_CUR;` keeps the rest of the code as is
* a new constant MON = {y, b, c, by, calib} gives the month numbers used in labels
* month words in labels come from MON; the model coefficients shown in 「この予想の前提」 come from
  TODAY.coef instead of being typed into the code
* static sentences that describe the data period are wrapped in <span data-gen="KEY"> and rewritten
  by build.py on every run
"""
import json
import re

DATA_CONSTS = ['DAYS_BASE', 'DAYS_CUR', 'MON', 'MONTH', 'TODAY', 'EXTRA', 'TARGET', 'SUMMARY']
LINE = re.compile(r'^const ([A-Z_]+) = (.*);$', re.M)

# (old, new, expected count) — applied once, to a page that is not migrated yet
JS_EDITS = [
    ('const DAYS_SEP = ', 'const DAYS_BASE = ', 1),
    ('const DAYS_OCT = ', 'const DAYS_CUR = ', 1),
    ('let DAYS = DAYS_SEP;', 'const DAYS_SEP = DAYS_BASE, DAYS_OCT = DAYS_CUR; // base (previous) month, current month\nlet DAYS = DAYS_SEP;', 1),
    ("`9/1〜9/26の来院実績と、9/1〜${DAYS[n - 1].date}の予約履歴から算出`",
     "`${MON.calib}の来院実績と、${DAYS[0].date}〜${DAYS[n - 1].date}の予約履歴から算出`", 1),
    ("'pos' : 'warn'}\">9月平均 ${fmt(m)}", "'pos' : 'warn'}\">${MON.b}月平均 ${fmt(m)}", 1),
    ("'aria-label': `9/${day} 決済", "'aria-label': `${MON.b}/${day} 決済", 1),
    ("`<b>9/${day}</b>　来院", "`<b>${MON.b}/${day}</b>　来院", 1),
    ("textContent = '9/' + day;", "textContent = MON.b + '/' + day;", 1),
    ("`9月の決済÷予約は平均${avg.toFixed(2)}です。9/${selDay}は${mine.toFixed(2)}で、26日中低いほうから",
     "`${MON.b}月の決済÷予約は平均${avg.toFixed(2)}です。${MON.b}/${selDay}は${mine.toFixed(2)}で、${MONTH.length}日中低いほうから", 1),
    ("`残りに9月の上乗せ率 ×", "`残りに${MON.b}月の上乗せ率 ×", 1),
    ("${T.date.startsWith('10/') ? '10月分' : '9月分'}", "${T.date.startsWith(MON.c + '/') ? MON.c + '月分' : MON.b + '月分'}", 1),
    ('<p class="range">9月の外れ幅（平均±', '<p class="range">${MON.b}月の外れ幅（平均±', 1),
    ('<div class="n">9月の予約金額からの上乗せ率を反映</div>', '<div class="n">${MON.b}月の予約金額からの上乗せ率を反映</div>', 1),
    ('件が土台。9月は実績がこれを平均', '件が土台。${MON.b}月は実績がこれを平均', 1),
    ('</span></div><p>9月の来院予定のうち、当日キャ', '</span></div><p>${MON.b}月の来院予定のうち、当日キャ', 1),
    ('<span>初診 ×1.227、再診 ×1.101</span></div><p>9月の来院で、メニュー入力済み',
     "<span>初診 ×${T.coef.upsell['初診'].toFixed(3)}、再診 ×${T.coef.upsell['再診'].toFixed(3)}</span></div><p>${MON.b}月の来院で、メニュー入力済み", 1),
    ('<p>9月全体では1日平均', '<p>${MON.b}月全体では1日平均', 1),
    ('<span>初診 23,376円、再診 7,349円</span></div><p>メニュー未入力や、9月に実績のないメニュー',
     "<span>初診 ${yen(T.coef.fill['初診'])}円、再診 ${yen(T.coef.fill['再診'])}円</span></div><p>メニュー未入力や、${MON.b}月に実績のないメニュー", 1),
    ("${M.asof || '10/3'}", "${M.asof}", 3),
    ("${M.asof ? '10/' + (+M.asof.split('/')[1] + 1) : '10/4'}〜10/31の予約",
     "${MON.c}/${+M.asof.split('/')[1] + 1}〜${MON.c}/${G.days}の予約", 1),
    ("9月に「${M.asof ? M.asof.split('/')[1] : 3}日時点で入っていた${M.asof ? +M.asof.split('/')[1] + 1 : 4}日以降の予約」",
     "${MON.b}月に「${M.asof.split('/')[1]}日時点で入っていた${+M.asof.split('/')[1] + 1}日以降の予約」", 1),
    ('までの実績 ＋ 9月の同じ曜日の平均</td>', 'までの実績 ＋ ${MON.b}月の同じ曜日の平均</td>', 1),
    ('9月のパターンでの補正は、10月の', '${MON.b}月のパターンでの補正は、${MON.c}月の', 1),
    ('日を9月の同じ曜日の平均で見込み`', '日を${MON.b}月の同じ曜日の平均で見込み`', 1),
    ('<p>9月の実績で試した外れ幅です。', '<p>${MON.b}月の実績で試した外れ幅です。', 1),
    ('<p>9月のある日を、同じ曜日の', '<p>${MON.b}月のある日を、同じ曜日の', 1),
    ("const m = v === 'oct' ? '10' : '9';", "const m = v === 'oct' ? MON.c : MON.b, yy = v === 'oct' ? MON.y : MON.by;", 1),
    ("`2026年${m}月${DAYS[0]", "`${yy}年${m}月${DAYS[0]", 1),
    ("  const VIEWS = ['today', 'oct', 'past', 'sum'];",
     "  document.getElementById('vt-oct').textContent = MON.c + '月分'; document.getElementById('vt-past').textContent = MON.b + '月分';\n"
     "  const VIEWS = ['today', 'oct', 'past', 'sum'];", 1),
    # on the 1st of a month the current month has no finished day yet: hide its tab instead of failing
    ("  function view(v){\n    try { sessionStorage.setItem('fa-view', v); }",
     "  function view(v){\n    if (v === 'oct' && !DAYS_CUR.length) v = 'today';\n    try { sessionStorage.setItem('fa-view', v); }", 1),
    ("document.getElementById('vt-past').textContent = MON.b + '月分';\n",
     "document.getElementById('vt-past').textContent = MON.b + '月分'; document.getElementById('vt-oct').hidden = !DAYS_CUR.length;\n", 1),
]

# static sentences that depend on the period: wrapped once, rewritten by build.py every time
GEN_WRAP = {
    'sub': '（差額＝実決済 − 予約時点の予想。来院率 初診90%・再診95%。メニュー未入力は9月分は平均予約単価、10/4以降は9月の未入力の実績で補完）',
    'goalFoot': '予約データのない日は、9月の同じ曜日の平均で見込んでいます。日割り目標は、30日すべて営業する前提で等分しています。',
    'cmpFoot': '9/27〜9/29は実際に朝お出しした予想、9/1〜9/26は予約登録日から朝の時点の予約を再現しています。',
    'tbaseSub': ('<h2 id="h-tbase">この予想の前提</h2><span class="muted">', '9/1〜9/26の実績から算出'),
    'monthHead': '9月の予約金額と決済額（来院者のみ）',
}
GEN_BLOCK = {  # id of the element whose whole inner text is generated
    'footPast': re.compile(r'(<footer id="footPast"[^>]*>)(.*?)(</footer>)', re.S),
    'footToday': re.compile(r'(<footer id="footToday"[^>]*>)(.*?)(</footer>)', re.S),
}


def script_bounds(html):
    a = html.index('<script>') + len('<script>')
    return a, html.index('</script>', a)


def get_consts(html):
    a, b = script_bounds(html)
    out = {}
    for m in LINE.finditer(html[a:b]):
        if m.group(1) in DATA_CONSTS + ['DAYS_SEP', 'DAYS_OCT']:
            out[m.group(1)] = json.loads(m.group(2))
    if 'DAYS_SEP' in out:  # not migrated yet
        out['DAYS_BASE'], out['DAYS_CUR'] = out.pop('DAYS_SEP'), out.pop('DAYS_OCT')
    return out


def dumps(v):
    return json.dumps(v, ensure_ascii=False).replace('</', '<\\/')


def set_consts(html, consts):
    a, b = script_bounds(html)
    js = html[a:b]
    done = set()

    def rep(m):
        if m.group(1) in consts:
            done.add(m.group(1))
            return f'const {m.group(1)} = {dumps(consts[m.group(1)])};'
        return m.group(0)
    js = LINE.sub(rep, js)
    missing = set(consts) - done
    if missing:
        raise SystemExit(f'STOP: constants not found in the page: {sorted(missing)}')
    return html[:a] + js + html[b:]


def is_migrated(html):
    return 'const DAYS_BASE = ' in html


def migrate(html, mon):
    """Apply JS_EDITS and wrap GEN_WRAP sentences. Fails loudly if the page differs from what we expect."""
    if is_migrated(html):
        return html
    a, b = script_bounds(html)
    js = html[a:b]
    for old, new, n in JS_EDITS:
        c = js.count(old)
        if c != n:
            raise SystemExit(f'STOP: page code changed; expected {n}× {old[:60]!r}, found {c}')
        js = js.replace(old, new)
    # MON goes right after the day lists
    i = js.index('\nconst DAYS_SEP = DAYS_BASE')
    js = js[:i] + f'\nconst MON = {dumps(mon)};' + js[i:]
    head = html[:a]
    for key, text in GEN_WRAP.items():
        pre, text = text if isinstance(text, tuple) else ('', text)
        if head.count(pre + text) != 1:
            raise SystemExit(f'STOP: page text changed; expected once: {text[:40]!r}')
        head = head.replace(pre + text, f'{pre}<span data-gen="{key}">{text}</span>')
    for key, rx in GEN_BLOCK.items():
        head, n = rx.subn(lambda m: f'{m.group(1)}<span data-gen="{key}">{m.group(2)}</span>{m.group(3)}', head)
        if n != 1:
            raise SystemExit(f'STOP: page element changed: {key}')
    return head + js + html[b:]


def set_gen(html, texts):
    for key, text in texts.items():
        rx = re.compile(r'(<span data-gen="%s">)(.*?)(</span>)' % re.escape(key), re.S)
        html, n = rx.subn(lambda m: m.group(1) + text + m.group(3), html, count=1)
        if n != 1:
            raise SystemExit(f'STOP: generated text slot not found: {key}')
    return html


def set_month_svg_label(html, label):
    return re.sub(r'(<svg id="month" role="img" aria-label=")[^"]*(")', lambda m: m.group(1) + label + m.group(2), html, count=1)
