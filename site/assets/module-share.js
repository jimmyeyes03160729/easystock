/* Capture the selected module only. No data is uploaded to a screenshot service. */
(() => {
  let exportFile = null, previewURL = null, generation = 0, returnFocus = null;
  const get = id => document.getElementById(id);
  const status = text => { get('moduleShareStatus').textContent = text; };
  // html2canvas cannot parse CSS Color 4 values emitted by color-mix().
  // Freeze the visible source, then resolve paint colors through the browser.
  function freezeStyles(source, copy) {
    const probe=document.createElement('canvas');probe.width=probe.height=1;
    const paint=probe.getContext('2d',{willReadFrequently:true}), colors=new Map();
    const resolve=color=>{
      if(!/\b(?:color|oklch|oklab|lab|lch)\(/.test(color))return color;
      if(colors.has(color))return colors.get(color);
      paint.clearRect(0,0,1,1);paint.fillStyle=color;paint.fillRect(0,0,1,1);
      const [r,g,b,a]=paint.getImageData(0,0,1,1).data;
      const value=`rgba(${r},${g},${b},${a/255})`;colors.set(color,value);return value;
    };
    const originals=[source,...source.querySelectorAll('*')], copies=[copy,...copy.querySelectorAll('*')];
    originals.forEach((node,index)=>{
      const target=copies[index], style=getComputedStyle(node);
      // The browser may retain boxes inside a closed <details>, even though
      // its contents are not painted. Never export those hidden descendants.
      let closedDetails=false;
      for(let parent=node.parentElement;parent&&source.contains(parent);parent=parent.parentElement){
        if(parent.tagName==='DETAILS'&&!parent.open){
          const summary=[...parent.children].find(el=>el.tagName==='SUMMARY');
          if(!summary?.contains(node)){closedDetails=true;break;}
        }
      }
      if (closedDetails || !node.getClientRects().length || style.display==='none') {
        target.remove(); return;
      }
      for(let i=0;i<style.length;i++){
        const name=style[i];let value=style.getPropertyValue(name);
        if(/color$/.test(name))value=resolve(value);
        else if(/background-image|box-shadow|text-shadow/.test(name))
          value=value.replace(/\b(?:color|oklch|oklab|lab|lch)\([^)]*\)/g,resolve);
        target.style.setProperty(name,value);
      }
      target.style.animation='none';target.style.transition='none';
      target.style.backdropFilter='none';target.style.webkitBackdropFilter='none';
      // Inset glass shadows render as overlapping bands in html2canvas.
      // Flatten them only in the exported copy, keeping text and chart colors.
      target.style.boxShadow='none';target.style.textShadow='none';
      // A cloned canvas has no bitmap; preserve charts without touching the source.
      if (node instanceof HTMLCanvasElement) {
        target.width=node.width;target.height=node.height;
        target.getContext('2d')?.drawImage(node,0,0);
      }
    });
  }
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
      const bounds=source.getBoundingClientRect(), copy=source.cloneNode(true);
      freezeStyles(source,copy);
      copy.querySelectorAll('[hidden]').forEach(el=>el.remove());
      copy.removeAttribute('id');
      // Tabs are buttons too: retain their visible labels in the exported image.
      copy.querySelectorAll('[data-share-ignore]').forEach(el => el.remove());
      copy.querySelectorAll('[id]').forEach(el => el.removeAttribute('id'));
      copy.querySelectorAll('[onclick],[onkeydown]').forEach(el => {el.removeAttribute('onclick');el.removeAttribute('onkeydown');});
      // Keep the source's exact border-box width and padding. Resizing after
      // freezing children mixes two layouts, especially on 320/390px screens.
      Object.assign(copy.style,{position:'relative',left:'0',top:'0',width:`${bounds.width}px`,height:`${bounds.height}px`,maxHeight:'none',margin:'0',transform:'none'});
      // Keep the footer outside the frozen module's measured height.
      staging=document.createElement('div');
      const background=getComputedStyle(document.documentElement).getPropertyValue('--lg-canvas').trim() || (document.documentElement.dataset.theme==='dark'?'#0b1529':'#ffffff');
      Object.assign(staging.style,{position:'fixed',left:'-20000px',top:'0',width:`${bounds.width}px`,height:'auto',overflow:'visible',margin:'0',backgroundColor:background,color:getComputedStyle(source).color,fontFamily:getComputedStyle(source).fontFamily});
      staging.append(copy);
      const footer = document.createElement('div');
      footer.textContent = `當沖吧！牛馬仔 · ${new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',dateStyle:'short',timeStyle:'short'}).format(new Date())} 擷取 · 僅供研究`;
      Object.assign(footer.style,{padding:'16px 18px',fontSize:'12px',lineHeight:'20px',color:getComputedStyle(document.documentElement).getPropertyValue('--sub')});
      staging.append(footer);document.body.append(staging);
      const width=staging.scrollWidth,height=staging.scrollHeight;
      if (!width || !height || height>16000) throw new Error('模塊過長，請縮小顯示範圍後再試。');
      const canvas=await html2canvas(staging,{backgroundColor:background,useCORS:true,logging:false,width,height,scale:Math.min(2,Math.sqrt(12000000/(width*height)))});
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
