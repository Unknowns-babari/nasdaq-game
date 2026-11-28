"""야후 파이낸스에서 게임 종목의 최신 실제 가격을 받아 live.json으로 저장. GitHub Actions에서 실행.
출력 위치는 환경변수 OUT (기본: live.json). 바뀐 게 없으면 파일을 건드리지 않고 종료 코드 3."""
import json, os, re, sys, time, datetime, concurrent.futures as cf, urllib.request, urllib.parse

OUT = os.environ.get('OUT', 'live.json')
html = open('index.html', encoding='utf-8').read()
ROW = re.compile(r"\['([^']+)','[^']*','[^']*',[-\d.]+,[^,\]]+,[^,\]]+,'(\w+)'(?:,'([^']+)',[-\d.]+)?\]")
SUF = {'kospi': '.KS', 'kosdaq': '.KQ', 'nikkei': '.T'}
syms = {}
for t, g, under in ROW.findall(html):
    if g in ('bond', 'coin'):
        continue
    syms[t] = t + SUF[g] if g in SUF else t.replace('.', '-')
syms['_KRW'] = 'KRW=X'
syms['_JPY'] = 'JPY=X'
UA = {'User-Agent': 'nasdaq-game-price-sync/1.1'}


def meta_to_q(m):
    p = m.get('regularMarketPrice')
    pc = m.get('chartPreviousClose') or m.get('previousClose')
    if not p:
        return None
    return {'p': round(p, 4), 'pc': round(pc, 4) if pc else None, 't': m.get('regularMarketTime')}


def spark(batch):
    """여러 종목을 한 번에 (최대 20개)"""
    ys = ','.join(y for _, y in batch)
    url = 'https://query1.finance.yahoo.com/v8/finance/spark?' + urllib.parse.urlencode({'symbols': ys, 'range': '1d', 'interval': '1d'})
    back = {y: t for t, y in batch}
    out = {}
    try:
        j = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20))
        for r in (j.get('spark') or {}).get('result') or []:
            resp = (r.get('response') or [{}])[0]
            q = meta_to_q(resp.get('meta') or {})
            if q and r.get('symbol') in back:
                out[back[r['symbol']]] = q
    except Exception as e:
        print('spark 실패', e)
    return out


def chart(t, y):
    for host in ('query1', 'query2'):
        try:
            req = urllib.request.Request(f'https://{host}.finance.yahoo.com/v8/finance/chart/{y}?range=1d&interval=1d', headers=UA)
            q = meta_to_q(json.load(urllib.request.urlopen(req, timeout=15))['chart']['result'][0]['meta'])
            if q:
                return t, q
        except Exception:
            time.sleep(1)
    return t, None


items = list(syms.items())
res = {}
for k in range(0, len(items), 20):
    res.update(spark(items[k:k + 20]))
miss = [(t, y) for t, y in items if t not in res]
if miss:
    print(f'spark로 못 받은 {len(miss)}개는 하나씩')
    with cf.ThreadPoolExecutor(4) as ex:
        for t, q in ex.map(lambda kv: chart(*kv), miss):
            if q:
                res[t] = q

quotes = {t: q for t, q in res.items() if not t.startswith('_')}
fx = {k[1:]: q['p'] for k, q in res.items() if k.startswith('_')}
print(f'{len(quotes)}/{len(syms) - 2} 종목, 환율 {fx}')
if len(quotes) < 20:
    sys.exit('받아온 종목이 너무 적어요 (접속이 막혔을 수 있어요)')
try:
    old = json.load(open(OUT, encoding='utf-8'))
except Exception:
    old = {}
if old.get('quotes') == quotes and old.get('fx') == fx:
    print('변동 없음')
    sys.exit(3)
json.dump({'updated': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'source': 'Yahoo Finance', 'fx': fx, 'quotes': quotes},
          open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
