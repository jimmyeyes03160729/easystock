// Public repository gate: CI never checks out or authenticates to a private core.
import {readFile,readdir,lstat} from 'node:fs/promises';
import {join} from 'node:path';
const expected=JSON.parse(await readFile('site-allowlist.json','utf8')).sort();
async function walk(dir,prefix='') {
  const names=[];
  for(const name of await readdir(dir)) {
    const path=join(dir,name),rel=prefix+name,stat=await lstat(path);
    if(stat.isSymbolicLink()) throw Error('symlink rejected');
    if(stat.isDirectory()) names.push(...await walk(path,rel+'/'));
    else {
      if(/(^|\/)(vm_runtime|daytrade_learning|research|tests?|deploy|ops|\.git)(\/|$)|\.(py|pem|key|db|sqlite|zip|map|env)$/i.test(rel)) throw Error('forbidden source path');
      const data=await readFile(path);
      if(/-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}/.test(data.toString('utf8'))) throw Error('secret pattern rejected');
      names.push(rel);
    }
  }
  return names;
}
const actual=(await walk('site')).sort();
if(JSON.stringify(actual)!==JSON.stringify(expected)) throw Error('site differs from reviewed allowlist');
console.log(`Verified ${actual.length} allowlisted public files`);
