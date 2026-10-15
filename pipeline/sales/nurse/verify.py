"""看護師ダッシュボードの表示を、API から作り直したデータの表示と突き合わせる。

    python3 -I pipeline/sales/nurse/verify.py HTML WORK [--from YYYY-MM-DD --until YYYY-MM-DD]
        [--table] [--detail] [--raw] [--strict] [--expect OUT.json]

- 期間は省略するとページの期間（EMBED.files の「KOS OpenAPI 開始〜終了」、Excel 版なら施術の最初と最後の日）。
- 比べるのはページで選べる表示すべて（全期間・各日 × VOC「施術と同期間」「全回答」）の
  サマリー（施術件数・施術患者数・指名件数・指名率・VOC 平均と件数・ガードレール該当・未取込の日）と、
  看護師ごとの行（施術件数・施術患者数・医師施術の担当・指名 確定/推定・VOC 平均/件数/3点以下・
  ガードレール・輝き言及・コメント・日別件数・カテゴリ別件数）。集計は page.Calc（ページの JS の再現）。
- --table: 全期間と日ごとの主要指標の対照表（Markdown）。--detail: 違う値をすべて出す。
- --raw: EMBED の行（T・P・S）を患者キー以外で突き合わせ、片方にしかない行の数を出す。
- --expect: 作り直した側の表示の期待値を JSON に書く（check_render.js --expect が画面と突き合わせる）。
- --strict: 1つでも違えば終了コード1（毎日の更新で、作ったページが API と一致するかの確認）。
患者の氏名・カルテ番号は出さない（集計値と看護師名だけ）。
"""
import argparse
import collections
import datetime as dt
import decimal
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aggregate as A  # noqa: E402
import fetch  # noqa: E402
import page  # noqa: E402

ROW_KEYS = ['cnt', 'pts', 'assist', 'nomFix', 'nomEst', 'avg', 'n', 'low', 'st', 'ment', 'comments', 'days', 'cats']
TILE_KEYS = ['period', 'nurses', 'cnt', 'pts', 'nom', 'nomFix', 'nomEst', 'rate', 'voc', 'voc_n', 'flagged', 'gapP', 'gapS', 'unassigned']


def page_period(e):
    m = re.search(r'KOS OpenAPI (\d{4}-\d\d-\d\d)〜(\d{4}-\d\d-\d\d)', ' '.join(e.get('files') or []))
    if m:
        return dt.date.fromisoformat(m[1]), dt.date.fromisoformat(m[2])
    ds = sorted({page.dstr(s) for r in e['T'] if isinstance(r[0], str) for s in r[0].split('->')
                 if page.DATE_RE.match(s.strip())})
    return dt.date.fromisoformat(ds[0]), dt.date.fromisoformat(ds[-1])


def rebuild(work, d0, d1):
    return A.build(fetch.load(work, 'procedure', d0, d1), fetch.load(work, 'purchase', d0, d1),
                   fetch.load(work, 'survey', d0, d1), d0, d1)


def same(a, b):
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= 1e-9
    return a == b


def compare(vp, vn):
    """[(表示, 看護師 or '*', 項目, 公開値, 再計算値)]"""
    out = []
    for key in sorted(set(vp) | set(vn)):
        tp, rp = vp.get(key, ({}, {}))
        tn, rn = vn.get(key, ({}, {}))
        for k in TILE_KEYS:
            if not same(tp.get(k), tn.get(k)):
                out.append((key, '*', k, tp.get(k), tn.get(k)))
        for n in sorted(set(rp) | set(rn)):
            a, b = rp.get(n), rn.get(n)
            if not a or not b:
                out.append((key, n, 'row', 'あり' if a else 'なし', 'あり' if b else 'なし'))
                continue
            for k in ROW_KEYS:
                if not same(a[k], b[k]):
                    out.append((key, n, k, a[k], b[k]))
    return out


def short(k, v):
    if k == 'comments':
        return f'{len(v)}件'
    if isinstance(v, float):
        return f'{v:.4f}'
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return str(v)


def table(vp, vn):
    """全期間と日ごと（VOC は施術と同期間）の主要指標。公開値 → 再計算値。"""
    def cell(a, b, f=str):
        return f(a) if same(a, b) else f'{f(a)} → {f(b)}'
    pct = lambda v: '–' if v is None else f'{v:.1%}'  # noqa: E731
    lines = ['| 表示 | 看護師 | 施術件数 | 施術患者数 | 指名（確定／推定） | 指名率 | VOC平均(n) | ガードレール該当 | 輝き言及 | VOCコメント | 看護師別の差 |',
             '|---|---|---|---|---|---|---|---|---|---|---|']
    for key in sorted(vp, key=lambda k: (k[0] != 'ALL', k)):
        if key[1] != 'same' or key not in vn:
            continue
        (ta, ra), (tb, rb) = vp[key], vn[key]
        ment = lambda r: sum(x['ment'] for x in r.values())  # noqa: E731
        cm = lambda r: sum(len(x['comments']) for x in r.values())  # noqa: E731
        nd = sorted({n for (k, n, f, _, _) in compare({key: vp[key]}, {key: vn[key]}) if n != '*'})
        lines.append('| ' + ' | '.join([
            '全期間' if key[0] == 'ALL' else key[0][5:], cell(ta['nurses'], tb['nurses']), cell(ta['cnt'], tb['cnt']),
            cell(ta['pts'], tb['pts']), cell((ta['nomFix'], ta['nomEst']), (tb['nomFix'], tb['nomEst']),
                                             lambda v: '–' if v[0] is None else f'{v[0]}／{v[1]}'),
            cell(ta['rate'], tb['rate'], pct), cell((ta['voc'], ta['voc_n']), (tb['voc'], tb['voc_n']), lambda v: f'{v[0]}({v[1]})'),
            cell(len(ta['flagged']), len(tb['flagged'])), cell(ment(ra), ment(rb)), cell(cm(ra), cm(rb)),
            '、'.join(nd) or '一致']) + ' |')
    return '\n'.join(lines)


def raw_diff(pub, new):
    def k_t(rows):
        path, out = [], collections.Counter()
        for r in rows:
            if isinstance(r[0], str) and '->' in r[0]:
                path = [s.strip() for s in r[0].split('->')[1:]]
                continue
            if all(x is None for x in r[1:]):
                continue
            di = next((i for i, s in enumerate(path) if page.DATE_RE.match(s)), -1)
            out[(path[di].replace('.', '-'), path[di - 1]) + tuple(r[1:4])] += 1
        return out
    res = {}
    for name, f in (('T', k_t), ('P', lambda rows: collections.Counter((r[0],) + tuple(r[2:]) for r in rows)),
                    ('S', lambda rows: collections.Counter(tuple(r[2:]) for r in rows))):
        a, b = f(pub[name]), f(new[name])
        res[name] = (sum(a.values()), sum(b.values()), a - b, b - a)
    return res


def expect(views):
    """check_render.js 用: 表示ごとのサマリーと表の各行を、画面と同じ書式の文字列で。"""
    pct = lambda v: '–' if v is None else f'{round(v * 100 + 1e-9):.0f}%'  # noqa: E731
    # the page uses JS toFixed(2): half-up on the exact binary value (4.625 -> '4.63'; Python's :.2f gives '4.62')
    fmt1 = lambda v: '–' if v is None else str(decimal.Decimal(v).quantize(decimal.Decimal('0.01'), decimal.ROUND_HALF_UP))  # noqa: E731
    lab = {'good': '良好', 'warn': '注意', 'crit': '要確認', 'na': 'VOCなし'}
    out = {}
    for (day, mode), (t, rows) in views.items():
        no_p = t['nom'] is None
        voc = '–' if (t['noS'] and mode != 'all') or t['voc'] is None else t['voc']
        tiles = [str(t['cnt']), '–' if no_p else str(t['nom']), '–' if no_p else pct(t['rate']), voc, f"{len(t['flagged'])}名"]
        board = {n: [str(r['cnt']), str(r['pts']), str(r['assist'] or '–'), str(r['nom'] or '–'),
                     '–' if no_p else pct(r['rate']), f"{fmt1(r['avg'])} n={r['n']}", str(r['low'] or '–'),
                     str(r['ment'] or '–'), lab[r['st']] + (' n少' if 0 < r['n'] < 3 else '')] for n, r in rows.items()}
        out[f'{day}|{mode}'] = dict(tiles=tiles, board=board, comments=sum(len(r['comments']) for r in rows.values()))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('html')
    ap.add_argument('work')
    ap.add_argument('--from', dest='d0')
    ap.add_argument('--until')
    ap.add_argument('--table', action='store_true')
    ap.add_argument('--detail', action='store_true')
    ap.add_argument('--raw', action='store_true')
    ap.add_argument('--strict', action='store_true')
    ap.add_argument('--expect', help='write the expected screen values of the rebuilt data (for check_render.js)')
    a = ap.parse_args()
    html = page.read_html(a.html)
    cfg = page.config(html)
    pub = page.get_embed(html)
    p0, p1 = page_period(pub)
    d0 = dt.date.fromisoformat(a.d0) if a.d0 else p0
    d1 = dt.date.fromisoformat(a.until) if a.until else p1
    new = rebuild(a.work, d0, d1)
    vp, vn = page.views(pub, cfg), page.views(new, cfg)
    diffs = compare(vp, vn)
    print(f'period {d0}..{d1}: {len(vp)} views on the page, {len(diffs)} differing values')
    shown = diffs if a.detail else [d for d in diffs if d[0] == ('ALL', 'same') or d[1] == '*']
    for key, n, k, x, y in shown:
        print(f"  {key[0]}/{key[1]} {n} {k}: {short(k, x)} -> {short(k, y)}")
    if a.table:
        print(table(vp, vn))
    if a.raw:
        for name, (na, nb, oa, ob) in raw_diff(pub, new).items():
            print(f'raw {name}: page {na} rows, API {nb} rows; only on page {sum(oa.values())}, only in API {sum(ob.values())}')
            if name == 'T':
                for k, c in list(oa.items())[:10]:
                    print('   page only:', k[0], k[1], k[2:], c)
                for k, c in list(ob.items())[:10]:
                    print('   API only: ', k[0], k[1], k[2:], c)
    if a.expect:
        os.umask(0o077)
        json.dump(expect(vn), open(a.expect, 'w'), ensure_ascii=False)
    if a.strict and diffs:
        sys.exit(f'STRICT: {len(diffs)} values differ')


if __name__ == '__main__':
    main()
