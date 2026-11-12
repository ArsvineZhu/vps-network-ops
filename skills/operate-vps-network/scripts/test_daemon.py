import datetime,http.server,json,os,pathlib,socketserver,sqlite3,subprocess,sys,tempfile,threading,unittest
from unittest.mock import patch
import observed_usage as o
import usage_daemon as d

def config():return {'socket':d.SOCKET,'db':d.DB,'inbound':'reality','instance':'vps1','users':['owner','friend01'],'interval':5}
def snapshot(user='friend01',up=10,down=20):return {'connections':[{'id':'connection-id','metadata':{'inboundName':'reality','inboundUser':user,'host':'PRIVATE-DOMAIN.invalid','destinationIP':'198.51.100.123'},'upload':up,'download':down}]}
class Tests(unittest.TestCase):
 def test_null_official_idle_and_bad_missing(self):
  db=sqlite3.connect(':memory:');o.ingest(db,{'connections':None},d.stamp(),'reality',{'owner'},'vps1')
  self.assertEqual(db.execute('SELECT state,active FROM polls').fetchone(),('observed',0))
  for x in ({},{'connections':{}},None):
   with self.assertRaises(ValueError):o.ingest(db,x,d.stamp(),'reality',{'owner'},'vps1')
 def test_first_cli_failure_records_gap(self):
  with tempfile.TemporaryDirectory() as td:
   p=pathlib.Path(td);(p/'users.json').write_text('["owner"]')
   r=subprocess.run([sys.executable,str(pathlib.Path(o.__file__)),'--db',str(p/'usage.sqlite'),'--unix-socket',str(p/'missing.sock'),'--inbound','reality','--instance','vps1','--users-file',str(p/'users.json')],capture_output=True,text=True)
   self.assertEqual(r.returncode,1)
   db=sqlite3.connect(p/'usage.sqlite');self.assertEqual(db.execute('SELECT state FROM polls').fetchall(),[('gap/error',)]);db.close()
 def test_initial_failure_and_resume(self):
  db=sqlite3.connect(':memory:');c=config()
  self.assertFalse(d.sample(db,c,lambda:(_ for _ in ()).throw(ConnectionError('SECRET')),d.stamp()))
  self.assertTrue(d.sample(db,c,lambda:snapshot(),d.stamp()))
  self.assertEqual(db.execute('SELECT state FROM polls').fetchall(),[('gap/error',),('observed',)])
  dump='\n'.join(db.iterdump());self.assertNotIn('PRIVATE-DOMAIN',dump);self.assertNotIn('198.51.100.123',dump);self.assertNotIn('SECRET',dump)
 def test_restarts_deduplicate_and_status(self):
  db=sqlite3.connect(':memory:');c=config();event=threading.Event();messages=[]
  c['interval']=0.001
  def fetch():event.set();return snapshot()
  d.loop(db,c,event,fetch,messages.append)
  event.clear();d.loop(db,c,event,fetch,messages.append)
  self.assertEqual(db.execute('SELECT up,down FROM totals').fetchone(),(10,20))
  states=[r[0] for r in db.execute('SELECT state FROM polls')]
  self.assertEqual(states,['startup/gap','observed','stopped']*2)
  result=d.report(db,c);self.assertFalse(result['fresh']);self.assertIsNone(result['users'][1]['active_connections'])
 def test_stale_and_fresh_report(self):
  db=sqlite3.connect(':memory:');c=config();o.ingest(db,snapshot(),'2000-01-01T00:00:00+00:00','reality',set(c['users']),'vps1')
  self.assertFalse(d.report(db,c)['fresh'])
  o.ingest(db,snapshot(),d.stamp(),'reality',set(c['users']),'vps1')
  self.assertTrue(d.report(db,c)['fresh'])
  self.assertFalse(d.report(db,c)['users'][0]['ever_observed'])
 def test_scope_and_intervals(self):
  d.validate_config(config())
  for value in (0,11,True,'5'):
   c=config();c['interval']=value
   with self.assertRaises(ValueError):d.validate_config(c)
  c=config();c['socket']='/tmp/open.sock'
  with self.assertRaises(ValueError):d.validate_config(c)
 def test_private_socket_get_only(self):
  seen=[]
  class Handler(http.server.BaseHTTPRequestHandler):
   def do_GET(self):
    seen.append((self.command,self.path));body=json.dumps(snapshot()).encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
   def log_message(self,*args):pass
  with tempfile.TemporaryDirectory() as td:
   path=pathlib.Path(td)/'control.sock'
   try:server=socketserver.UnixStreamServer(str(path),Handler)
   except PermissionError:self.skipTest('executor disallows AF_UNIX fixture creation; transport requires VPS verification')
   os.chmod(path,0o666)
   thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    self.assertEqual(d.fetch(str(path))['connections'][0]['upload'],10)
    self.assertEqual(seen,[('GET','/connections')])
    os.chmod(td,0o755)
    with self.assertRaises(ValueError):d.fetch(str(path))
   finally:os.chmod(td,0o700);server.shutdown();server.server_close();thread.join()
 def test_fetch_get_only_mocked_transport(self):
  seen=[]
  class Connection:
   def __init__(self,path):self.path=path
   def request(self,method,target):seen.append((method,target))
   def getresponse(self):return type('Response',(),{'status':200,'read':lambda self,limit:json.dumps(snapshot()).encode()})()
   def close(self):seen.append(('closed',None))
  with patch.object(d,'check_socket'),patch.object(d,'UnixHTTP',Connection):
   self.assertEqual(d.fetch('/synthetic/socket')['connections'][0]['upload'],10)
  self.assertEqual(seen,[('GET','/connections'),('closed',None)])
 def test_socket_boundary_mode_and_symlink(self):
  with tempfile.TemporaryDirectory() as td:
   root=pathlib.Path(td);private=root/'private';private.mkdir(mode=0o700)
   d.check_socket(private/'sock',check_file=False)
   private.chmod(0o755)
   with self.assertRaises(ValueError):d.check_socket(private/'sock',check_file=False)
   private.chmod(0o700);link=root/'link';link.symlink_to(private,target_is_directory=True)
   with self.assertRaises(ValueError):d.check_socket(link/'sock',check_file=False)
 def test_storage_limit_stops_without_deleting(self):
  db=sqlite3.connect(':memory:');c=config()
  with patch.object(d,'MAX_DATABASE',1):
   with self.assertRaises(ValueError):d.loop(db,c,threading.Event(),lambda:snapshot(),lambda msg:None)
  self.assertEqual(db.execute('SELECT state FROM polls').fetchall(),[('startup/gap',)])
if __name__=='__main__':unittest.main(verbosity=2)
