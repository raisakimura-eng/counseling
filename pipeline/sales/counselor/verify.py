"""公開中のダッシュボードの数値を API から作り直して突き合わせる。

    python3 -I pipeline/sales/counselor/verify.py HTML WORK [--months 2026-04,2026-05] [--export-gaps]
        [--last 2026-10-10 --voc-last 2026-10-09 --visit-last 2026-10-10] [--detail] [--json OUT]

- 期間（--last など）は省略すると HTML の D.last_date / voc_last / visit_last を使う（＝公開版と同じ締め）。
- --export-gaps: 公開版の元になったエクスポートの欠損（9/24 10:16以降の販売、9/24 の満足度調査、
  9/29・10/1・10/2 の来院）を再現する。Excel 時代の公開版（2026-10-10 版）と比べるときだけ使う。
- --exclude-shared-voc: 共用アカウント宛ての評価を VOC から除いた場合を試す（公開版は除いていない）。
- --table: 月ごとの主要指標の対照表（Markdown）。
- 出力: 指標ごと・月ごとの「公開値 → 再計算値（差）」。一致した項目は数だけ数える。
  --strict を付けると、--months に挙げた月の主要指標（クリニック全体・カウンセラー別の販売）が
  1件でもずれたら終了コード1（毎日の更新で、締めた月がずれていないかの確認に使う）。
患者の氏名・カルテ番号は出さない（集計値とカウンセラー名だけ）。
"""
import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import page  # noqa: E402
import source  # noqa: E402

KEY = ['customers', 'revenue', 'arpu', 'procs', 'prepaid_cust', 'prepaid_amt', 'course_cust', 'course_amt',
       'refund_cust', 'new_cust', 'disc', 'one_rate', 'visits']


def close(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-6 * max(1, abs(a), abs(b))
    return a == b


def walk(a, b, path, out):
    """a = 公開値, b = 再計算値。差のある葉を (path, a, b) で集める。"""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            walk(a.get(k), b.get(k), path + [k], out)
    elif isinstance(a, list) and isinstance(b, list) and not (a and isinstance(a[0], dict)):
        if a != b:
            out.append((path, a, b))
    elif isinstance(a, list) and isinstance(b, list):
        # コメント一覧: 件数と中身（本文・点・日付・チャネル）の集合で比べる
        ka = sorted(json.dumps(x, ensure_ascii=False, sort_keys=True) for x in a)
        kb = sorted(json.dumps(x, ensure_ascii=False, sort_keys=True) for x in b)
        if ka != kb:
            out.append((path, f'{len(a)}件', f'{len(b)}件 (一致 {len(set(ka) & set(kb))})'))
    elif not close(a, b):
        out.append((path, a, b))


def fmt(v):
    if isinstance(v, float):
        return f'{v:.4f}' if abs(v) < 10 else f'{v:,.1f}'
    return str(v)


def compare(pub, new, months):
    rows = []
    for m in months:
        for ch in pub['ch_order']:
            walk(pub['clinic'][ch].get(m), new['clinic'][ch].get(m), ['clinic', ch, m], rows)
            for n in pub['main']:
                walk(((pub['counselors'].get(n) or {}).get(ch) or {}).get(m),
                     ((new['counselors'].get(n) or {}).get(ch) or {}).get(m), ['counselors', n, ch, m], rows)
            if m in pub['voc'].get(ch, {}):
                walk(pub['voc'][ch][m], new['voc'][ch].get(m), ['voc', ch, m], rows)
        for n in pub['main']:
            walk((pub['duration'].get(n) or {}).get(m), (new['duration'].get(n) or {}).get(m), ['duration', n, m], rows)
        walk(pub['duration_clinic'].get(m), new['duration_clinic'].get(m), ['duration_clinic', m], rows)
        if m in pub['comments']:
            walk(pub['comments'][m], new['comments'].get(m), ['comments', m], rows)
        walk(pub['month_range'].get(m), new['month_range'].get(m), ['month_range', m], rows)
    return rows


def table(pub, new, months):
    """月ごとの主要指標（公開値 / 再計算値）。担当者別は4名＋新任の顧客数・売上の最大のずれ。"""
    def g(d, *ks):
        for k in ks:
            d = (d or {}).get(k)
        return d
    lines = ['| 月 | 顧客数 | 売上 | 顧客単価 | プリペイド率 | コース率 | 返金率 | 1人あたり施術 | 値引後率 | 進行時間中央値(n) | CS満足度(n) | 担当者別の最大差（顧客数／売上） |',
             '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for m in months:
        a, b = g(pub, 'clinic', 'ALL', m), g(new, 'clinic', 'ALL', m)
        if not a or not b:
            continue

        def cell(k, f):
            x, y = a[k], b[k]
            return f(x) if close(x, y) else f'{f(x)} → {f(y)}'
        dur = lambda d: f"{d['med']:g}分({d['n']})" if d else '—'  # noqa: E731
        da, db = g(pub, 'duration_clinic', m), g(new, 'duration_clinic', m)
        va, vb = g(pub, 'voc', 'ALL', m, 'clinic', 'カウンセラー'), g(new, 'voc', 'ALL', m, 'clinic', 'カウンセラー')
        vf = lambda v: f"{v['mean']:.2f}({v['n']})" if v and v['n'] else '—'  # noqa: E731
        worst_c, worst_r = 0, 0.0
        for n in pub['main']:
            x, y = g(pub, 'counselors', n, 'ALL', m), g(new, 'counselors', n, 'ALL', m)
            if x and y:
                worst_c = max(worst_c, abs(y['customers'] - x['customers']), key=abs)
                if x['revenue']:
                    worst_r = max(worst_r, abs(y['revenue'] / x['revenue'] - 1))
        lines.append('| ' + ' | '.join([
            m, cell('customers', lambda v: f'{v:,}'), cell('revenue', lambda v: f'{v:,.0f}'),
            cell('arpu', lambda v: f'{v:,.0f}'), cell('prepaid_rate', lambda v: f'{v:.2%}'),
            cell('course_rate', lambda v: f'{v:.2%}'), cell('refund_rate', lambda v: f'{v:.2%}'),
            cell('procs_per_cust', lambda v: f'{v:.3f}'), cell('disc', lambda v: f'{v:.4f}'),
            dur(da) if dur(da) == dur(db) else f'{dur(da)} → {dur(db)}',
            vf(va) if vf(va) == vf(vb) else f'{vf(va)} → {vf(vb)}',
            f'±{worst_c}人／{worst_r:.2%}']) + ' |')
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('html')
    ap.add_argument('work')
    ap.add_argument('--months', help='comma separated YYYY-MM / ALL / VOCWIN (default: every month on the page + ALL + VOCWIN)')
    ap.add_argument('--export-gaps', action='store_true')
    ap.add_argument('--exclude-shared-voc', action='store_true')
    ap.add_argument('--last')
    ap.add_argument('--voc-last')
    ap.add_argument('--visit-last')
    ap.add_argument('--detail', action='store_true', help='show every differing leaf (default: sales KPIs of ALL channel only)')
    ap.add_argument('--strict', action='store_true')
    ap.add_argument('--table', action='store_true', help='print a markdown table of the key metrics per month')
    ap.add_argument('--json', help='write all differences to this file (outside the repository)')
    a = ap.parse_args()
    pub = page.get_d(page.read_html(a.html))
    d = lambda s, k: dt.date.fromisoformat(s or pub[k])  # noqa: E731
    new = source.load(a.work, d(a.last, 'last_date'), voc_last=d(a.voc_last, 'voc_last'),
                      visit_last=d(a.visit_last, 'visit_last'), export_gaps=a.export_gaps,
                      exclude_shared_voc=a.exclude_shared_voc, main=pub['main'])
    months = a.months.split(',') if a.months else pub['months'] + ['ALL', 'VOCWIN']
    diffs = compare(pub, new, months)
    n_leaf = [0]

    def count(x):
        if isinstance(x, dict):
            for v in x.values():
                count(v)
        else:
            n_leaf[0] += 1
    for m in months:
        for ch in pub['ch_order']:
            count(pub['clinic'][ch].get(m))
            for n in pub['main']:
                count(((pub['counselors'].get(n) or {}).get(ch) or {}).get(m))
    print(f'months {",".join(months)}: {len(diffs)} differing values (sales leaves checked: {n_leaf[0]})')
    shown = diffs if a.detail else [x for x in diffs if x[0][0] in ('clinic', 'counselors') and 'ALL' in x[0][1:3] and x[0][-1] in KEY]
    for p, x, y in shown:
        delta = f' ({y - x:+,.4g})' if isinstance(x, (int, float)) and isinstance(y, (int, float)) else ''
        print(f"  {'/'.join(map(str, p))}: {fmt(x)} -> {fmt(y)}{delta}")
    if a.table:
        print(table(pub, new, months))
    if a.json:
        os.umask(0o077)
        json.dump([['/'.join(map(str, p)), x, y] for p, x, y in diffs], open(a.json, 'w'), ensure_ascii=False, indent=0)
    if a.strict:
        bad = [x for x in diffs if x[0][0] in ('clinic', 'counselors')]
        if bad:
            sys.exit(f'STRICT: {len(bad)} sales values differ in {",".join(months)}')


if __name__ == '__main__':
    main()
