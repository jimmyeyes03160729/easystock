import fs from 'fs';
import path from 'path';

const assetsDir = path.resolve('chrome-store-assets');
const cowLogoUrl = 'https://lh3.googleusercontent.com/aida/AEtjO1WFNJ2d6YlurB4tEkdZh02fw8ijTlCvu8JpkeyMACqtpbvZmYNRBMzJMilEiWgnuyUquvodXUSG8NZgAV3WnJyB9i82WF9d2_EPpBZIEwIaFcaaqPP5QG90n0LFxY1Tu-CiPu0s4i4683M645vcl0gkQO24RbBdROVgzeHj6lpcWaXxOEg-W-9ciJZO6cJoyfgkKOC6RKsyrhavUZGV-Sv0qoU2nZeHNg09Csd5Tjl9upp5hkHNRGm2Pg';

// 1. Process small.html (440x280)
{
  let html = fs.readFileSync(path.join(assetsDir, 'small.html'), 'utf8');

  // Replace body opening and wrapping structure
  // Find the inner card <div class="relative w-[440px] h-[280px] rounded-xl ...">
  const cardStart = html.indexOf('<div class="relative w-[440px] h-[280px]');
  const cardEnd = html.indexOf('<!-- Store Preview Meta Information -->');

  if (cardStart !== -1 && cardEnd !== -1) {
    let cardContent = html.substring(cardStart, cardEnd).trim();
    // Remove rounded-xl from card
    cardContent = cardContent.replace('rounded-xl', 'rounded-none');
    cardContent = cardContent.replace('border border-sky-500/30', 'border-0');
    cardContent = cardContent.replace('shadow-[0_20px_50px_rgba(0,0,0,0.8)] glow-cyan', '');

    // Extract head
    const headEnd = html.indexOf('</head>');
    const head = html.substring(0, headEnd) + `
  <style>
    html, body {
      margin: 0 !important;
      padding: 0 !important;
      width: 440px !important;
      height: 280px !important;
      overflow: hidden !important;
      background: #070c18 !important;
    }
  </style>
</head>`;

    const cleanHtml = `${head}
<body class="w-[440px] h-[280px] overflow-hidden m-0 p-0">
  ${cardContent}
</body>
</html>`;
    fs.writeFileSync(path.join(assetsDir, 'small_clean.html'), cleanHtml, 'utf8');
    console.log('Created small_clean.html');
  }
}

// 2. Process marquee.html (1400x560)
{
  let html = fs.readFileSync(path.join(assetsDir, 'marquee.html'), 'utf8');

  // Add overrides to head
  html = html.replace('</head>', `
  <style>
    html, body {
      margin: 0 !important;
      padding: 0 !important;
      width: 1400px !important;
      height: 560px !important;
      overflow: hidden !important;
    }
    .banner-container {
      width: 1400px !important;
      height: 560px !important;
      border-radius: 0 !important;
    }
  </style>
</head>`);

  // Ensure body has no margin/padding
  html = html.replace('<body>', '<body class="m-0 p-0 overflow-hidden w-[1400px] h-[560px]">');
  fs.writeFileSync(path.join(assetsDir, 'marquee_clean.html'), html, 'utf8');
  console.log('Created marquee_clean.html');
}

// 3. Process screen.html (1280x800)
{
  let html = fs.readFileSync(path.join(assetsDir, 'screen.html'), 'utf8');

  // Replace placeholder logo with cow logo
  html = html.replace('https://www.gstatic.com/labs-code/stitch/stitch-placeholder-300x300.svg', cowLogoUrl);

  // Extract inner wrapper
  const wrapStart = html.indexOf('<div class="relative w-[1280px] h-[800px]');
  const wrapEnd = html.lastIndexOf('</body>');

  if (wrapStart !== -1 && wrapEnd !== -1) {
    let innerContent = html.substring(wrapStart, wrapEnd).trim();
    // remove rounded-xl and outer shadow/borders from main container
    innerContent = innerContent.replace('rounded-xl', 'rounded-none');
    innerContent = innerContent.replace('border border-slate-700/60', 'border-0');
    innerContent = innerContent.replace('shadow-[0_25px_60px_-15px_rgba(0,0,0,0.7)]', '');

    const headEnd = html.indexOf('</head>');
    const head = html.substring(0, headEnd) + `
  <style>
    html, body {
      margin: 0 !important;
      padding: 0 !important;
      width: 1280px !important;
      height: 800px !important;
      overflow: hidden !important;
      background: #f1f5f9 !important;
    }
  </style>
</head>`;

    const cleanHtml = `${head}
<body class="w-[1280px] h-[800px] overflow-hidden m-0 p-0">
  ${innerContent}
</body>
</html>`;
    fs.writeFileSync(path.join(assetsDir, 'screen_clean.html'), cleanHtml, 'utf8');
    console.log('Created screen_clean.html');
  }
}
