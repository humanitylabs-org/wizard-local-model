"""Fail closed on tag-discovery errors; never replace a published version."""
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request


def main():
    version=os.environ['VERSION']
    assert re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',version),'Version must be semver.'
    root=Path(__file__).resolve().parents[1]
    assert '\nversion: '+version+'\n' in (root/'wizard.md').read_text()
    assert json.loads((root/'runtipi/config.json').read_text())['version']==version
    assert 'image.version="'+version+'"' in (root/'Dockerfile').read_text()
    owner,name=os.environ['GITHUB_REPOSITORY'].split('/')
    page=1
    while True:
        url=f'https://api.github.com/orgs/{owner}/packages/container/{name}/versions?per_page=100&page={page}'
        request=urllib.request.Request(url,headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
        try:
            with urllib.request.urlopen(request,timeout=30) as response: versions=json.load(response)
        except urllib.error.HTTPError as error:
            if error.code==404 and page==1: break  # First publication: package absent.
            raise RuntimeError(f'Package tag discovery refused ({error.code}); no publish.') from None
        if not isinstance(versions,list): raise RuntimeError('Unrecognized tag discovery response; no publish.')
        if any(version in item.get('metadata',{}).get('container',{}).get('tags',[]) for item in versions):
            raise RuntimeError('Refusing to replace an existing version.')
        if len(versions)<100: break
        page+=1
    print('Fresh version confirmed; publication authorized by workflow input, not by this script.')


if __name__=='__main__': main()
