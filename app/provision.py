"""One-shot provisioning only: no HTTP listener, relay, tokens, prompts or private data."""
import hashlib
import json
import os
from pathlib import Path
import urllib.request
from artifacts import CATALOG


def provision(root, model, opener=urllib.request.urlopen):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    marker = root / 'ready.json'
    marker.unlink(missing_ok=True)  # No stale readiness, including a failed upgrade.
    target = root / model['file']
    def verified(path):
        if not path.exists() or path.stat().st_size != model['size']: return False
        digest = hashlib.sha256()
        with path.open('rb') as src:
            for chunk in iter(lambda: src.read(1024 * 1024), b''): digest.update(chunk)
        return digest.hexdigest() == model['sha256']
    part = root / '.weights.part'
    try:
        if not verified(target):
            target.unlink(missing_ok=True)
            url = f"https://huggingface.co/{model['repo']}/resolve/{model['revision']}/{model['file']}"
            received = 0
            with opener(url, timeout=120) as src, part.open('wb') as out:
                while chunk := src.read(1024 * 1024):
                    received += len(chunk)
                    if received > model['size']: raise ValueError('Oversized model artifact')
                    out.write(chunk)
                out.flush(); os.fsync(out.fileno())
            if not verified(part): raise ValueError('Model sha256/size mismatch')
            part.chmod(0o644); part.replace(target)
        ready = {'model':model['id'], 'sha256':model['sha256'], 'size':model['size']}
        pending = root / '.ready.pending'
        with pending.open('w') as out:
            json.dump(ready, out); out.flush(); os.fsync(out.fileno())
        pending.chmod(0o644); pending.replace(marker)
        return ready
    finally:
        part.unlink(missing_ok=True)


if __name__ == '__main__':
    model = next(m for m in CATALOG if m['id'] == os.environ.get('DEFAULT_MODEL','qwen2.5-1.5b'))
    print(json.dumps({'provisioned':provision(os.environ.get('MODEL_DIR','/models'), model)}), flush=True)
