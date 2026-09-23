"""Executed as the dedicated, unprivileged account in a systemd sandbox."""
import os
import json
import subprocess
import sys
from pathlib import Path

job = Path('/var/lib/easystock-codex/jobs') / sys.argv[1]
if not job.is_dir() or not sys.argv[1].isalnum():
    raise SystemExit('Invalid job')
isolation={'uid':os.getuid(),'production_readable':os.access('/home/ubuntu/easystock/.env',os.R_OK),
           'capabilities_readable':os.access('/var/lib/easystock-guardian/capabilities.json',os.R_OK),
           'production_writable':os.access('/home/ubuntu/easystock/firebase_store.py',os.W_OK)}
if isolation['uid']==0 or any(isolation[k] for k in ('production_readable','capabilities_readable','production_writable')):
    raise SystemExit('Agent OS isolation preflight failed')
(job/'isolation.json').write_text(json.dumps(isolation))
env = {k:v for k,v in os.environ.items() if k in ('PATH','LANG','GUARDIAN_PROXY_TOKEN')}
env.update({'HOME':str(job/'home'),'CODEX_HOME':str(job/'home/.codex')})
Path(env['CODEX_HOME']).mkdir(parents=True,exist_ok=True)
Path(env['CODEX_HOME'],'config.toml').write_text('''model = "gpt-5.6-luna"
model_provider = "guardian"
model_reasoning_effort = "low"
approval_policy = "never"
[model_providers.guardian]
name = "Guardian"
base_url = "http://127.0.0.1:18765/v1"
env_key = "GUARDIAN_PROXY_TOKEN"
wire_api = "responses"
request_max_retries = 0
stream_max_retries = 0
''')
cmd = ['/usr/local/bin/easystock-codex','exec','--sandbox','danger-full-access','--skip-git-repo-check',
       '--ephemeral','--json','-C',str(job/'workspace'),'--output-schema',str(job/'schema.json'),
       '-o',str(job/'result.json'),'-']
with (job/'events.jsonl').open('w') as out, (job/'stderr.log').open('w') as err:
    result = subprocess.run(cmd,input=(job/'prompt.txt').read_text(),text=True,env=env,stdout=out,stderr=err,timeout=420)
raise SystemExit(result.returncode)
