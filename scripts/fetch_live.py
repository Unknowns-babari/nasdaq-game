"""야후 파이낸스에서 게임 종목의 마지막 실제 가격(지연 시세)을 받아 live.json으로 저장. GitHub Actions에서 실행."""
import json, re, time, datetime, concurrent.futures as cf, urllib.request

html = open('index.html', encoding='utf-8').read()
ROW = re.compile(r"\['([^']+)','[^']*','[^']*',[-\d.]+,[^,\]]+,[^,\]]+,'(\w+)'(?:,'([^']+)',[-\d.]+)?\]")
SUF = {'kospi': '.KS', 'kosdaq': '.KQ', 'nikkei': '.T'}
syms = {}
for t, g, under in ROW.findall(html):
    if under or g in ('bond', 'coin'):
        continue  # 레버리지·연동 ETF는 기초자산을 따라가고, 국채·코인은 따로 처리
    syms[t] = t + SUF[g] if g in SUF else t.replace('.', '-')
syms['_KRW'] = 'KRW=X'
syms['_JPY'] = 'JPY=X'


def get(t, y):
    for host in ('query1', 'query2'):
        try:
            req = urllib.request.Request(
                f'https://{host}.finance.yahoo.com/v8/finance/chart/{y}?range=1d&interval=1d',
                headers={'User-Agent': 'nasdaq-game-price-sync/1.0'})
            m = json.load(urllib.request.urlopen(req, timeout=15))['chart']['result'][0]['meta']
            p = m.get('regularMarketPrice')
            pc = m.get('chartPreviousClose') or m.get('previousClose')
            if p:
                return t, {'p': round(p, 4), 'pc': round(pc, 4) if pc else None, 't': m.get('regularMarketTime')}
        except Exception:
            time.sleep(1)
    return t, None


with cf.ThreadPoolExecutor(4) as ex:
    res = dict(ex.map(lambda kv: get(*kv), syms.items()))

quotes = {t: q for t, q in res.items() if q and not t.startswith('_')}
fx = {k[1:]: q['p'] for k, q in res.items() if q and k.startswith('_')}
print(f'{len(quotes)}/{len(syms) - 2} 종목, 환율 {fx}')
if len(quotes) < 20:
    raise SystemExit('받아온 종목이 너무 적어요 (접속이 막혔을 수 있어요)')

try:
    old = json.load(open('live.json', encoding='utf-8'))
except Exception:
    old = {}
if old.get('quotes') == quotes and old.get('fx') == fx:
    print('변동 없음')
    raise SystemExit(0)
json.dump({'updated': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'source': 'Yahoo Finance (지연 시세)', 'fx': fx, 'quotes': quotes},
          open('live.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
