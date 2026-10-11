"""Summary blocks and narrative copy (headlines / explanations) of the dashboard payload.

The templates reproduce the hand-written copy of the original dashboard word for
word for Aug/Sep/Oct (see verify.py), so regenerated periods read the same way.
"""
ROLES = ['受付', 'カウンセラー', '医師', '看護師']
QLAB = {'受付': '受付の雰囲気', 'カウンセラー': 'カウンセリング', '医師': '医師の診察', '看護師': '施術の満足度', 'clinic': '総評'}
QFULL = {'受付': '「受付の雰囲気を教えてください」', 'カウンセラー': '「カウンセリングの質はいかがでしたか」',
         '医師': '「医師の診察の質を教えてください」', '看護師': '「施術の満足度を教えてください」'}
THEMES = [['manner', '接遇・態度'], ['explain', '説明のわかりやすさ'], ['listen', '傾聴・相談対応'], ['skill', '技術・仕上がり'],
          ['pain', '痛みへの配慮'], ['speed', 'スピード・待ち時間'], ['proposal', '提案・営業姿勢'], ['ops', '連携・オペレーション'],
          ['env', '清潔感・環境'], ['other', 'その他・判断保留']]
TL = dict(THEMES)
f2 = lambda v: '—' if v is None else f'{v:.2f}'


def gap_of(d):
    """★5群と★4以下群の総評の差 (None while one of the groups is still empty, e.g. early in a month)."""
    return d['hi'] - d['lo'] if d['hi'] is not None and d['lo'] is not None else None

def themes_pol(comments):
    rt = {k: dict(n=0, pos=0, mix=0, neu=0, neg=0) for k, _ in THEMES}; rp = dict(pos=0, mix=0, neu=0, neg=0)
    for c in comments:
        rp[c['p']] += 1
        for t in c['t']: rt[t]['n'] += 1; rt[t][c['p']] += 1
    return rt, rp

def flagged(D):
    mn = D['meta']['minN']; out = []
    for s in D['staff']:
        rate = s['low'] / s['n']
        if s['n'] >= mn and (s['avg'] < D['role']['avg'] - 0.25 or rate >= 0.15): out.append(s)
    return out

def summary(P, per):
    """P: {role: period dict}"""
    any_ = P[ROLES[0]]; c = any_['clinic']; m = any_['meta']
    roles = []
    for r in ROLES:
        D = P[r]; dv = next(d for d in D['drivers'] if d['role'] == r)
        req = D['rolePol']['neg'] + D['rolePol']['mix']; com = len(D['comments'])
        roles.append(dict(role=r, n=D['role']['n'], avg=D['role']['avg'], top=D['role']['top'], low=D['role']['low'], r=dv['r'],
                          gap=gap_of(dv), hi=dv['hi'], lo=dv['lo'], nhi=dv['nhi'], nlo=dv['nlo'], com=com, req=req,
                          reqRate=req / com * 100 if com else 0, q=QFULL[r]))
    heat = []
    for k, lab in THEMES:
        cells = [dict(role=r, n=P[r]['roleThemes'][k]['n'], req=P[r]['roleThemes'][k]['neg'] + P[r]['roleThemes'][k]['mix']) for r in ROLES]
        heat.append(dict(key=k, lab=lab, cells=cells, req=sum(x['req'] for x in cells), n=sum(x['n'] for x in cells)))
    heat.sort(key=lambda h: (-h['req'], -h['n']))
    flags = [dict(role=r, name=s['name'], n=s['n'], avg=s['avg'], low=s['low'], rate=s['low'] / s['n'] * 100, cavg=s['cavg'])
             for r in ROLES for s in flagged(P[r])]
    flags.sort(key=lambda f: f['avg'])
    low = any_['lowClinic']
    lowBreak = [dict(role=r, n=sum(1 for x in low if x['roles'].get(r, 9) <= 3)) for r in ROLES]
    return dict(nResp=m['nResp'], clinicAvg=c['avg'], clinicLow=c['low'], clinicTop=c['top'], clinicN=c['n'], **{'from': m['subFrom']},
                to=m['subTo'], minN=m['minN'], roles=roles, reqTotal=sum(x['req'] for x in roles), comTotal=sum(x['com'] for x in roles),
                heat=heat, flags=flags, lowBreak=lowBreak, lowN=len(low))

def nth(i): return f'{i}番目'

def copy(P, r, PL):
    D = P[r]; m = D['meta']; mn = m['minN']; out = {}
    gaps = sorted(((next(d for d in P[x]['drivers'] if d['role'] == x), x) for x in ROLES),
                  key=lambda t: -gap_of(t[0]) if gap_of(t[0]) is not None else float('inf'))
    rank = [x for _, x in gaps].index(r) + 1; dv = gaps[rank - 1][0]; top = gaps[0]
    out['driver-h'] = (f'総評をいちばん動かしているのは{r}' if rank == 1 else '総評への効き方は4職種でいちばん弱い' if rank == 4
                       else f'総評への効き方は4職種で{rank}番目')
    s = (f'その職種を★5と付けた人の総評平均と、★4以下を付けた人の総評平均を並べたものです。差が大きいほど「そこの体験が総評を左右している」ことになります。'
         f'{PL}の{r}は差 <strong>+{f2(gap_of(dv))}</strong>・相関 {f2(dv["r"])} で4職種で{rank}番目')
    if gap_of(dv) is None:
        s = s[:s.rindex(f'{PL}の')] + f'{PL}の{r}は、まだ★5群と★4以下群の両方がそろっていないため差を出せません'
    elif rank > 1: s += f'（最大は{top[1]} +{f2(gap_of(top[0]))}）'
    five = sorted([(P[x]['role']['avg'], x) for x in ROLES] + [(D['clinic']['avg'], 'clinic')], key=lambda t: -t[0])
    qi = [x for _, x in five].index(r) + 1; bot = five[-1]
    phr = {1: 'いちばん高い', 2: '上から2番目', 3: '下から3番目', 4: '下から2番目', 5: 'いちばん低い'}[qi]
    s += f'。{QLAB[r]} {f2(D["role"]["avg"])} は5設問のなかで{phr}' + ('' if qi == 5 else f'（最下位は{QLAB[bot[1]]} {f2(bot[0])}）') + '。'
    out['driver-sub'] = s
    if not D['staff']:
        out['staff-h'] = '担当者別スコアと、その回の総評'
        out['staff-sub'] = 'この設問は担当者名が記録されないため、担当者別の集計はありません。'
    elif not [x for x in D['staff'] if x['n'] >= mn]:
        out['staff-h'] = '担当者別スコアと、その回の総評'
        out['staff-sub'] = f'{PL}は評価が{mn}件以上ある担当者がまだいないため、担当者ごとの比較は件数がたまってから表示します。'
    else:
        fl = flagged(D)
        out['staff-h'] = ('担当者別スコアと、その回の総評' if not fl else 'ひとりだけ明確に外れている' if len(fl) == 1 else f'要注意ラインの担当者が{len(fl)}名')
        el = [x for x in D['staff'] if x['n'] >= mn]
        best = max(el, key=lambda x: x['avg']); worst = min(el, key=lambda x: x['avg'])
        def lw(x): return '★3以下ゼロ' if not x['low'] else f'★3以下{x["low"]}件／{x["low"] / x["n"] * 100:.0f}%'
        s = (f'オリーブが本人の評価、ゴールドがその担当者が入った来院のクリニック総評です。{PL}は<strong>{best["name"]} {f2(best["avg"])}</strong>'
             f'（n={best["n"]}・{lw(best)}）が最も高く、担当回の総評は {f2(best["cavg"])}。いちばん低いのは {worst["name"]} {f2(worst["avg"])}'
             f'（n={worst["n"]}・{lw(worst)}）で、担当回の総評は {f2(worst["cavg"])} です。')
        fl.sort(key=lambda x: -x['avg'])
        s += (f'要注意ラインに入るのは {"・".join(x["name"] for x in fl)}（n≥{mn}で判定）。' if fl else f'要注意ラインに入る担当者はいません（n≥{mn}で判定）。')
        out['staff-sub'] = s
    hs = D['hours']
    if not hs:
        out['hours-h'] = '時間帯別のスコア'
        out['hours-sub'] = f'{PL}は時間帯別に分けられる回答がまだありません。'
    else:
        hi = max(hs, key=lambda h: h['avg']); lo = min(hs, key=lambda h: h['avg']); d = hi['avg'] - lo['avg']
        out['hours-h'] = '時間帯による大きな差はない' if d < 0.2 else f'{lo["h"]}時台が落ち込む'
        out['hours-sub'] = (f'来院枠の時間帯ごとの{r}スコアです。{PL}は{hi["h"]}時台 {f2(hi["avg"])} が最高、<strong>{lo["h"]}時台 {f2(lo["avg"])}</strong> が最低で、'
                            f'差は {f2(d)}pt。1時間あたり{min(h["n"] for h in hs)}〜{max(h["n"] for h in hs)}件と母数が小さいので、傾向として読んでください。')
    out['voc-h'] = f'{r}へのコメント'
    req = D['rolePol']['neg'] + D['rolePol']['mix']; com = len(D['comments'])
    rq = sorted(((D['roleThemes'][k]['neg'] + D['roleThemes'][k]['mix'], i, k) for i, (k, _) in enumerate(THEMES)), key=lambda t: (-t[0], t[1]))
    rq = [t for t in rq if t[0] > 0][:3]
    mx = max(((D['roleThemes'][k]['n'], -i, k) for i, (k, _) in enumerate(THEMES)))
    out['voc-sub'] = (f'{r}への自由記述{com}件を、テーマと極性で分類したものです。テーマ行をクリックすると下のコメントが絞り込まれます。'
                      f'{PL}の改善要望は <strong>{req}件（{req / com * 100 if com else 0:.1f}%）</strong>で、内訳は{"・".join(f"{TL[k]} {n}件" for n, _, k in rq)}。'
                      f'言及がいちばん多いテーマは「{TL[mx[2]]}」{mx[0]}件です。')
    out['segs-h'] = f'患者属性別：{r}と総評'
    sg = [x for k in ('seg', 'age', 'nat') for x in D['segs'][k]]
    if not sg:
        out['segs-sub'] = f'{PL}は n が{mn}件以上ある区分がまだないため、属性別の比較は件数がたまってから表示します。'
    else:
        b = max(sg, key=lambda x: x['recep']); w = min(sg, key=lambda x: x['recep']); cl = [x['clinic'] for x in sg]
        out['segs-sub'] = (f'{PL}は {b["v"]} {f2(b["recep"])}（n={b["n"]}）が最高、{w["v"]} {f2(w["recep"])}（n={w["n"]}）が最低で、差は {f2(b["recep"] - w["recep"])}pt。'
                           f'同じ区分のクリニック総評は {f2(min(cl))}〜{f2(max(cl))} に収まっています。n が{mn}件未満の区分は省いています。')
    named = [x for x in D['shine'] if x['role'] == r and '名前なし' not in x['name']]
    nn = next((x['n'] for x in D['shine'] if x['name'] == f'{r}（名前なし）'), 0)
    k = sum(x['n'] for x in named)
    s = f'クリニック全体への設問なので全職種が対象です。{PL}の言及{m["nShine"]}件のうち、{r}で名前が挙がったのは{k}件（{len(named)}名）。'
    if k == 0: s += f'この設問では名前が書かれることがほとんどありません。職種だけで書かれた「{r}（名前なし）」が{nn}件あります。'
    else: s += f'上位は{"・".join(x["name"] + "さん" + str(x["n"]) + "件" for x in named[:4])}。職種だけで書かれた「{r}（名前なし）」も{nn}件あります。'
    out['shine-sub'] = s
    out['foot'] = f'「{r}」はアンケート設問{QFULL[r]}の星評価、「クリニック総評」は「NaAクリニックの総評をお願いします」の星評価です。'
    return out
