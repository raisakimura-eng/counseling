"""カウンセラー販売実績ダッシュボードの「週次の課題」セクションを作り、ページに差し込む（または差し替える）。

    python3 -I pipeline/sales/counselor/review_page.py --numbers NUMBERS.json --issues ISSUES.json \
        --into CURRENT.html --out NEW.html

- NUMBERS.json: weekly.py の出力（数字。患者コメントの本文も入っているが、ページには載せない）。
- ISSUES.json: Claude が週ごとに書く課題の文章（形式は README「週次の課題」）。
- セクションはタブで切り替える（チーム全体／カウンセラーごと）。オーナーの決定 2026-10-24。
- CURRENT.html: 公開中の naa-counselor のページ。セクションは <!--WEEKLY:BEGIN--> 〜 <!--WEEKLY:END--> の間だけで、
  初回は「カウンセラー別」の表（#bycounselor）のすぐ後に入れる。毎日の build.py は D の行と日付の文だけを
  書き換えるので、このセクションはそのまま残る。
- 個人名と課題が載るため、naa-counselor はパスワード保護で公開する（オーナーの決定 2026-10-24）。
"""
import argparse
import html
import json
import os
import re

TEAM = 'クリニック全体'
BEGIN, END = '<!--WEEKLY:BEGIN-->', '<!--WEEKLY:END-->'
ANCHOR = '<section class="wrap" id="trend">'   # 初回はこの直前（＝カウンセラー別の表の後）に入れる


def esc(s):
    return html.escape(str(s))


def yen(v):
    return '—' if v is None else f'{v:,.0f}円'


def pct(v):
    return '—' if v is None else f'{v * 100:.0f}%'


def num(v, nd=2):
    return '—' if v is None else f'{v:.{nd}f}'


def delta(w, b, better, rate=False):
    """週の値と直前4週の比較。better: 'up' は高いほど良い、'down' は低いほど良い。
    rate=True の指標（割合）はポイント差、それ以外は変化率で示す。"""
    if w is None or b is None or (not rate and b == 0):
        return ''
    r = (w - b) * 100 if rate else (w / b - 1) * 100
    if abs(r) < (2 if rate else 5):
        return '<span class="rv-d">→</span>'
    good = (r > 0) == (better == 'up')
    unit = 'pt' if rate else '%'
    return f'<span class="rv-d {"rv-good" if good else "rv-bad"}">{"↑" if r > 0 else "↓"}{abs(r):.0f}{unit}</span>'


ROWS = [  # (label, key, fmt, better, kind) kind: 'count' は直前4週を週平均にして比べる、'rate' は割合
    ('担当客数', 'customers', lambda v: f'{v:.0f}人', None, 'count'),
    ('客単価', 'arpu', yen, 'up', 'value'),
    ('1施術あたり単価', 'price_per_proc', yen, 'up', 'value'),
    ('1人あたり施術数', 'procs_per_cust', lambda v: num(v), 'up', 'value'),
    ('1施術で終わった割合', 'one_rate', pct, 'down', 'rate'),
    ('プリペイド販売', 'prepaid_cust', lambda v: f'{v:.1f}件'.replace('.0件', '件'), None, 'count'),
    ('返金・一部返金', 'refund_rate', pct, 'down', 'rate'),
]


def table(people, weeks):
    names = list(people)
    head = ''.join(f'<th class="num">{esc(n)}</th>' for n in names)
    body = []
    for label, key, fmt, better, kind in ROWS:
        cells = []
        for n in names:
            w, b = people[n]['week'] or {}, people[n]['base'] or {}
            v, bv = w.get(key), b.get(key)
            if kind == 'count' and bv is not None:
                bv = bv / weeks
            note = '週平均 ' if kind == 'count' else ''
            cells.append(f'<td class="num">{fmt(v) if v is not None else "—"}{delta(v, bv, better, kind == "rate") if better else ""}'
                         f'<small>{note}{fmt(bv) if bv is not None else "—"}</small></td>')
        body.append(f'<tr><th class="name">{label}</th>{"".join(cells)}</tr>')
    cells = []
    for n in names:
        w, b = people[n]['week_voc'], people[n]['base_voc']
        txt = f'{num(w["mean"])} (n={w["n"]})' if w else '—'
        cells.append(f'<td class="num">{txt}{delta(w and w["mean"], b and b["mean"], "up")}<small>{num(b["mean"]) if b else "—"}</small></td>')
    body.append(f'<tr><th class="name">満足度（5点）</th>{"".join(cells)}</tr>')
    cells = []
    for n in names:
        w, b = people[n]['week_dwell'], people[n]['base_dwell']
        mins = lambda d: f'{d["med"]:.0f}分' if d else '—'  # noqa: E731
        cells.append(f'<td class="num">{mins(w)}<small>{mins(b)}</small></td>')
    body.append(f'<tr><th class="name">カウンセリング時間（中央値）</th>{"".join(cells)}</tr>')
    narrow = ' rv-narrow' if len(names) <= 2 else ''
    return f'<div class="tablewrap"><table class="rv-table{narrow}"><thead><tr><th class="name"></th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def lis(items):
    return ''.join(f'<li>{esc(x)}</li>' for x in items or [])


def card(name, p, iss):
    w = p['week'] or {}
    few = '<span class="rv-tag">件数少なめ</span>' if p.get('few') else ''
    sec = lambda title, items, cls: (f'<div class="{cls}"><h4>{title}</h4><ul>{lis(items)}</ul></div>' if items else '')  # noqa: E731
    return (f'<div class="card rv-card"><div class="rv-top"><h3>{esc(name)}{few}</h3>'
            f'<span class="rv-kpi">客単価 <b class="num">{yen(w.get("arpu"))}</b>・担当 {w.get("customers", 0)}人</span></div>'
            f'<p class="rv-head">{esc(iss.get("headline", ""))}</p>'
            f'{sec("良かった点", iss.get("good"), "rv-good-b")}{sec("課題", iss.get("issues"), "rv-issue-b")}'
            f'{sec("来週やること", iss.get("actions"), "rv-act-b")}</div>')


CSS = """
#weekly{margin-top:44px}
#weekly .rv-lead{background:var(--surface);border:1px solid var(--line);border-radius:3px;padding:18px 20px;margin-bottom:16px}
#weekly .rv-lead p{margin:0 0 8px}#weekly .rv-lead ul{margin:0;padding-left:18px}
#weekly .rv-table{min-width:880px;font-size:13px}#weekly .rv-table.rv-narrow{min-width:0}#weekly .rv-table td small{display:block;color:var(--muted);font-size:11px}
#weekly .rv-d{margin-left:4px;font-size:11px;color:var(--muted)}#weekly .rv-good{color:var(--pos)}#weekly .rv-bad{color:var(--neg)}
#weekly .rv-tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}
#weekly .rv-tab{border:1px solid var(--line);background:var(--surface);color:var(--ink2);font-family:var(--sans);font-size:13px;padding:5px 12px;border-radius:999px;cursor:pointer}
#weekly .rv-tab[aria-selected="true"]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
#weekly .rv-card{margin-bottom:14px}
#weekly .rv-top{display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap}
#weekly .rv-top h3{font-size:16px}#weekly .rv-kpi{color:var(--muted);font-size:12.5px}
#weekly .rv-head{font-weight:600;margin:8px 0}
#weekly .rv-tag{font-family:var(--sans);font-size:11px;font-weight:400;background:var(--grow-soft);padding:1px 6px;border-radius:8px;margin-left:6px}
#weekly h4{margin:8px 0 2px;font-size:13px;font-family:var(--sans)}#weekly ul{margin:0;padding-left:18px;font-size:14px}
#weekly .rv-good-b h4{color:var(--pos)}#weekly .rv-issue-b h4{color:var(--neg)}#weekly .rv-act-b h4{color:var(--grow)}
"""


def section(numbers, issues):
    """チーム全体のタブ（まとめ・全員の表）と、カウンセラーごとのタブ（本人のカードと、本人とクリニック全体の表）。"""
    people = numbers['people']
    w0, w1 = numbers['week']
    b0, b1 = numbers['base']
    weeks = numbers['base_weeks']
    names = [n for n in people if n != TEAM]
    iss = issues.get('people') or {}
    tabs = ['<button type="button" class="rv-tab" role="tab" aria-selected="true" data-rv="0">チーム全体</button>']
    tabs += [f'<button type="button" class="rv-tab" role="tab" aria-selected="false" data-rv="{k + 1}">{esc(n)}</button>'
             for k, n in enumerate(names)]
    panels = [f'<div class="rv-panel" data-rv="0"><div class="rv-lead"><p>{esc(issues.get("overview", ""))}</p>'
              f'<ul>{lis(issues.get("team"))}</ul></div>{table(people, weeks)}</div>']
    for k, n in enumerate(names):
        pair = {n: people[n], TEAM: people[TEAM]} if TEAM in people else {n: people[n]}
        panels.append(f'<div class="rv-panel" data-rv="{k + 1}" hidden>{card(n, people[n], iss.get(n, {}))}'
                      f'{table(pair, weeks)}</div>')
    js = ("<script>(function(){var r=document.getElementById('weekly');if(!r)return;"
          "var t=r.querySelectorAll('.rv-tab'),p=r.querySelectorAll('.rv-panel');"
          "t.forEach(function(b){b.addEventListener('click',function(){var v=b.getAttribute('data-rv');"
          "t.forEach(function(x){x.setAttribute('aria-selected',x===b?'true':'false')});"
          "p.forEach(function(x){x.hidden=x.getAttribute('data-rv')!==v})})})})();</script>")
    return (f'{BEGIN}<style>{CSS}</style><section class="wrap" id="weekly">'
            f'<div class="shead"><h2>週次の課題</h2><p>対象週 {w0}〜{w1}（月〜日）。比較は直前{weeks}週（{b0}〜{b1}）。'
            f'{esc(issues.get("updated", ""))}。毎週月曜に更新（上の期間・チャネルの切り替えとは連動しません）</p></div>'
            f'<div class="rv-tabs" role="tablist">{"".join(tabs)}</div>{"".join(panels)}</section>{js}{END}')


def merge(page, block):
    """BEGIN〜END があれば差し替え、無ければ ANCHOR の直前に入れる。"""
    if BEGIN in page:
        out, n = re.subn(re.escape(BEGIN) + '.*?' + re.escape(END), lambda _: block, page, count=1, flags=re.S)
        if n != 1:
            raise SystemExit('STOP: the weekly section markers are broken on the page')
        return out
    if page.count(ANCHOR) != 1:
        raise SystemExit(f'STOP: {ANCHOR!r} not found once on the page; cannot place the weekly section')
    return page.replace(ANCHOR, block + ANCHOR)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--numbers', required=True)
    ap.add_argument('--issues', required=True)
    ap.add_argument('--into', required=True, help='the live naa-counselor page')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    os.umask(0o077)
    n, i = json.load(open(a.numbers)), json.load(open(a.issues))
    if i.get('week') != n['week']:
        raise SystemExit(f"STOP: issues are for {i.get('week')}, numbers for {n['week']}")
    missing = [p for p in n['people'] if p != TEAM and not (i.get('people') or {}).get(p, {}).get('issues')]
    if missing:
        raise SystemExit(f'STOP: no issues written for {missing}')
    page = open(a.into, encoding='utf-8').read()
    open(a.out, 'w', encoding='utf-8').write(merge(page, section(n, i)))
    print('PAGE:', a.out)


if __name__ == '__main__':
    main()
