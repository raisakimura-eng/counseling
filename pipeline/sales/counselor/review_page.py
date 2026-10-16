"""週次の「カウンセラー別の課題」ページ（1ファイルの HTML）を作る。

    python3 -I pipeline/sales/counselor/review_page.py --numbers NUMBERS.json --issues ISSUES.json --out PAGE.html

- NUMBERS.json: weekly.py の出力（数字。患者コメントの本文も入っているが、ページには載せない）。
- ISSUES.json: Claude が週ごとに書く課題の文章（形式は README「週次の課題ページ」）。
- ページはパスワード保護のサイト（naa-counselor-review）にだけ公開する。
"""
import argparse
import html
import json
import os

TEAM = 'クリニック全体'


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
        return '<span class="d flat">→</span>'
    good = (r > 0) == (better == 'up')
    unit = 'pt' if rate else '%'
    return f'<span class="d {"good" if good else "bad"}">{"↑" if r > 0 else "↓"}{abs(r):.0f}{unit}</span>'


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
    head = ''.join(f'<th scope="col">{esc(n)}</th>' for n in names)
    body = []
    for label, key, fmt, better, kind in ROWS:
        cells = []
        for n in names:
            w, b = people[n]['week'] or {}, people[n]['base'] or {}
            v, bv = w.get(key), b.get(key)
            if kind == 'count' and bv is not None:
                bv = bv / weeks
            note = '週平均 ' if kind == 'count' else ''
            cells.append(f'<td>{fmt(v) if v is not None else "—"}{delta(v, bv, better, kind == "rate") if better else ""}'
                         f'<small>{note}{fmt(bv) if bv is not None else "—"}</small></td>')
        body.append(f'<tr><th scope="row">{label}</th>{"".join(cells)}</tr>')
    cells = []
    for n in names:
        w, b = people[n]['week_voc'], people[n]['base_voc']
        txt = f'{num(w["mean"])} (n={w["n"]})' if w else '—'
        cells.append(f'<td>{txt}{delta(w and w["mean"], b and b["mean"], "up")}<small>{num(b["mean"]) if b else "—"}</small></td>')
    body.append(f'<tr><th scope="row">満足度（5点）</th>{"".join(cells)}</tr>')
    cells = []
    for n in names:
        w, b = people[n]['week_dwell'], people[n]['base_dwell']
        mins = lambda d: f'{d["med"]:.0f}分' if d else '—'  # noqa: E731
        cells.append(f'<td>{mins(w)}<small>{mins(b)}</small></td>')
    body.append(f'<tr><th scope="row">カウンセリング時間（中央値）</th>{"".join(cells)}</tr>')
    return f'<div class="scroll"><table><thead><tr><th></th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def lis(items):
    return ''.join(f'<li>{esc(x)}</li>' for x in items or [])


def card(name, p, iss):
    w = p['week'] or {}
    few = '<span class="tag">件数少なめ</span>' if p.get('few') else ''
    sec = lambda title, items, cls: (f'<div class="blk {cls}"><h4>{title}</h4><ul>{lis(items)}</ul></div>' if items else '')  # noqa: E731
    return (f'<section class="card"><header><h3>{esc(name)}{few}</h3>'
            f'<p class="kpi">客単価 <b>{yen(w.get("arpu"))}</b>・担当 {w.get("customers", 0)}人</p></header>'
            f'<p class="head">{esc(iss.get("headline", ""))}</p>'
            f'{sec("良かった点", iss.get("good"), "good")}{sec("課題", iss.get("issues"), "issue")}'
            f'{sec("来週やること", iss.get("actions"), "act")}</section>')


CSS = """
:root{--bg:#f7f6f3;--panel:#fff;--ink:#1f2328;--sub:#5d6570;--line:#e3e1dc;--good:#1f7a4d;--bad:#b4442c;--acc:#7a5c2e;--tag:#efe9df}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#16181b;--panel:#1f2226;--ink:#e8e6e3;--sub:#a3a9b1;--line:#33373d;--good:#5cc28f;--bad:#ef8a72;--acc:#d9b27a;--tag:#2c2a26}}
:root[data-theme="dark"]{--bg:#16181b;--panel:#1f2226;--ink:#e8e6e3;--sub:#a3a9b1;--line:#33373d;--good:#5cc28f;--bad:#ef8a72;--acc:#d9b27a;--tag:#2c2a26}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.7 -apple-system,"Hiragino Sans","Noto Sans JP",sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:24px 16px 48px}h1{font-size:22px;margin:0 0 4px}.sub{color:var(--sub);margin:0 0 20px}
.panel,.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}
h2{font-size:17px;margin:0 0 10px}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border-bottom:1px solid var(--line);padding:8px 10px;text-align:right;white-space:nowrap;vertical-align:top}thead th{text-align:right}
tbody th{text-align:left;color:var(--sub);font-weight:600}td small{display:block;color:var(--sub);font-size:11px}
.d{margin-left:4px;font-size:11px}.d.good{color:var(--good)}.d.bad{color:var(--bad)}.d.flat{color:var(--sub)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}.card{margin:0}
.card header{display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap}h3{margin:0;font-size:17px}
.kpi{margin:0;color:var(--sub);font-size:13px}.head{font-weight:600;margin:8px 0}.tag{font-size:11px;background:var(--tag);padding:1px 6px;border-radius:8px;margin-left:6px;font-weight:400}
h4{margin:8px 0 2px;font-size:13px}.good h4{color:var(--good)}.issue h4{color:var(--bad)}.act h4{color:var(--acc)}ul{margin:0;padding-left:18px}
.team li{margin-bottom:4px}.foot{color:var(--sub);font-size:12px;margin-top:24px}
"""


def render(numbers, issues):
    people = numbers['people']
    w0, w1 = numbers['week']
    b0, b1 = numbers['base']
    cards = ''.join(card(n, p, (issues.get('people') or {}).get(n, {})) for n, p in people.items() if n != TEAM)
    team = issues.get('team') or []
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>カウンセラー週次の課題</title><style>{CSS}</style></head><body><div class="wrap">
<h1>カウンセラー別の課題（週次）</h1>
<p class="sub">対象週 {w0}〜{w1}（月〜日）。比較は直前{numbers['base_weeks']}週（{b0}〜{b1}）。{esc(issues.get('updated', ''))}</p>
<section class="panel"><h2>今週のまとめ</h2><p>{esc(issues.get('overview', ''))}</p><ul class="team">{lis(team)}</ul></section>
<section class="panel"><h2>数字（上段が今週、下段が直前{numbers['base_weeks']}週。人数・件数は週平均）</h2>{table(people, numbers['base_weeks'])}</section>
<div class="grid">{cards}</div>
<p class="foot">数字はカウンセラー販売実績ダッシュボードと同じ定義（KOS の購入・予約・満足度調査）。満足度は5点満点、共用アカウント宛ては除外。
担当客数が10人未満の週は「件数少なめ」。課題の文章は数字と満足度調査の自由記述をもとに毎週作成しています。このページは関係者限りです。</p>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--numbers', required=True)
    ap.add_argument('--issues', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    os.umask(0o077)
    n, i = json.load(open(a.numbers)), json.load(open(a.issues))
    if i.get('week') != n['week']:
        raise SystemExit(f"STOP: issues are for {i.get('week')}, numbers for {n['week']}")
    missing = [p for p in n['people'] if p != TEAM and not (i.get('people') or {}).get(p, {}).get('issues')]
    if missing:
        raise SystemExit(f'STOP: no issues written for {missing}')
    open(a.out, 'w', encoding='utf-8').write(render(n, i))
    print('PAGE:', a.out)


if __name__ == '__main__':
    main()
