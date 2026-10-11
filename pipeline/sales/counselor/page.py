"""カウンセラー販売実績ダッシュボードの HTML から `const D = {...};` を読み書きする。

画面は D だけから描画される（PERIODS・METRICS・DBAND などは D から作る JS の定数で、データではない）。
build.py は D の行だけを差し替え、CSS / JS には触れない。ただし本文の「指標の定義」と
フッターに日付が文章で書かれているので、それは set_dates() で書き換える（該当箇所が見つからなければ止める）。
"""
import json
import re

D_LINE = re.compile(r'^const D = (\{.*\});[ \t]*$', re.M)
# claude.ai の Artifact read で保存したページに付く外枠
WRAP_HEAD = re.compile(r'^<!doctype html><html><head><meta charset=utf8>.*?</head><body>', re.S | re.I)


def read_html(path):
    t = open(path, encoding='utf-8').read()
    m = WRAP_HEAD.match(t)
    if m and '<title>NaAクリニック カウンセラー' not in t[:m.end()]:
        t = t[m.end():]
        t = t[:t.rindex('</body></html>')] if t.rstrip().endswith('</body></html>') else t
    return t


def get_d(html):
    m = D_LINE.search(html)
    if not m:
        raise ValueError('const D = {...}; not found')
    return json.loads(m.group(1))


def set_d(html, d):
    js = json.dumps(d, ensure_ascii=False).replace('</', '<\\/')
    out, n = D_LINE.subn(lambda _: 'const D = ' + js + ';', html, count=1)
    if n != 1:
        raise ValueError('const D = {...}; not found')
    return out


def jp(d):
    return f'{d.month}月{d.day}日'


def set_dates(html, sales_last, voc_last, visit_last, dur_last, notes):
    """本文中の日付つきの文を最新に合わせる。notes は欠損の説明（データ源ごとの締めの文）。"""
    subs = [
        (r'出典：[^。]*?（2026年3月20日〜[^）]*）',
         f'出典：KOS OpenAPIの購入・予約来院・満足度調査アンケートのデータ（2026年3月20日〜{sales_last.year}年{jp(sales_last)}）'),
        (r'(<dt>集計期間</dt><dd>2026年3月20日（開院）〜)[^。]*?(。)', r'\g<1>' + jp(sales_last) + r'\g<2>'),
        (r'(4名の記録率はほぼ100%です。)[^<]*?(</dd>)', r'\g<1>' + f'{jp(dur_last)}までを反映しています。' + r'\g<2>'),
        (r'(<dt>データの欠損</dt><dd>)[^<]*(</dd>)', r'\g<1>' + notes['gap'] + r'\g<2>'),
        (r'(<dt>データ源ごとの締め</dt><dd>)[^<]*(</dd>)', r'\g<1>' + notes['close'] + r'\g<2>'),
        (r'(回答は)\d+月\d+日(分まで、欠損なく反映しています。)', r'\g<1>' + jp(voc_last) + r'\g<2>'),
    ]
    for pat, rep in subs:
        html, n = re.subn(pat, rep, html, count=1)
        if n != 1:
            raise ValueError(f'text to update not found: {pat[:40]}')
    return html
