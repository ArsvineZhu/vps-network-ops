#!/usr/bin/env python3
import os, pathlib, sqlite3, tempfile, unittest
from observed_usage import ingest as raw_ingest, private_db
def ingest(d,p,t='1'): return raw_ingest(d,p,t,'vless-in',{'friend1'},'vps1')
def snap(up=10,down=20,id='a'):
 return {'connections':[{'id':id,'metadata':{'inboundUser':'friend1','inboundName':'vless-in','destinationIP':'DO_NOT_STORE','host':'secret.invalid'},'upload':up,'download':down}]}
def total(d):return d.execute('select up,down from totals').fetchone()
class Usage(unittest.TestCase):
 def test_monotonic(self):
  d=sqlite3.connect(':memory:')
  for p in [snap(100,100),snap(50,50),snap(100,100),snap(50,120),snap(110,100)]:ingest(d,p)
  self.assertEqual(total(d),(110,120))
 def test_disappearance_replay(self):
  d=sqlite3.connect(':memory:')
  ingest(d,snap());ingest(d,{'connections':[]});ingest(d,snap());self.assertEqual(total(d),(10,20))
  self.assertNotIn('secret.invalid','\n'.join(d.iterdump()))
 def test_reopen_and_scope(self):
  with tempfile.TemporaryDirectory() as t:
   p=pathlib.Path(t)/'usage.db';d=private_db(p);ingest(d,snap());d.close()
   d=private_db(p);ingest(d,snap());self.assertEqual(total(d),(10,20))
   before='\n'.join(d.iterdump())
   for instance,inbound in [('vps2','vless-in'),('vps1','other')]:
    with self.assertRaises(ValueError):raw_ingest(d,snap(),'2',inbound,{'friend1'},instance)
    self.assertEqual(before,'\n'.join(d.iterdump()))
   d.close()
 def test_permissions(self):
  with tempfile.TemporaryDirectory() as t:
   p=pathlib.Path(t)/'u.db';p.touch();p.chmod(0o644)
   with self.assertRaises(ValueError):private_db(p)
   p.chmod(0o600);d=private_db(p);d.close()
   pathlib.Path(t).chmod(0o755)
   with self.assertRaises(ValueError):private_db(p)
   pathlib.Path(t).chmod(0o700)
 def test_unknown(self):
  d=sqlite3.connect(':memory:');p=snap();p['connections'][0]['metadata']['inboundName']='other'
  ingest(d,p)
  self.assertEqual(d.execute('select count(*) from totals').fetchone()[0],0)
  self.assertEqual(d.execute('select ignored from ignored_polls').fetchone()[0],1)
  p=snap();p['connections'][0]['metadata']['inboundUser']='unknown';ingest(d,p)
  self.assertEqual(d.execute('select count(*) from totals').fetchone()[0],0)
 def test_invalid_atomic(self):
  d=sqlite3.connect(':memory:');ingest(d,snap());before='\n'.join(d.iterdump())
  with self.assertRaises(ValueError):ingest(d,snap(-1,2))
  self.assertEqual(before,'\n'.join(d.iterdump()))
 def test_identity_reuse(self):
  d=sqlite3.connect(':memory:');ingest(d,snap());p=snap()
  p['connections'][0]['metadata']['inboundUser']='friend2'
  with self.assertRaises(ValueError):raw_ingest(d,p,'2','vless-in',{'friend1','friend2'},'vps1')
  self.assertEqual(total(d),(10,20))
if __name__=='__main__':unittest.main()
