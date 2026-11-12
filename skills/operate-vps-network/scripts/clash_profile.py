#!/usr/bin/env python3
"""Generate a local Mihomo profile from a private JSON node descriptor. Fixed VLESS TCP REALITY xtls-rprx-vision; no networking."""
import argparse, base64, ipaddress, json, os, re, uuid
from pathlib import Path


def generate(d):
    required = {'server', 'port', 'uuid', 'servername', 'public_key', 'short_id'}
    if not isinstance(d, dict) or not required <= d.keys():
        raise ValueError('missing required descriptor fields')
    if set(d) - required - {'name', 'fingerprint'}:
        raise ValueError('unknown descriptor fields (never supply server private keys)')
    if not isinstance(d['port'], int) or isinstance(d['port'], bool) or not 1 <= d['port'] <= 65535:
        raise ValueError('port must be 1..65535')
    def host(s):
        if not isinstance(s, str) or not s or len(s)>253: return False
        try: ipaddress.ip_address(s); return True
        except ValueError: return all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', p) for p in s.split('.'))
    if not host(d['server']) or not host(d['servername']): raise ValueError('invalid server or servername')
    if not isinstance(d['uuid'], str): raise ValueError('uuid must be text')
    ident = str(uuid.UUID(d['uuid']))
    key = d['public_key']
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',key) or len(base64.urlsafe_b64decode(key+'=')) != 32:
        raise ValueError('public_key must be a 32-byte base64url public key')
    sid=d['short_id']
    if not isinstance(sid,str) or not re.fullmatch(r'(?:[0-9a-fA-F]{2}){0,8}',sid): raise ValueError('short_id must be even-length hex, at most 16 digits')
    name=d.get('name','Private-VPS')
    if not isinstance(name,str) or not name.strip() or len(name)>80 or any(ord(c)<32 for c in name) or name.startswith('Route-') or name in {'DIRECT','REJECT','GLOBAL','VPS-Select'}: raise ValueError('invalid node name')
    fp=d.get('fingerprint','chrome')
    if fp not in {'chrome','firefox','safari','ios','android','edge','random'}: raise ValueError('unsupported fingerprint')
    node={'name':name,'type':'vless','server':d['server'],'port':d['port'],'uuid':ident,'network':'tcp','tls':True,'udp':True,'flow':'xtls-rprx-vision','servername':d['servername'],'client-fingerprint':fp,'reality-opts':{'public-key':key,'short-id':sid}}
    return {'mixed-port':7897,'allow-lan':False,'bind-address':'127.0.0.1','mode':'rule','log-level':'warning','ipv6':False,'tun':{'enable':False},'proxies':[node],'proxy-groups':[{'name':'VPS-Select','type':'select','proxies':[name]}],'rules':['MATCH,VPS-Select']}


def enrich(profile):
    """Optional remote categorization; every group defaults to the VPS, including CN."""
    cats=[('GitHub','github'),('YouTube','youtube'),('Google','google'),('Telegram','telegram'),('Netflix','netflix'),('Spotify','spotify'),('Bilibili','bilibili'),('China','cn'),('Private','private')]
    profile['rule-providers']={}
    rules=[]
    for group,key in cats:
        profile['proxy-groups'].append({'name':'Route-'+group,'type':'select','proxies':['VPS-Select','DIRECT']})
        profile['rule-providers'][key]={'type':'http','behavior':'domain','format':'mrs','path':'./rules/'+key+'.mrs','url':'https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite/'+key+'.mrs','interval':86400,'proxy':'VPS-Select'}
        rules.append('RULE-SET,'+key+',Route-'+group)
    profile['rules']=rules+['MATCH,VPS-Select']
    return profile


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('descriptor',type=Path); p.add_argument('output',type=Path)
    p.add_argument('--rules', choices=['all-proxy','categorized'],default='all-proxy',help='categorized downloads official MetaCubeX rules when core runs; every group starts via VPS')
    p.add_argument('--kind', choices=['profile','provider'],default='profile',help='provider contains only proxies and is not a standalone profile')
    a=p.parse_args()
    try:
        profile=generate(json.loads(a.descriptor.read_text(encoding='utf-8-sig')))
        if a.rules=='categorized': profile=enrich(profile)
        if a.kind=='provider': profile={'proxies':profile['proxies']}
        # Exclusive creation prevents overwriting or following an existing symlink.
        fd=os.open(a.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(profile,f,ensure_ascii=False,indent=2); f.write('\n')
    except (ValueError,TypeError,KeyError,OSError) as e:
        # Exception messages from parsing may contain credentials; print type only.
        p.exit(1,'Failed: '+type(e).__name__+'. Check descriptor schema and output path.\n')
    print('Created private local JSON-formatted YAML. Import/reload it explicitly; no system settings changed.')
    if os.name=='nt': print('Windows: verify output folder ACL; POSIX mode 0600 does not enforce Windows ACLs.')
if __name__=='__main__': main()
