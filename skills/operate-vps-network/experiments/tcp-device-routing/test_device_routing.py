#!/usr/bin/env python3
"""Disposable localhost experiment, no packet injection or network-setting changes.

Runs verified official Mihomo 1.19.33 and a tiny test-only SOCKS server, proving
per-VLESS-user egress selection. The SOCKS fixture only applies IP_TTL, NOT full
Windows/iOS impersonation. TCP_SAVE_SYN inspects real received SYN headers.
"""
import concurrent.futures
import json
import pathlib
import socket
import struct
import subprocess
import tempfile
import threading
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parent
BINARY = ROOT / 'mihomo-v1.19.33'
SAVE_SYN, SAVED_SYN = 27, 28
events = []
errors = []
threads = []
stop = threading.Event()

def readn(s, n):
    b = b''
    while len(b) < n:
        c = s.recv(n-len(b))
        if not c:
            raise EOFError('short stream')
        b += c
    return b

def parse_syn(data):
    ihl = (data[0] & 15) * 4
    tcp = data[ihl:]
    opts = tcp[20:((tcp[12] >> 4) * 4)]
    kinds, mss, scale, pos = [], None, None, 0
    while pos < len(opts):
        kind = opts[pos]
        kinds.append(kind)
        if kind == 0:
            break
        if kind == 1:
            pos += 1
            continue
        length = opts[pos+1]
        if length < 2 or pos+length > len(opts):
            raise ValueError('bad TCP option')
        if kind == 2:
            mss = int.from_bytes(opts[pos+2:pos+4], 'big')
        if kind == 3:
            scale = opts[pos+2]
        pos += length
    window = int.from_bytes(tcp[14:16], 'big')
    return {'ttl':data[8], 'window':window, 'mss':mss,
            'scale':scale, 'options':kinds,
            'ja4t':f'{window}_{"-".join(map(str,kinds))}_{mss}_{scale}'}

def listener():
    s = socket.socket()
    s.setsockopt(socket.IPPROTO_TCP, SAVE_SYN, 1)
    s.bind(('127.0.0.1', 0))
    s.listen(32)
    s.settimeout(.2)
    return s

def serve(ls, handler):
    while not stop.is_set():
        try:
            conn, _ = ls.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        def wrapped(c=conn):
            try:
                with c:
                    c.settimeout(4)
                    handler(c)
            except Exception as e:
                errors.append(type(e).__name__ + ': ' + str(e))
        t = threading.Thread(target=wrapped)
        threads.append(t)
        t.start()

def target_handler(conn):
    syn = parse_syn(conn.getsockopt(socket.IPPROTO_TCP, SAVED_SYN, 256))
    request = b''
    while b'\r\n\r\n' not in request:
        request += readn(conn, 1)
    body = json.dumps(syn).encode()
    conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\nConnection: close\r\n\r\n'+body)

def socks_handler(conn):
    incoming_syn = parse_syn(conn.getsockopt(socket.IPPROTO_TCP, SAVED_SYN, 256))
    version, count = readn(conn,2)
    assert version == 5 and 2 in readn(conn,count)
    conn.sendall(b'\x05\x02')
    authver, n = readn(conn,2)
    username = readn(conn,n).decode()
    password = readn(conn,readn(conn,1)[0]).decode()
    assert authver == 1 and password == 'local-test-only'
    assert username in ('windows','ios')
    conn.sendall(b'\x01\x00')
    ver, command, reserved, atyp = readn(conn,4)
    assert (ver,command,reserved,atyp) == (5,1,0,1)
    addr = socket.inet_ntoa(readn(conn,4))
    port = int.from_bytes(readn(conn,2),'big')
    assert (addr,port) == target.getsockname()
    with socket.socket() as upstream:
        upstream.settimeout(4)
        upstream.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, 128 if username == 'windows' else 64)
        upstream.connect((addr,port))
        conn.sendall(b'\x05\x00\x00\x01'+socket.inet_aton('127.0.0.1')+struct.pack('!H',upstream.getsockname()[1]))
        data = b''
        while b'\r\n\r\n' not in data:
            data += readn(conn,1)
        upstream.sendall(data)
        response = b''
        while True:
            chunk = upstream.recv(65536)
            if not chunk:
                break
            response += chunk
        conn.sendall(response)
    events.append({'profile':username,'sidecar_inbound_syn':incoming_syn})

def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0))
        return s.getsockname()[1]

target = listener()
sidecar = listener()
server_port = free_port()
reality_dest_port = free_port()
ports = {'windows':free_port(),'ios':free_port()}
uids = {k:str(uuid.uuid4()) for k in ports}
tmp = tempfile.TemporaryDirectory(prefix='tcp-device-routing-')
home = pathlib.Path(tmp.name)
keypair = dict(line.split(': ',1) for line in subprocess.check_output([str(BINARY),'generate','reality-keypair'],text=True).strip().splitlines())
short_id = uuid.uuid4().hex[:16]
subprocess.run(['openssl','req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-keyout',str(home/'tls.key'),'-out',str(home/'tls.crt'),'-days','1','-subj','/CN=example.invalid','-addext','subjectAltName=DNS:example.invalid'],check=True,capture_output=True)
server = {
 'mode':'rule','log-level':'warning','ipv6':False,'allow-lan':False,
 'find-process-mode':'off', 'tun':{'enable':False},'dns':{'enable':False},
 'listeners':[{'name':'vless-in','type':'vless','listen':'127.0.0.1','port':server_port,
               'users':[{'username':k+'-device','uuid':v,'flow':'xtls-rprx-vision'} for k,v in uids.items()],
               'reality-config':{'dest':f'127.0.0.1:{reality_dest_port}','private-key':keypair['PrivateKey'],'short-id':[short_id],'server-names':['example.invalid']}}],
 'proxies':[{'name':'egress-'+k,'type':'socks5','server':'127.0.0.1','port':sidecar.getsockname()[1],
             'username':k,'password':'local-test-only'} for k in ports],
 'rules':[f'AND,((IP-CIDR,127.0.0.1/32),(DST-PORT,{reality_dest_port})),DIRECT']+[f'IN-USER,{k}-device,egress-{k}' for k in ports]+['MATCH,REJECT']}
client = {
 'mode':'rule','log-level':'warning','ipv6':False,'allow-lan':False,
 'find-process-mode':'off','tun':{'enable':False},'dns':{'enable':False},
 'listeners':[{'name':k+'-client','type':'mixed','listen':'127.0.0.1','port':p,'proxy':k+'-vless'} for k,p in ports.items()],
 'proxies':[{'name':k+'-vless','type':'vless','server':'127.0.0.1','port':server_port,'uuid':v,'network':'tcp','tls':True,'flow':'xtls-rprx-vision','servername':'example.invalid','client-fingerprint':'chrome','reality-opts':{'public-key':keypair['PublicKey'],'short-id':short_id}} for k,v in uids.items()],
 'rules':['MATCH,REJECT']}
processes, files = [], []
try:
    tls_log = (home/'tls.log').open('w')
    files.append(tls_log)
    processes.append(subprocess.Popen(['openssl','s_server','-accept',f'127.0.0.1:{reality_dest_port}','-tls1_3','-groups','X25519','-alpn','h2,http/1.1','-cert',str(home/'tls.crt'),'-key',str(home/'tls.key'),'-www'],stdout=tls_log,stderr=tls_log))
    for ls, handler in ((target,target_handler),(sidecar,socks_handler)):
        t = threading.Thread(target=serve,args=(ls,handler))
        threads.append(t)
        t.start()
    for name, cfg in (('server',server),('client',client)):
        conf = home/(name+'.json')
        conf.write_text(json.dumps(cfg))
        apphome = home/name
        apphome.mkdir()
        subprocess.run([str(BINARY),'-t','-d',str(apphome),'-f',str(conf)],check=True,capture_output=True)
        log = (home/(name+'.log')).open('w')
        files.append(log)
        processes.append(subprocess.Popen([str(BINARY),'-d',str(apphome),'-f',str(conf)],stdout=log,stderr=log))
    time.sleep(.6)
    assert all(p.poll() is None for p in processes), [(home/(n+'.log')).read_text() for n in ('server','client')]
    def request(k):
        r = subprocess.run(['curl','-q','--noproxy','','--proxy',f'http://127.0.0.1:{ports[k]}','--max-time','4','-fsS',f'http://127.0.0.1:{target.getsockname()[1]}/'],capture_output=True,text=True)
        assert r.returncode == 0, {'curl':r.stderr,'logs':{n:(home/(n+'.log')).read_text() for n in ('server','client')},'fixture_errors':errors}
        syn = json.loads(r.stdout)
        assert syn['ttl'] == (128 if k == 'windows' else 64), syn
        assert syn['options'] == [2,4,8,1,3], syn
        return {'selected_profile':k,'target_received_syn':syn}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(request,['windows','ios']*10))
    assert len(events) == 20 and not errors, (len(events),errors)
    assert all(x['sidecar_inbound_syn']['ttl'] == 64 for x in events)
    output = {'mihomo_version':subprocess.check_output([str(BINARY),'-v'],text=True).strip(),
              'tested':'20 real loopback HTTP exchanges through Mihomo VLESS/REALITY/Vision -> IN-USER -> SOCKS auth -> per-socket TTL fixture',
              'passed':len(results),'profile_counts':{k:sum(x['selected_profile']==k for x in results) for k in ports},
              'examples':{k:next(x for x in results if x['selected_profile']==k) for k in ports},
              'sidecar_received_mihomo_syn':events[0]['sidecar_inbound_syn'],
              'limits':['No kernel rewrite backend loaded','No production service accessed or modified','No Windows/iOS real device was used','TCP options remain Linux; TTL-only is NOT full spoofing','All observed packets are loopback with loopback MSS','Outer REALITY/Vision and VLESS authenticated routing tested; no full external fingerprint spoofing claim']}
    (ROOT/'device-routing-results.json').write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(output,indent=2))
finally:
    for p in processes:
        p.terminate()
    for p in processes:
        p.wait(timeout=5)
    stop.set()
    target.close()
    sidecar.close()
    for t in threads:
        t.join(timeout=5)
    for f in files:
        f.close()
    if errors:
        print('fixture_errors',errors)
    tmp.cleanup()
