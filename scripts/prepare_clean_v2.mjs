import fs from 'fs';
import path from 'path';

const assetsDir = path.resolve('chrome-store-assets');

// 1. Process small_v2.html (440x280)
{
  let html = fs.readFileSync(path.join(assetsDir, 'small_v2.html'), 'utf8');
  const cardStart = html.indexOf('<div class="relative w-[440px] h-[280px]');
  const cardEnd = html.indexOf('<!-- Format Specification Indicator Bar -->');

  // Find inner card
  if (cardStart !== -1) {
    // Extract head
    const headEnd = html.indexOf('</head>');
    let head = html.substring(0, headEnd);
    head += `
  <style>
    html, body {
      margin: 0 !important;
      padding: 0 !important;
      width: 440px !important;
      height: 280px !important;
      overflow: hidden !important;
      background: #070d1a !important;
    }
  </style>
</head>`;

    // Find end of main promo container
    // It ends before the store preview indicator
    const promoEndTag = '<!-- Store Preview Sub-bar -->';
    let endIdx = html.indexOf(promoEndTag);
    if (endIdx === -1) {
      endIdx = html.lastIndexOf('</div>\n\n  </div>\n\n</body>');
    }

    let cardContent = html.substring(cardStart, endIdx !== -1 ? endIdx : html.length).trim();
    // remove rounded-xl from outer container
    cardContent = cardContent.replace('rounded-xl', 'rounded-none');
    cardContent = cardContent.replace('border border-slate-700/60', 'border-0');
    cardContent = cardContent.replace('shadow-[0_20px_50px_rgba(0,0,0,0.85)]', '');

    const cleanHtml = `${head}
<body class="w-[440px] h-[280px] overflow-hidden m-0 p-0">
  ${cardContent}
</body>
</html>`;
    fs.writeFileSync(path.join(assetsDir, 'small_v2_clean.html'), cleanHtml, 'utf8');
    console.log('Created small_v2_clean.html');
  }
}

// 2. Process screen_v2.html (1280x800)
{
  let html = fs.readFileSync(path.join(assetsDir, 'screen_v2.html'), 'utf8');
  const cardStart = html.indexOf('<div class="relative w-[1280px] h-[800px]');
  
  if (cardStart !== -1) {
    const headEnd = html.indexOf('</head>');
    let head = html.substring(0, headEnd);
    head += `
  <style>
    html, body {
      margin: 0 !important;
      padding: 0 !important;
      width: 1280px !important;
      height: 800px !important;
      overflow: hidden !important;
      background: #070b16 !important;
    }
  </style>
</head>`;

    let endIdx = html.lastIndexOf('</body>');
    // Find the closing div of the main canvas
    let cardContent = html.substring(cardStart, endIdx).trim();
    // In screen_v2, there's a wrapper div at the end before </body>
    // Remove rounded-xl and outer borders
    cardContent = cardContent.replace('rounded-xl', 'rounded-none');
    cardContent = cardContent.replace('border border-slate-800', 'border-0');
    cardContent = cardContent.replace('shadow-[0_25px_70px_rgba(0,0,0,0.85)]', '');

    const cleanHtml = `${head}
<body class="w-[1280px] h-[800px] overflow-hidden m-0 p-0">
  ${cardContent}
</body>
</html>`;
    fs.writeFileSync(path.join(assetsDir, 'screen_v2_clean.html'), cleanHtml, 'utf8');
    console.log('Created screen_v2_clean.html');
  }
}

// 3. Process marquee_v2.html (1400x560)
{
  let html = fs.readFileSync(path.join(assetsDir, 'marquee_v2.html'), 'utf8');
  const mainStart = html.indexOf('<main class="w-[1400px] h-[560px]');

  if (mainStart !== -1) {
    const headEnd = html.indexOf('</head>');
    let head = html.substring(0, headEnd);
    head += `
  <style>
    html, body {
      margin: 0 !important;
      padding: 0 !important;
      width: 1400px !important;
      height: 560px !important;
      overflow: hidden !important;
      background: #050b17 !important;
    }
  </style>
</head>`;

    const mainEnd = html.lastIndexOf('</main>');
    let mainContent = html.substring(mainStart, mainEnd + 7).trim();
    mainContent = mainContent.replace('rounded-2xl', 'rounded-none');
    mainContent = mainContent.replace('border border-slate-800', 'border-0');
    mainContent = mainContent.replace('shadow-[0_25px_60px_rgba(0,0,0,0.8)]', '');

    const cleanHtml = `${head}
<body class="w-[1400px] h-[560px] overflow-hidden m-0 p-0">
  ${mainContent}
</body>
</html>`;
    fs.writeFileSync(path.join(assetsDir, 'marquee_v2_clean.html'), cleanHtml, 'utf8');
    console.log('Created marquee_v2_clean.html');
  }
}
