/**
 * Run with Node.js to generate PNG icons from SVG.
 * node extension/icons/generate-icons.js
 *
 * Requires: npm install sharp
 * Or simply use the SVG as-is (Chrome supports SVG icons in MV3).
 */

const fs = require('fs');
const path = require('path');

const svgContent = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
  <rect width="128" height="128" rx="20" fill="#1a1b1e"/>
  <rect x="4" y="4" width="120" height="120" rx="17" fill="none" stroke="#4dabf7" stroke-width="2"/>
  <path d="M72 16L24 72h36l-8 40 52-60H68l4-36z"
        fill="#4dabf7" stroke="#4dabf7" stroke-width="1" stroke-linejoin="round"/>
</svg>`;

const sizes = [16, 48, 128];
const iconsDir = path.dirname(__filename);

// Write SVG for reference
fs.writeFileSync(path.join(iconsDir, 'icon.svg'), svgContent);
console.log('icon.svg written.');

// Try to generate PNGs with sharp if available
try {
  const sharp = require('sharp');
  Promise.all(sizes.map(size =>
    sharp(Buffer.from(svgContent))
      .resize(size, size)
      .png()
      .toFile(path.join(iconsDir, `icon${size}.png`))
      .then(() => console.log(`icon${size}.png generated`))
  )).then(() => console.log('All icons generated.'));
} catch (_) {
  console.log('sharp not installed — using SVG icon fallback.');
  console.log('To generate PNGs: npm install sharp && node extension/icons/generate-icons.js');
  // Write placeholder 1x1 PNG files so manifest doesn't error
  // A real 1-byte PNG header (transparent 1x1)
  const png1x1 = Buffer.from(
    '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489' +
    '0000000a49444154789c6260000000020001e221bc330000000049454e44ae426082',
    'hex'
  );
  sizes.forEach(size => {
    const file = path.join(iconsDir, `icon${size}.png`);
    if (!fs.existsSync(file)) fs.writeFileSync(file, png1x1);
  });
  console.log('Placeholder PNGs written. Replace with real icons before publishing.');
}
