import fs from 'fs';
import path from 'path';
import http from 'http';
import { URL } from 'url';
import { exec } from 'child_process';

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

function openBrowser(url) {
  const start = process.platform === 'darwin' ? 'open' : process.platform === 'win32' ? 'start' : 'xdg-open';
  exec(`${start} "${url}"`);
}

async function getOAuthTokens(credentials) {
  const clientInfo = credentials.installed || credentials.web;
  if (!clientInfo) {
    throw new Error('client_secret.json 格式不符合預期的 installed 或 web 類型');
  }

  const clientId = clientInfo.client_id;
  const clientSecret = clientInfo.client_secret;
  const port = 8085;
  const redirectUri = `http://localhost:${port}/oauth2callback`;

  return new Promise((resolve, reject) => {
    const server = http.createServer(async (req, res) => {
      try {
        const reqUrl = new URL(req.url, `http://localhost:${port}`);
        if (reqUrl.pathname === '/oauth2callback') {
          const code = reqUrl.searchParams.get('code');
          if (!code) {
            res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' });
            res.end('<h1>授權失敗：未取得授權碼</h1>');
            server.close();
            return reject(new Error('未取得授權碼'));
          }

          res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
          res.end('<h1 style="color: #10b981; font-family: sans-serif; text-align: center; margin-top: 50px;">✓ Google 帳號授權成功！正在開始上傳影片，請返回終端機檢視進度...</h1>');
          server.close();

          console.log('✓ 成功取得授權碼，正在向 Google 兌換存取權杖 (Access Token)...');
          const tokenRes = await fetch('https://oauth2.googleapis.com/token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({
              code,
              client_id: clientId,
              client_secret: clientSecret,
              redirect_uri: redirectUri,
              grant_type: 'authorization_code'
            })
          });

          const tokenData = await tokenRes.json();
          if (tokenData.access_token) {
            resolve(tokenData.access_token);
          } else {
            reject(new Error('取得權杖失敗: ' + JSON.stringify(tokenData)));
          }
        }
      } catch (err) {
        reject(err);
      }
    });

    server.listen(port, () => {
      const authUrl = `https://accounts.google.com/o/oauth2/v2/auth?client_id=${clientId}&redirect_uri=${encodeURIComponent(redirectUri)}&response_type=code&scope=${encodeURIComponent('https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube')}&access_type=offline&prompt=consent`;
      console.log('\n================================================================');
      console.log('🔑 請在即將開啟的瀏覽器中登入您的 YouTube / Google 帳號並點擊「允許」');
      console.log('若瀏覽器未自動開啟，請手動複製並在瀏覽器貼上此網址：');
      console.log(authUrl);
      console.log('================================================================\n');
      openBrowser(authUrl);
    });
  });
}

async function uploadVideo(accessToken) {
  console.log('🚀 開始上傳影片至 YouTube (Resumable Upload)...');
  const videoBuffer = fs.readFileSync(VIDEO_PATH);
  const videoSize = videoBuffer.length;

  const initMetadata = {
    snippet: {
      title: VIDEO_METADATA.title,
      description: VIDEO_METADATA.description,
      tags: VIDEO_METADATA.tags,
      categoryId: VIDEO_METADATA.categoryId
    },
    status: {
      privacyStatus: VIDEO_METADATA.privacyStatus,
      selfDeclaredMadeForKids: false
    }
  };

  // 1. 初始化可續傳上傳會話
  const initRes = await fetch('https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${accessToken}`,
      'Content-Type': 'application/json; charset=UTF-8',
      'X-Upload-Content-Length': videoSize.toString(),
      'X-Upload-Content-Type': 'video/mp4'
    },
    body: JSON.stringify(initMetadata)
  });

  if (!initRes.ok) {
    const errText = await initRes.text();
    throw new Error(`初始化上傳失敗 (${initRes.status}): ${errText}`);
  }

  const uploadUrl = initRes.headers.get('location');
  if (!uploadUrl) {
    throw new Error('Google 未返回上傳位址 (Location Header missing)');
  }

  console.log(`✓ 上傳位址建立成功，正在傳輸影片二進位資料 (${(videoSize / 1024 / 1024).toFixed(2)} MB)...`);

  // 2. 傳輸影片資料
  const uploadRes = await fetch(uploadUrl, {
    method: 'PUT',
    headers: {
      'Content-Type': 'video/mp4',
      'Content-Length': videoSize.toString()
    },
    body: videoBuffer
  });

  const uploadResult = await uploadRes.json();
  if (!uploadRes.ok || !uploadResult.id) {
    throw new Error('影片傳輸失敗: ' + JSON.stringify(uploadResult));
  }

  const videoId = uploadResult.id;
  console.log(`🎉 影片上傳成功！Video ID: ${videoId}`);
  console.log(`🔗 影片觀看連結：https://youtu.be/${videoId}`);

  // 3. 上傳專屬自訂封面縮圖
  if (fs.existsSync(THUMBNAIL_PATH)) {
    console.log('🖼️ 正在上傳 YouTube 高點閱率自訂封面...');
    try {
      const thumbBuffer = fs.readFileSync(THUMBNAIL_PATH);
      const thumbRes = await fetch(`https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId=${videoId}`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'image/jpeg',
          'Content-Length': thumbBuffer.length.toString()
        },
        body: thumbBuffer
      });
      if (thumbRes.ok) {
        console.log('✓ 自訂封面縮圖設定成功！');
      } else {
        console.log('⚠️ 封面設定提示 (您的頻道可能尚未驗證手機號碼以啟用自訂縮圖權限):', await thumbRes.text());
      }
    } catch (thumbErr) {
      console.log('⚠️ 封面設定略過:', thumbErr.message);
    }
  }

  return videoId;
}

async function main() {
  const clientSecretPath = path.resolve('client_secret.json');

  if (!fs.existsSync(clientSecretPath)) {
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
    console.log('\n💡 提示：如需透過 API 全自動上傳，請先在 Google Cloud Console 下載 OAuth 2.0 憑證並命名為 client_secret.json 放置於專案根目錄。');
    console.log('或是您可以直接點擊下方連結，手動拖曳影片與封面，並複製上方完整資料貼上發布：');
    console.log('👉 YouTube Studio 快速上傳連結：https://studio.youtube.com\n');
    return;
  }

  try {
    const rawCredentials = JSON.parse(fs.readFileSync(clientSecretPath, 'utf8'));
    const accessToken = await getOAuthTokens(rawCredentials);
    await uploadVideo(accessToken);
  } catch (err) {
    console.error('❌ 上傳發生錯誤:', err.message);
  }
}

main();
