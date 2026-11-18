import os,sys,tempfile,unittest,json,time
from unittest.mock import patch
os.environ['GTA_RADAR_DATA']=tempfile.mkdtemp()
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]))
import runner as r
class Response:
 def __init__(self,data):self.data=data
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def read(self,*args):return json.dumps(self.data).encode()
class Tests(unittest.TestCase):
 def setUp(self):
  r.STOP.clear();r.init();r.setmeta('deadline',time.time()+100);r.setmeta('stopped','0');r.setmeta('x_reserved',0);r.KEY.write_text('x'*50)
  for key in ['x_next','x_since','x_pending_newest']:r.setmeta(key,'')
 def test_restart_keeps_deadline(self):
  d=r.meta('deadline');r.init();self.assertEqual(d,r.meta('deadline'))
 def test_expiry_and_budget_prevent_network(self):
  with patch.object(r,'urlopen') as net:
   r.setmeta('deadline',time.time()-1);r.x_poll();net.assert_not_called()
   r.setmeta('deadline',time.time()+100);r.setmeta('x_reserved',895);r.x_poll();net.assert_not_called()
 def test_pages_and_reservations(self):
  pages=[{'data':[{'id':'20','text':'GTA VI','author_id':'1'}],'meta':{'next_token':'page2'}},{'data':[{'id':'19','text':'GTA 6','author_id':'1'}],'meta':{}}]
  with patch.object(r,'urlopen',side_effect=[Response(x) for x in pages]):
   r.x_poll();self.assertEqual(r.meta('x_since'),'');self.assertEqual(r.meta('x_next'),'page2')
   r.x_poll();self.assertEqual(r.meta('x_since'),'20');self.assertEqual(r.meta('x_next'),'');self.assertEqual(r.meta('x_reserved'),'2')
 def test_dedup_and_safe_urls(self):
  self.assertTrue(r.put('GTA VI','https://example.org/test?utm_source=x','Test'))
  self.assertFalse(r.put('GTA VI','https://example.org/test','Test'))
  self.assertFalse(r.put('Bad','javascript:alert(1)','Test'))
 def test_failed_request_keeps_reservation(self):
  with patch.object(r,'urlopen',side_effect=TimeoutError()):r.x_poll()
  self.assertEqual(r.meta('x_reserved'),'10')
if __name__ == "__main__": unittest.main()
