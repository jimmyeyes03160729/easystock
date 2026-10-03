/* Only the backend's public allowlist is consumed here. */
(() => {
  const root=document.getElementById('providerHealthCard');if(!root)return;
  const style=document.createElement('style');style.textContent=`
  #providerHealthCard{padding:14px 18px;margin:14px 0}
  .provider-health-heading{display:flex;gap:12px;justify-content:space-between;align-items:center;margin-bottom:10px}
  .provider-health-heading h2{font-size:13px;font-weight:700;margin:0}
  #providerHealthChecked{color:var(--sub);font-size:11px}
  .provider-health-rows{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
  .provider-health-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:12px}
  .provider-health-dot{width:7px;height:7px;border-radius:50%;background:#64748b;flex:none}
  .provider-health-row[data-status=ONLINE] .provider-health-dot{background:#34d399}
  .provider-health-row[data-status=DEGRADED] .provider-health-dot{background:#fbbf24}
  .provider-health-row[data-status=OFFLINE] .provider-health-dot{background:#fb7185}
  .provider-health-state{color:var(--sub);font-size:11px}
  @media(max-width:700px){.provider-health-rows{grid-template-columns:repeat(3,minmax(0,1fr))}}
  @media(max-width:400px){.provider-health-rows{grid-template-columns:repeat(2,minmax(0,1fr))}}
  `;document.head.append(style);
  const labels={shioaji:'永豐行情',esun:'玉山行情',fugle:'Fugle',firebase:'Firebase'};
  const states={ONLINE:'正常',DEGRADED:'延遲',OFFLINE:'離線',UNKNOWN:'未知',MARKET_CLOSED:'休市'};
  let busy=false;
  function render(summary){
    const elapsed=Date.now()-Date.parse(summary?.generated_at);
    const recent=summary?.schema_version===1 && Number.isFinite(elapsed) && elapsed>=-2000 && elapsed<=180000;
    const list=document.getElementById('providerHealthRows');list.replaceChildren();
    for(const [key,label] of Object.entries(labels)){
      const candidate=recent?summary?.providers?.[key]?.status:'UNKNOWN',status=Object.hasOwn(states,candidate)?candidate:'UNKNOWN';
      const row=document.createElement('div');row.className='provider-health-row';row.dataset.status=status;row.dataset.provider=key;
      const dot=document.createElement('span');dot.className='provider-health-dot';dot.setAttribute('aria-hidden','true');
      const name=document.createElement('span');name.textContent=label;
      const state=document.createElement('span');state.className='provider-health-state';state.textContent=states[status];
      row.append(dot,name,state);list.append(row);
    }
    document.getElementById('providerHealthChecked').textContent=recent?'最後檢查 '+new Date(summary.generated_at).toLocaleTimeString('zh-TW',{timeZone:'Asia/Taipei',hour12:false}):'等待最新狀態';
  }
  async function refresh(){
    if(busy)return;busy=true;
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);
    try{const response=await fetch(`${FIREBASE_ROOT}/provider_health.json`,{cache:'no-store',signal:controller.signal});if(!response.ok)throw Error();render(await response.json());}
    catch(_){render(null);}finally{clearTimeout(timer);busy=false;}
  }
  render(null);refresh();setInterval(refresh,60000);
})();
