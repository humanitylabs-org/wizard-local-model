"""Wizard local private provider. stdlib only; conversation bytes never enter storage/logs."""
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import re
import secrets
import socket
import struct
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('DATA_DIR', '/data/private'))
MODELS = Path(os.environ.get('MODEL_DIR', '/data/models'))
PORT = int(os.environ.get('PORT', '18805'))
RELAY_PORT = int(os.environ.get('RELAY_PORT', '8090'))
LOCAL_BASE = 'http://model:8080/v1'
LOCK = threading.RLock()
DOWNLOAD_LOCK = threading.Lock()
LOCAL_READY = threading.Event()
MAX_BODY = 8 * 1024 * 1024
POOL = ipaddress.ip_network('10.252.0.0/16')
AGENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')
PROGRESS = {'state': 'idle', 'received': 0, 'total': 0}
CATALOG = [
    {'id':'qwen2.5-1.5b','label':'Qwen2.5 1.5B Instruct (recommended)', 'size':1117320736,
     'repo':'Qwen/Qwen2.5-1.5B-Instruct-GGUF','revision':'91cad51170dc346986eccefdc2dd33a9da36ead9',
     'file':'qwen2.5-1.5b-instruct-q4_k_m.gguf','sha256':'6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e'},
    {'id':'qwen2.5-3b','label':'Qwen2.5 3B Instruct', 'size':2104932768,
     'repo':'Qwen/Qwen2.5-3B-Instruct-GGUF','revision':'7dabda4d13d513e3e842b20f0d435c732f172cbe',
     'file':'qwen2.5-3b-instruct-q4_k_m.gguf','sha256':'626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d'},
    {'id':'qwen2.5-0.5b','label':'Qwen2.5 0.5B Instruct (small test)', 'size':491400032,
     'repo':'Qwen/Qwen2.5-0.5B-Instruct-GGUF','revision':'9217f5db79a29953eb74d5343926648285ec7e67',
     'file':'qwen2.5-0.5b-instruct-q4_k_m.gguf','sha256':'74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db'},
]

def csv(key):
    return {x.strip().lower() for x in os.environ.get(key, '').split(',') if x.strip()}


def hosts():
    ports = {str(PORT), os.environ.get('APP_PORT', str(PORT))}
    return csv('WIZARD_TRUSTED_HOSTS') | {f'{h}:{p}' for h in ('localhost','127.0.0.1','wizard-local-model') for p in ports}


def origins():
    return csv('WIZARD_TRUSTED_ORIGINS') | {'http://' + h for h in hosts() if h.startswith(('localhost:', '127.0.0.1:'))}


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            os.fchmod(out.fileno(), 0o600)
            json.dump(value, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def load(name, default):
    try: return json.loads((DATA / name).read_text())
    except FileNotFoundError: return default


def settings():
    return load('settings.json', {'mode':'on-box','model':os.environ.get('DEFAULT_MODEL','qwen2.5-1.5b'),'base_url':''})


def mint(agent):
    if not isinstance(agent, str) or not AGENT.fullmatch(agent): raise ValueError()
    token = secrets.token_urlsafe(48)
    with LOCK:
        clients = load('clients.json', {})
        clients[agent] = hashlib.sha256(token.encode()).hexdigest()
        atomic(DATA / 'clients.json', clients)
    return token


def revoke(agent):
    if not AGENT.fullmatch(agent): raise ValueError()
    with LOCK:
        clients = load('clients.json', {})
        clients.pop(agent, None)
        atomic(DATA / 'clients.json', clients)


def token_ok(value):
    if not value.startswith('Bearer ') or len(value) > 256: return False
    digest = hashlib.sha256(value[7:].encode()).hexdigest()
    with LOCK:
        return any(hmac.compare_digest(digest, known) for known in load('clients.json', {}).values())


def relay_subnets():
    """Derive allowed peer ranges from real interface addresses, never user headers/env."""
    result = []
    try:
        import fcntl  # Linux container: SIOCGIFADDR and SIOCGIFNETMASK.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            for _, name in socket.if_nameindex():
                ifreq = struct.pack('256s', name.encode()[:15])
                try:
                    addr = socket.inet_ntoa(fcntl.ioctl(sock, 0x8915, ifreq)[20:24])
                    mask = socket.inet_ntoa(fcntl.ioctl(sock, 0x891b, ifreq)[20:24])
                    net = ipaddress.ip_network(f'{addr}/{mask}', strict=False)
                    if ipaddress.ip_address(addr) in POOL and net.subnet_of(POOL): result.append(net)
                except OSError: pass
    except (ImportError, OSError, ValueError): pass
    return result


def owner_peer_ok(peer):
    """Owner trust is explicit, never inferred from a possibly shared default route.

    Pin only trusted proxy/controller IPs; the inherited box-only Origin gate
    assumes that proxy/controller itself enforces owner access.
    """
    try:
        address = ipaddress.ip_address(peer)
        if address.is_loopback: return True
        if address in POOL: return False
        trusted = {ipaddress.ip_address(item) for item in csv('WIZARD_OWNER_PEERS')}
        return address in trusted
    except ValueError: return False


def peer_ok(peer):
    try:
        addr = ipaddress.ip_address(peer)
        return any(addr in net for net in relay_subnets())
    except ValueError: return False


def tailnet_address(addr):
    return addr in ipaddress.ip_network('100.64.0.0/10') if addr.version == 4 else addr in ipaddress.ip_network('fd7a:115c:a1e0::/48')


def endpoint(s):
    """Pin DNS to a validated tailnet address per connection (no redirect/rebinding)."""
    if s['mode'] == 'on-box':
        parsed = urllib.parse.urlsplit(LOCAL_BASE)
        return parsed, None
    parsed = urllib.parse.urlsplit(s['base_url'])
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ValueError('Invalid private machine address.')
    if parsed.path.rstrip('/') not in ('', '/v1'): raise ValueError('Use an OpenAI base URL ending /v1.')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    addresses = {r[4][0] for r in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)}
    if not addresses or not all(tailnet_address(ipaddress.ip_address(a)) for a in addresses):
        raise ValueError('The address must resolve only to tailnet IPs.')
    return parsed, sorted(addresses)[0]


def upstream(method, path, body=None):
    s = settings()
    if s['mode'] == 'on-box' and not LOCAL_READY.is_set(): raise OSError('Local model not verified/ready.')
    parsed, pinned = endpoint(s)
    if s['mode'] == 'on-box' and method == 'POST':
        # During model switch, do not silently serve the old still-running process.
        probe = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        try:
            probe.request('GET', parsed.path.rstrip('/') + '/models')
            ready = probe.getresponse()
            raw = ready.read(1024 * 1024 + 1)
            if ready.status != 200 or len(raw) > 1024 * 1024 or not any(m.get('id') == s['model'] for m in json.loads(raw).get('data',[]) if isinstance(m,dict)):
                raise OSError('Selected model still loading.')
        finally: probe.close()
    cls = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
    conn = cls(parsed.hostname, parsed.port, timeout=180)
    if pinned:
        conn._create_connection = lambda address, timeout=180, source_address=None: socket.create_connection((pinned, parsed.port or (443 if parsed.scheme == 'https' else 80)), timeout, source_address)
    # Only these headers leave the relay; client bearer/forwarded metadata never do.
    headers = {'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
    base = parsed.path.rstrip('/') or '/v1'
    conn.request(method, base + path.removeprefix('/v1'), body=body, headers=headers)
    return conn, conn.getresponse()


def model_list():
    conn = None
    try:
        conn, response = upstream('GET','/v1/models')
        if response.status != 200: return []
        raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024: return []
        data = json.loads(raw)
        selected = settings()
        return [{'id':m['id'], 'label':m['id']} for m in data.get('data', []) if isinstance(m,dict) and isinstance(m.get('id'),str) and (selected['mode'] != 'on-box' or m['id'] == selected['model'])]
    except Exception: return []
    finally:
        if conn: conn.close()


def status():
    s = settings()
    models = model_list()
    with LOCK: progress = dict(PROGRESS)
    return {**s, 'contract':'wizard.ai-connection/1','provider':'wizard-local-model','name':'Local model',
            'status':'connected' if models else 'not_connected','models':models,
            'credentialStored':False,'credentialVerified':False,'error':None,
            'plan':None,'account':None,'usage':None,
            'verification':{'mode':'local-model','sdk':None,'lastVerifiedAt':None},
            'chatIntegration':'private-relay',
            'private_inference':{'kind':'local','relay_port':8090,'egress':[]},
            'boundary':'Runs on this box' if s['mode']=='on-box' else 'That machine is now inside your private boundary',
            'download':progress,'catalog':[{k:m[k] for k in ('id','label','size')} for m in CATALOG]}


def download_model():
    """Only this app downloads curated, revision+SHA-pinned weights; model server is offline."""
    with DOWNLOAD_LOCK:
        while True:
            s = settings()
            if s['mode'] != 'on-box':
                with LOCK: PROGRESS.update(state='idle',received=0,total=0)
                return
            model = next(m for m in CATALOG if m['id'] == s['model'])
            target = MODELS / model['file']
            with LOCK: PROGRESS.update(state='downloading',received=0,total=model['size'])
            try:
                MODELS.mkdir(parents=True, exist_ok=True, mode=0o755)
                if target.exists():
                    digest = hashlib.sha256()
                    with target.open('rb') as inp:
                        for chunk in iter(lambda: inp.read(1024*1024), b''): digest.update(chunk)
                    if target.stat().st_size != model['size'] or digest.hexdigest() != model['sha256']: target.unlink()
                if not target.exists():
                    part = target.with_suffix('.part')
                    url = f"https://huggingface.co/{model['repo']}/resolve/{model['revision']}/{model['file']}"
                    digest = hashlib.sha256()
                    received = 0
                    try:
                        with urllib.request.urlopen(url, timeout=60) as response, part.open('wb') as out:
                            while chunk := response.read(1024 * 1024):
                                received += len(chunk)
                                if received > model['size']: raise ValueError()
                                out.write(chunk); digest.update(chunk)
                                with LOCK: PROGRESS['received'] = received
                        if received != model['size'] or digest.hexdigest() != model['sha256']: raise ValueError()
                        os.chmod(part, 0o644); os.replace(part, target)
                    finally: part.unlink(missing_ok=True)
                if settings() != s: continue
                # Atomic link + generation commit; wrapper notices generation and restarts llama.
                link = MODELS / '.next-model'
                link.unlink(missing_ok=True); link.symlink_to(target.name)
                os.replace(link, MODELS / 'model.gguf')
                (MODELS / '.next-id').write_text(model['id'])
                os.chmod(MODELS / '.next-id', 0o644)
                os.replace(MODELS / '.next-id', MODELS / 'model.id')
                (MODELS / '.next-generation').write_text(secrets.token_hex(16))
                os.chmod(MODELS / '.next-generation', 0o644)
                os.replace(MODELS / '.next-generation', MODELS / 'generation')
                with LOCK: PROGRESS.update(state='ready',received=model['size'],total=model['size'])
                LOCAL_READY.set()
                return
            except Exception:
                with LOCK: PROGRESS['state'] = 'failed'
                return


def start_download():
    LOCAL_READY.clear()
    threading.Thread(target=download_model, daemon=True).start()


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True
    def handle_error(self, request, client_address): pass  # No traceback/exception body leakage.


class Common(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def setup(self):
        super().setup()
        self.connection.settimeout(180)
    def log_message(self, *args): pass
    def send_error(self, code, message=None, explain=None): self.send(code, {'error':'Request refused.'})
    def send(self, code, obj=None, kind='application/json'):
        # Never parse an unread refused request body as a pipelined request.
        self.close_connection = True
        data = b'' if obj is None else obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        for k,v in {'Content-Type':kind,'Content-Length':str(len(data)), 'Cache-Control':'no-store',
                    'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Connection':'close',
                    'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'self' " + ' '.join(sorted(origins()))}.items(): self.send_header(k,v)
        self.end_headers()
        if self.command != 'HEAD': self.wfile.write(data)
    def body(self, maximum=MAX_BODY):
        if self.headers.get('Transfer-Encoding'): raise ValueError()
        lengths = self.headers.get_all('Content-Length', [])
        if len(lengths) != 1 or not lengths[0].isdigit(): raise ValueError()
        n = int(lengths[0])
        if not 0 < n <= maximum: raise ValueError()
        raw = self.rfile.read(n)
        if len(raw) != n: raise ValueError()
        return raw


class Owner(Common):
    def allowed(self, write=False):
        if not owner_peer_ok(self.client_address[0]): return False
        origin = self.headers.get('Origin','').lower()
        if self.headers.get('Host','').lower() not in hosts(): return False
        if origin and origin not in origins() or self.headers.get('Sec-Fetch-Site') == 'cross-site': return False
        if any(k.lower() in {'tailscale-user-login','x-forwarded-for','forwarded','x-real-ip'} or k.lower().startswith('cf-') for k in self.headers): return False
        # Like Tinfoil's key-save route: exact trusted origin + non-simple header.
        return not write or origin in origins() and self.headers.get('X-Wizard-Request') == '1'
    def do_GET(self):
        if not self.allowed(): return self.send(403, {'error':'Box-only endpoint.'})
        if self.path == '/healthz': return self.send(200, {'ok':True,'app':'wizard-local-model','version':'0.1.0'})
        if self.path in ('/api/connection','/api/status'): return self.send(200, status())
        allowed = {'/':'web/index.html','/styles.css':'web/styles.css','/app.js':'web/app.js','/appearance.js':'web/appearance.js','/openapi.json':'openapi.json'}
        name = allowed.get(self.path)
        if not name: return self.send(404, {'error':'Not found.'})
        kind = {'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.json':'application/json'}[Path(name).suffix]
        return self.send(200, (ROOT / name).read_bytes(), kind)
    def do_POST(self):
        if not self.allowed(True): return self.send(403, {'error':'Use the trusted settings page.'})
        try:
            if self.headers.get('Content-Type','').split(';')[0] != 'application/json': raise ValueError()
            body = json.loads(self.body(8192))
            if not isinstance(body, dict): raise ValueError()
            if self.path == '/api/private-clients':
                if set(body) != {'agent'}: raise ValueError()
                return self.send(200, {'token':mint(body['agent']),'relay_url':'http://wizard-local-model-relay:8090'})
            if self.path == '/api/settings':
                if set(body) != {'mode','model','base_url'}: raise ValueError()
                if body['mode'] not in ('on-box','another-machine') or body['model'] not in {m['id'] for m in CATALOG} or not isinstance(body['base_url'],str) or len(body['base_url']) > 2048: raise ValueError()
                if body['mode'] == 'another-machine': endpoint(body)
                else: body['base_url'] = ''
                with LOCK: atomic(DATA / 'settings.json', body)
                if body['mode'] == 'on-box': start_download()
                return self.send(200, {'saved':True})
            return self.send(404, {'error':'Not found.'})
        except (ValueError, TypeError, KeyError, OSError):
            self.close_connection = True
            return self.send(400, {'error':'Invalid settings, agent id or non-tailnet address.'})
    def do_DELETE(self):
        if not self.allowed(True): return self.send(403, {'error':'Use the trusted settings page.'})
        if not self.path.startswith('/api/private-clients/'): return self.send(404, {'error':'Not found.'})
        try: revoke(urllib.parse.unquote(self.path.removeprefix('/api/private-clients/')))
        except ValueError: return self.send(400, {'error':'Invalid agent id.'})
        return self.send(204)


class Relay(Common):
    def admitted(self):
        if not peer_ok(self.client_address[0]):
            self.close_connection = True
            self.send(403, {'error':'Relay network only.'}); return False
        if self.path == '/healthz' and self.command == 'GET': return True
        auths = self.headers.get_all('Authorization', [])
        if len(auths) != 1 or not token_ok(auths[0]):
            self.close_connection = True
            self.send(401, {'error':'Client token required.'}); return False
        return True
    def do_GET(self): self.forward()
    def do_POST(self): self.forward()
    def forward(self):
        if not self.admitted(): return
        if self.path == '/healthz' and self.command == 'GET': return self.send(200, b'ok', 'text/plain')
        if (self.command,self.path) not in {('GET','/v1/models'),('POST','/v1/chat/completions')}:
            return self.send(404, {'error':'Not found.'})
        conn = None
        started = False
        try: body = self.body() if self.command == 'POST' else None
        except (ValueError, TypeError):
            self.close_connection = True
            return self.send(400, {'error':'Invalid request framing.'})
        try:
            conn, response = upstream(self.command,self.path,body)
            if response.status != 200:
                return self.send(502, {'error':'Private model unavailable. No fallback.'})
            self.send_response(200)
            self.send_header('Content-Type', response.getheader('Content-Type','application/json'))
            self.send_header('Cache-Control','no-store')
            self.send_header('Connection','close')
            self.end_headers()
            self.close_connection = True
            started = True
            # read1 yields available SSE bytes, not a full 64KB buffer. No JSON parsing or persistence.
            while chunk := response.read1(65536):
                self.wfile.write(chunk); self.wfile.flush()
        except Exception:
            if not started: self.send(502, {'error':'Private model unavailable. No fallback.'})
            self.close_connection = True
        finally:
            if conn: conn.close()


def initialize():
    os.umask(0o077)
    DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(DATA,0o700)
    if not (DATA / 'settings.json').exists(): atomic(DATA / 'settings.json', settings())


def main():
    initialize()
    if settings()['mode'] == 'on-box': start_download()
    relay = QuietServer(('0.0.0.0', RELAY_PORT), Relay)
    threading.Thread(target=relay.serve_forever, daemon=True).start()
    QuietServer((os.environ.get('BIND','0.0.0.0'), PORT), Owner).serve_forever()


if __name__ == '__main__': main()
