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

DATA_CONSTS = ['DAYS_BASE', 'DAYS_CUR', 'MON', 'MONTH', 'TODAY', 'EXTRA', 'TARGET', 'SUMMARY', 'SUMMARIES']
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
    # 客単価の前月平均: 来院ベースの決済（決済ベースで上書きされる前の値）から、除外来院の自費分を引いた額 ÷ 来院数
    ("const V = DAYS_SEP.reduce((a, d) => a + d.visN, 0), C = DAYS_SEP.reduce((a, d) => a + d.C, 0);",
     "const V = DAYS_SEP.reduce((a, d) => a + d.visN, 0), C = DAYS_SEP.reduce((a, d) => a + (d.Cvisit ?? d.C) - (d.Cex || 0), 0);", 1),
    # a month with a single finished day: the line charts divided by (days - 1)
    ("(W - left - right) * i / (DAYS.length - 1)", "(W - left - right) * i / Math.max(1, DAYS.length - 1)", 1),
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
    # 「予測ロジックの見直し案」の2つ目以降: 数値だけ生成（考察文はそのまま）
    'fixFill': ('<b>メニュー未入力の補完単価</b><span>', '初診 23,376円、再診 7,349円'),
    'fixMult': ('<b>予約金額から決済への倍率</b><span>', '初診 1.01、再診 1.08'),
    'fixMultNote': ('</span></div><p>', 'メニュー入力済みの来院者の9月平均です。'),
    'fixHigh': ('6万円を超える初診予約は成約の振れ幅が大きいため', '（9/1は4件、計375,500円が決済0円）'),
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


# ---------------------------------------------------------------- stage 2: monthly まとめ tabs ----
# 「9月まとめ」 (SUMMARY, written by hand) stays exactly as it is. Every later month gets an entry in
# SUMMARIES (numbers from build.py, sentences written by the daily job's Claude) and its own tab
# 「◯月まとめ」, drawn by summaryViewX(), a data-driven copy of summaryView().
SUMMARY_VIEW_X = r'''
  function summaryViewX(S){
    const Ms = S.months, cur = Ms[2], X = S.text, L = S.label, N = S.next;
    const tr = (lab, key, fmt, better) => {
      const v = Ms.map(m => m[key]); const d = v[2] - v[1];
      const good = better === 'up' ? d >= 0 : better === 'down' ? d <= 0 : null;
      return `<tr><td class="name">${lab}</td>${v.map((x, k) => `<td${k === 2 ? ' style="font-weight:700;color:var(--ink)"' : ''}>${fmt(x)}</td>`).join('')}<td class="${good == null ? 'muted' : good ? 'pos' : 'warn'}">${good == null ? '—' : good ? '改善' : '悪化'}</td></tr>`;
    };
    const yf = v => yen(v) + '円', nf = v => v.toFixed(1) + '件', pf = v => pct(v), tf = v => v.toFixed(2), mf = v => (v >= 0 ? '+' : '−') + (Math.abs(v) / 1e4).toFixed(1) + '万円';
    const wkMax = Math.max(...S.week.map(w => w[1])), over = S.target && S.total >= S.target, perT = S.target ? S.target / S.days : 0;
    const gap = (S.C - S.M) / S.M;
    document.getElementById('viewSum').innerHTML = `
    <p class="daylabel">${S.y}年${S.m}月のまとめ</p>
    <div class="resbar resbar5">
      <div><span class="k">${L}の売上（決済ベース）</span><span class="v">${yen(S.total)}<small>円</small></span><span class="n">${S.target ? `目標${yen(S.target)}円の${pct(S.total / S.target)}` : '売上目標は未設定'}</span></div>
      <div><span class="k">目標との差</span><span class="v ${over ? 'pos' : 'warn'}">${S.target ? sgn(S.total - S.target) : '—'}<small>${S.target ? '円' : ''}</small></span><span class="n">${S.target ? `1日あたり${yen(Math.abs(S.target - S.total) / S.days)}円の${over ? '超過' : '不足'}` : ''}</span></div>
      <div><span class="k">1日あたりの売上（決済ベース）</span><span class="v">${yen(S.perdayAll)}<small>円</small></span><span class="n">${S.target ? `日割り目標${yen(perT)}円の${pct(S.perdayAll / perT)}` : ''}</span></div>
      <div><span class="k">予約時点（朝）の予想</span><span class="v">${yen(S.M)}<small>円</small></span><span class="n">実決済は${yen(S.C)}円（来院ベース）</span></div>
      <div><span class="k">実決済 − 予約時点（朝）の予想</span><span class="v ${gap >= 0 ? 'pos' : 'warn'}">${sgn(S.C - S.M)}<small>円</small></span><span class="n">${gap >= 0 ? '+' : '−'}${pct(Math.abs(gap))}、${S.days}日中${S.plusDays}日でプラス</span></div>
    </div>
    <div class="stack">
    <section class="panel" aria-labelledby="h-xbr">
      <div class="panel-head"><h2 id="h-xbr">売上の数字の違い（決済ベースと来院ベース）</h2><span class="muted">${S.m}/1〜${S.m}/${S.days}</span></div>
      <div class="grid2" style="margin-top:0">
        <div class="scroll"><table><thead><tr><th scope="col">決済履歴（お金の受け取り）</th><th scope="col">金額</th></tr></thead><tbody>
          <tr><td class="name">カード</td><td>${yen(S.pay.card)}円</td></tr>
          <tr><td class="name">現金</td><td>${yen(S.pay.cash)}円</td></tr>
          <tr><td class="name">事前決済（カンナムオンニ）</td><td>${yen(S.pay.pre)}円</td></tr>
          <tr><td class="name">決済のキャンセル（${S.pay.cancelN}件）・返金</td><td class="warn">${sgn(S.pay.cancel + S.pay.refund)}円</td></tr>
        </tbody><tfoot><tr><td>決済ベースの売上</td><td>${yen(S.total)}円</td></tr></tfoot></table></div>
        <div class="scroll"><table><thead><tr><th scope="col">来院ベース（施術の決済総額）との違い</th><th scope="col">金額</th></tr></thead><tbody>
          <tr><td class="name">来院時の施術決済総額</td><td>${yen(S.totalVisit)}円</td></tr>
          <tr><td class="name">＋ プリペイドのチャージ（${S.bridge.prepChargeN}件）</td><td class="pos">+${yen(S.bridge.prepCharge)}円</td></tr>
          <tr><td class="name">− プリペイドでの支払い（すでに受け取り済み）</td><td class="warn">−${yen(S.bridge.prepUse)}円</td></tr>
          <tr><td class="name">＋ 施術以外の品目（物販など）</td><td class="pos">+${yen(S.bridge.goods)}円</td></tr>
          <tr><td class="name">そのほか（決済のキャンセル・日付のずれなど）</td><td>${sgn(S.total - (S.totalVisit + S.bridge.prepCharge - S.bridge.prepUse + S.bridge.goods))}円</td></tr>
        </tbody><tfoot><tr><td>決済ベースの売上</td><td>${yen(S.total)}円</td></tr></tfoot></table></div>
      </div>
      <p class="foot">決済ベースは「その月に受け取ったお金」、来院ベースは「その月に来院した方の施術の金額」です。プリペイドを買った月は決済ベースが大きく、プリペイドで支払った月は来院ベースが大きくなります。日々の当日ページ・日別の分析は来院ベース、月の売上の確定は決済ベースで見ています。</p>
    </section>
    <section class="panel" aria-labelledby="h-x3m">
      <div class="panel-head"><h2 id="h-x3m">${Ms[0].m}・${Ms[1].m}との比較</h2><span class="muted">スタッフ・インフルエンサー除く。評価は${Ms[1].m}→${Ms[2].m}の変化</span></div>
      <div class="scroll"><table><thead><tr><th scope="col">指標</th>${Ms.map(m => `<th scope="col">${m.m}</th>`).join('')}<th scope="col">評価</th></tr></thead><tbody>
        ${tr('1日あたりの売上', 'perday', yf, 'up')}${tr('1日あたりの来院', 'vday', nf, 'up')}${tr('客単価', 'aov', yf, 'up')}
        ${tr('1日あたりの初診', 'first', nf, 'up')}${tr('1日あたりの再診', 'rep', nf, 'up')}
        ${tr('1施術だけの方の割合', 'single', pf, 'down')}${tr('1人あたりの施術数', 'tpp', tf, 'up')}
        ${tr('増額（1日あたり）', 'up', mf, 'up')}${tr('減額（1日あたり）', 'dn', mf, 'up')}
        ${tr('メニュー未入力の割合', 'nm', pf, 'down')}${tr('コース消化の0円来院（1日あたり）', 'course', nf, null)}
        <tr><td class="name">プリペイドの購入</td>${Ms.map((m, k) => `<td${k === 2 ? ' style="font-weight:700;color:var(--ink)"' : ''}>${m.prep[0]}件・${Math.round(m.prep[1] / 1e4)}万円</td>`).join('')}<td class="${Ms[2].prep[1] >= Ms[1].prep[1] ? 'pos' : 'warn'}">${Ms[2].prep[1] >= Ms[1].prep[1] ? '改善' : '悪化'}</td></tr>
      </tbody></table></div>
      <p class="foot">${esc(X.cmpNote)}${L}は${S.m}/1〜${S.m}/${S.days}の集計です。</p>
    </section>
    <div class="grid2" style="margin-top:0">
    <section class="panel" aria-labelledby="h-xwk">
      <div class="panel-head"><h2 id="h-xwk">曜日別</h2><span class="muted">売上は全体、上乗せ率は実決済 ÷ 朝の予想</span></div>
      ${S.week.map(w => `<div class="agerow" style="--lw:40px"><span class="lab">${w[0]}</span><div class="track"><i style="width:${Math.max(1, w[1] / wkMax * 68).toFixed(1)}%;background:var(--blue)"></i><em>${yen(w[1])}円</em></div><span class="val ${w[2] >= 0 ? 'pos' : 'warn'}"><b style="color:inherit">${w[2] >= 0 ? '+' : ''}${pct(w[2])}</b></span><span class="val"></span></div>`).join('')}
      <p class="foot">${esc(X.weekNote)}</p>
    </section>
    <section class="panel" aria-labelledby="h-xtop">
      <div class="panel-head"><h2 id="h-xtop">売れた施術</h2><span class="muted">施術実施額の上位5</span></div>
      ${rankBlock(S.top, '人')}
      <div class="flow3" style="grid-template-columns:repeat(2,minmax(0,1fr));margin-top:14px">
        <div class="got"><span class="k">プリペイドの購入</span><span class="v">${cur.prep[0]}<small>件</small></span><span class="n">${yen(cur.prep[1])}円（${Ms[0].m}${Ms[0].prep[0]}件、${Ms[1].m}${Ms[1].prep[0]}件）</span></div>
        <div><span class="k">当日予約</span><span class="v">${S.sd.n}<small>件/日</small></span><span class="n">月${yen(S.sd.paid)}円の決済</span></div>
      </div>
    </section>
    </div>
    <div class="grid2" style="margin-top:0">
    <section class="panel" aria-labelledby="h-xch"><div class="panel-head"><h2 id="h-xch">経路別</h2><span class="muted">来院20件以上</span></div><div style="--lw:132px">${ageBlock(S.ch, '経路')}</div></section>
    <section class="panel" aria-labelledby="h-xag"><div class="panel-head"><h2 id="h-xag">年代別</h2><span class="muted">来院20件以上</span></div>${ageBlock(S.ages)}</section>
    </div>
    <section class="panel" aria-labelledby="h-xiss">
      <div class="panel-head"><h2 id="h-xiss">${L}の課題</h2></div>
      <ol class="factors">${X.issues.map(i => `<li><span class="fk neg">${esc(i.tag)}</span><p>${esc(i.text)}</p><b></b></li>`).join('')}</ol>
    </section>
    <section class="panel" aria-labelledby="h-xokr">
      <div class="panel-head"><h2 id="h-xokr">${N.label}のOKR（案）</h2><span class="muted">${N.target ? `売上目標 ${(N.target / 1e4).toLocaleString('ja-JP')}万円（1日約${Math.round(N.target / N.days / 1e4)}万円）` : '売上目標 未設定'}</span></div>
      <p style="color:var(--ink);font-weight:700;margin-bottom:10px">Objective：${esc(X.okr.objective)}</p>
      <div class="scroll"><table><thead><tr><th scope="col">KR</th><th scope="col">${L}の実績</th><th scope="col">${N.label}の目標（案）</th></tr></thead><tbody>
        <tr><td class="name">実決済 ÷ 予約時点（朝）の予想</td><td>${gap >= 0 ? '+' : '−'}${pct(Math.abs(gap))}</td><td><b>${esc(X.okr.targets.ratio)}</b></td></tr>
        <tr><td class="name">予約時点（朝）の予想（1日平均）</td><td>${yen(S.morningPerDay)}円</td><td><b>${esc(X.okr.targets.morning)}</b></td></tr>
        <tr><td class="name">2施術以上の方の割合</td><td>${pct(1 - cur.single)}</td><td><b>${esc(X.okr.targets.multi)}</b></td></tr>
        <tr><td class="name">減額（1日あたり）</td><td>${mf(cur.dn)}</td><td><b>${esc(X.okr.targets.dn)}</b></td></tr>
        <tr><td class="name">コース消化の来院での追加提案率</td><td>未計測</td><td><b>${esc(X.okr.targets.course)}</b></td></tr>
        <tr><td class="name">当日キャンセル率</td><td>${pct(S.same)}</td><td><b>${esc(X.okr.targets.same)}</b></td></tr>
      </tbody></table></div>
      <p class="foot">${esc(X.okr.note)}</p>
    </section>
    </div>`;
  }
'''

JS_EDITS_2 = [
    # a ratio with a zero denominator (a day or month without visits yet) is shown as 「—」, not Infinity / NaN
    ("  const yen = v => Math.round(Math.abs(v)).toLocaleString('ja-JP');",
     "  const yen = v => isFinite(v) ? Math.round(Math.abs(v)).toLocaleString('ja-JP') : '—';", 1),
    ("  const pct = (v, d = 1) => (v * 100).toFixed(d) + '%';",
     "  const pct = (v, d = 1) => isFinite(v) ? (v * 100).toFixed(d) + '%' : '—';", 1),
    ("  function hoursChart(){", SUMMARY_VIEW_X + "\n  function hoursChart(){", 1),
    ("    if (v === 'oct' && !DAYS_CUR.length) v = 'today';\n",
     "    if (v === 'oct' && !DAYS_CUR.length) v = 'today';\n"
     "    const SX = SUMMARIES.find(s => 'sum-' + s.key === v);\n    if (v.startsWith('sum-') && !SX) v = 'today';\n", 1),
    ("    const map = {today: 'viewToday', past: 'viewPast', sum: 'viewSum', oct: 'viewPast'};\n"
     "    ['today', 'past', 'sum', 'oct'].forEach(k =>",
     "    const map = {today: 'viewToday', past: 'viewPast', sum: 'viewSum', oct: 'viewPast'};\n"
     "    if (SX) { map[v] = 'viewSum'; summaryViewX(SX); } else if (v === 'sum') summaryView();\n"
     "    VIEWS.forEach(k =>", 1),
    ("v === 'sum' ? '2026年9月のまとめ' : `${yy}",
     "v === 'sum' ? '2026年9月のまとめ' : SX ? `${SX.y}年${SX.m}月のまとめ` : `${yy}", 1),
    ("  const VIEWS = ['today', 'oct', 'past', 'sum'];",
     "  { let prev = document.getElementById('vt-sum');\n"
     "    SUMMARIES.forEach(s => { const b = prev.cloneNode(false); b.id = 'vt-sum-' + s.key; b.textContent = s.label + 'まとめ'; b.setAttribute('aria-selected', 'false'); b.tabIndex = -1; prev.after(b); prev = b; }); }\n"
     "  const VIEWS = ['today', 'oct', 'past', 'sum', ...SUMMARIES.map(s => 'sum-' + s.key)];", 1),
]


def migrate_summaries(html):
    """Stage 2 (idempotent): SUMMARIES constant, summaryViewX and one tab per entry."""
    if 'const SUMMARIES = ' in html:
        return html
    a, b = script_bounds(html)
    js = html[a:b]
    for old, new, n in JS_EDITS_2:
        c = js.count(old)
        if c != n:
            raise SystemExit(f'STOP: page code changed; expected {n}× {old[:60]!r}, found {c}')
        js = js.replace(old, new)
    i = js.index('\nconst SUMMARY = ')
    j = js.index('\n', i + 1)
    js = js[:j] + '\nconst SUMMARIES = [];' + js[j:]
    return html[:a] + js + html[b:]


# ---------------------------------------------------------------- stage 3: 日中の「現時点の決済」 ----
# The block already exists in today() and is drawn whenever TODAY.live is set (and TODAY.final is not);
# the 0:30 run leaves TODAY.live = null, so it is hidden then. Small wording fixes only.
JS_EDITS_3 = [
    # also show the 来院ベース amount (the page's 着地結果 of the day is 決済ベース; 客単価 is 来院ベース)
    ('<span class="n">来院${L.vis}件、客単価${yen(L.aov)}円</span>',
     '<span class="n">来院${L.vis}件、客単価${yen(L.aov)}円${L.paidVisit != null ? `、来院ベース${yen(L.paidVisit)}円` : \'\'}</span>', 1),
    # nothing sold yet (early morning)
    ("売れた施術（現時点）：${L.top.slice(0, 3).map(r => `${esc(r[0])} ${yen(r[2])}円`).join('、')}。",
     "売れた施術（現時点）：${L.top.length ? L.top.slice(0, 3).map(r => `${esc(r[0])} ${yen(r[2])}円`).join('、') : 'まだありません'}。", 1),
    # the forecast is made from the reservations at 0:00, not from the previous evening's export
    ("下は${L.noTime ? '当日朝' : '前日夜'}の予約からの予想です。",
     "下は${L.noTime ? '当日朝' : (L.basisLabel || '前日夜')}の予約からの予想です。", 1),
]


def migrate_live(html):
    """Stage 3 (idempotent)."""
    if 'L.basisLabel' in html:
        return html
    a, b = script_bounds(html)
    js = html[a:b]
    for old, new, n in JS_EDITS_3:
        c = js.count(old)
        if c != n:
            raise SystemExit(f'STOP: page code changed; expected {n}× {old[:60]!r}, found {c}')
        js = js.replace(old, new)
    return html[:a] + js + html[b:]
