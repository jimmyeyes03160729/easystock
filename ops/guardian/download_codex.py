import json,urllib.request,tarfile,hashlib
from pathlib import Path
r=json.load(urllib.request.urlopen('https://api.github.com/repos/openai/codex/releases/latest',timeout=30))
assets=[a for a in r['assets'] if a['name']=='codex-x86_64-unknown-linux-musl.tar.gz']
print('release',r['tag_name'],'asset',[(a['name'],a.get('digest')) for a in assets])
a=assets[0]; data=urllib.request.urlopen(a['browser_download_url'],timeout=60).read()
digest=a.get('digest'); actual='sha256:'+hashlib.sha256(data).hexdigest()
assert digest and digest==actual
p=Path('/tmp/easystock-codex.tar.gz');p.write_bytes(data)
with tarfile.open(p) as t:
 names=t.getnames();print('archive',names)
 for m in t.getmembers():
  if m.isfile() and m.name.split('/')[-1].startswith('codex'):
   b=Path('/tmp/easystock-codex-bin');b.write_bytes(t.extractfile(m).read());b.chmod(0o755)
Path('/tmp/easystock-codex-release.json').write_text(json.dumps({'release':r['tag_name'],'sha256':actual,'url':a['browser_download_url']}))
