const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {createDOM,settle}=require('./dom.cjs');
test('Guardian is Owner-only, read-only and uses safe text, with failed reads UNKNOWN',async()=>{
 const html=fs.readFileSync('easystock_admin/static/index.html','utf8'),{w,run}=createDOM(html),calls=[];
 let failed=false;
 w.api=async(path,options)=>{calls.push({path,options});if(failed)throw Error('expired');return {overall_status:'REVIEW',report_status:'CURRENT',counts:{high:1},commit:'abcdef',review_required:true,changed_critical_files:['market_risk.py'],findings:[{severity:'HIGH',title:'<img src=x onerror=alert(1)>',impact:'risk',recommendation:'review',blocks_live_auto:true,evidence:[{path:'x.py',line:2,detail:'structure'}]}],resolved_findings:[]};};
 w.showAdminTab=()=>{};run('easystock_admin/static/guardian.js');
 assert(w.document.getElementById('workspace').hidden);assert.equal(calls.length,0);
 w.document.getElementById('workspace').hidden=false;w.document.dispatchEvent(new w.Event('easystock:owner-ready'));await settle();
 assert.equal(calls.length,1);assert.equal(calls[0].path,'api/guardian');assert.equal(calls[0].options,undefined);
 assert.equal(w.document.querySelectorAll('#guardianFindings img').length,0);
 assert(w.document.getElementById('guardianFindings').textContent.includes('僅提示'));
 failed=true;await w.loadGuardian();assert(w.document.getElementById('guardianStatus').textContent.includes('UNKNOWN'));assert.equal(w.document.getElementById('guardianFindings').children.length,0);
 failed=false;await w.loadGuardian();w.document.getElementById('logout').click();assert.equal(w.document.getElementById('guardianFindings').children.length,0);
 assert(!fs.readFileSync('index.html','utf8').includes('guardianPanel'));w.close();
});
