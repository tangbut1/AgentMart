# 购物参谋 · AgentMart

跨平台购物**决策助手**：一次搜索，看清京东 / 淘宝 / 天猫 / 拼多多 / 抖音商城的真实到手价、
优惠条件、售后政策差异与专业评测，并给出带证据、可解释的购买建议。

> **它是决策助手，不是代下单工具。** 两个版本都不代领券、不代下单、不代付款；
> 优惠券由你自己在平台上领取，购买链接一律指向原平台真实商品页。

---

## 两个独立项目，按你的情况选一个

仓库根目录下有两个**完全独立**的项目：各自的代码、端口、数据库、依赖、
测试套件，可以分别启动、分别回滚，互不影响。

| | [`agentmart-api/`](agentmart-api/) | [`agentmart-browser/`](agentmart-browser/) |
|---|---|---|
| 版本标识 | `1.0.0-api` | `1.0.0-browser` |
| 数据来源 | 各平台**开放接口** | **你自己的浏览器**在官方页面的登录会话 |
| 需要平台资质 | **需要**：开放平台开发者资质 + 推广权限 | 不需要任何资质 |
| 能看账号可见券 / 国补资格 | 不能，接口不提供 | 能，以你本人登录后页面显示为准 |
| 账号密码 | 无账号概念 | 只进你自己的浏览器，工具不索取、不记录 |
| 默认端口 | 8000 | 8000 |
| 前端 dev 端口 | 5173 | 5174 |
| 适合谁 | 团队部署、批量、可审计 | 个人日常比价 |

**怎么选：有开放平台资质用 `agentmart-api/`；没资质但想比价用 `agentmart-browser/`。**

两个项目不共用任何东西，**不要同时占用 8000 端口**——想同时看就改其中一个的
`APP_PORT`（或启动时加 `--port`）。

两个项目共用同一套 domain 层逻辑（到手价计算、优惠互斥、同款匹配、可解释推荐），
所以结论口径一致：五档价格确定性、演示数据隔离、不捏造任何数字。

---

## 快速开始

```bash
# 个人浏览器版（不需要任何平台资质，推荐先用这个看效果）
cd agentmart-browser
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements.txt
python -m playwright install chromium
cd frontend && npm install && npm run build && cd ..
uvicorn app.main:app --reload --port 8000
# 打开 http://127.0.0.1:8000

# 官方开放接口版
cd agentmart-api
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env          # 填平台凭据；留空则界面显示「未接入」
cd frontend && npm install && npm run build && cd ..
uvicorn app.main:app --reload --port 8000
# 打开 http://127.0.0.1:8000
```

各项目的详细说明、代码地图、安全边界：

- [`agentmart-api/README.md`](agentmart-api/README.md) · [`agentmart-api/docs/architecture.md`](agentmart-api/docs/architecture.md)
- [`agentmart-browser/README.md`](agentmart-browser/README.md) · [`agentmart-browser/docs/personal-browser.md`](agentmart-browser/docs/personal-browser.md)

---

## 五档价格确定性（两个版本一致）

不混淆「看到过」和「一定适用」：

| 档位 | 含义 | 是否计入到手价 |
|---|---|---|
| 页面公开 | 商品页明示、无需任何身份条件 | 计入「确定可算」 |
| 账号券 | 已确认在你账号下、且本次可用 | 计入「确定可算」 |
| 有条件 | 页面写了条件，未验证你是否满足 | 只计入「含待确认」 |
| 预付定金 | 预售定金 + 尾款结构 | 只计入「含待确认」 |
| 无法核验 | 只有宣传口径、没有可核验证据 | 不计入，单独列出 |

金额由确定性代码计算，不让模型做心算。拿不到的数据就说拿不到，并说明原因。

---

## 共同硬性边界

- **不捏造任何价格、优惠、补贴资格或店铺政策。**
- **演示数据与真实数据严格分离**，演示报价在界面上明确标注，不参与结论。
- **购买链接指向原平台真实商品页**，没有假链接、没有站内交易。
- 商品描述、商家文案、用户评论一律视为不可信数据，不作为指令执行。
- 服务端出站请求仅允许 `http`/`https`，请求前校验 host，拒绝 localhost、环回、私有与保留地址。
- 数据库查询一律参数绑定，不用拼接 / format / f-string 组装 SQL。
- 凭据只从环境变量或密钥服务读取，源码、示例、测试里不写可用凭据字面量。
