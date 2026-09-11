/* Capture the selected module only. No data is uploaded to a screenshot service. */
(() => {
  let exportFile = null, previewURL = null, generation = 0, returnFocus = null;
  const get = id => document.getElementById(id);
  const status = text => { get('moduleShareStatus').textContent = text; };
  function clearFile() {
    exportFile = null;
    if (previewURL) URL.revokeObjectURL(previewURL);
    previewURL = null;
    get('moduleSharePreview').hidden = true;
    get('moduleSharePreview').removeAttribute('src');
    get('moduleShareSend').disabled = get('moduleShareDownload').disabled = true;
  }
  window.closeModuleShare = () => {
    generation++; clearFile(); get('moduleShareDialog').close(); returnFocus?.focus();
  };
  document.addEventListener('DOMContentLoaded', () => {
    get('moduleShareDialog').addEventListener('cancel', e => { e.preventDefault(); closeModuleShare(); });
  });
  window.prepareModuleShare = async (id, title) => {
    const source = get(id);
    if (!source) return;
    const token = ++generation;
    returnFocus = document.activeElement;
    clearFile(); get('moduleShareTitle').textContent = `${title}・圖片預覽`;
    if (!get('moduleShareDialog').open) get('moduleShareDialog').showModal();
    status('正在製作圖片…');
    let staging = null;
    try {
      if (typeof html2canvas !== 'function') throw new Error('圖片元件尚未載入，請稍後再試。');
      if (document.fonts?.ready) await document.fonts.ready;
      if (token !== generation) return;
      // Freeze this module before the live Firebase refresh changes the DOM.
      staging = source.cloneNode(true);
      staging.removeAttribute('id');
      staging.querySelectorAll('[data-share-ignore],button').forEach(el => el.remove());
      staging.querySelectorAll('[id]').forEach(el => el.removeAttribute('id'));
      staging.querySelectorAll('[onclick],[onkeydown]').forEach(el => {el.removeAttribute('onclick');el.removeAttribute('onkeydown');});
      Object.assign(staging.style,{position:'fixed',left:'-20000px',top:'0',width:`${Math.max(360,Math.min(1000,source.getBoundingClientRect().width))}px`,height:'auto',maxHeight:'none',overflow:'visible',padding:'24px',margin:'0',transform:'none'});
      const footer = document.createElement('div');
      footer.textContent = `當沖吧！牛馬仔 · ${new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',dateStyle:'short',timeStyle:'short'}).format(new Date())} 擷取 · 僅供研究`;
      Object.assign(footer.style,{paddingTop:'18px',fontSize:'12px',color:getComputedStyle(document.documentElement).getPropertyValue('--sub')});
      staging.append(footer);document.body.append(staging);
      const width=staging.scrollWidth,height=staging.scrollHeight;
      if (!width || !height || height>16000) throw new Error('模塊過長，請縮小顯示範圍後再試。');
      const canvas=await html2canvas(staging,{backgroundColor:getComputedStyle(source).backgroundColor,useCORS:true,logging:false,width,height,scale:Math.min(2,Math.sqrt(12000000/(width*height)))});
      const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
      if (token!==generation) return;
      if (!blob) throw new Error('圖片製作失敗，請再試一次。');
      exportFile=new File([blob],`當沖吧！牛馬仔-${title}-${Date.now()}.png`,{type:'image/png'});
      previewURL=URL.createObjectURL(blob);
      get('moduleSharePreview').src=previewURL;get('moduleSharePreview').hidden=false;
      get('moduleShareDownload').disabled=false;
      const supported=!!(navigator.canShare && navigator.canShare({files:[exportFile]}));
      get('moduleShareSend').disabled=!supported;
      status(supported?'圖片已準備好，請選擇分享 App 或下載。':'此瀏覽器不支援圖片直接分享，請下載 PNG 後傳送至 LINE。');
    } catch(e) {if(token===generation)status(e.message || '無法製作圖片。');}
    finally {staging?.remove();}
  };
  window.sendModuleShare = async () => {
    if (!exportFile) return;
    try {
      // A separate click preserves user activation after the asynchronous render.
      await navigator.share({files:[exportFile]});
      status('已交給系統分享選單。');
    } catch(e) {status(e.name==='AbortError'?'已取消分享。':'分享未完成，可改用下載 PNG。');}
  };
  window.downloadModuleShare = () => {
    if(!exportFile || !previewURL)return;
    const a=document.createElement('a');a.href=previewURL;a.download=exportFile.name;
    document.body.append(a);a.click();a.remove();status('已開始下載 PNG。');
  };
})();
