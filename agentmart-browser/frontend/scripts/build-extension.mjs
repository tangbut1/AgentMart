/** 打包 Chrome/Edge MV3 扩展。
 *
 *  为什么要一个脚本而不是直接 vite build：MV3 的 service worker 和 content
 *  script 都必须是**单个 classic script**，不能用 ESM import，也不能拆出共享
 *  chunk。所以 background 和 content script 各自单独构建并内联成一个文件；
 *  侧面板是普通 React 应用，可以正常拆包。
 *
 *  manifest.json 里不能写哈希文件名，所以这两个脚本都用固定名输出，
 *  侧面板的 HTML 由 Vite 自己注入带哈希的资源。
 *
 *  content script 是常驻的：它负责在商品页加载完（以及 SPA 换页）时把一份
 *  轻量指纹报给 service worker，让侧边栏不用用户手点「读取」就能并排展示
 *  同款。它只跑在 manifest 列出的五个平台域名下，且只读页面、不碰账号信息。
 *  需要按详情页现抽字段时，仍由 background 用 chrome.scripting.executeScript
 *  按需注入 extractPage.ts，不依赖这个常驻脚本。
 *
 *  用法：
 *    node scripts/build-extension.mjs                     # → dist-extension/
 *    AGENTMART_EXT_DEV=1 node scripts/build-extension.mjs # 额外允许
 *    localhost，供端到端测试打本地夹具页
 */
import { build } from "vite";
import react from "@vitejs/plugin-react";
import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const EXT_DIR = join(ROOT, "extension");
const OUT_DIR = join(ROOT, "dist-extension");
const DEV = process.env.AGENTMART_EXT_DEV === "1";

const SHARED = {
  root: ROOT,
  configFile: false,
  logLevel: "warn",
  // 不压缩：扩展是要被人审的，压成一行没法读
  build: {
    outDir: OUT_DIR,
    emptyOutDir: false,
    minify: false,
    target: "chrome114",
  },
};

/** 清空产物目录。删不掉不致命（编辑器/安全钩子可能正握着里面的文件），
 *  后面的构建会覆盖同名文件。 */
async function cleanDir(dir) {
  try {
    await rm(dir, { recursive: true, force: true });
  } catch {
    /* 忽略：继续构建 */
  }
  await mkdir(dir, { recursive: true });
}

await cleanDir(OUT_DIR);

// 1) background：单个 IIFE，不拆 chunk、不动态 import
await build({
  ...SHARED,
  build: {
    ...SHARED.build,
    rollupOptions: {
      input: join(EXT_DIR, "background", "index.ts"),
      output: {
        format: "iife",
        inlineDynamicImports: true,
        entryFileNames: "background.js",
      },
      preserveEntrySignatures: false,
    },
  },
});

// 2) 常驻内容脚本：同样单个 IIFE，不拆 chunk、不动态 import
await build({
  ...SHARED,
  build: {
    ...SHARED.build,
    rollupOptions: {
      input: join(EXT_DIR, "content", "session.ts"),
      output: {
        format: "iife",
        inlineDynamicImports: true,
        entryFileNames: "content-session.js",
      },
      preserveEntrySignatures: false,
    },
  },
});

// 3) 侧面板：HTML 入口 + React
await build({
  ...SHARED,
  // root 指到 extension/，HTML 就会直接落在产物根目录，
  // 文件名就是 manifest 里写的 sidepanel.html
  root: EXT_DIR,
  base: "./",
  plugins: [react()],
  build: {
    ...SHARED.build,
    publicDir: false,
    rollupOptions: {
      input: { sidepanel: join(EXT_DIR, "sidepanel.html") },
      output: {
        entryFileNames: "assets/[name]-[hash].js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
      },
    },
  },
});

// 4) 静态资源（manifest + 图标）原样拷进去
await cp(join(EXT_DIR, "static"), OUT_DIR, { recursive: true });

if (DEV) {
  const manifestPath = join(OUT_DIR, "manifest.json");
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  manifest.host_permissions = [
    ...manifest.host_permissions,
    "*://localhost/*",
    "*://127.0.0.1/*",
  ];
  await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  process.stdout.write(
    "dev build: 已追加 localhost / 127.0.0.1 主机权限（仅供端到端测试）\n",
  );
}

process.stdout.write(`扩展已打包到 ${OUT_DIR}\n`);
