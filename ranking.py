"""Explainable editorial estimates from titles; no claims of verified exclusivity."""
import re, datetime as dt, math

def rank_items(items, now):
 def words(title):
  title=re.sub(r'https?://\S+', '', title.lower())
  title=re.sub(r'grand theft auto|gta\s*(vi|6)', '', title)
  return set(re.findall(r'\w{3,}',title))-{'the','and','for','with','you','les','des','une','dans','how','that','this'}
 topics=[('Voitures / véhicules',r'\bcar[s]?\b|vehicle|voiture|véhicule|grotti|cheetah|infernus|banshee'),('Missions / histoire',r'mission|story|histoire|ending|prologue|chapter|chapitre'),('Secrets / découvertes',r'secret|easter egg|discover|découvr|found|découverte'),('Carte / lieux',r'\bmap\b|carte|location|lieu|house|maison|propert'),('Armes / combat',r'weapon|gun|arme|combat'),('PNJ / bugs / physique',r'npc|pnj|glitch|bug|physics|ragdoll'),('Personnages',r'jason|lucia|bautista|character|personnage')]
 for i in items:
  i['topics']=[name for name,pattern in topics if re.search(pattern,i['title'],re.I)] or ['Autres infos']
 tokens=[words(i['title']) for i in items]
 for n,i in enumerate(items):
  title=i['title'].lower(); reasons=[];mreasons=[]
  importance=25;meme=10
  for pattern,points,label in [
   (r'gameplay|mechanic|mécanique|mission|story|histoire|ending|prologue',30,'Gameplay ou histoire'),
   (r'launch|release|sortie|delay|reporté|trailer|bande.annonce|official|officiel|confirmed|confirmé',25,'Annonce ou changement majeur potentiel'),
   (r'map|carte|secret|discover|découvr|easter egg|first look|premier aperçu|reveal|révél',20,'Découverte potentielle'),
   (r'patch|performance|crash|broken|bug|fps|update',15,'Impact technique sur les joueurs'),
   (r'review|test\b|metacritic',10,'Évaluation du jeu')]:
   if re.search(pattern,title):importance+=points;reasons.append(label)
  if re.search(r'rumou?r|leak|fuite|alleged|pourrait|would|predict|speculat|wishlist|think|\?',title):
   importance-=15;reasons.append('Incertitude ou spéculation : −15')
  if re.search(r'pre.order|précommande|discount|deal|bonus|edition|skin|gta\+|membership',title):
   importance-=15;reasons.append('Promotion ou bonus : −15')
  if 'forum' in i['source'].lower():importance-=5;reasons.append('Discussion de forum : −5')
  for pattern,points,label in [
   (r'meme|funny|hilarious|absurd|ridiculous|wtf|drôle|absurde|insolite|chaos|cursed',35,'Humour ou absurdité explicite'),
   (r'glitch|bug|ragdoll|fail|physics|physique|npc|pnj',25,'Situation propice aux clips et détournements'),
   (r'florida|floride|alligator|crocodile|twerk|naked|\bnu\b|funeral|kfc',25,'Image ou situation insolite'),
   (r'jason|lucia|couple|romance|betray|trahi',15,'Personnages ou relations reconnaissables'),
   (r'clip|video|vidéo|screenshot|image|photo',10,'Support visuel mentionné'),
   (r'"|“|”|«|»',10,'Citation potentiellement détournable')]:
   if re.search(pattern,title):meme+=points;mreasons.append(label)
  similar=sum(1 for j,t in enumerate(tokens) if j!=n and tokens[n] and len(tokens[n]&t)/max(1,len(tokens[n]|t))>=.55)
  try:
   published=dt.datetime.fromisoformat(i['published'].replace('Z','+00:00'))
   if published.tzinfo is None:published=published.replace(tzinfo=dt.timezone.utc)
   age=max(0,(now-published.timestamp())/3600)
  except (ValueError,KeyError,AttributeError):age=None
  freshness=80 if age is not None and age<=1 else 60 if age is not None and age<=6 else 35 if age is not None and age<=24 else 10
  novelty=max(0,freshness-min(60,similar*20))
  importance=max(0,min(100,importance));meme=max(0,min(100,meme))
  related=[j for j,t in enumerate(tokens) if j!=n and len(tokens[n]&t)>=3 and len(tokens[n]&t)/max(1,len(tokens[n]|t))>=.35]
  i['repeat_count']=len(related)+1
  i['repeat_sources']=len({items[j].get('author') or items[j]['source'] for j in related+[n]})
  likes=i.get('likes');views=i.get('views');reposts=i.get('reposts')
  engagement=None if likes is None and views is None else min(100,round(10*math.log10(1+(views or 0))+15*math.log10(1+(likes or 0))+10*math.log10(1+(reposts or 0))))
  i['engagement_score']=engagement
  i['trend_score']=round((engagement or 0)*.6+importance*.25+min(100,len(related)*20)*.15)
  i.update(importance_score=importance,exclusivity_score=novelty,news_score=round(.75*importance+.25*novelty),meme_score=meme,
   news_reasons=reasons or ['Pas de signal majeur détecté dans le titre'],
   meme_reasons=mreasons or ['Pas de signal fort de détournement dans le titre'],
   exclusivity_reason=f'{similar} titre(s) proche(s) dans le radar ; '+('date inconnue' if age is None else f'publication il y a {round(age,1)} h'))
 return items


def build_signals(items, now):
 """Group recent similar wording; measure separate accounts, never assert truth."""
 def stamp(i):
  try:
   t=dt.datetime.fromisoformat(i['published'].replace('Z','+00:00'))
   return (t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)).timestamp()
  except (ValueError,KeyError,AttributeError):return None
 def identity(i):
  from urllib.parse import urlparse
  return ('x:'+str(i.get('author') or i['source'])) if i['source'].startswith('X ') else urlparse(i['url']).hostname
 def tokens(i):
  s=re.sub(r'https?://\S+|grand theft auto|gta\s*(?:vi|6)|#\w+', ' ',i['title'].lower())
  return set(re.findall(r'\w{3,}',s))-{'the','and','for','this','that','with','you','are','was','has','from','new','les','des','une','dans','pour','sur','est','qui','game','gameplay','video','vidéo'}
 groups=[]
 for i in sorted(items,key=lambda x:x.get('engagement_score') or 0,reverse=True):
  title=i['title'].lower()
  speculative=bool(re.search(r'rumou?r|speculat|theor|théor|rumeur|alleged|leak|fuit|might|could|would|wishlist|predict|guess|pourrait|suppos|\?',title))
  i['discovery_kind']='Spéculation / fuite non confirmée' if speculative else 'Nouveauté / information rapportée'
  i['signal_id']=None
  t=stamp(i)
  if t is None or t<now-6*3600 or t>now+300:continue
  tok=tokens(i)
  if len(tok)<3:continue
  match=None
  for g in groups:
   overlap=len(tok&g['_tokens'])
   if overlap>=3 and overlap/max(1,len(tok|g['_tokens']))>=.32:match=g;break
  if match is None:
   match={'id':i['id'],'title':i['title'],'items':[],'_tokens':tok};groups.append(match)
  match['items'].append(i);i['signal_id']=match['id']
 result=[]
 for g in groups:
  rows=g['items'];identities={identity(i) for i in rows};recent=[i for i in rows if stamp(i)>=now-1800];previous=[i for i in rows if now-3600<=stamp(i)<now-1800]
  views=[i['views'] for i in rows if i.get('views') is not None];likes=[i['likes'] for i in rows if i.get('likes') is not None]
  result.append({'id':g['id'],'title':g['title'],'posts':len(rows),'sources':len(identities),'accounts':len({identity(i) for i in rows if i['source'].startswith('X ')}),'recent':len(recent),'previous':len(previous),'max_views':max(views) if views else None,'max_likes':max(likes) if likes else None,'speculative':any(i['discovery_kind'].startswith('Spéculation') for i in rows),'status':'Signal multi-sources' if len(identities)>=3 else 'À surveiller','score':round(40*min(1,len(identities)/5)+30*min(1,len(recent)/5)+.3*max((i.get('engagement_score') or 0) for i in rows))})
 return sorted(result,key=lambda g:(g['score'],g['sources']),reverse=True)[:50]
