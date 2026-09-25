import fs from 'fs';
import path from 'path';

function createWavBuffer(samples, sampleRate = 44100) {
  const buffer = Buffer.alloc(44 + samples.length * 2);
  // RIFF header
  buffer.write('RIFF', 0);
  buffer.writeUInt32LE(36 + samples.length * 2, 4);
  buffer.write('WAVE', 8);
  // fmt chunk
  buffer.write('fmt ', 12);
  buffer.writeUInt32LE(16, 16); // Subchunk1Size
  buffer.writeUInt16LE(1, 20);  // PCM format
  buffer.writeUInt16LE(1, 22);  // Mono
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * 2, 28); // Byte rate
  buffer.writeUInt16LE(2, 32);  // Block align
  buffer.writeUInt16LE(16, 34); // Bits per sample
  // data chunk
  buffer.write('data', 36);
  buffer.writeUInt32LE(samples.length * 2, 40);

  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    buffer.writeInt16LE(Math.floor(s * 32767), 44 + i * 2);
  }
  return buffer;
}

// 1. Mouse Click SFX (short crisp transient, ~30ms)
function generateClick() {
  const sampleRate = 44100;
  const numSamples = Math.floor(sampleRate * 0.04);
  const samples = new Float32Array(numSamples);
  for (let i = 0; i < numSamples; i++) {
    const t = i / sampleRate;
    const decay = Math.exp(-t * 200);
    const noise = (Math.random() * 2 - 1) * 0.3;
    const tone = Math.sin(2 * Math.PI * 1800 * t);
    samples[i] = (tone * 0.7 + noise) * decay;
  }
  return createWavBuffer(samples, sampleRate);
}

// 2. Notification Ding / Chime SFX (pleasant crystal bell chime: 1046Hz -> 2093Hz C6/C7, ~0.6s)
function generateDing() {
  const sampleRate = 44100;
  const numSamples = Math.floor(sampleRate * 0.65);
  const samples = new Float32Array(numSamples);
  for (let i = 0; i < numSamples; i++) {
    const t = i / sampleRate;
    const decay = Math.exp(-t * 6);
    // Two harmonious bell frequencies (F6 and C7)
    const bell1 = Math.sin(2 * Math.PI * 1396.9 * t);
    const bell2 = Math.sin(2 * Math.PI * 2093.0 * t) * 0.6;
    const bell3 = Math.sin(2 * Math.PI * 4186.0 * t) * 0.2;
    samples[i] = (bell1 + bell2 + bell3) * decay * 0.8;
  }
  return createWavBuffer(samples, sampleRate);
}

const assetsDir = path.resolve('chrome-store-assets');
fs.writeFileSync(path.join(assetsDir, 'sfx_click.wav'), generateClick());
fs.writeFileSync(path.join(assetsDir, 'sfx_ding.wav'), generateDing());
console.log('✓ SFX generated: sfx_click.wav and sfx_ding.wav');
