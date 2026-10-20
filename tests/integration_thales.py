#!/usr/bin/env python3
"""Isolated REAL model acceptance. Heavy: coordinator submits this on Thales.

No live installation is touched. Project/network/container names use pp-test-.
Writes only receipts (no conversation bodies or tokens), removes its containers/volumes.
"""
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import socketserver
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'pp-test-local-' + secrets.token_hex(3)
IMAGE = 'pp-test-local-model:' + secrets.token_hex(4)
OWNER_PORT = 19885
MODEL_PORT = 19887
PROXY_PORT = 19888
EVIDENCE = ROOT / 'evidence'
DOCKER = ['docker','--context',os.environ.get('TEST_DOCKER_CONTEXT','colima')]
ENV = {**os.environ,'LOCAL_MODEL_IMAGE':IMAGE,'DEFAULT_MODEL':'qwen2.5-0.5b','APP_PORT':str(OWNER_PORT)}
COMPOSE = DOCKER + ['compose','-p',PREFIX,'-f',str(ROOT/'runtipi/docker-compose.yml'),'-f',str(EVIDENCE/'override.yml')]
RECEIPT = {'kind':'real-model-integration','checks':{},'source_revision':os.environ.get('SOURCE_REVISION','unset'),'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def run(args, *, timeout=60, stdin=None, check=True, env=None):
    p = subprocess.run(args,input=stdin,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout,env=env or ENV)
    if check and p.returncode:
        # Docker build/start errors may carry paths, never model request bodies/tokens.
        raise RuntimeError('command failed: ' + ' '.join(args[:6]) + '\n' + p.stderr.decode(errors='replace')[-3000:])
    return p


def compose(*args, **kw): return run(COMPOSE + list(args), **kw)


def owner(method,path,body=None):
    conn=http.client.HTTPConnection('127.0.0.1',OWNER_PORT,timeout=10)
    try:
        conn.request(method,path,body=None if body is None else json.dumps(body),headers={'Content-Type':'application/json','Origin':f'http://127.0.0.1:{OWNER_PORT}','X-Wizard-Request':'1'})
        response=conn.getresponse(); data=response.read(); assert response.status in (200,204),(path,response.status)
        return json.loads(data) if data else None
    finally: conn.close()


def await_models(limit=600):
    until=time.monotonic()+limit
    last=None
    while time.monotonic()<until:
        try:
            status=owner('GET','/api/status')
            progress=status['download']
            if progress != last:
                print('download',progress,flush=True); last=progress
            if status['models']: return status
            if progress['state']=='failed': raise RuntimeError('model download failed (no body recorded)')
        except (OSError, http.client.HTTPException): pass
        time.sleep(2)
    raise TimeoutError('model readiness deadline')


CLIENT = r'''
import json,sys,urllib.request,urllib.error
p=json.load(sys.stdin)
def call(method,path,body=None,token=None):
 r=urllib.request.Request('http://wizard-local-model-relay:8090'+path,data=None if body is None else json.dumps(body).encode(),method=method,headers={'Authorization':'Bearer '+token} if token else {})
 try:
  with urllib.request.urlopen(r,timeout=90) as response: return response.status,response.read()
 except urllib.error.HTTPError as e: return e.code,e.read()
assert call('GET','/healthz')[0]==200
assert call('GET','/v1/models')[0]==401
# A private client cannot mint/control other agents by forging browser headers on owner port.
owner=urllib.request.Request('http://wizard-local-model-relay:18805/api/private-clients',data=b'{"agent":"forged-owner"}',headers={'Host':'localhost:18805','Origin':'http://localhost:18805','X-Wizard-Request':'1','Content-Type':'application/json'})
try:
 urllib.request.urlopen(owner,timeout=10); raise AssertionError('relay peer gained owner authority')
except urllib.error.HTTPError as e: assert e.code==403
if p.get('fail_closed'):
 assert call('POST','/v1/chat/completions',{'model':p['model'],'messages':[{'role':'user','content':'hello'}]},p['token'])[0]==502
else:
 assert call('GET','/v1/models',token=p['token'])[0]==200
 for stream in (False,True):
  body={'model':p['model'],'messages':[{'role':'user','content':p['probe']+' Reply with a short greeting.'}],'max_tokens':24,'stream':stream}
  code,raw=call('POST','/v1/chat/completions',body,p['token']); assert code==200,code
  if stream: assert b'data: ' in raw and b'[DONE]' in raw
  else: assert json.loads(raw)['choices'][0]['message']['content']
print(json.dumps({'passed':True,'stream':not p.get('fail_closed'),'nonstream':not p.get('fail_closed')}))
'''


def client(net,payload):
    p=run(DOCKER+['run','--rm','-i','--name',PREFIX+'-client','--network',net,'--entrypoint','python',IMAGE,'-c',CLIENT],stdin=json.dumps(payload).encode(),timeout=240)
    return json.loads(p.stdout)


BRIDGE = r'''
import socket,socketserver,select
class Server(socketserver.ThreadingTCPServer):
 allow_reuse_address=True
 daemon_threads=True
 def handle_error(self,*args): pass
class Forward(socketserver.BaseRequestHandler):
 def handle(self):
  with socket.create_connection(('model',8080),timeout=10) as upstream:
   sockets=[self.request,upstream]
   while True:
    ready,_,_=select.select(sockets,[],[],100)
    if not ready: return
    for source in ready:
     chunk=source.recv(65536)
     if not chunk: return
     (upstream if source is self.request else self.request).sendall(chunk)
Server(('0.0.0.0',18087),Forward).serve_forever()
'''


class TailnetProxy(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True


class Forward(socketserver.BaseRequestHandler):
    def handle(self):
        import select
        with socket.create_connection(('127.0.0.1',MODEL_PORT),timeout=10) as upstream:
            sockets=[self.request,upstream]
            while True:
                ready,_,_=select.select(sockets,[],[],100)
                if not ready: break
                for source in ready:
                    chunk=source.recv(65536)
                    if not chunk: return
                    (upstream if source is self.request else self.request).sendall(chunk)


def main():
    if not str(ROOT).startswith('/Volumes/ThalesMedia/'):
        raise SystemExit('Heavy integration must run on the external ThalesMedia volume.')
    if os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize < 8 * 1024**3:
        raise SystemExit('Insufficient external-volume reserve (8 GiB).')
    EVIDENCE.mkdir(exist_ok=True)
    (EVIDENCE/'override.yml').write_text('services:\n  wizard-local-model:\n    ports: ["127.0.0.1:19885:18805", "127.0.0.1:19887:18087"]\n')
    relay_net=PREFIX+'-relay'
    proxy=None
    try:
        run(DOCKER+['build','-t',IMAGE,str(ROOT)],timeout=300)
        compose('up','-d',timeout=180)
        status=await_models()
        RECEIPT['checks']['download_sha_verified_and_model_ready']=True
        app=compose('ps','-q','wizard-local-model').stdout.decode().strip()
        model=compose('ps','-q','model').stdout.decode().strip()
        used=[]
        ids=run(DOCKER+['network','ls','-q']).stdout.decode().split()
        if ids:
            for network in json.loads(run(DOCKER+['network','inspect',*ids]).stdout):
                used.extend(x.get('Subnet','') for x in network.get('IPAM',{}).get('Config',[]))
        import ipaddress
        occupied=[ipaddress.ip_network(x) for x in used if x]
        subnet=next(f'10.252.{n}.0/24' for n in range(240,255) if not any(ipaddress.ip_network(f'10.252.{n}.0/24').overlaps(x) for x in occupied if x.version==4))
        run(DOCKER+['network','create','--internal','--subnet',subnet,relay_net])
        run(DOCKER+['network','connect','--alias','wizard-local-model-relay',relay_net,app])
        token=owner('POST','/api/private-clients',{'agent':PREFIX})['token']
        probe='PRIVPROBE-'+secrets.token_hex(12)
        model_id=status['models'][0]['id']
        RECEIPT['checks']['on_box_relay_completion']=client(relay_net,{'token':token,'model':model_id,'probe':probe})
        # Loopback is not an attached 10.252 peer: even with a valid token it is refused.
        script="import urllib.request,urllib.error;\ntry: urllib.request.urlopen('http://127.0.0.1:8090/healthz'); raise Exception('unexpected relay admission')\nexcept urllib.error.HTTPError as e: assert e.code==403\nprint('non-relay peer refused')"
        assert b'non-relay peer refused' in run(DOCKER+['exec',app,'python','-c',script]).stdout
        RECEIPT['checks']['non_relay_peer_refused']=True
        topology=json.loads(run(DOCKER+['inspect',model]).stdout)[0]['NetworkSettings']['Networks']
        assert len(topology)==1,topology
        details=json.loads(run(DOCKER+['network','inspect',next(iter(topology))]).stdout)[0]
        assert details['Internal'] is True
        egress=run(DOCKER+['exec',model,'curl','--noproxy','*','--connect-timeout','3','--max-time','5','-sS','https://example.com'],check=False,timeout=10)
        ip_egress=run(DOCKER+['exec',model,'curl','--noproxy','*','--connect-timeout','3','--max-time','5','-sS','http://1.1.1.1'],check=False,timeout=10)
        assert egress.returncode!=0 and ip_egress.returncode!=0
        RECEIPT['checks']['model_network_offline']={'internal':True,'attached_networks':len(topology),'hostname_exit':egress.returncode,'direct_ip_exit':ip_egress.returncode}
        # Prefer an existing owner Ollama if it has a model; otherwise use the SAME actual llama model
        # exposed only through this disposable host-side tailnet listener. No public inference service.
        tailnet_ip=run(['tailscale','ip','-4']).stdout.decode().strip().splitlines()[0]
        assert ipaddress.ip_address(tailnet_ip) in ipaddress.ip_network('100.64.0.0/10')
        tags=run(['curl','-sS','--max-time','3',f'http://{tailnet_ip}:11434/api/tags'],check=False)
        existing=json.loads(tags.stdout).get('models',[]) if tags.returncode==0 else []
        if existing:
            upstream_url=f'http://{tailnet_ip}:11434/v1'
            expected='existing owner Ollama'
        else:
            # Test-only tunnel runs INSIDE the app (already dual-homed), never on model's offline net.
            # Production app exposes no such listener. Only a loopback publish is added by override.
            run(DOCKER+['exec','-d',app,'python','-c',BRIDGE])
            deadline=time.monotonic()+10
            while True:
                try:
                    with socket.create_connection(('127.0.0.1',MODEL_PORT),timeout=1): break
                except OSError:
                    if time.monotonic()>deadline: raise
                    time.sleep(0.2)
            proxy=TailnetProxy((tailnet_ip,PROXY_PORT),Forward)
            threading.Thread(target=proxy.serve_forever,daemon=True).start()
            upstream_url=f'http://{tailnet_ip}:{PROXY_PORT}/v1'
            expected='on-box llama via disposable tailnet listener'
        owner('POST','/api/settings',{'mode':'another-machine','model':'qwen2.5-0.5b','base_url':upstream_url})
        remote=await_models(60)
        assert remote['mode']=='another-machine' and remote['boundary']=='That machine is now inside your private boundary'
        RECEIPT['checks']['another_machine_relay_completion']={**client(relay_net,{'token':token,'model':remote['models'][0]['id'],'probe':probe}),'route':expected}
        owner('POST','/api/settings',{'mode':'on-box','model':'qwen2.5-0.5b','base_url':''})
        await_models(60)
        compose('stop','model',timeout=30)
        RECEIPT['checks']['stopped_model_fails_closed']=client(relay_net,{'token':token,'model':model_id,'fail_closed':True})
        logs=compose('logs','--no-color',timeout=10).stdout
        assert probe.encode() not in logs and token.encode() not in logs
        scan="import pathlib,sys; p,t=sys.stdin.buffer.read().split(b'\\n'); files=list(pathlib.Path('/data/private').rglob('*')); assert all(p not in f.read_bytes() and t not in f.read_bytes() for f in files if f.is_file()); print('data leak scan passed')"
        assert b'passed' in run(DOCKER+['exec','-i',app,'python','-c',scan],stdin=(probe+'\n'+token).encode()).stdout
        RECEIPT['checks']['no_body_or_token_in_app_logs_data']={'passed':True,'log_bytes':len(logs),'logs_sha256':hashlib.sha256(logs).hexdigest()}
        RECEIPT['passed']=True
    except Exception as error:
        RECEIPT['passed']=False
        RECEIPT['error']=str(error)
        raise
    finally:
        if proxy: proxy.shutdown(); proxy.server_close()
        compose('down','--volumes','--remove-orphans',check=False,timeout=60)
        run(DOCKER+['rm','-f',PREFIX+'-client'],check=False)
        run(DOCKER+['network','rm',relay_net],check=False)
        run(DOCKER+['image','rm',IMAGE],check=False,timeout=30)
        RECEIPT['cleanup_remaining_containers']=run(DOCKER+['ps','-a','--filter','name='+PREFIX,'--format','{{.Names}}']).stdout.decode().split()
        (EVIDENCE/'integration-receipt.json').write_text(json.dumps(RECEIPT,indent=2)+'\n')
        print(json.dumps(RECEIPT,indent=2),flush=True)


if __name__=='__main__': main()
