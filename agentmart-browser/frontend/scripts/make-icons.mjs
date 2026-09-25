/** 生成扩展图标（16/32/48/128 PNG）。
 *
 *  没有图片依赖：直接往 RGBA 缓冲里画几个矩形和圆，再用 zlib 压成 PNG。
 *  图形取自主品牌的「秤」——一根立柱、一根横梁、两个托盘，和侧面板里
 *  用的 Icon name="scale" 是同一个意思。
 */
import { deflateSync } from "node:zlib";
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT_DIR = join(ROOT, "extension", "static", "icons");

const BRAND = [0x1d, 0x5c, 0x4f];
const WHITE = [0xff, 0xff, 0xff];

function crc32(buffer) {
  let crc = ~0;
  for (const byte of buffer) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return ~crc >>> 0;
}

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, crc]);
}

function encodePng(width, height, rgba) {
  const raw = Buffer.alloc(height * (1 + width * 4));
  for (let y = 0; y < height; y += 1) {
    const rowStart = y * (1 + width * 4);
    raw[rowStart] = 0; // filter: none
    rgba.copy(raw, rowStart + 1, y * width * 4, (y + 1) * width * 4);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // colour type: truecolour + alpha
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

class Canvas {
  constructor(size) {
    this.size = size;
    this.pixels = Buffer.alloc(size * size * 4, 0);
  }

  set(x, y, [r, g, b], alpha = 255) {
    if (x < 0 || y < 0 || x >= this.size || y >= this.size) return;
    const index = (y * this.size + x) * 4;
    // 直接覆盖（图形之间不重叠，不需要混合）
    this.pixels[index] = r;
    this.pixels[index + 1] = g;
    this.pixels[index + 2] = b;
    this.pixels[index + 3] = alpha;
  }

  rect(x0, y0, x1, y1, color, alpha = 255) {
    for (let y = Math.round(y0); y < Math.round(y1); y += 1) {
      for (let x = Math.round(x0); x < Math.round(x1); x += 1) {
        this.set(x, y, color, alpha);
      }
    }
  }

  disc(cx, cy, radius, color, alpha = 255) {
    for (let y = Math.floor(cy - radius); y <= Math.ceil(cy + radius); y += 1) {
      for (let x = Math.floor(cx - radius); x <= Math.ceil(cx + radius); x += 1) {
        const dx = x + 0.5 - cx;
        const dy = y + 0.5 - cy;
        if (dx * dx + dy * dy <= radius * radius) this.set(x, y, color, alpha);
      }
    }
  }

  /** 圆角矩形：四角切掉 */
  rounded(x0, y0, x1, y1, radius, color) {
    this.rect(x0 + radius, y0, x1 - radius, y1, color);
    this.rect(x0, y0 + radius, x1, y1 - radius, color);
    for (const [cx, cy] of [
      [x0 + radius, y0 + radius],
      [x1 - radius, y0 + radius],
      [x0 + radius, y1 - radius],
      [x1 - radius, y1 - radius],
    ]) {
      this.disc(cx, cy, radius, color);
    }
    // 把圆外四角清空
    for (const [cx, cy, sx, sy] of [
      [x0 + radius, y0 + radius, -1, -1],
      [x1 - radius, y0 + radius, 1, -1],
      [x0 + radius, y1 - radius, -1, 1],
      [x1 - radius, y1 - radius, 1, 1],
    ]) {
      for (let y = 0; y < radius; y += 1) {
        for (let x = 0; x < radius; x += 1) {
          const px = cx + sx * (radius - x);
          const py = cy + sy * (radius - y);
          const dx = px + 0.5 - cx;
          const dy = py + 0.5 - cy;
          if (dx * dx + dy * dy > radius * radius) this.set(px, py, [0, 0, 0], 0);
        }
      }
    }
  }
}

function drawIcon(size) {
  const canvas = new Canvas(size);
  const pad = size * 0.08;
  const radius = size * 0.22;
  canvas.rounded(pad, pad, size - pad, size - pad, radius, BRAND);

  const unit = size / 128;
  const cx = size / 2;
  // 立柱
  canvas.rect(cx - 3 * unit, 30 * unit, cx + 3 * unit, 92 * unit, WHITE);
  // 横梁
  canvas.rect(28 * unit, 34 * unit, 100 * unit, 40 * unit, WHITE);
  // 两个托盘
  canvas.disc(28 * unit, 52 * unit, 9 * unit, WHITE);
  canvas.disc(100 * unit, 52 * unit, 9 * unit, WHITE);
  // 底座
  canvas.rect(38 * unit, 96 * unit, 90 * unit, 102 * unit, WHITE);
  return canvas;
}

mkdirSync(OUT_DIR, { recursive: true });
for (const size of [16, 32, 48, 128]) {
  const canvas = drawIcon(size);
  const file = join(OUT_DIR, `icon-${size}.png`);
  writeFileSync(file, encodePng(size, size, canvas.pixels));
  process.stdout.write(`wrote ${file}\n`);
}
