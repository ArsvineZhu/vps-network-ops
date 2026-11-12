#!/usr/bin/env python3
"""Offline member bundle. Does NOT register/revoke a server user or publish a subscription."""
import argparse, json, os, uuid
from pathlib import Path
from clash_profile import generate, enrich
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('public_template',type=Path,help='JSON server/port/servername/public_key/short_id, optional fingerprint; NO UUID/private key')
    p.add_argument('member',help='unique local label, not a real name')
    p.add_argument('output',type=Path,help='new private directory')
    p.add_argument('--rules',choices=['all-proxy','categorized'],default='all-proxy')
    a=p.parse_args()
    try:
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',a.member): raise ValueError()
        d=json.loads(a.public_template.read_text(encoding='utf-8-sig'))
        if set(d)-{'server','port','servername','public_key','short_id','fingerprint'}: raise ValueError()
        ident=str(uuid.uuid4()); d.update(uuid=ident,name=a.member)
        profile=generate(d)
        if a.rules=='categorized': profile=enrich(profile)
        a.output.mkdir(mode=0o700,parents=False,exist_ok=False)
        # Ignore before writing credentials, including when output is inside a repository.
        fd=os.open(a.output/'.gitignore',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f: f.write('*\n')
        files={
          'profile.yaml':profile,
          'provider.yaml':{'proxies':profile['proxies']},
          'server-user.pending.json':{'username':a.member,'uuid':ident,'flow':'xtls-rprx-vision'},
          'record.json':{'member':a.member,'uuid':ident,'status':'pending-server-registration','revoke':'Remove matching UUID from correct VLESS listener users, validate, reload, test denial; deleting client files is not revocation.'}
        }
        for name,data in files.items():
            fd=os.open(a.output/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(data,f,ensure_ascii=False,indent=2)
    except (OSError,ValueError,TypeError,KeyError):
        p.exit(1,'Failed. Check template schema, label and new output directory; partial private files may remain.\n')
    print('Private bundle created. PENDING: register server-user.pending.json in the intended listener users, validate and restart before sharing. No server changes or publication performed.')
    if os.name=='nt': print('Protect output directory with Windows ACLs before use; POSIX modes are not Windows access controls.')
if __name__=='__main__': main()
