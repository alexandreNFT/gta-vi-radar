"""72-hour GTA information collector. Standard library, loopback UI, bounded X reads."""
import concurrent.futures, datetime as dt, email.utils, hashlib, html, json, os, re, secrets, signal, socketserver, sqlite3, threading, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse
import xml.etree.ElementTree as ET
from ranking import rank_items, build_signals
from contextlib import contextmanager
from localization import localize

ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('GTA_RADAR_DATA',ROOT/'data')); DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/'radar.sqlite3'; KEY=DATA/'x_bearer'; STOP=threading.Event(); PORT=8768
FEEDS=[
 ('RockstarINTEL','https://rockstarintel.com/feed/',False),
 ('GTABase','https://www.gtabase.com/news?format=feed&type=rss',False),
 ('VGC','https://www.videogameschronicle.com/feed/',False),
 ('GamesRadar','https://www.gamesradar.com/feeds/all/',False),
 ('Eurogamer','https://www.eurogamer.net/feed',False),
 ('IGN','https://www.ign.com/rss/articles/feed',False),
 ('PC Gamer','https://www.pcgamer.com/feeds/all/',False),
 ('GTANF','https://www.gtanf.com/forums/forum/269-gta-6.xml',True),
 ('GTAForums','https://gtaforums.com/forum/396-gta-vi.xml/',True),
 ('GTANet forum','https://gtaforums.com/rss/4-gtanetcom.xml/',False),
]
GTA=re.compile(r'\b(?:gta\s*(?:vi|6)|grand theft auto\s*(?:vi|6)|leonida|lucia caminos|jason duval)\b',re.I)
QUERY='("GTA VI" OR "GTA 6" OR GTAVI OR GTA6 OR "Grand Theft Auto VI") (new OR discover OR found OR reveal OR gameplay OR car OR vehicle OR mission OR secret OR weapon OR map OR npc OR glitch OR detail OR nouveau OR nouvelle OR voiture OR mission OR découverte OR easter OR rumor OR rumour OR speculation OR theory OR leak OR rumeur OR théorie OR rifle OR pistol OR fusil OR bike OR grotti OR banshee) -is:retweet -is:reply -crypto -memecoin -airdrop -giveaway'
# Reserve a maximum 10 post reads before every request, including failures.
X_LIMIT=900
CSRF=secrets.token_urlsafe(32)

@contextmanager
def conn():
 c=sqlite3.connect(DB,timeout=15);c.row_factory=sqlite3.Row
 try:
  with c:yield c
 finally:c.close()

def init():
 with conn() as c:
  c.executescript('''PRAGMA journal_mode=WAL;
  CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY,v TEXT);
  CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY,title TEXT,url TEXT,source TEXT,published TEXT,first_seen REAL,last_seen REAL,category TEXT,spoiler TEXT,confidence TEXT,priority INTEGER,excerpt TEXT);
  CREATE TABLE IF NOT EXISTS health(source TEXT PRIMARY KEY,last_attempt REAL,last_success REAL,state TEXT,detail TEXT,count INTEGER);
  CREATE TABLE IF NOT EXISTS x_metrics(id TEXT PRIMARY KEY,likes INTEGER,views INTEGER,reposts INTEGER,replies INTEGER,measured REAL,author TEXT);
  CREATE TABLE IF NOT EXISTS feed_cache(url TEXT PRIMARY KEY,etag TEXT,modified TEXT);
  ''')
  c.execute('INSERT OR IGNORE INTO meta VALUES (?,?)',('started',str(time.time())))
  start=float(c.execute('SELECT v FROM meta WHERE k="started"').fetchone()[0])
  c.execute('INSERT OR IGNORE INTO meta VALUES (?,?)',('deadline',str(start+72*3600)))
  c.execute('INSERT OR IGNORE INTO meta VALUES (?,?)',('x_reserved','0'))

def meta(k,default=''):
 with conn() as c:
  r=c.execute('SELECT v FROM meta WHERE k=?',(k,)).fetchone();return r[0] if r else default

def setmeta(k,v):
 with conn() as c:c.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',(k,str(v)))

def active():return not STOP.is_set() and time.time()<float(meta('deadline','0')) and meta('stopped')!='1'

def health(source,state,detail='',count=0):
 with conn() as c:
  old=c.execute('SELECT last_success FROM health WHERE source=?',(source,)).fetchone()
  success=time.time() if state=='ok' else (old[0] if old else None)
  c.execute('INSERT OR REPLACE INTO health VALUES (?,?,?,?,?,?)',(source,time.time(),success,state,detail[:300],count))

def classify(title):
 s=title.lower()
 category='Information';spoiler='Possible';priority=40
 if re.search(r'ending|final mission|plot twist|betray|ending|fin du jeu|mort de',s):category='Histoire';spoiler='Majeur';priority=90
 elif re.search(r'cutscene|mission|prologue|story|histoire|personnage',s):category='Histoire';spoiler='Histoire';priority=75
 elif re.search(r'gameplay|mechanic|easter egg|secret|weapon|vehicle|car |map|carte|armes|véhicule|détail',s):category='Découverte';spoiler='Gameplay';priority=70
 elif re.search(r'patch|update|release|trailer|announc|sortie|mise à jour',s):category='Annonce';spoiler='Aucun détecté';priority=65
 elif re.search(r'review|test |metacritic|rating',s):category='Critique';priority=50
 confidence='Rapporté / non vérifié'
 if re.search(r'rumou?r|alleged|leak|fuit[eé]|reportedly|potential|would|pourrait|speculat|wishlist|predict|guess',s):confidence='Non confirmé'
 if re.search(r'fake|debunk|false|faux|dément',s):confidence='Contesté';priority=80
 if '[spoilers]' in s:spoiler='Signalé par la source'
 if '[no spoilers]' in s or '[no story spoilers]' in s:spoiler='Sans spoiler selon la source'
 return category,spoiler,confidence,priority

def canon(url):
 p=urlparse(url)
 if p.scheme not in ('http','https') or not p.hostname:return ''
 # Keep forum comment identifiers; strip only tracking query parameters.
 q={k:v for k,v in parse_qs(p.query).items() if not k.lower().startswith('utm_') and k not in ('at_medium','at_campaign')}
 return urlunparse((p.scheme,p.netloc,p.path,'',urlencode(q,doseq=True),''))

def put(title,url,source,published='',excerpt='',native_id=None):
 url=canon(url)
 if not url:return False
 ident=native_id or hashlib.sha256(url.encode()).hexdigest()
 category,spoiler,confidence,priority=classify(title)
 if source=='X @RockstarGames':confidence='Source officielle';priority=max(priority,85)
 now=time.time()
 with conn() as c:
  old=c.execute('SELECT title FROM items WHERE id=?',(ident,)).fetchone()
  if old:
   c.execute('UPDATE items SET title=?,last_seen=?,category=?,spoiler=?,confidence=?,priority=?,excerpt=? WHERE id=?',(title,now,category,spoiler,confidence,priority,excerpt,ident))
  else:c.execute('INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(ident,title[:1000],url,source,published,now,now,category,spoiler,confidence,priority,excerpt[:1600]))
 return old is None

def dateparse(value):
 try:return email.utils.parsedate_to_datetime(value).isoformat()
 except (ValueError,TypeError):
  try:return dt.datetime.fromisoformat(value.replace('Z','+00:00')).isoformat()
  except (ValueError,TypeError,AttributeError):return ''

def fetch_feed(entry):
 if not active():return
 name,url,dedicated=entry
 headers={'User-Agent':'GTA72Research/1.0','Accept':'application/rss+xml, application/atom+xml, application/xml'}
 with conn() as c: cached=c.execute('SELECT * FROM feed_cache WHERE url=?',(url,)).fetchone()
 if cached:
  if cached['etag']:headers['If-None-Match']=cached['etag']
  if cached['modified']:headers['If-Modified-Since']=cached['modified']
 try:
  with urlopen(Request(url,headers=headers),timeout=12) as r:
   payload=r.read(2500001)
   if len(payload)>2500000:raise ValueError('Flux trop volumineux')
   etag=r.headers.get('ETag');modified=r.headers.get('Last-Modified')
  root=ET.fromstring(payload);count=0
  for e in root.iter():
   if e.tag.split('}')[-1] not in ('item','entry'):continue
   fields={n.tag.split('}')[-1]:n for n in e}
   def val(k):return ''.join(fields[k].itertext()).strip() if k in fields else ''
   title=val('title');link=val('link') or (fields['link'].get('href','') if 'link' in fields else '')
   if not title or (not dedicated and not GTA.search(title)):continue
   published=dateparse(val('pubDate') or val('published') or val('updated'))
   # Topic RSS is retained regardless of age: replies may be current.
   if published and not dedicated:
    d=dt.datetime.fromisoformat(published)
    if d.tzinfo is None:d=d.replace(tzinfo=dt.timezone.utc)
    if d.timestamp()<time.time()-7*86400 or d.timestamp()>time.time()+3600:continue
   if not active():return
   summary=html.unescape(re.sub(r'<[^>]+>',' ',val('description') or val('summary')))
   summary=' '.join(summary.split())[:700]
   count+=int(put(title,link,name,published,summary))
  with conn() as c:c.execute('INSERT OR REPLACE INTO feed_cache VALUES (?,?,?)',(url,etag,modified))
  health(name,'ok','Flux interrogé ; dates de sujet pour les forums',count)
 except HTTPError as e:
  if e.code==304:health(name,'ok','Inchangé (304)')
  else:health(name,'error',f'HTTP {e.code}')
 except Exception as e:health(name,'error',type(e).__name__+': '+str(e)[:150])

def x_poll():
 if not KEY.exists():health('X API','waiting','Clé API non configurée');return
 if not active():return
 reserved=int(meta('x_reserved','0'))
 batch=min(int(meta('x_batch','10')),X_LIMIT-reserved)
 if batch<10:health('X API','budget','Plafond local atteint (900 lectures réservées maximum)');return
 # Reserve before the request; never retry an uncertain charged request for free.
 setmeta('x_reserved',reserved+batch)
 params={'query':QUERY,'max_results':batch,'tweet.fields':'created_at,author_id,public_metrics','sort_order':'recency'}
 page=meta('x_next');since=meta('x_since')
 if page:params['next_token']=page
 if since:params['since_id']=since
 else:params['start_time']=meta('x_start') or dt.datetime.fromtimestamp(time.time()-900,dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
 if not since and not meta('x_start'):setmeta('x_start',params['start_time'])
 try:
  token=KEY.read_text().strip()
  req=Request('https://api.x.com/2/tweets/search/recent?'+urlencode(params),headers={'Authorization':'Bearer '+token,'User-Agent':'GTA72Research/1.0'})
  with urlopen(req,timeout=15) as r:data=json.loads(r.read(2000000))
  posts=data.get('data',[])
  # Successful empty reads cost no post credits; reserve only returned resources.
  setmeta('x_reserved',reserved+len(posts))
  setmeta('x_batch',10)
  newest=meta('x_pending_newest')
  for p in posts:
   pid=str(p['id']);newest=str(max(int(newest or '0'),int(pid)))
   put(html.unescape(p.get('text','')),'https://x.com/i/status/'+pid,'X — auteur '+p.get('author_id',''),p.get('created_at',''),native_id='x:'+pid)
   m=p.get('public_metrics',{})
   with conn() as c:c.execute('INSERT OR REPLACE INTO x_metrics VALUES (?,?,?,?,?,?,?)',('x:'+pid,m.get('like_count'),m.get('impression_count'),m.get('retweet_count'),m.get('reply_count'),time.time(),p.get('author_id','')))
  setmeta('x_pending_newest',newest)
  next_token=data.get('meta',{}).get('next_token','')
  setmeta('x_next',next_token)
  if not next_token and newest:
   setmeta('x_since',newest);setmeta('x_pending_newest','')
  health('X API','ok',f'{len(posts)} posts reçus ; recherche ouverte GTA VI toutes les 15 s',len(posts))
 except HTTPError as e:
  detail=e.read(2000).decode('utf-8','replace').replace(token,'[redacted]')
  health('X API','error',f'HTTP {e.code}: '+detail[:230])
  # Avoid consuming reservations continuously on account errors.
  if e.code in (401,402,403):setmeta('x_retry_after',time.time()+600)
  elif e.code==429:setmeta('x_retry_after',time.time()+max(60,min(900,int(e.headers.get('Retry-After','60')))))
 except Exception as e:health('X API','error',type(e).__name__)

def feed_loop():
 with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
  while active():
   list(pool.map(fetch_feed,FEEDS))
   STOP.wait(min(60,max(0,float(meta('deadline'))-time.time())))

def collector():
 threading.Thread(target=feed_loop,daemon=True).start()
 next_x=0
 while active():
  if time.time()>=next_x and time.time()>=float(meta('x_retry_after','0')):
   x_poll();next_x=time.time()+15
  setmeta('heartbeat',time.time());STOP.wait(1)
 health('Collecteur','stopped','Échéance de 72 h atteinte ou arrêt manuel')

def snapshot():
 with conn() as c:
  items=[dict(r) for r in c.execute('SELECT items.*,x_metrics.likes,x_metrics.views,x_metrics.reposts,x_metrics.replies,x_metrics.measured,x_metrics.author FROM items LEFT JOIN x_metrics ON items.id=x_metrics.id ORDER BY first_seen DESC LIMIT 5000')]
  h=[dict(r) for r in c.execute('SELECT * FROM health ORDER BY source')]
 ranked=rank_items(items,time.time())
 return {'items':ranked,'signals':build_signals(ranked,time.time()),'sources':h,'deadline':float(meta('deadline')),'started':float(meta('started')),'active':active(),'heartbeat':float(meta('heartbeat','0')),'x_reserved':int(meta('x_reserved','0')),'x_key_present':KEY.exists()}

class Server(ThreadingHTTPServer):
 def server_bind(self):socketserver.TCPServer.server_bind(self);self.server_name='localhost';self.server_port=self.server_address[1]
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def send(self,status,body,ctype='text/html; charset=utf-8'):
  self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'");self.end_headers();self.wfile.write(body)
 def host_ok(self):return self.headers.get('Host') in (f'127.0.0.1:{PORT}',f'localhost:{PORT}')
 def do_GET(self):
  if not self.host_ok():return self.send(403,b'Forbidden')
  if self.path=='/api/state':return self.send(200,json.dumps(localize(snapshot())).encode(),'application/json')
  if self.path=='/':return self.send(200,(ROOT/'index.html').read_text().replace('__CSRF__',CSRF).encode())
  self.send(404,b'Not found')
 def do_POST(self):
  if not self.host_ok() or self.headers.get('Origin') not in (f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'):return self.send(403,b'Forbidden')
  try:
   length=int(self.headers.get('Content-Length','0'))
   if length>12000:return self.send(413,b'Too large')
   form=parse_qs(self.rfile.read(length).decode())
   if not secrets.compare_digest(form.get('csrf',[''])[0],CSRF):return self.send(403,b'Forbidden')
   if self.path=='/key':
    key=form.get('key',[''])[0].strip()
    if not re.fullmatch(r'[A-Za-z0-9%_~+./=-]{30,2000}',key):return self.send(400,b'Invalid key')
    fd=os.open(KEY,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:f.write(key)
    os.chmod(KEY,0o600);setmeta('x_retry_after','0')
   elif self.path=='/stop':setmeta('stopped','1');STOP.set()
   else:return self.send(404,b'Not found')
   self.send_response(303);self.send_header('Location','/');self.end_headers()
  except (ValueError,UnicodeError):self.send(400,b'Invalid request')

def main():
 init()
 # Prevent duplicate billing/collection processes.
 import fcntl
 lock=(DATA/'process.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 threading.Thread(target=collector,daemon=True).start()
 server=Server(('127.0.0.1',PORT),Handler)
 def terminate(*_):
  STOP.set();threading.Thread(target=server.shutdown,daemon=True).start()
 signal.signal(signal.SIGTERM,terminate)
 print(f'GTA radar: http://127.0.0.1:{PORT}/ ; deadline {meta("deadline")}',flush=True)
 server.serve_forever()
if __name__=='__main__':main()
