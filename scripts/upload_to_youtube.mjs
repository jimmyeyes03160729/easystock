import fs from 'fs';
import path from 'path';
import http from 'http';
import { URL } from 'url';

const VIDEO_PATH = path.resolve('chrome-store-assets/easystock_promo_official.mp4');
const THUMBNAIL_PATH = path.resolve('chrome-store-assets/youtube_thumbnail_1280x720.jpg');

const VIDEO_METADATA = {
  title: '【工位摸魚神器】EasyStock · 牛馬自救終端｜台股即時逐筆、VWAP均線突破、一鍵日誌偽裝（Chrome / Edge 擴充功能）',
  description: `上班想看盤又怕主管站在身後？打工人的離職自由金由 EasyStock 來守護！
專為上班族、當沖客打造的輕量極速看盤擴充套件，全面支援 Google Chrome 與 Microsoft Edge。

🔥 核心功能特色：
1. ⚡ 台股即時逐筆跳動：支援 00878、台積電等台股個股與 ETF，盤中報價毫秒級同步！
2. 📈 獨家 VWAP 均價線突破：盤中動態計算成交量加權平均價，爆量大單點火秒速掌握！
3. 🐮 一鍵摸魚偽裝模式：快捷鍵一按瞬間切換「系統日誌 Diagnostic Console」，主管路過毫無破綻！
4. 🚨 桌面原生毫秒級推播：免開券商軟體，均線突破、主力敲進即時桌面彈窗提醒！
5. 🛡️ 完全免費無廣告：輕量無負擔、開源透明、守護個人隱私。

📌 影片章節 (Timestamps)：
00:00 吸睛開場：工位看盤神器登場
00:06 實機演示：00878 即時跳價與 VWAP 均線
00:09 摸魚示範：一鍵切換系統日誌偽裝
00:14 毫秒推播：桌面突破通知即時彈出
00:16 結尾安裝：免費加入 Chrome / Edge

🔗 擴充套件下載與專案連結：
• GitHub 程式庫：https://github.com/jimmyeyes03160729/easystock
• 適用平台：Google Chrome、Microsoft Edge、Brave 瀏覽器

#EasyStock #台股 #當沖 #看盤軟體 #上班摸魚 #工位神器 #00878 #台積電 #VWAP #均線突破 #Chrome擴充功能 #Edge擴充功能 #股票即時行情 #辦公室摸魚 #股票推播`,
  tags: [
    'EasyStock',
    '台股',
    '當沖',
    '看盤軟體',
    '上班摸魚',
    '工位神器',
    '00878',
    '台積電',
    'VWAP',
    '均線突破',
    'Chrome擴充功能',
    'Edge擴充功能',
    '股票即時行情',
    '辦公室摸魚',
    '股票推播'
  ],
  categoryId: '28', // Science & Technology
  privacyStatus: 'public'
};

console.log('====================================================');
console.log('🎬 EasyStock YouTube 上傳專屬資料包');
console.log('====================================================');
console.log('【標題 Title】：');
console.log(VIDEO_METADATA.title);
console.log('\n【說明欄 Description】：');
console.log(VIDEO_METADATA.description);
console.log('\n【標籤 Tags】：');
console.log(VIDEO_METADATA.tags.join(', '));
console.log('\n【隱私設定 Privacy】：', VIDEO_METADATA.privacyStatus);
console.log('【影片路徑 Video File】：', VIDEO_PATH);
console.log('【自訂封面 Thumbnail】：', THUMBNAIL_PATH);
console.log('====================================================');

// Check for client_secret.json
const clientSecretPath = path.resolve('client_secret.json');
if (!fs.existsSync(clientSecretPath)) {
  console.log('\n💡 提示：如需透過 API 全自動上傳，請先在 Google Cloud Console 下載 OAuth 2.0 憑證並命名為 client_secret.json 放置於專案根目錄。');
  console.log('或是您可以直接點擊下方連結，手動拖曳影片與封面，並複製上方完整資料貼上發布：');
  console.log('👉 YouTube Studio 快速上傳連結：https://studio.youtube.com\n');
}
