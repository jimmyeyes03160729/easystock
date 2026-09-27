// EasyStock Chrome Extension - Content Script
// 連動網頁端當沖即時更新，在網頁開啟時提供 0 秒級即時跳出桌面通知
(function () {
  'use strict';

  window.addEventListener('easystock-live-update', (event) => {
    if (!event || !event.detail) return;
    try {
      if (chrome.runtime && chrome.runtime.id) {
        chrome.runtime.sendMessage({
          type: 'LIVE_DATA_SYNC',
          live: event.detail
        }).catch(() => {});
      }
    } catch {
      // 擴充功能重新載入或 Context 釋放時靜默忽略
    }
  });
})();
