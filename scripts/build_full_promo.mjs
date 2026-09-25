import fs from 'fs';
import path from 'path';
import puppeteer from 'puppeteer-core';
import ffmpegPath from 'ffmpeg-static';
import { spawn } from 'child_process';

const assetsDir = path.resolve('chrome-store-assets');
const edgePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';

function runFfmpeg(args, desc = 'FFmpeg') {
  return new Promise((resolve, reject) => {
    console.log(`[${desc}] Starting...`);
    const proc = spawn(ffmpegPath, args);
    let stderr = '';
    proc.stderr.on('data', d => { stderr += d.toString(); });
    proc.on('close', code => {
      if (code === 0) {
        console.log(`✓ [${desc}] Done!`);
        resolve();
      } else {
        console.error(`✗ [${desc}] Failed with code ${code}`);
        console.error(stderr.slice(-600));
        reject(new Error(`FFmpeg failed: ${code}`));
      }
    });
  });
}

// 1. Build Scene 1: Veo 3.1 slow motion (30fps) + Cyber HUD Overlay + Voice 1
async function buildScene1(browser) {
  console.log('=== Step 1: Rendering Scene 1 (Veo 3.1 Intro + Cyber HUD) ===');
  
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 720 });
  const overlayHtml = path.join(assetsDir, 'scene1_overlay.html');
  await page.goto(`file:///${overlayHtml.replace(/\\/g, '/')}`, { waitUntil: 'networkidle0' });
  const overlayPng = path.join(assetsDir, 'scene1_overlay.png');
  await page.screenshot({ path: overlayPng, omitBackground: true });
  await page.close();
  console.log('✓ Scene 1 overlay rendered.');

  const veoVideo = path.join(assetsDir, 'veo_intro.mp4');
  const voice1 = path.join(assetsDir, 'voice_part1.wav');
  const outScene1 = path.join(assetsDir, 'temp_scene1.mp4');

  const args = [
    '-y',
    '-i', veoVideo,
    '-i', overlayPng,
    '-i', voice1,
    '-filter_complex',
    '[0:v]setpts=1.5*PTS,scale=1280:720,fps=30[bg];[bg][1:v]overlay=0:0[v];[2:a]aformat=sample_rates=48000:channel_layouts=stereo,apad=pad_dur=1.0[a]',
    '-map', '[v]',
    '-map', '[a]',
    '-c:v', 'libx264',
    '-pix_fmt', 'yuv420p',
    '-r', '30',
    '-c:a', 'aac',
    '-b:a', '192k',
    '-ar', '48000',
    '-ac', '2',
    '-t', '6.0',
    outScene1
  ];

  await runFfmpeg(args, 'Scene 1 Composite');
  return outScene1;
}

// 2. Build Scene 2: Interactive Demo (300 frames @ 30fps) + SFX + Voice 2
async function buildScene2(browser) {
  console.log('=== Step 2: Rendering Scene 2 (Interactive UI + SFX) ===');
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 720 });
  const scene2Html = path.join(assetsDir, 'scene2_template.html');
  await page.goto(`file:///${scene2Html.replace(/\\/g, '/')}`, { waitUntil: 'networkidle0' });

  const totalFrames = 300; // 10.0s at 30 fps
  const rawScene2 = path.join(assetsDir, 'temp_scene2_raw.mp4');

  const ffmpeg = spawn(ffmpegPath, [
    '-y',
    '-f', 'image2pipe',
    '-vcodec', 'png',
    '-r', '30',
    '-i', '-',
    '-c:v', 'libx264',
    '-pix_fmt', 'yuv420p',
    '-r', '30',
    rawScene2
  ]);

  console.log(`Rendering ${totalFrames} frames for Scene 2...`);
  for (let i = 0; i < totalFrames; i++) {
    await page.evaluate((idx, total) => {
      window.renderFrame(idx, total);
    }, i, totalFrames);
    const buf = await page.screenshot({ type: 'png' });
    ffmpeg.stdin.write(buf);
    if (i % 60 === 0) process.stdout.write(`[${Math.round(i / totalFrames * 100)}%] `);
  }
  process.stdout.write('[100%]\n');
  ffmpeg.stdin.end();

  await new Promise((resolve, reject) => {
    ffmpeg.on('close', code => code === 0 ? resolve() : reject(new Error('rawScene2 failed')));
  });
  await page.close();

  // Combine raw video with Voice 2 + SFX
  const voice2 = path.join(assetsDir, 'voice_part2.wav');
  const sfxClick = path.join(assetsDir, 'sfx_click.wav');
  const sfxDing = path.join(assetsDir, 'sfx_ding.wav');
  const outScene2 = path.join(assetsDir, 'temp_scene2.mp4');

  const audioArgs = [
    '-y',
    '-i', rawScene2,
    '-i', voice2,
    '-i', sfxClick,
    '-i', sfxDing,
    '-filter_complex',
    '[2:a]adelay=3300|3300[c1];[2:a]adelay=6500|6500[c2];[3:a]adelay=6800|6800[d];[1:a][c1][c2][d]amix=inputs=4:dropout_transition=0,aformat=sample_rates=48000:channel_layouts=stereo,apad=pad_dur=1.5[aout]',
    '-map', '0:v',
    '-map', '[aout]',
    '-c:v', 'libx264',
    '-pix_fmt', 'yuv420p',
    '-r', '30',
    '-c:a', 'aac',
    '-b:a', '192k',
    '-ar', '48000',
    '-ac', '2',
    '-t', '10.0',
    outScene2
  ];

  await runFfmpeg(audioArgs, 'Scene 2 Audio Sync');
  return outScene2;
}

// 3. Build Scene 3: CTA Card (180 frames @ 30fps) + Voice 3
async function buildScene3(browser) {
  console.log('=== Step 3: Rendering Scene 3 (CTA Showcase + Voice 3) ===');
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 720 });
  const scene3Html = path.join(assetsDir, 'scene3_template.html');
  await page.goto(`file:///${scene3Html.replace(/\\/g, '/')}`, { waitUntil: 'networkidle0' });

  const totalFrames = 180; // 6.0s at 30 fps
  const rawScene3 = path.join(assetsDir, 'temp_scene3_raw.mp4');

  const ffmpeg = spawn(ffmpegPath, [
    '-y',
    '-f', 'image2pipe',
    '-vcodec', 'png',
    '-r', '30',
    '-i', '-',
    '-c:v', 'libx264',
    '-pix_fmt', 'yuv420p',
    '-r', '30',
    rawScene3
  ]);

  console.log(`Rendering ${totalFrames} frames for Scene 3...`);
  for (let i = 0; i < totalFrames; i++) {
    await page.evaluate((idx, total) => {
      window.renderFrame(idx, total);
    }, i, totalFrames);
    const buf = await page.screenshot({ type: 'png' });
    ffmpeg.stdin.write(buf);
    if (i % 60 === 0) process.stdout.write(`[${Math.round(i / totalFrames * 100)}%] `);
  }
  process.stdout.write('[100%]\n');
  ffmpeg.stdin.end();

  await new Promise((resolve, reject) => {
    ffmpeg.on('close', code => code === 0 ? resolve() : reject(new Error('rawScene3 failed')));
  });
  await page.close();

  // Combine raw video with Voice 3
  const voice3 = path.join(assetsDir, 'voice_part3.wav');
  const outScene3 = path.join(assetsDir, 'temp_scene3.mp4');

  const audioArgs = [
    '-y',
    '-i', rawScene3,
    '-i', voice3,
    '-filter_complex',
    '[1:a]aformat=sample_rates=48000:channel_layouts=stereo,apad=pad_dur=2.0[aout]',
    '-map', '0:v',
    '-map', '[aout]',
    '-c:v', 'libx264',
    '-pix_fmt', 'yuv420p',
    '-r', '30',
    '-c:a', 'aac',
    '-b:a', '192k',
    '-ar', '48000',
    '-ac', '2',
    '-t', '6.0',
    outScene3
  ];

  await runFfmpeg(audioArgs, 'Scene 3 Audio Sync');
  return outScene3;
}

// 4. Master Filter Concat
async function masterConcat(s1, s2, s3) {
  console.log('=== Step 4: Master Assembly into Final Promotional Video ===');
  const finalVideo = path.join(assetsDir, 'easystock_promo_official.mp4');

  const args = [
    '-y',
    '-i', s1,
    '-i', s2,
    '-i', s3,
    '-filter_complex',
    '[0:v][0:a][1:v][1:a][2:v][2:a]concat=n=3:v=1:a=1[v][a]',
    '-map', '[v]',
    '-map', '[a]',
    '-c:v', 'libx264',
    '-pix_fmt', 'yuv420p',
    '-r', '30',
    '-c:a', 'aac',
    '-b:a', '192k',
    finalVideo
  ];

  await runFfmpeg(args, 'Master Concat');

  // Clean temp files
  try {
    [s1, s2, s3].forEach(f => { if (fs.existsSync(f)) fs.unlinkSync(f); });
    const raw2 = path.join(assetsDir, 'temp_scene2_raw.mp4');
    const raw3 = path.join(assetsDir, 'temp_scene3_raw.mp4');
    if (fs.existsSync(raw2)) fs.unlinkSync(raw2);
    if (fs.existsSync(raw3)) fs.unlinkSync(raw3);
  } catch (e) {
    // ignore
  }

  console.log('================================================================');
  console.log('🎉 SUCCESS! Final Promotional Video produced:');
  console.log(finalVideo);
  console.log('================================================================');
  return finalVideo;
}

async function main() {
  const browser = await puppeteer.launch({
    executablePath: edgePath,
    headless: 'new'
  });

  try {
    const s1 = await buildScene1(browser);
    const s2 = await buildScene2(browser);
    const s3 = await buildScene3(browser);
    await masterConcat(s1, s2, s3);
  } catch (err) {
    console.error('Fatal error during promo build:', err);
  } finally {
    await browser.close();
  }
}

main();
