# 购物参谋 · 跨平台智能购物决策平台

输入商品名称、型号或链接，一次看清京东、淘宝、天猫、拼多多、抖音商城的**真实到手价、优惠条件、售后政策差异与专业评测观点**，并给出**可解释**的购买建议。

项目有**两个版本，共用同一套核心计算与界面**，区别只在数据从哪来：

| 版本 | 版本标识 | 数据来源 | 现在能不能用 |
|------|---------|---------|-------------|
| **官方 API 架构版** | `1.0.0-api` | 各平台**开放接口** | 接口已实现，但**未实际授权接入**；没配凭据时明确显示「未接入」，不虚构数据 |
| **个人浏览器版** | `1.0.0-browser` | 你本地的浏览器会话（你本人在官方页面登录） | 任务框架、价格计算、状态机、界面都已可用；五平台**尚未用真实账号验证**，需要你本人登录后才能跑 |

两个版本**都不代领券、不代下单、不代付款**。详细边界见第 8 节，个人浏览器版的架构与验收表见 [docs/personal-browser.md](docs/personal-browser.md)。

---

## 1. 它能回答什么问题

| # | 问题 | 在哪个页面看 |
|---|------|------------|
| 1 | 这个型号在各平台有哪些可买的购买选项？ | 搜索结果 → 商品详情「跨平台购买选项」 |
| 2 | 每个平台的标价、优惠券、补贴、活动折扣、支付优惠、以旧换新分别是多少？ | 商品详情 → 「查看到手价拆解」 |
| 3 | 满足什么条件我实际付多少？哪些优惠不能叠加？哪些金额无法核实？ | 拆解弹层的「确定 / 潜在 / 待核验」三档与互斥组 |
| 4 | 各平台售后、保修、发货、正品政策有什么差别？是平台规则、店铺承诺还是商品页承诺？ | 商品详情「售后政策对照」 |
| 5 | 专业博主怎么评价这款产品？优缺点、适用人群、是否实测、有无商业合作？ | 商品详情「专业评测」/ 评测库 |
| 6 | 综合来看买哪个更合适？依据、条件与风险是什么？ | 商品详情顶部「购买建议」 |

**个人浏览器版**回答的是同一组问题，但数据来自你登录后的官方页面，因此多了三件事：
账号里已经领到的券、你能享受的国补资格、以及页面当下的真实活动价。
用法：先在首页或「平台与模型」页点平台表格里的「登录」，在弹出的可见窗口里**用你自己的账号登录**
（比价任务本身是无头跑的，没法让你输账号），然后再到「个人浏览器比价」里写下需求和预算开始。

---

## 2. 本地启动（一个端口跑完整应用）

环境要求：Python 3.11+、Node 18+。

```bash
# 1) 后端
git clone <你的仓库地址> && cd AgentMart
python -m venv .venv
source .venv/Scripts/activate        # Windows Git Bash；macOS/Linux 用 source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # 所有凭据都可留空，留空即显示「未接入」

# 2) 前端（构建产物由后端直接托管）
cd frontend
npm install
npm run build
cd ..

# 3) 启动
uvicorn app.main:app --reload --port 8000
```

打开 <http://127.0.0.1:8000> 即可。接口文档在 <http://127.0.0.1:8000/docs>。

只跑后端（不构建前端）也可以：`/api/*` 与 `/docs` 正常可用，页面访问会提示「前端未构建」。

**只想看界面与计算逻辑**：在搜索框勾选「包含演示数据」。演示数据带明显标记（`演示` 徽标、`演示数据` 提示条），不参与购买建议，也不会与真实数据混排。

### Windows 上跑个人浏览器版要注意

```bash
pip install -r requirements.txt      # 里面已含 playwright
python -m playwright install chromium
```

不装 Chromium 也能启动服务和浏览界面，但任务一开始就会在该平台记「页面打开失败」，
不会用假数据补齐。浏览器登录态默认放在 `~/.agentmart/browser-profiles/`（仓库外），
清除入口在「平台与模型」页面。

**跑任务前要先登录**：比价任务默认无头运行，没有让你输账号的地方，
所以要点平台表格里的「登录」按钮单独开一个可见窗口，由你本人在那里登录。
登录态探测只读 DOM，不碰你的账号、cookie 和验证码；窗口开着时同一平台不能同时跑任务
（同一个浏览器目录同时只能被一个窗口占用）。详见
[docs/personal-browser.md](docs/personal-browser.md) 第 6 节。

### 前端独立开发模式

```bash
cd frontend && npm run dev        # http://127.0.0.1:5173，/api 已代理到 8000
```

---

## 3. 配置说明

所有配置通过环境变量或 `.env` 读取，**源码中没有任何可用凭据**。每一项都是可选的：

| 分组 | 变量 | 说明 |
|------|------|------|
| 应用 | `APP_ENV` / `APP_HOST` / `APP_PORT` / `CORS_ORIGINS` | 运行环境与跨域白名单 |
| 数据库 | `DATABASE_URL` | 默认 `sqlite+aiosqlite:///./agentmart.db`，零配置；可换 PostgreSQL |
| 缓存 | `CACHE_TTL_SECONDS` / `CACHE_MAX_ENTRIES` | 接口响应缓存，避免重复请求平台 |
| 出站请求 | `HTTP_TIMEOUT_SECONDS` / `HTTP_MAX_RETRIES` | 平台 API 调用的超时与重试 |
| 平台凭据 | `JD_*` / `TAOBAO_*` / `PDD_*` / `DOUYIN_*` | 见第 4 节，未配置即「未接入」 |
| 评测 | `BILIBILI_SESSDATA` | 可选，仅用于启用 B 站视频搜索；不配也能解析用户提交的视频链接元数据 |
| LLM | `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | 可选，仅用于「AI 观点归纳」，界面上单独标注；不配则全部用本地规则 |
| 整理令牌 | `CURATION_ADMIN_TOKEN` | 评测整理接口的写入令牌；留空时仅 development 环境可用 |
| 浏览器版 | `AGENTMART_HOME` | 浏览器登录态与模型配置的根目录，默认 `~/.agentmart`（仓库外） |
| 浏览器版模型 | `AGENTMART_MODEL_API_KEY` / `AGENTMART_MODEL_BASE_URL` / `AGENTMART_MODEL_NAME` | 自带模型 Key；一般直接在界面「平台与模型」填写，环境变量适合 CI |

> `.env` 已被 `.gitignore` 忽略，不要提交真实凭据。

---

## 4. 平台接入状态与需要申请的权限

| 平台 | 适配器 | 状态 | 需要的环境变量 | 申请入口 |
|------|--------|------|---------------|----------|
| 京东 | `JDAdapter` | 接口已实现，未配置凭据时返回「未接入」 | `JD_APP_KEY` `JD_APP_SECRET` `JD_ACCESS_TOKEN` | <https://open.jd.com/>（开发者资质 + 联盟推广 `jd.union.open.*` 权限） |
| 淘宝 | `TaobaoAdapter` | 同上 | `TAOBAO_APP_KEY` `TAOBAO_APP_SECRET` `TAOBAO_ACCESS_TOKEN` | <https://open.taobao.com/>（应用 + 淘宝客 tbk 权限） |
| 天猫 | `TmallAdapter` | 同上 | 同淘宝（同一套开放平台凭据） | 同上 |
| 拼多多 | `PddAdapter` | 同上 | `PDD_CLIENT_ID` `PDD_CLIENT_SECRET` | <https://open.pinduoduo.com/>（DDK 商品推广 API） |
| 抖音商城 | `DouyinAdapter` | 同上 | `DOUYIN_CLIENT_KEY` `DOUYIN_CLIENT_SECRET` `DOUYIN_ACCESS_TOKEN` `DOUYIN_GOODS_SEARCH_PATH` | <https://open.douyin.com/>（电商 / 团购带货权限；搜索接口路径按应用资质填写） |
| 哔哩哔哩 | `bilibili.resolve_video` | **已可用**：解析用户提交的视频链接公开元数据 | 无（搜索能力才需要 `BILIBILI_SESSDATA`） | — |
| 抖音评测 | — | 无公开元数据接口，走「手动填写 + 整理署名」流程 | 无 | — |

> 各平台开放接口的可用范围、QPS 与返回字段以你申请到的资质为准。适配器在 `app/adapters/` 下，新增平台只需继承 `PlatformAdapter` 并注册到 `registry.py`。

---

## 5. 核心设计

### 5.1 到手价三层：确定 / 潜在 / 待核验

```
标价 + 运费
  ├─ 无条件成立的抵扣      → 确定到手价（definite_total）
  ├─ 满足条件才成立的抵扣   → 潜在到手价（potential_total）
  └─ 无法核实的金额         → 单独列示，不计入任何到手价
```

- 满减门槛、新用户专享、指定支付方式、以旧换新 → 只进「潜在」；
- 地区补贴、残值估算等无法从接口核实的金额 → 只列示，不进合计；
- 每个优惠都带 `condition`（条件）、`source_url`（来源）、`data_status`（数据性质）。

### 5.2 优惠互斥组

平台规则中「优惠券与活动价不可叠加」一类约束，由数据源声明的 `stack_group` 表达：同组只保留金额最高的一项，被舍弃的项目在拆解中注明原因。以旧换新永远只作为条件性抵扣展示。

### 5.3 同款匹配：规格不一致绝不合并

从标题提取品牌、型号词、容量、版本、成色、套装信息：

- **硬冲突**（容量 / 版本 / 成色 / 套装 / 品牌不同）→ 不合并，分别成组并给出提示；
- **软提示**（仅颜色不同）→ 合并但标注。

因此「iPhone 15 Pro 256G」与「512G」会是两个商品组，不会被平均成一个价格。

### 5.4 可解释推荐

规则引擎（`app/domain/recommendation.py`）按以下维度加权打分：

- 价格：按相对价差折算（价差 25% 以内线性衰减），不是简单取最低价；
- 售后：店铺类型（自营 / 旗舰 / 第三方）与政策覆盖度；
- 数据：真实数据比例、新鲜度、评测可核验比例。

输出 `best_overall`（综合首选）/ `cheapest`（更省钱）/ `safest`（更稳妥）三种标签，**每个建议都附带依据、生效条件与风险**。只有演示数据时，推荐会直接说明数据不足而不给结论。

### 5.5 评测五维评估

不按粉丝量排序，而按可复核维度评估：是否实测该型号、是否给出测试方法与数据、是否说明使用条件与局限、是否披露商业合作关系、观点是否有足够内容支撑。五项全部满足且评分达标才标记「建议参考」。

原文摘录、整理内容、AI 归纳三者分开呈现；AI 归纳单独标注「AI 分析（非创作者原话）」。

---

## 6. 目录结构

```
app/
  domain/        纯业务逻辑（无 IO）：价格计算、优惠互斥、规格匹配、推荐规则
  adapters/      平台适配器：统一接口 + 京东/淘宝/天猫/拼多多/抖音 + 演示数据
  infra/         安全 HTTP 客户端、限流、缓存
  reviews/       B 站元数据解析、五维评估、人工整理（curation）
  services/      搜索编排：并发调用适配器 → 分组 → 详情/对比
  browser/       个人浏览器版：profile 管理、Playwright 驱动、页面解析、编排器、落库
  routers/       API 路由：search / reviews / sources / health / browser
  database.py    SQLAlchemy 2.0 异步 ORM（默认 SQLite）
frontend/
  src/pages/     首页、搜索、商品详情、横向对比、评测库、数据来源、个人浏览器比价（3 页）
  src/components/ 设计系统与业务组件（表格/卡片双形态、拆解、推荐面板、评测卡片、购买卡片）
  src/lib/       API 客户端、类型、格式化与中文标签映射
tests/           142 个用例：价格、叠加、匹配、推荐、API、HTTP 客户端、浏览器编排与端到端
docs/            personal-browser.md —— 个人浏览器版架构、五平台验收表与安全边界
```

分层方向：`domain`（纯逻辑，可单测）→ `adapters` / `browser`（外部数据，可替换）→ `services`（编排）→ `routers`（HTTP）→ 前端。

---

## 7. 测试与构建

```bash
# 后端测试
python -m pytest                       # 142 passed（含 2 个真实 Chromium 端到端用例）

# 前端类型检查 + 生产构建
cd frontend && npm run build           # tsc --noEmit && vite build

# 接口文档
uvicorn app.main:app --port 8000       # 然后访问 /docs
```

测试覆盖重点：到手价三层的边界（含运费、互斥、以旧换新、演示折扣）、规格硬冲突不合并（容量/版本/成色/套装/品牌/尺码）、推荐打分与「数据不足时拒答」、搜索/详情/对比 API 的诚实降级、HTTP 客户端对非 http(s) 与内网地址的拦截。

个人浏览器版另覆盖：优惠门槛与互斥组、国补资格不确定只列示、视觉金额与 DOM 证据不一致被拦截、单平台失败不影响其它平台、验证码/风控记 `restricted`、登录过期等你接管、取消与预算耗尽安全停下、任务结果落库并在服务重启后回读、接口层不存在任何「领券/加购/下单/付款」端点、登录窗口与比价任务对同一登录组互斥（两个方向都有用例）、登录探测脚本里不允许出现读 cookie/输入框/密码的写法、「要不要加入专业评测」只问一次且回答后必须继续执行。

端到端用例用 `app/browser/fixtures.py` 起的本地受控页面 + 真实 Chromium，**不访问任何真实电商网站**。

---

## 8. 诚实的边界（系统明确不做的事）

- **不抓取需登录的商品页面**（API 版）：个性化价格、登录后优惠券、下单流程中的最终优惠需要账号环境；API 版只用开放接口与公开规则，不绕过登录、验证码与反爬机制。需要这些数据时用个人浏览器版，由你本人登录。
- **不代你做任何账号操作**（两个版本都一样）：不领券、不加购、不关注店铺、不发消息、不下单、不付款；不代填账号密码，不记录短信验证码，不尝试识别或绕过验证码，不伪造请求来源，不做高频抓取。
- **不虚构任何数据**：接口没数据就显示「未接入」，页面读不到就记「受限/失败」，绝不用演示数据补齐真实结论。
- **不把「看到有张券」当成「这张券你能用」**：优惠要核对商品、店铺、门槛、地区、有效期、能否叠加；核验不了就只列示，不计入到手价。国补资格无法核实时不给你一个确定的到手价。
- **不生成评测结论**：不抓取视频内容、不代创作者发言。优缺点与原文摘录由整理人填写并署名，AI 归纳单独标注。
- **不承诺价格准确**：到手价基于接口返回的标价与已声明优惠计算，实际以下单时页面显示为准。
- **演示数据不参与结论**：仅在勾选后展示，带明显标记，且只有演示数据时购买建议会说明数据不足。
- **购买链接一律指向原平台**：没有伪装成正常链接的返利/推广链接；界面上的数据来源（真实平台页面 / 你手动提供 / 测试夹具 / 演示数据）分开标注，不混排。

---

## 9. 常用 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/search?keyword=&include_demo=` | 跨平台搜索，返回商品组与各平台接入状态 |
| GET | `/api/products/detail?keyword=&group_id=&budget_max=&priority=` | 购买选项、拆解、政策、评测、推荐 |
| POST | `/api/compare` | 2-5 个商品组横向对比 |
| GET | `/api/reviews?status=&include_demo=` | 已整理评测列表 |
| POST | `/api/reviews/resolve` | 解析 B 站链接，获取真实公开元数据 |
| POST | `/api/reviews` | 提交评测链接与人工整理内容 |
| POST | `/api/reviews/{id}/curate` | 整理审核（需 `CURATION_ADMIN_TOKEN`） |
| GET | `/api/sources` `/api/platforms` | 数据来源清单与平台接入状态 |

个人浏览器版（`/api/browser/*`，边界见 [docs/personal-browser.md](docs/personal-browser.md)）：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/browser/mode` | 模式说明与边界（不代领券/不代下单/不代付款） |
| GET | `/api/browser/platforms` | 五平台配方、登录态状态、登录态存放位置 |
| POST | `/api/browser/platforms/{group}/login` | 弹出可见登录窗口（你本人登录，Agent 只探测是否登录） |
| POST | `/api/browser/platforms/{group}/login/close` | 关闭登录窗口（登录态保留） |
| POST | `/api/browser/platforms/{group}/clear` | 清除某平台浏览器登录态（删整个目录） |
| GET/POST/DELETE | `/api/browser/model` | 查看（不含 Key）/ 保存 / 删除本地模型配置 |
| POST | `/api/browser/model/test` | 测试连接与视觉能力（据实判断能否看图） |
| GET | `/api/browser/model/usage` | 本次会话模型调用与费用估算 |
| POST | `/api/browser/parse` | 解析自然语言需求（预算/类目/场景/地区） |
| POST | `/api/browser/tasks` | 创建购物任务（选平台、设上限） |
| POST | `/api/browser/tasks/{id}/start` `/cancel` | 开始执行 / 取消整个任务 |
| POST | `/api/browser/tasks/{id}/platforms/{p}/pause` `/resume` `/cancel` | 单平台暂停 / 恢复 / 取消 |
| POST | `/api/browser/tasks/{id}/answer` | 回答任务的待决问题（如是否加入专业评测） |
| POST | `/api/browser/tasks/{id}/reviews` | 运行中开关专业评测分析 |
| GET | `/api/browser/tasks` `/api/browser/tasks/{id}` | 任务列表 / 实时状态（重启后从库里回读） |
| GET | `/api/browser/tasks/{id}/result` | 购买卡片、横向对比、购买建议 |

---

## 10. 技术栈

**后端** FastAPI · Pydantic v2 · SQLAlchemy 2.0（异步）· SQLite · httpx · loguru · cachetools · Playwright（个人浏览器版）
**前端** Vite · React 18 · TypeScript · react-router（HashRouter）
**测试** pytest + pytest-asyncio（含真实 Chromium 端到端）

设计上刻意避开了「AI 产品黑底 + 紫蓝渐变 + 发光玻璃卡片」的套路：暖白纸感底色、松绿主色、陶土橙价格色、细分隔线、表格用等宽数字，信息密度优先，桌面端密集表格、移动端重组成卡片。
