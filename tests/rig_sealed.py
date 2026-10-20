#!/usr/bin/env python3
"""Disposable pp-rig local adaptations of checks 1/4; reuse stock checks 2/3/5/6.
Local inference has no EHBP/cloud key: prove on-box transport and relay-token hygiene instead.
PCAPs contain private bearer/prompt bytes and must never be published.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import urllib.request

spec=importlib.util.spec_from_file_location('rig_check','/opt/pp-rig/checks/check.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)


def local_relay(a):
    b.require(a.provider_app=='wizard-local-model' and a.trigger and a.codeword,'local trigger/codeword required')
    cs=b.provider_containers(a);b.require(len(cs)==1,'single sealed runtime required')
    c=cs[0];nets=c['NetworkSettings']['Networks']
    b.require(set(nets)=={'wizard-relay-wizard-local-model','wizard-egress-wizard-local-model'},'unexpected runtime network')
    for name,link in nets.items():
        b.require(b.inspect('network',name)['Internal'] and not link.get('Gateway'),'internet route present')
    routes=b.docker('exec',c['Id'],'cat','/proc/net/route').stdout.decode()
    b.require(not any(line.split()[1]=='00000000' for line in routes.splitlines()[1:] if line.split()),'default route present')
    env=dict(item.split('=',1) for item in c['Config']['Env'] if '=' in item)
    b.require(not any(env.get(k) for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy']),'proxy configured')
    proxy=b.docker('container','inspect','wizard-egress-proxy-wizard-local-model',ok=False)
    b.require(proxy.returncode!=0,'local egress proxy exists')
    for url in ['https://example.com','http://1.1.1.1']:b.blocked(c['Id'],url)
    net=b.inspect('network','wizard-relay-wizard-local-model')
    bridge=net.get('Options',{}).get('com.docker.network.bridge.name') or 'br-'+net['Id'][:12]
    root=Path(a.evidence_dir);root.mkdir(parents=True,exist_ok=True,mode=0o700);root.chmod(0o700)
    captures=[]
    try:
        for iface in [bridge,'eth0']:
            path=root/f'local-{iface}-{time.time_ns()}.pcap';path.touch(mode=0o600)
            cap=subprocess.Popen(['tcpdump','-Z','root','-i',iface,'-s','0','-U','-w',str(path),'tcp'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            captures.append((iface,path,cap))
        time.sleep(1);b.require(all(cap.poll() is None for _,_,cap in captures),'capture failed')
        b.require(b.run([a.trigger],ok=False,timeout=a.timeout).returncode==0,'completed local chat failed')
        time.sleep(1)
    finally:
        for iface,path,cap in captures:
            if cap.poll() is None:cap.send_signal(signal.SIGINT)
            _,err=cap.communicate(timeout=10)
            b.require(cap.returncode==0 and re.search(rb'0 packets dropped by kernel',err),'incomplete capture')
    summary=[]
    for iface,path,cap in captures:
        streams=b.run(['tshark','-r',str(path),'-T','fields','-e','tcp.stream']).stdout.decode().split()
        found=False;ehbp=False
        for stream in sorted(set(streams)):
            raw=b.run(['tshark','-r',str(path),'-q','-z','follow,tcp,raw,'+stream]).stdout.decode()
            directions=[bytearray(),bytearray()]
            for line in raw.splitlines():
                if re.fullmatch(r'\t?[0-9a-fA-F]+',line) and len(line.strip())%2==0:
                    directions[int(line.startswith('\t'))].extend(bytes.fromhex(line.strip()))
            found |= any(a.codeword.encode() in data for data in directions)
            ehbp |= any(b'ehbp-encapsulated-key:' in data.lower() for data in directions)
        b.require(found if iface==bridge else not found,'probe transport boundary mismatch')
        summary.append({'interface':iface,'streams':len(set(streams)),'codeword_present':found,'ehbp_present':ehbp,'pcap':str(path)})
    print('PASS local relay capture='+json.dumps(summary)+'; EHBP N/A; no default route, external egress blocked, no egress proxy')


def local_credentials(a):
    cs=b.provider_containers(a);allowed=b.data_roots(a,cs)
    runtime=Path(a.os_home)/'agents'/a.agent/'runtime'
    token_file=runtime/'relay-token';token=token_file.read_bytes()
    b.require(token_file.stat().st_mode & 0o777==0o400,'relay token not 0400')
    hashes=[]
    for root in allowed:
        for path in root.rglob('clients.json'):hashes.append(json.loads(path.read_text()).get(a.agent))
        for path in b.files([root]):b.require(not b.contains(path,token),'plaintext token persisted by provider')
    import hashlib
    b.require(hashlib.sha256(token).hexdigest() in hashes,'provider does not store only the relay-token hash')
    roots=[Path(a.os_home)/'agents'/a.agent,Path(a.runtipi_root)/'apps',Path(a.runtipi_root)/'user-config']
    for path in b.files(roots):
        if path.resolve()!=token_file.resolve():b.require(not b.contains(path,token),'relay token outside runtime token file')
    for cid in b.docker('ps','-aq').stdout.decode().split():
        b.require(token not in json.dumps(b.inspect('container',cid)).encode(),'relay token in Docker metadata')
    with urllib.request.urlopen('http://127.0.0.1:18805/api/connection',timeout=10) as response:connection=json.load(response)
    b.require(connection.get('credentialStored') is False,'local provider unexpectedly stores a cloud credential')
    print('PASS local cloud-provider key N/A (none); relay token only in 0400 runtime file outside Hermes home; provider stores SHA256 only; no token in env/compose/inspect/data')


if __name__=='__main__':
    b.relay=local_relay;b.key_location=local_credentials
    b.main()
