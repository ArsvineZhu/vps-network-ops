#!/usr/bin/env python3
"""Offline tests with synthetic credentials; never access a server."""
import importlib.util, pathlib, tempfile, subprocess, sys, json, unittest, shutil
HERE=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('profile',HERE/'clash_profile.py'); m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Tests(unittest.TestCase):
 def node(self): return dict(server='example.invalid',port=8443,uuid='11111111-1111-4111-8111-111111111111',servername='example.com',public_key='A'*43,short_id='aabb')
 def test_profile(self):
  p=m.generate(self.node());self.assertEqual(p['proxies'][0]['port'],8443); self.assertFalse(p['tun']['enable']);self.assertEqual(p['rules'],['MATCH,VPS-Select'])
 def test_invalid(self):
  for k,v in [('port',True),('port',0),('short_id','abc'),('server','a\nb'),('public_key','secret'),('uuid','bad'),('uuid',123),('name','Route-GitHub'),('name','DIRECT')]:
   d=self.node();d[k]=v
   with self.subTest(k=k,v=v), self.assertRaises((ValueError,TypeError)): m.generate(d)
 def test_private_key_rejected(self):
  d=self.node();d['private_key']='DO-NOT-PRINT'
  with self.assertRaises(ValueError):m.generate(d)
 def test_cli_no_overwrite_or_secret_stdout(self):
  with tempfile.TemporaryDirectory() as t:
   d=pathlib.Path(t)/'input.json';o=pathlib.Path(t)/'profile.yaml';d.write_text(json.dumps(self.node()))
   cmd=[sys.executable,str(HERE/'clash_profile.py'),str(d),str(o)]
   r=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(r.returncode,0);self.assertNotIn(self.node()['uuid'],r.stdout+r.stderr)
   r=subprocess.run(cmd,capture_output=True,text=True);self.assertNotEqual(r.returncode,0)
 def test_provider(self):
  with tempfile.TemporaryDirectory() as t:
   d=pathlib.Path(t)/'input.json';o=pathlib.Path(t)/'provider.yaml';d.write_text(json.dumps(self.node()))
   subprocess.run([sys.executable,str(HERE/'clash_profile.py'),str(d),str(o),'--kind','provider'],check=True,capture_output=True)
   self.assertEqual(set(json.loads(o.read_text())),{'proxies'})
 def test_categories(self):
  p=m.enrich(m.generate(self.node()))
  self.assertLess(p['rules'].index('RULE-SET,youtube,Route-YouTube'),p['rules'].index('RULE-SET,google,Route-Google'))
  names=[n['name'] for n in p['proxies']+p['proxy-groups']]
  self.assertEqual(len(names),len(set(names)))
  self.assertTrue(all(g['proxies'][0]=='VPS-Select' for g in p['proxy-groups'][1:]))
 def test_members(self):
  with tempfile.TemporaryDirectory() as t:
   base=pathlib.Path(t);d=self.node();d.pop('uuid');src=base/'template.json';src.write_text(json.dumps(d))
   ids=[]
   for label in ['friend1','friend2']:
    out=base/label
    subprocess.run([sys.executable,str(HERE/'new_member.py'),str(src),label,str(out)],check=True,capture_output=True)
    self.assertEqual((out/'.gitignore').read_bytes(),b'*\n')
    server=json.loads((out/'server-user.pending.json').read_text())
    self.assertEqual(set(server),{'username','uuid','flow'})
    self.assertEqual(server['username'],label);ids.append(server['uuid'])
    profile=json.loads((out/'profile.yaml').read_text())
    self.assertEqual(profile['proxies'][0]['uuid'],server['uuid'])
   self.assertNotEqual(*ids)
 def test_member_bundle_ignored_by_git(self):
  if not shutil.which('git'): self.skipTest('git unavailable')
  with tempfile.TemporaryDirectory() as t:
   base=pathlib.Path(t);d=self.node();d.pop('uuid');src=base/'template.json';src.write_text(json.dumps(d))
   subprocess.run(['git','init','-q',str(base)],check=True,capture_output=True)
   out=base/'friend'
   subprocess.run([sys.executable,str(HERE/'new_member.py'),str(src),'friend',str(out)],check=True,capture_output=True)
   for file in out.iterdir():
    r=subprocess.run(['git','-C',str(base),'check-ignore','--quiet',str(file)],capture_output=True)
    self.assertEqual(r.returncode,0,file.name)
   r=subprocess.run([sys.executable,str(HERE/'new_member.py'),str(src),'friend',str(out)],capture_output=True)
   self.assertNotEqual(r.returncode,0)
   self.assertEqual((out/'.gitignore').read_bytes(),b'*\n')
if __name__=='__main__': unittest.main()
