import fs from 'fs';
import path from 'path';
import { GoogleGenAI } from '@google/genai';
import ffmpegPath from 'ffmpeg-static';
import { spawn } from 'child_process';

const envContent = fs.readFileSync('.env', 'utf8');
const match = envContent.match(/GEMINI_API_KEY\s*=\s*(.+)/);
if (!match || !match[1].trim()) {
  console.error('Error: GEMINI_API_KEY not found in .env');
  process.exit(1);
}
const apiKey = match[1].trim();
const ai = new GoogleGenAI({ vertexai: false, apiKey });

const assetsDir = path.resolve('chrome-store-assets');

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// 1. Audio Generation
async function generateAudio() {
  console.log('--- [1/3] Generating Mandarin AI Voiceover via Gemini 3.8 Flash TTS ---');
  const ttsUrl = `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash-tts:generateContent?key=${apiKey}`;
  const scriptText = '上班摸魚不露餡！台股盤中爆量雷達、突破點火即時推播，打工人專屬的看盤神器，當沖吧，牛馬仔！';

  const body = {
    contents: [
      { parts: [{ text: scriptText }] }
    ],
    generationConfig: {
      responseModalities: ['AUDIO'],
      speechConfig: {
        voiceConfig: {
          prebuiltVoiceConfig: {
            voiceName: 'Puck'
          }
        }
      }
    }
  };

  const res = await fetch(ttsUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });

  const data = await res.json();
  if (data.candidates && data.candidates[0].content && data.candidates[0].content.parts) {
    const part = data.candidates[0].content.parts.find(p => p.inlineData && p.inlineData.mimeType && p.inlineData.mimeType.startsWith('audio'));
    if (part) {
      const audioBuffer = Buffer.from(part.inlineData.data, 'base64');
      const wavPath = path.join(assetsDir, 'promo_voice.wav');
      fs.writeFileSync(wavPath, audioBuffer);
      console.log(`✓ Audio saved: ${wavPath} (${audioBuffer.length} bytes)`);
      return wavPath;
    }
  }
  throw new Error('TTS Generation failed: ' + JSON.stringify(data));
}

// 2. Video Generation via Veo 3.1
async function generateVeoVideo() {
  console.log('--- [2/3] Calling Google Veo 3.1 (veo-3.1-generate-preview) ---');
  const prompt = 'Cinematic close-up of a modern cyberpunk trading desk at night, sleek computer monitor showing Taiwan stock market charts with glowing red and green neon candlesticks, volumetric cyan and purple lighting, futuristic financial technology, 4k ultra realistic, smooth slow camera movement';
  console.log('Prompt:', prompt);

  let operation = await ai.models.generateVideos({
    model: 'veo-3.1-generate-preview',
    source: { prompt },
    config: {
      numberOfVideos: 1,
      durationSeconds: 4,
      aspectRatio: '16:9'
    }
  });

  console.log('Operation launched:', operation.name || 'started');

  let attempts = 0;
  while (!operation.done) {
    attempts++;
    process.stdout.write(`[Veo rendering ${attempts * 10}s]... \n`);
    await delay(10000);
    operation = await ai.operations.get({ operation });
  }
  console.log('✓ Veo 3.1 rendering completed!');

  if (operation.error) {
    throw new Error('Operation error: ' + JSON.stringify(operation.error));
  }

  const videos = operation.response?.generatedVideos;
  if (!videos || videos.length === 0) {
    throw new Error('No videos found in response: ' + JSON.stringify(operation.response));
  }

  const outVideoPath = path.join(assetsDir, 'veo_intro.mp4');
  console.log('Downloading video asset...');
  await ai.files.download({
    file: videos[0].video,
    downloadPath: outVideoPath
  });

  console.log(`✓ Downloaded Veo video: ${outVideoPath}`);
  return outVideoPath;
}

// 3. Combine with ffmpeg
async function combineVideoAndAudio(videoPath, audioPath) {
  console.log('--- [3/3] Combining Video and Audio with ffmpeg ---');
  const finalOutput = path.join(assetsDir, 'promo_video_test_v1.mp4');

  return new Promise((resolve, reject) => {
    // Loop the 4s video to cover the ~11s audio smoothly (loop 2 times is ~12s)
    const args = [
      '-y',
      '-stream_loop', '3',
      '-i', videoPath,
      '-i', audioPath,
      '-c:v', 'libx264',
      '-pix_fmt', 'yuv420p',
      '-c:a', 'aac',
      '-b:a', '192k',
      '-t', '11',
      finalOutput
    ];

    console.log('Running ffmpeg:', ffmpegPath, args.join(' '));
    const proc = spawn(ffmpegPath, args);

    proc.stderr.on('data', data => {
      const s = data.toString();
      if (s.includes('frame=') || s.includes('time=')) {
        process.stdout.write('.');
      }
    });

    proc.on('close', code => {
      if (code === 0) {
        console.log(`\n✓ Final Promotional Video rendered: ${finalOutput}`);
        resolve(finalOutput);
      } else {
        reject(new Error(`ffmpeg exited with code ${code}`));
      }
    });
  });
}

async function main() {
  try {
    const audioPath = await generateAudio();
    const videoPath = await generateVeoVideo();
    const finalVideo = await combineVideoAndAudio(videoPath, audioPath);
    console.log('====================================================');
    console.log('SUCCESS! First promotional demo video ready:');
    console.log(finalVideo);
    console.log('====================================================');
  } catch (err) {
    console.error('Execution Error:', err);
    // If attached op failed, try a fresh one
    if (err.message && err.message.includes('operations/')) {
      console.log('Retrying with a fresh Veo operation...');
      const videoPath = await generateVeoVideo(null);
      const audioPath = path.join(assetsDir, 'promo_voice.wav');
      await combineVideoAndAudio(videoPath, audioPath);
    } else {
      process.exit(1);
    }
  }
}

main();
