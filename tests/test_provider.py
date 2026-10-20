"""Real HTTP fixtures prove admission/forwarding; upstream is synthetic, not model proof."""
import contextlib
import hashlib
import http.client
import io
import ipaddress
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import server as s


class FakeModel(s.Common):
    requests = []
    def do_GET(self):
        self.requests.append((self.command,self.path,dict(self.headers),None))
        self.send(200, {'data':[{'id':'qwen2.5-1.5b'}]})
    def do_POST(self):
        raw = self.body()
        self.requests.append((self.command,self.path,dict(self.headers),raw))
        if json.loads(raw).get('stream'):
            self.send_response(200); self.send_header('Content-Type','text/event-stream')
            self.send_header('Connection','close'); self.end_headers(); self.close_connection=True
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n'); self.wfile.flush()
            time.sleep(0.25)
            self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()
        else: self.send(200, {'choices':[{'message':{'content':'fixture answer'}}]})


class ProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = s.QuietServer(('127.0.0.1',0), FakeModel)
        cls.owner = s.QuietServer(('127.0.0.1',0), s.Owner)
        cls.relay = s.QuietServer(('127.0.0.1',0), s.Relay)
        for server in (cls.model,cls.owner,cls.relay): threading.Thread(target=server.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):
        for server in (cls.model,cls.owner,cls.relay): server.shutdown(); server.server_close()
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patches = [patch.object(s,'DATA',self.root/'private'),patch.object(s,'MODELS',self.root/'models'),
            patch.object(s,'PORT',self.owner.server_port),patch.object(s,'LOCAL_BASE',f'http://127.0.0.1:{self.model.server_port}/v1')]
        for p in self.patches: p.start(); self.addCleanup(p.stop)
        s.initialize(); FakeModel.requests = []; s.LOCAL_READY.set()
        self.addCleanup(s.LOCAL_READY.clear)
        self.origin = f'http://127.0.0.1:{self.owner.server_port}'
    def request(self, server, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1',server.server_port, timeout=3)
        self.addCleanup(conn.close)
        if isinstance(body,dict): body=json.dumps(body).encode()
        conn.request(method,path,body=body,headers=headers or {})
        response=conn.getresponse(); return response.status,response.read(),dict(response.headers)
    def owner_headers(self): return {'Origin':self.origin,'X-Wizard-Request':'1','Content-Type':'application/json'}
    def relay_request(self,method,path,body=None,token=None):
        with patch.object(s,'peer_ok',return_value=True):
            return self.request(self.relay,method,path,body,{'Authorization':'Bearer '+token} if token else {})
    def test_manifest_declaration(self):
        manifest=(s.ROOT/'wizard.md').read_text()
        for text in ['provides: [ai-connection, private-inference]','kind: local','relay_port: 8090','egress: []']: self.assertIn(text,manifest)
    def test_token_rotation_hash_and_revoke(self):
        one=s.mint('agent-a'); two=s.mint('agent-a')
        self.assertGreaterEqual(len(one),43); self.assertNotEqual(one,two)
        self.assertFalse(s.token_ok('Bearer '+one)); self.assertTrue(s.token_ok('Bearer '+two))
        contents=(s.DATA/'clients.json').read_text(); self.assertNotIn(two,contents)
        self.assertIn(hashlib.sha256(two.encode()).hexdigest(),contents)
        self.assertEqual((s.DATA/'clients.json').stat().st_mode & 0o777,0o600)
        s.revoke('agent-a'); self.assertFalse(s.token_ok('Bearer '+two))
    def test_restart_retains_hashed_clients(self):
        token=s.mint('agent-b'); s.initialize(); self.assertTrue(s.token_ok('Bearer '+token))
    def test_agent_id_restrictions(self):
        for agent in ['../x','a/b','', 'a'*129, 12]:
            with self.assertRaises(ValueError): s.mint(agent)
    def test_owner_mint_delete_contract(self):
        code,raw,_=self.request(self.owner,'POST','/api/private-clients',{'agent':'demo'},self.owner_headers())
        self.assertEqual(code,200); body=json.loads(raw)
        self.assertEqual(body['relay_url'],'http://wizard-local-model-relay:8090')
        self.assertTrue(s.token_ok('Bearer '+body['token']))
        code,raw,_=self.request(self.owner,'DELETE','/api/private-clients/demo',headers=self.owner_headers())
        self.assertEqual((code,raw),(204,b'')); self.assertFalse(s.token_ok('Bearer '+body['token']))
    def test_owner_cross_site_and_rebinding_refused(self):
        for headers in [{},{'Origin':'https://evil.example','X-Wizard-Request':'1'},
                        {**self.owner_headers(),'Host':'evil.example'},
                        {**self.owner_headers(),'X-Forwarded-For':'127.0.0.1'},
                        {**self.owner_headers(),'Tailscale-User-Login':'owner'}]:
            code,_,_=self.request(self.owner,'POST','/api/private-clients',{'agent':'x'},headers)
            self.assertEqual(code,403)
        self.assertFalse((s.DATA/'clients.json').exists())
    def test_owner_internal_peer_cannot_forge_browser_gate(self):
        with patch.object(s,'owner_peer_ok',return_value=False):
            self.assertEqual(self.request(self.owner,'POST','/api/private-clients',{'agent':'attacker'},self.owner_headers())[0],403)
            self.assertEqual(self.request(self.owner,'GET','/api/connection',headers=self.owner_headers())[0],403)
        self.assertFalse((s.DATA/'clients.json').exists())
        self.assertFalse(s.owner_peer_ok('10.252.23.5'))
    def test_owner_shared_bridge_peer_not_implicitly_trusted(self):
        with patch.dict(os.environ,{'WIZARD_OWNER_PEERS':'172.23.0.2'}):
            self.assertTrue(s.owner_peer_ok('172.23.0.2'))
            self.assertFalse(s.owner_peer_ok('172.23.0.3'))
            self.assertFalse(s.owner_peer_ok('172.23.0.1'))
            self.assertFalse(s.owner_peer_ok('10.252.23.5'))
        with patch.dict(os.environ,{'WIZARD_OWNER_PEERS':'172.23.0.0/24'}):
            self.assertFalse(s.owner_peer_ok('172.23.0.3'))
        with patch.dict(os.environ,{'WIZARD_OWNER_PEERS':''}):
            self.assertFalse(s.owner_peer_ok('172.23.0.2'))
            self.assertTrue(s.owner_peer_ok('127.0.0.1'))
    def test_refused_request_body_cannot_smuggle_owner_write(self):
        payload=json.dumps({'agent':'smuggled'}).encode()
        inner=(f'POST /api/private-clients HTTP/1.1\r\nHost: 127.0.0.1:{self.owner.server_port}\r\nOrigin: {self.origin}\r\nX-Wizard-Request: 1\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\n\r\n').encode()+payload
        outer=(f'POST /api/private-clients HTTP/1.1\r\nHost: 127.0.0.1:{self.owner.server_port}\r\nOrigin: https://evil.example\r\nContent-Length: {len(inner)}\r\n\r\n').encode()+inner
        with socket.create_connection(('127.0.0.1',self.owner.server_port),timeout=3) as conn:
            conn.sendall(outer)
            raw=b''
            while chunk:=conn.recv(4096): raw+=chunk
        self.assertIn(b'403 Forbidden',raw)
        self.assertEqual(raw.count(b'HTTP/1.1'),1)
        self.assertFalse((s.DATA/'clients.json').exists())
    def test_private_models_and_status_contract(self):
        code,raw,_=self.request(self.owner,'GET','/api/connection')
        self.assertEqual(code,200); body=json.loads(raw)
        self.assertEqual(body['contract'],'wizard.ai-connection/1')
        self.assertEqual(body['models'],[{'id':'qwen2.5-1.5b','label':'qwen2.5-1.5b'}])
    def test_untrusted_peer_even_health_refused(self):
        for path in ['/healthz','/v1/models']:
            code,_,_=self.request(self.relay,'GET',path,headers={'Authorization':'Bearer '+s.mint('x')})
            self.assertEqual(code,403)
    def test_subnet_check_specific_interface_and_no_spoof(self):
        with patch.object(s,'relay_subnets',return_value=[ipaddress.ip_network('10.252.23.0/24')]):
            for addr in ['10.252.23.7','10.252.23.254']: self.assertTrue(s.peer_ok(addr))
            for addr in ['10.252.24.7','127.0.0.1','::ffff:10.252.23.7','100.64.0.1']: self.assertFalse(s.peer_ok(addr))
        self.assertEqual(self.request(self.relay,'GET','/healthz',headers={'X-Forwarded-For':'10.252.23.7'})[0],403)
    def test_health_no_token_but_models_require_token(self):
        self.assertEqual(self.relay_request('GET','/healthz')[:2],(200,b'ok'))
        for token in [None,'bad']:
            self.assertEqual(self.relay_request('GET','/v1/models',token=token)[0],401)
    def test_nonstream_tools_bytes_unchanged_bearer_stripped(self):
        token=s.mint('demo'); body={'model':'qwen2.5-1.5b','messages':[{'role':'user','content':'PRIVPROBE-unit'}], 'tools':[{'type':'function','function':{'name':'sample'}}]}
        code,raw,_=self.relay_request('POST','/v1/chat/completions',body,token)
        self.assertEqual(code,200); self.assertIn('choices',json.loads(raw))
        method,path,headers,forwarded=FakeModel.requests[-1]
        self.assertEqual((method,path),('POST','/v1/chat/completions')); self.assertEqual(json.loads(forwarded),body)
        self.assertNotIn('Authorization',headers)
    def test_sse_first_chunk_not_buffered(self):
        token=s.mint('demo')
        with patch.object(s,'peer_ok',return_value=True):
            conn=http.client.HTTPConnection('127.0.0.1',self.relay.server_port,timeout=3)
            self.addCleanup(conn.close)
            conn.request('POST','/v1/chat/completions',body=json.dumps({'stream':True}).encode(),headers={'Authorization':'Bearer '+token})
            r=conn.getresponse(); before=time.monotonic(); line=r.readline(); elapsed=time.monotonic()-before
            self.assertTrue(line.startswith(b'data: ')); self.assertLess(elapsed,0.2)
            self.assertIn(b'[DONE]',r.read()); self.assertEqual(r.getheader('Content-Type'),'text/event-stream')
    def test_no_body_or_token_in_logs_data(self):
        token=s.mint('demo'); probe='PRIVPROBE-do-not-persist'
        out=io.StringIO()
        with contextlib.redirect_stderr(out),contextlib.redirect_stdout(out):
            code,_,_=self.relay_request('POST','/v1/chat/completions',{'messages':[{'role':'user','content':probe}]},token)
        self.assertEqual(code,200)
        self.assertNotIn(probe,out.getvalue()); self.assertNotIn(token,out.getvalue())
        for file in self.root.rglob('*'):
            if file.is_file():
                self.assertNotIn(probe.encode(),file.read_bytes()); self.assertNotIn(token.encode(),file.read_bytes())
    def test_fail_closed_no_model(self):
        with patch.object(s,'upstream',side_effect=OSError('PRIVATE exception')):
            code,raw,_=self.relay_request('POST','/v1/chat/completions',{'messages':[]},s.mint('demo'))
        self.assertEqual(code,502); self.assertNotIn(b'PRIVATE exception',raw); self.assertIn(b'No fallback',raw)
    def test_relay_allowlist(self):
        token=s.mint('demo')
        for method,path in [('GET','/api/connection'),('POST','/api/private-clients'),('GET','/v1/models?host=evil')]:
            self.assertEqual(self.relay_request(method,path,{},token)[0],404)
    def test_tailnet_only_rebinding_and_url_validation(self):
        def cfg(url): return {'mode':'another-machine','base_url':url}
        for url in ['file:///etc/passwd','http://user:password@100.64.1.2/v1','http://100.64.1.2/v1?x=y','http://100.64.1.2/admin']:
            with self.assertRaises(ValueError): s.endpoint(cfg(url))
        with patch.object(socket,'getaddrinfo',return_value=[(2,1,6,'',('100.64.1.2',11434))]):
            parsed,pinned=s.endpoint(cfg('http://owner-machine:11434/v1'))
            self.assertEqual(pinned,'100.64.1.2')
        for addr in ['127.0.0.1','169.254.169.254','8.8.8.8','192.168.1.2']:
            with patch.object(socket,'getaddrinfo',return_value=[(2,1,6,'',(addr,80))]):
                with self.assertRaises(ValueError): s.endpoint(cfg('http://owner-machine/v1'))
    def test_setting_switch_is_persistent(self):
        body={'mode':'another-machine','model':'qwen2.5-1.5b','base_url':'http://100.64.1.2:11434/v1'}
        lookup = socket.getaddrinfo
        def resolve(host, port, *args, **kwargs):
            if host == '100.64.1.2': return [(2,1,6,'',('100.64.1.2',11434))]
            return lookup(host, port, *args, **kwargs)
        with patch.object(socket,'getaddrinfo',side_effect=resolve):
            self.assertEqual(self.request(self.owner,'POST','/api/settings',body,self.owner_headers())[0],200)
        self.assertEqual(s.settings(),body)
    def test_local_selection_not_yet_verified_fails_closed(self):
        s.LOCAL_READY.clear()
        token=s.mint('demo')
        self.assertEqual(self.relay_request('POST','/v1/chat/completions',{'messages':[]},token)[0],502)
        self.assertEqual(s.model_list(),[])
        self.assertEqual(FakeModel.requests,[])
    def test_switch_never_falls_back_to_old_model(self):
        config=s.settings();config['model']='qwen2.5-3b';s.atomic(s.DATA/'settings.json',config)
        token=s.mint('demo')
        self.assertEqual(self.relay_request('POST','/v1/chat/completions',{'messages':[]},token)[0],502)
        self.assertEqual(s.model_list(),[])
        self.assertFalse(any(r[0]=='POST' for r in FakeModel.requests))
    def test_static_assets_and_real_csp(self):
        for path in ['/','/app.js','/styles.css','/appearance.js','/openapi.json']:
            code,raw,headers=self.request(self.owner,'GET',path)
            self.assertEqual(code,200);self.assertGreater(len(raw),100)
            self.assertIn("script-src 'self'",headers['Content-Security-Policy'])
            self.assertNotIn("'unsafe-inline'",headers['Content-Security-Policy'])
    def test_download_hash_pin_and_progress(self):
        data=b'tiny-gguf-test-fixture'; model={**s.CATALOG[0],'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
        with patch.object(s,'CATALOG',[model]),patch.object(s.urllib.request,'urlopen',return_value=io.BytesIO(data)):
            s.download_model()
        self.assertEqual(s.PROGRESS['state'],'ready'); self.assertEqual((s.MODELS/'model.gguf').read_bytes(),data)
        self.assertEqual((s.MODELS/'model.id').read_text(),model['id'])
        self.assertTrue((s.MODELS/'generation').exists())
    def test_bad_download_never_publishes(self):
        with patch.object(s.urllib.request,'urlopen',return_value=io.BytesIO(b'wrong-weights')): s.download_model()
        self.assertEqual(s.PROGRESS['state'],'failed'); self.assertFalse((s.MODELS/'generation').exists())
        self.assertFalse(list(s.MODELS.glob('*.part')))


if __name__=='__main__': unittest.main()
