# 购物参谋 · 比价侧边栏（Chrome / Edge MV3 扩展）

在你**自己的浏览器**里读当前商品页，算清确定到手价和待确认优惠，并去其它平台找同款。
跑在你登录后的真实会话里，所以看到的价格、券、活动就是你自己能看到的那一份。

**它是只读的**：不领券、不加购、不代下单、不代付款；不读 cookie、不读账号信息、
不读输入框内容；不破解验证码、不伪装身份、不绕过风控。

---

## 为什么要一个扩展

服务端版（`agentmart-browser`）用 Playwright 开一个独立的浏览器上下文替你跑，
好处是能调度多个平台，代价是那个上下文**没有你的登录状态**，也带着自动化指纹，
京东/淘宝的价格和券常常看不到，还容易触发风控。

扩展换了个思路：比价逻辑搬到你正在用的那个浏览器里跑。

- 用的是你自己的登录状态和指纹，价格/券/活动的可见性和你本人完全一致；
- 没有 `navigator.webdriver = true`，不是一个"被标记过的"自动化上下文；
- 只在你点下去的那一刻读当前页，不开后台轮询，不做高频抓取。

---

## 安装（加载已解压的扩展）

```bash
cd frontend
npm install          # 首次
npm run build:extension
```

产物在 `frontend/dist-extension/`。然后：

1. Chrome / Edge 地址栏输入 `chrome://extensions`（Edge 用 `edge://extensions`）；
2. 打开右上角的**开发者模式**；
3. 点**加载已解压的扩展程序**，选 `frontend/dist-extension/` 这个目录；
4. 把扩展图标固定到工具栏，之后在任意商品页点它就会打开侧边栏。

> 只想改前端界面时 `npm run build`；动了 `extension/` 下的任何代码都要重新
> `npm run build:extension`，然后回 `chrome://extensions` 点一下该扩展的刷新。

---

## 怎么用

1. 用你自己的账号登录京东 / 淘宝 / 天猫 / 拼多多 / 抖音商城（在普通标签页里登录即可，
   扩展不碰登录流程）；
2. 打开一个商品页，点工具栏图标，侧边栏会读出这一页；
3. 填一下**收货地**（决定国补资格和运费判断，只存在 `chrome.storage.session`，不上传）；
4. 侧边栏算出这一页的确定到手价、待确认优惠、防套路提示；
5. 想比同款就勾选其它平台，扩展会**逐个平台、串行地**开搜索页找同款 ——
   一次只开少量页面，两次加载之间留间隔，保持人的节奏。

看到登录墙 / 验证码时扩展会停下来告诉你是哪个平台卡住了，不会自己去碰。
价格读不到就如实说读不到，**不留空也不猜**。

---

## 目录结构

```
extension/
├── static/
│   ├── manifest.json        # MV3 清单：权限、主机范围、入口
│   └── icons/               # 图标（构建时由 scripts/make-icons.mjs 生成）
├── content/
│   ├── extractPage.ts       # 注入页面的只读抽取函数（DOM 文本字段）
│   └── session.ts           # 常驻内容脚本：商品页抽轻量指纹报给 background
├── background/
│   ├── index.ts             # service worker：开标签页、等加载、抽取、关标签页
│   └── session.ts           # service worker：chrome.storage.session 维护会话池
├── sidepanel/
│   ├── App.tsx              # 侧面板，复用 src/components/BrowserCompare.tsx 等
│   ├── SessionBar.tsx       # 「正在对比 N 个标签页」指示条，点击跳回
│   ├── useSessionPool.ts    # 读会话池：直接读 storage + 监听 onChanged
│   ├── main.tsx
│   └── sidepanel.css
├── core/                    # 与后端 app/domain/ 逐条对应的纯逻辑（TypeScript）
│   ├── money.ts             #   整数「分」+ 银行家舍入，和 Python Decimal 一致
│   ├── discount.ts          #   优惠文案解释（门槛/比例/封顶/归属层级/确定性）
│   ├── pricing.ts           #   确定价 / 潜在价 / 待核实价 + 公开轨 / 我的轨
│   ├── couponTree.ts        #   优惠券树：按层级摊开，标出 counted / beaten_by
│   ├── subsidy.ts           #   国补：两种情形都算出来，不合并
│   ├── traps.ts             #   防套路：激活不退、非国行、不退不换、运费险
│   ├── grouping.ts          #   跨平台同款归组（保守匹配）
│   ├── modelTokens.ts       #   从标题/规格里挑「像型号」的 token
│   ├── session.ts           #   会话池纯逻辑：聚类、增删、激活（不碰 chrome/DOM）
│   ├── sessionOffers.ts     #   池子条目 → OfferView（只有侧面板用）
│   ├── platforms.ts         #   五个平台的搜索/商品 URL 配方
│   ├── offer.ts / model.ts / serialize.ts / text.ts / index.ts
├── protocol.ts              # 侧面板 ↔ service worker 的消息协议
├── sidepanel.html
└── tests/
    ├── *.test.ts            # node --test 单元测试
    ├── manifest.test.ts     # manifest 与构建产物校验
    ├── corpus/page-fields.json   # 与后端共用的 27 条页面语料
    └── parity-emit.ts       # 供 Python 侧一致性校验调用
```

`core/` 是这份扩展的重心：它和后端 `app/domain/` 是**同一套规则的两次实现**
（一次 Python 跑在服务端，一次 TypeScript 跑在你浏览器里）。两边必须对同一个页面
给出同一个结论，所以有 `agentmart-browser/tests/test_extension_parity.py`
逐字段比对，语料就是上面那份 `page-fields.json`。

---

## 为什么 background 要单独构建

MV3 的 service worker 必须是**单个 classic script**：不能用 ESM `import`，
也不能拆出共享 chunk。所以 `scripts/build-extension.mjs` 把 `background/index.ts`
单独打成 `format: "iife"` + `inlineDynamicImports` 的 `background.js`（固定文件名，
manifest 里要写死）；侧面板是普通 React 应用，走 Vite 正常拆包，HTML 由 Vite
自己注入带哈希的资源。

产物**不压缩** —— 扩展是要被人审的，压成一行没法读。

---

## 权限与边界

`manifest.json` 申请的权限是最小集：

| 权限 | 用途 |
| --- | --- |
| `sidePanel` | 侧边栏 |
| `scripting` | 按需把只读抽取函数注入当前标签页 |
| `storage` | 存你自己填的收货地、上次读的那一页，以及跨标签页的会话池 |

主机权限只覆盖五个商城的域名，**没有 `<all_urls>`**。
明确没有申请的：`tabs`（能看到全部标签页标题）、`cookies`、`webRequest`、
`debugger`、`history`、`bookmarks`。

**常驻一个轻量 content script**（`content-session.js`），只跑在五个商城的域名下。
它干的事很窄：商品页加载完（以及 SPA 换页）时抽一份轻量指纹 —— URL、标题、
平台、型号 token —— 报给 service worker，让侧边栏不用你手点「读取」就能并排
展示同款。它只读页面，不点按钮、不提交表单、不读输入框、不读 cookie、
不改 DOM，也不轮询。

需要按详情页现抽字段时，仍由 background 通过
`chrome.scripting.executeScript` 按需注入 `extractPage.ts`，走的是原来那条路。

登录状态**只在浏览器自己手里**。扩展不读 cookie，不把登录态发给任何服务端，
模型也拿不到 cookie、完整鉴权状态或支付信息。页面上的商品文案、商家介绍和评价
一律当作不可信内容，不当成指令。

---

## 购物会话记忆池（跨标签页自动感知）

阶段一的能力：你在几个平台的同款商品页之间来回切，侧边栏一打开就已经并排摆好，
全程不用点「读取」。

```
内容脚本（每个商品页）
   └─ 抽轻量指纹 ──► service worker
                       ├─ chrome.storage.session 维护池子（纯 JSON 元数据）
                       ├─ chrome.tabs.onRemoved  关标签页 → 撤掉那一项
                       └─ chrome.tabs.onActivated 切标签页 → 标「(当前)」
侧边栏 ◄── 直接读 storage.session + 监听 onChanged（不等消息，更新更快）
```

几个设计取舍，都是为了「不把不同的商品说成同款」：

- **锚点固定**：一组的身份取最早进池子那个条目的型号 token，后来加入的只跟它比。
  用「进池时间」而不是「最近活跃」排序 —— 后者会被「用户切回旧标签页」改写，
  锚点跟着飘，XM5 和 XM4 就会被并成一组。
- **认不出型号的自成一组**：两个都没认出型号的页面不会因为「都没认出」而被归到一起。
- **部分重合必须报警**：组里只要有页面的型号和其他页面不完全一致，侧边栏就带着
  「规格可能不同」展示，不默默摆成一副能比的样子。
- **写操作串成一条链**：`storage.session` 的读写是异步的，连关两个标签页时若各自
  读-改-写，第二个就关不掉。

池子有容量上限（24 个标签页），超出丢最早不活跃的；当前活动的那个不会被丢。
`chrome.storage.session` 随浏览器会话清空，不落盘、不同步到账号。

---

## 测试

```bash
cd frontend
npm run test:extension      # node --test extension/tests/*.test.ts
npm run build:extension     # tsc --noEmit + 打包（typecheck 也在这步）
```

扩展侧 190 项单元测试 + manifest/产物校验。其中 `session.test.ts` 覆盖会话池的
聚类/增删/激活/容量，`sessionFlow.test.ts` 用假的 `chrome.storage.session`
把「内容脚本上报 → service worker 维护池子 → 侧边栏摆出对比」整条路跑通，
不需要真开浏览器。跨语言一致性在仓库根跑：

```bash
cd agentmart-browser
.venv/Scripts/python.exe -m pytest tests/test_extension_parity.py
```

那份测试把同一份语料分别喂给 Python 和 TypeScript，逐字段比对 `OfferView`。
它本身也被变异验证过：改一边的舍入方式、改优惠分支、改上面说的去重逻辑，
测试都会带着字段级差异失败，而不是安静地通过。

---

## 已知边界

- **只支持五个平台**：京东、淘宝、天猫、拼多多、抖音商城。其它站点不会去读。
- **跨平台同款匹配仅依据标题与规格文本**：没有品牌库、参数库的多路归一，
  认不出是同款就单独列出来并说明，不为了凑一个对比表把两件不同的商品排在一起。
- **国补永远不进"确定到手价"**：资格取决于收货地、品类、能效等级、是否已领取，
  这些都无法从商品页确认，所以两种情形都算出来让你自己对照。
- **读不到价格就留空**：宁可少给一个数，不给一个编的数。
