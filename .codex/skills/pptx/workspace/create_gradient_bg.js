const sharp = require('sharp');

async function createGradientBackground() {
  // Create gradient similar to the user's image: mint/teal to coral/pink
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">
    <defs>
      <linearGradient id="g1" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" style="stop-color:#5DD9C1;stop-opacity:1" />
        <stop offset="30%" style="stop-color:#7DCFB3;stop-opacity:1" />
        <stop offset="50%" style="stop-color:#E89BA3;stop-opacity:1" />
        <stop offset="70%" style="stop-color:#FA9189;stop-opacity:1" />
        <stop offset="100%" style="stop-color:#FF7B7B;stop-opacity:1" />
      </linearGradient>
      <filter id="blur">
        <feGaussianBlur in="SourceGraphic" stdDeviation="80" />
      </filter>
    </defs>
    <rect width="100%" height="100%" fill="url(#g1)" filter="url(#blur)"/>
  </svg>`;

  await sharp(Buffer.from(svg))
    .png()
    .toFile('gradient_background.png');

  console.log('✓ Gradient background created: gradient_background.png');
}

createGradientBackground().catch(console.error);
