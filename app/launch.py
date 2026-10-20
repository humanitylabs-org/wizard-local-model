"""Single sealed container; llama listens only on loopback. No body logging."""
import os
import signal
import subprocess
import threading
import server


def main():
    server.initialize()
    server.verify_weights()
    child = None
    if server.LOCAL_READY.is_set():
        model = next(m for m in server.CATALOG if m['id'] == server.settings()['model'])
        child = subprocess.Popen(['/app/llama-server','-m',str(server.MODELS / model['file']),
            '--alias',model['id'],'--host','127.0.0.1','--port','8080','-c','65536','--parallel','1',
            '--fit','off','--rope-scaling','yarn','--rope-scale','2','-t','4','--log-disable'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def stop(*_):
        if child:
            child.terminate()
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired: child.kill(); child.wait()
        os._exit(0)
    signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
    if child:
        def watch():
            child.wait()
            server.LOCAL_READY.clear()  # Model death can never leave a live advertised route.
        threading.Thread(target=watch,daemon=True).start()
    server.main()


if __name__ == '__main__': main()
