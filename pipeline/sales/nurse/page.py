"""看護師ダッシュボードの HTML から `const EMBED = {...};` を読み書きし、ページの集計（JS の compute / build）を
Python でそのまま再現する（verify.py・build.py の照合用）。

画面は EMBED（施術・購入・満足度調査の行）とページ内の設定 DOCTORS・NON_STAFF・ALIAS・MENTION から
JS で描画される。build.py は EMBED の行だけを差し替え、CSS / JS / 設定には触れない。
compute() / board() は JS の compute() / build() / render() の数値部分を1行ずつ移したもの。
JS を変えたらここも合わせる（check_render.js が Chromium の表示とこの再現を突き合わせる）。
"""
import json
import re

EMBED_LINE = re.compile(r'^const EMBED = (\{.*\});[ \t]*$', re.M)
WRAP_HEAD = re.compile(r'^<!doctype html><html><head><meta charset=utf8>.*?</head><body>', re.S | re.I)
DATE_RE = re.compile(r'^\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}$')
TRIVIAL = re.compile(r'^(なし|特になし|無し|ない|없음\.?|특별히 없음|-|ー|特にありません|とくになし)$')


def read_html(path):
    t = open(path, encoding='utf-8').read()
    m = WRAP_HEAD.match(t)
    if m and '<title>NaA 看護師' not in t[:m.end()]:
        t = t[m.end():]
        t = t[:t.rindex('</body></html>')] if t.rstrip().endswith('</body></html>') else t
    return t


def get_embed(html):
    m = EMBED_LINE.search(html)
    if not m:
        raise ValueError('const EMBED = {...}; not found')
    return json.loads(m.group(1))


def set_embed(html, e):
    js = json.dumps(e, ensure_ascii=False).replace('</', '<\\/')
    out, n = EMBED_LINE.subn(lambda _: 'const EMBED = ' + js + ';', html, count=1)
    if n != 1:
        raise ValueError('const EMBED = {...}; not found')
    return out


def _js_literal(html, name, close):
    m = re.search(r'^const ' + name + r' = (.*?' + re.escape(close) + r');', html, re.M | re.S)
    if not m:
        raise ValueError(f'const {name} not found')
    body = re.sub(r'//[^\n]*', '', m.group(1))
    body = re.sub(r"'((?:[^'\\]|\\.)*)'", lambda x: json.dumps(x.group(1), ensure_ascii=False), body)
    body = re.sub(r',\s*([}\]])', r'\1', body)
    return json.loads(body)


def config(html):
    """ページ内の設定（医師・非個人名・表記ゆれ・輝き言及の追加語）。"""
    return dict(DOCTORS=_js_literal(html, 'DOCTORS', ']'), NON_STAFF=_js_literal(html, 'NON_STAFF', ']'),
                ALIAS=_js_literal(html, 'ALIAS', '}'), MENTION=_js_literal(html, 'MENTION', '}'))


def _js(v):
    return json.dumps(v, ensure_ascii=False, separators=(',', ':')).replace('"', "'")


def set_config(html, cfg):
    """DOCTORS・ALIAS・MENTION の定数の行を cfg の内容で書き直す（ほかの JS には触れない）。"""
    subs = [(r"^const DOCTORS = \[.*?\];", 'const DOCTORS = ' + _js(cfg['DOCTORS']) + ';'),
            (r"^const ALIAS = \{.*?\};", 'const ALIAS = ' + _js(cfg['ALIAS']) + ';'),
            (r"^const MENTION = \{.*?\n\};", 'const MENTION = { // extra tokens for 輝きスタッフ\n  '
             + ','.join(f'{_js(k)}:{_js(v)}' for k, v in cfg['MENTION'].items()) + '\n};')]
    for pat, rep in subs:
        html, n = re.subn(pat, lambda _: rep, html, count=1, flags=re.M | re.S)
        if n != 1:
            raise ValueError(f'constant not found: {pat[:20]}')
    return html


# ------------------------------------------------------------- JS の compute / build の再現

def norm(s):
    return '' if s is None else re.sub(r'[\s　﻿]', '', str(s))


def dstr(v):
    if v is None:
        return None
    m = re.search(r'(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})', str(v))
    return f'{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}' if m else None


class Calc:
    def __init__(self, cfg):
        self.cfg = cfg
        self.non_staff = {norm(x) for x in cfg['NON_STAFF']}

    def canon(self, s):
        n = norm(s)
        return self.cfg['ALIAS'].get(n) or n

    def is_doctor(self, n):
        return n in self.cfg['DOCTORS']

    def is_non_staff(self, n):
        return not n or n in self.non_staff

    def compute(self, D, day=None):
        path, leaves = [], []
        for r in D['T']:
            g, cat, item, tanto, couns = r
            if isinstance(g, str) and '->' in g:
                path = [s.strip() for s in g.split('->')[1:]]
                continue
            if cat is None and item is None and tanto is None and couns is None:
                continue
            di = next((i for i, s in enumerate(path) if DATE_RE.match(s)), -1)
            if di < 1:
                continue
            leaves.append(dict(perf=[x for x in map(self.canon, (path[di - 1] or '').split(',')) if x],
                               date=dstr(path[di]), pt=norm(path[di + 1] if di + 1 < len(path) else None),
                               cat=cat, item=item, tanto=self.canon(tanto)))
        proc = [l for l in leaves if l['item'] is not None]
        dates = sorted({l['date'] for l in proc if l['date']})
        if day:
            proc = [l for l in proc if l['date'] == day]
        roster = {}

        def get(n):
            if n not in roster:
                roster[n] = dict(name=n, cnt=0, visits=set(), assist=0, days={}, cats={}, nomFix=0, nomEst=0, inTreat=False)
            return roster[n]
        for l in proc:
            for n in [p for p in l['perf'] if not self.is_doctor(p) and not self.is_non_staff(p)]:
                o = get(n)
                o['inTreat'] = True
                o['cnt'] += 1
                o['visits'].add(l['date'] + '|' + l['pt'])
                o['days'][l['date']] = o['days'].get(l['date'], 0) + 1
                c = (l['cat'] or '未分類').split(',')[-1]
                o['cats'][c] = o['cats'].get(c, 0) + 1
        for l in proc:
            if l['tanto'] and l['tanto'] not in l['perf'] and any(map(self.is_doctor, l['perf'])) and l['tanto'] in roster:
                roster[l['tanto']]['assist'] += 1
        nurse_set = list(roster)

        def resolve_fee(s):
            c = self.canon(re.sub(r'^看護師_', '', norm(s)))
            if c in nurse_set:
                return c
            return next((n for n in nurse_set if n.startswith(c) or n.endswith(c)), c)
        visits = {}
        for dt_, p_, fee, fee_cat, cls, status in D['P']:
            d, p = dstr(dt_), norm(p_)
            v = visits.setdefault(d + '|' + p if d else 'null|' + p, dict(d=d, p=p, cls=cls or '', fees=[]))
            if cls:
                v['cls'] = cls
            if fee_cat == '指名料' and norm(fee).startswith('看護師') and status != '返金済み':
                v['fees'].append(resolve_fee(fee))
        est_unassigned = 0
        for v in visits.values():
            if day and v['d'] != day:
                continue
            for n in v['fees']:
                get(n)['nomFix'] += 1
            if not v['fees'] and '看護師指名あり' in v['cls']:
                ls = [l for l in proc if l['date'] == v['d'] and l['pt'] == v['p']]
                cands = list(dict.fromkeys(n for l in ls for n in l['perf'] if n in nurse_set))
                if not cands:
                    cands = list(dict.fromkeys(l['tanto'] for l in ls if l['tanto'] in nurse_set))
                if cands:
                    for n in cands:
                        get(n)['nomEst'] += 1
                else:
                    est_unassigned += 1
        p0 = day or (dates[0] if dates else None)
        p1 = day or (dates[-1] if dates else None)
        resp, shine = {}, []
        for rd, _pt, typ, target, qtype, title, score, val, rid in D['S']:
            d = dstr(rd)
            if title and '輝いて' in str(title) and val:
                shine.append(dict(d=d, txt=str(val)))
            if typ != '施術者':
                continue
            n = self.canon(target)
            if not n or self.is_doctor(n) or self.is_non_staff(n):
                continue
            k = f'{rid}|{n}'
            resp.setdefault(k, dict(n=n, d=d))
            if qtype == '数値入力式' and score is not None:
                resp[k]['score'] = float(score)
            elif qtype != '数値入力式':
                resp[k]['text'] = val
        resp_list = [x for x in resp.values() if x.get('score') is not None or x.get('text')]
        return dict(proc=proc, dates=dates, roster=roster, resp=resp_list, shine=shine, p0=p0, p1=p1, day=day,
                    est_unassigned=est_unassigned, pDates={v['d'] for v in visits.values()},
                    sDates={dstr(r[0]) for r in D['S']})

    def board(self, C, voc_mode='same'):
        """JS の build(): 看護師ごとの行（スコアボード・散布図・ヒートマップ・VOC の元）。"""
        def in_p(d):
            return voc_mode == 'all' or (d and C['p0'] and C['p0'] <= d <= C['p1'])
        vocs = [r for r in C['resp'] if in_p(r['d'])]
        names = list(dict.fromkeys(list(C['roster']) + [r['n'] for r in vocs]))
        rows = []
        for n in names:
            o = C['roster'].get(n) or dict(cnt=0, visits=set(), assist=0, days={}, cats={}, nomFix=0, nomEst=0, inTreat=False)
            mine = [v for v in vocs if v['n'] == n]
            sc = [v['score'] for v in mine if v.get('score') is not None]
            avg = sum(sc) / len(sc) if sc else None
            st = 'na'
            if sc:
                st = 'good'
                if avg < 4.5 or min(sc) <= 3:
                    st = 'warn'
                if avg < 4.0 or min(sc) <= 2:
                    st = 'crit'
            toks = [n] + self.cfg['MENTION'].get(n, [])
            ment = sum(1 for s in C['shine'] if in_p(s['d']) and any(t in norm(s['txt']) for t in toks))
            comments = [v for v in mine if v.get('text') and not TRIVIAL.match(re.sub(r'[。．.！!、]+$', '', norm(v['text'])))]
            nv, nom = len(o['visits']), o['nomFix'] + o['nomEst']
            rows.append(dict(name=n, cnt=o['cnt'], pts=nv, assist=o['assist'], days=dict(o['days']), cats=dict(o['cats']),
                             nomFix=o['nomFix'], nomEst=o['nomEst'], nom=nom, rate=nom / nv if nv else None, avg=avg,
                             n=len(sc), low=sum(1 for s in sc if s <= 3), st=st, ment=ment,
                             comments=sorted([(v.get('score'), v['d'] or '', str(v['text'])) for v in comments], key=str),
                             inTreat=o['inTreat']))
        return [r for r in rows if r['inTreat'] or r['n'] > 0]

    def tiles(self, C, rows, call):
        """ヘッダーとサマリーの数値（JS の render() の前半）。"""
        treat = [r for r in rows if r['inTreat']]
        fix, est = sum(r['nomFix'] for r in rows), sum(r['nomEst'] for r in rows)
        tot_pts = sum(r['pts'] for r in treat)
        all_n = sum(r['n'] for r in rows)
        all_sc = sum(r['avg'] * r['n'] for r in rows if r['avg'] is not None)
        no_p = bool(C['day']) and C['day'] not in C['pDates']
        no_s = bool(C['day']) and C['day'] not in C['sDates']
        return dict(period=(C['p0'], C['p1'], len(C['dates'])), nurses=len(treat), cnt=sum(r['cnt'] for r in treat),
                    pts=tot_pts, nom=None if no_p else fix + est, nomFix=None if no_p else fix, nomEst=None if no_p else est,
                    rate=None if no_p or not tot_pts else (fix + est) / tot_pts,
                    voc=f"{all_sc / all_n:.2f}" if all_n else None, voc_n=all_n,
                    flagged=sorted(r['name'] for r in rows if r['st'] in ('crit', 'warn')),
                    gapP=[d for d in call['dates'] if d not in call['pDates']],
                    gapS=[d for d in call['dates'] if d not in call['sDates']],
                    unassigned=C['est_unassigned'], noS=no_s)


def views(html_or_embed, cfg):
    """ページで選べる表示（全期間 × VOC 2種、各日 × VOC 2種）ごとの (tiles, rows)。"""
    D = html_or_embed if isinstance(html_or_embed, dict) else get_embed(html_or_embed)
    calc = Calc(cfg)
    call = calc.compute(D)
    out = {}
    for day in [None] + call['dates']:
        C = call if day is None else calc.compute(D, day)
        for mode in ('same', 'all'):
            rows = calc.board(C, mode)
            out[(day or 'ALL', mode)] = (calc.tiles(C, rows, call), {r['name']: r for r in rows})
    return out
