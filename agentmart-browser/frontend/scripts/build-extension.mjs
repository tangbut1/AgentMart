/** 打包 Chrome/Edge MV3 扩展。
 *
 *  为什么要一个脚本而不是直接 vite build：MV3 的 service worker 必须是
 *  **单个 classic script**，不能用 ESM import，也不能拆出共享 chunk。所以
 *  background 单独构建并内联成一个文件；侧面板是普通 React 应用，可以正常
 *  拆包。
 *
 *  manifest.json 里不能写哈希文件名，所以 background.js 用固定名输出，
 *  侧面板的 HTML 由 Vite 自己注入带哈希的资源。
 *
 *  本版本**不常驻 content script**：抽取函数由 background 通过
 *  chrome.scripting.executeScript 按需注入，页面不被打扰，也不需要在
 *  manifest 里为一个常驻脚本申请额外权限。
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

// 2) 侧面板：HTML 入口 + React
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

// 3) 静态资源（manifest + 图标）原样拷进去
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
