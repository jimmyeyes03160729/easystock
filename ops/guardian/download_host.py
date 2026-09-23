import urllib.request,json,hashlib,tarfile,io
from pathlib import Path
meta=json.loads(Path('/tmp/easystock-codex-release.json').read_text())
r=json.load(urllib.request.urlopen('https://api.github.com/repos/openai/codex/releases/tags/'+meta['release'],timeout=30))
a=next(a for a in r['assets'] if a['name']=='codex-code-mode-host-x86_64-unknown-linux-musl.tar.gz')
b=urllib.request.urlopen(a['browser_download_url'],timeout=120).read()
assert 'sha256:'+hashlib.sha256(b).hexdigest()==a['digest']
with tarfile.open(fileobj=io.BytesIO(b)) as t:
 for m in t.getmembers():
  if m.isfile():
   p=Path('/tmp/codex-code-mode-host');p.write_bytes(t.extractfile(m).read());p.chmod(0o755)
print('Verified host',meta['release'],a['digest'])
