/** manifest 与构建产物校验。
 *
 *  这一份测的是「扩展装得进 Chrome、且装进去的确实是刚构建的那份」：
 *  - manifest 是合法 MV3，声明的能力和代码里真正用到的一致；
 *  - manifest 引用的每个文件在产物里都真实存在（少一个图标扩展就装不上）；
 *  - 产物里没有任何凭据、Cookie、令牌 —— 扩展只读页面，不该也不需要它们。
 *
 *  产物不存在时（没跑过 build:extension）只测 manifest 源文件，
 *  并明确 skip 掉产物断言，不假装测过。
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import { fileURLToPath } from "node:url";

const EXT_DIR = join(fileURLToPath(new URL("..", import.meta.url)));
const STATIC_DIR = join(EXT_DIR, "static");
const DIST_DIR = join(EXT_DIR, "..", "dist-extension");

interface Manifest {
  manifest_version: number;
  name: string;
  version: string;
  description: string;
  minimum_chrome_version: string;
  permissions: string[];
  host_permissions: string[];
  background: { service_worker: string };
  side_panel: { default_path: string };
  action: { default_title: string; default_icon: Record<string, string> };
  icons: Record<string, string>;
  content_scripts?: unknown;
}

function readManifest(dir: string): Manifest {
  return JSON.parse(readFileSync(join(dir, "manifest.json"), "utf8")) as Manifest;
}

/** 递归列出目录下所有文件（相对路径）。 */
function listFiles(dir: string, prefix = ""): string[] {
  if (!existsSync(dir)) return [];
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const rel = prefix ? `${prefix}/${entry}` : entry;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...listFiles(full, rel));
    else out.push(rel);
  }
  return out;
}

const manifest = readManifest(STATIC_DIR);

describe("manifest（源文件）", () => {
  it("是 Manifest V3", () => {
    assert.equal(manifest.manifest_version, 3);
  });

  it("版本号和 package.json 一致", () => {
    const pkg = JSON.parse(
      readFileSync(join(EXT_DIR, "..", "package.json"), "utf8"),
    ) as { version: string };
    assert.equal(manifest.version, pkg.version);
  });

  it("名字和描述说清了「只读」边界", () => {
    // 用户装之前唯一能看到的承诺，必须写对：不领券、不加购、不代下单
    assert.ok(manifest.description.includes("不领券"));
    assert.ok(manifest.description.includes("不代下单"));
    assert.ok(manifest.description.includes("不代付款"));
  });

  it("申请的权限是最小集，没有越权", () => {
    // sidePanel=侧边栏 scripting=按需注入抽取函数 storage=保存用户自己填的收货地
    assert.deepEqual([...manifest.permissions].sort(), ["scripting", "sidePanel", "storage"]);
    // 明确不要的：tabs（能看到全部标签页标题）、cookies、webRequest、
    // debugger、history、bookmarks —— 一个都不该出现在比价工具里
    for (const forbidden of ["tabs", "cookies", "webRequest", "debugger", "history", "bookmarks"]) {
      assert.ok(!manifest.permissions.includes(forbidden), `不该申请 ${forbidden}`);
    }
  });

  it("不常驻 content script（按需注入，不打扰页面）", () => {
    assert.equal(manifest.content_scripts, undefined);
  });

  it("主机权限只覆盖五个商城，且没有 <all_urls>", () => {
    const hosts = manifest.host_permissions;
    assert.ok(hosts.length > 0);
    assert.ok(!hosts.includes("<all_urls>"));
    assert.ok(!hosts.includes("*://*/*"));
    for (const host of hosts) {
      assert.match(host, /^\*:\/\/\*\.[^*]+\/\*$/, `主机权限写法不最小：${host}`);
    }
    // 五个平台各自至少有一个域名在列
    const joined = hosts.join(" ");
    for (const marker of ["jd.com", "taobao.com", "tmall.com", "pinduoduo.com", "jinritemai.com"]) {
      assert.ok(joined.includes(marker), `缺少 ${marker}`);
    }
  });

  it("background 是单个 service worker 文件", () => {
    assert.equal(manifest.background.service_worker, "background.js");
  });

  it("manifest 引用的图标文件都在", () => {
    const icons = { ...manifest.icons, ...manifest.action.default_icon };
    for (const path of Object.values(icons)) {
      assert.ok(existsSync(join(STATIC_DIR, path)), `图标缺失：${path}`);
    }
  });
});

describe("构建产物 dist-extension", () => {
  const built = existsSync(join(DIST_DIR, "manifest.json"));

  it("manifest 引用的每个文件都真实存在于产物里", () => {
    if (!built) {
      // 没构建过就明说测不了，不用一个假绿糊弄过去
      assert.fail("dist-extension 不存在：请先跑 npm run build:extension");
    }
    const dist = readManifest(DIST_DIR);
    const referenced = [
      dist.background.service_worker,
      dist.side_panel.default_path,
      ...Object.values(dist.icons),
      ...Object.values(dist.action.default_icon),
    ];
    for (const path of referenced) {
      assert.ok(existsSync(join(DIST_DIR, path)), `产物缺少 ${path}`);
    }
  });

  it("侧面板 HTML 引用的资源也都在产物里", () => {
    if (!built) assert.fail("dist-extension 不存在：请先跑 npm run build:extension");
    const html = readFileSync(join(DIST_DIR, "sidepanel.html"), "utf8");
    const refs = [...html.matchAll(/(?:src|href)="\.\/([^"]+)"/g)].map((m) => m[1]);
    assert.ok(refs.length > 0, "侧面板 HTML 没有引用任何资源");
    for (const ref of refs) {
      assert.ok(existsSync(join(DIST_DIR, ref)), `产物缺少 ${ref}`);
    }
  });

  it("background.js 是单个 classic script，不含 ESM import/export", () => {
    if (!built) assert.fail("dist-extension 不存在：请先跑 npm run build:extension");
    const source = readFileSync(join(DIST_DIR, "background.js"), "utf8");
    assert.ok(source.length > 0, "background.js 是空文件");
    // MV3 service worker 不支持 ESM：有 import/export 语句 Chrome 会直接报错
    assert.ok(!/^\s*import\s/m.test(source), "background.js 里还有 import 语句");
    assert.ok(!/^\s*export\s/m.test(source), "background.js 里还有 export 语句");
    assert.ok(!/\bimport\s*\(/.test(source), "background.js 里还有动态 import");
  });

  it("产物里没有凭据、Cookie、令牌", () => {
    if (!built) assert.fail("dist-extension 不存在：请先跑 npm run build:extension");
    const files = listFiles(DIST_DIR);
    assert.ok(files.length > 0);
    // 只扫文本产物：图标是二进制，扫了也没意义
    const textFiles = files.filter((f) => /\.(js|html|json)$/.test(f));
    assert.ok(textFiles.length > 0);
    const forbidden = [
      /password\s*[:=]\s*["'][^"']+["']/i,
      /(?:api[_-]?key|secret|token)\s*[:=]\s*["'][A-Za-z0-9_\-]{16,}["']/i,
      /document\.cookie/,
      /setCookie|chrome\.cookies/,
    ];
    for (const file of textFiles) {
      const source = readFileSync(join(DIST_DIR, file), "utf8");
      for (const pattern of forbidden) {
        assert.ok(!pattern.test(source), `${file} 里出现了疑似凭据：${pattern}`);
      }
    }
  });

  it("注入页面的代码是只读的：不点击、不提交、不写存储", () => {
    if (!built) assert.fail("dist-extension 不存在：请先跑 npm run build:extension");
    // 只看扩展自己写的注入源码，而不是整个 bundle：bundle 里含有从页面
    // 解析出来的优惠文案（"支付立减""微信支付"），那是要读的文本，
    // 不是要做的动作。真正要守的边界是"不对页面做任何写操作"。
    const sources = ["content/extractPage.ts", "background/index.ts"].map((rel) =>
      readFileSync(join(EXT_DIR, rel), "utf8"),
    );
    for (const source of sources) {
      assert.ok(!/\.click\s*\(/.test(source), "出现了点击页面元素的动作");
      assert.ok(!/\.submit\s*\(/.test(source), "出现了提交表单的动作");
      assert.ok(!/dispatchEvent\s*\(/.test(source), "出现了派发事件的动作");
      assert.ok(!/document\.cookie/.test(source), "出现了读写 Cookie 的动作");
      assert.ok(!/localStorage\.setItem/.test(source), "出现了写 localStorage 的动作");
    }
  });

  it("产物不伪装自动化身份", () => {
    if (!built) assert.fail("dist-extension 不存在：请先跑 npm run build:extension");
    const source = readFileSync(join(DIST_DIR, "background.js"), "utf8");
    assert.ok(!/navigator\.webdriver\s*=\s*true/.test(source));
    assert.ok(!/delete\s+navigator\.webdriver/.test(source));
  });
});
