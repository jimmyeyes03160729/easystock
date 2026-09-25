import { mkdir, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';

const dir = resolve('chrome-store-assets');
await mkdir(dir, { recursive: true });

const assets = [
  {
    name: 'marquee_raw.png',
    url: 'https://lh3.googleusercontent.com/aida/AEtjO1X5MFo8Utv_mlUpRENGgTRj8eepho5Wez0z-8V5ap0RFMkHUK2I8GHgx-GpsinoafWOQFqF-ClI1-8P0jtKaeVQ366VfUaYjUHd9YmVj1loJN_tgGmevVGuLXhpResF7-Fsh8-TDCwHNFXDhU7braL0NatYsDmR6m7qUu-0ZM6DjO6-sMcE3FU5Jic0sh8z228zpaVEGmiZT1rhyNdUaqCDRUDscprJ2UNukFmGiTDAm8HY8EI8nZUzra0'
  },
  {
    name: 'small_raw.png',
    url: 'https://lh3.googleusercontent.com/aida/AEtjO1U_JDUYOxSCFwaqS83QRTrKI8Q_20zLom8PAmjk79HxtibCjJ2WmbWz_tKgVxkcRA72Vhti4NHN-3_Y1sFFm-EO5NtnuzjvgYLwiC96Esc6ZVV4HbJ_duU2sDPhMFNSw8ND-_l5QFsRRu0Yi7UZvNIVPJorUZmHxwkipR7zaEUliDK9phdpo9zJoEv8KvUkHwRO_yhkA7vTwUwCJHGiTpqQUjIhnfw4cW4i-rmweVjZPp1URDPK_UeD3AM'
  },
  {
    name: 'screen_raw.png',
    url: 'https://lh3.googleusercontent.com/aida/AEtjO1UGU1kVkt_Is52upMLY8YuJPBjP2MSD3kT9MFHzGBTsaGFTWmOq3CC6eTtf7GElp-GAZ78ZeseTf2PCWrTr-v4BdmPifzuoAoEf5uVihwUAGn_K1uA7QFkJ1GKjpi4vSGj9YdtpFYk5HuulOWkCK-oxqijUQcizEyCoxpGpE4_R6iccpc3BzQJ5NekYC26aAXc9XO0V3uVevzJXXpIDLwfgNXdbB4-9Qr7un9HTWkAjN_3iGFsayqpG_y8'
  }
];

for (const item of assets) {
  console.log(`Downloading ${item.name}...`);
  const res = await fetch(item.url);
  if (!res.ok) throw new Error(`Failed to fetch ${item.url}: ${res.statusText}`);
  const buf = Buffer.from(await res.arrayBuffer());
  await writeFile(join(dir, item.name), buf);
  console.log(`Saved ${item.name} (${buf.length} bytes)`);
}

console.log('All downloads completed!');
