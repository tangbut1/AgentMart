"""五平台的浏览器任务配方：URL、登录探测、风控探测、确定性字段抽取。

设计原则：
- **确定性优先**：所有字段先用 DOM 规则（JSON-LD / 常见选择器 / 文本正则）
  抽取，不消耗模型调用；只有在规则失败时才让视觉模型介入；
- **只读**：配方里没有任何会改变账号状态的动作（不领券、不加购、不下单）；
- **不猜**：抽不到的字段就留空并记录原因，绝不用常见值填充；
- **可测**：本地夹具页面（``app/browser/fixtures.py``）实现同一套结构，
  因此测试走的是与真实站点相同的代码路径。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List
from urllib.parse import quote_plus

from ..domain.enums import Platform

# ─── 通用探测脚本（在页面上下文执行，只读 DOM，不读取输入框内容） ───

# 登录状态探测：只判断"是否存在登录入口/是否找不到用户标识"，
# 绝不读取账号、手机号或任何个人信息。
JS_LOGIN_PROBE = r"""
() => {
  const text = (document.body && document.body.innerText || '').slice(0, 4000);
  const hasLoginEntry = /请登录|登录\/注册|立即登录|请先登录|去登录/.test(text);
  const loginLink = !!document.querySelector(
    'a[href*="login"], a[href*="Login"], .login, .login-info, #loginname'
  );
  // 用户标识元素（出现通常意味着已登录）
  const userMark = !!document.querySelector(
    '[class*="nick"], [class*="user-name"], [class*="username"], ' +
    '[class*="avatar"], .user-center, [class*="member"]'
  );
  // 三条同时满足才认为已登录：出现用户标识、没有登录文案、没有登录入口。
  // 任何一条不满足都按未登录处理（宁可多等一次用户接管，不可误判已登录）。
  const looksLoggedIn = userMark && !hasLoginEntry && !loginLink;
  return { hasLoginEntry, hasUserMark: userMark, looksLoggedIn };
}
"""

# 风控/验证码探测
# 三个信号分开报，因为给用户的原因必须准确——说错原因比没有原因更糟：
#
# 1. captcha：页面明确是验证码/滑块。
# 2. risk：被平台限制。京东限流页原文是「抱歉由于访问频繁导致无法搜索，
#    请稍后再试」，早期正则只写「访问过于频繁」，匹配不上，于是把限流误报成
#    "页面结构可能已变化或需要登录"——告诉用户一个错误的原因，他照着去
#    重新登录也不会好。京东的验证页会跳到
#    cfe.m.jd.com/privatedomain/risk_handler/...，那种页面只有"验证一下"和
#    "前往登录"，文案匹配不上，只能靠 URL 认。
# 3. unavailable：搜索端点本身挂了，返回 502/504 的网关错误页（抖音
#    haohuo.jinritemai.com/search 实测就是这样）。页面里没有任何商品，
#    但也不能说成"页面结构无法识别"。
JS_BLOCKED_PROBE = r"""
() => {
  const text = (document.body && document.body.innerText || '').slice(0, 3000);
  const title = document.title || '';
  const url = location.href;
  const captcha = /验证码|滑块|安全验证|人机识别|请完成验证|nc_icon|punish/.test(text)
    || /captcha|punish|verify/.test(url);
  const risk = /访问过于频繁|操作过于频繁|访问频繁|无法搜索|稍后再试|刷新太重|系统繁忙|异常流量|风控|已被限制|暂时无法/.test(text)
    || /risk_handler|privatedomain|risk_verify|slider_verify/.test(url);
  const unavailable = /502 Bad Gateway|504 Gateway|Bad Gateway|Gateway Time-?out|TLB|服务繁忙|系统维护/.test(text)
    || /^(502|503|504)\b/.test(title);
  const loginWall = /请登录后查看|登录后可见|请先登录/.test(text);
  return { captcha, risk, unavailable, loginWall };
}
"""

# 商品链接候选抽取：从搜索结果页收集可能的商品链接
JS_PRODUCT_LINKS = r"""
(maxLinks) => {
  const out = [];
  const seen = new Set();
  const anchors = Array.from(document.querySelectorAll('a[href]'));
  for (const a of anchors) {
    const href = a.href || '';
    if (!/^https?:/.test(href)) continue;
    if (seen.has(href)) continue;
    const title = (a.innerText || a.getAttribute('title') || '').trim();
    if (title.length < 6) continue;
    // 只收看起来像商品详情页的链接
    const looksLikeItem = /item\.|\/product[./]|\/detail\/|\/goods\/|\/sku\/|id=\d{4,}|\/p\/|haohuo\./.test(href);
    if (!looksLikeItem) continue;
    seen.add(href);
    out.push({ url: href, title: title.slice(0, 120) });
    if (out.length >= maxLinks) break;
  }
  return out;
}
"""

# 商品字段抽取：返回结构化字段 + 每字段的定位证据
JS_PRODUCT_FIELDS = r"""
() => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const evidence = {};
  const pick = (selectors) => {
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && clean(el.innerText || el.textContent)) {
        evidence[sel] = clean(el.innerText || el.textContent).slice(0, 200);
        return clean(el.innerText || el.textContent);
      }
    }
    return null;
  };

  // 1) JSON-LD（最可靠的结构化来源）
  let jsonld = null;
  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const data = JSON.parse(script.textContent);
      const nodes = Array.isArray(data) ? data : [data];
      for (const node of nodes) {
        if (node && (node['@type'] === 'Product' || node['@type'] === 'product')) {
          jsonld = node; break;
        }
      }
    } catch (e) { /* 忽略单个脚本解析失败 */ }
    if (jsonld) break;
  }
  if (jsonld) evidence['jsonld:Product'] = JSON.stringify(jsonld).slice(0, 300);

  const bodyText = clean(document.body ? document.body.innerText : '').slice(0, 20000);

  // 2) 标题
  let title = clean(document.title);
  const ogTitle = document.querySelector('meta[property="og:title"]');
  if (ogTitle && ogTitle.content) { title = clean(ogTitle.content); evidence['meta:og:title'] = title; }
  const h1 = document.querySelector('h1');
  if (h1 && clean(h1.innerText).length > 4) { title = clean(h1.innerText); evidence['h1'] = title; }
  if (jsonld && jsonld.name) { title = clean(jsonld.name); evidence['jsonld:name'] = title; }

  // 3) 价格：优先 JSON-LD offers，再常见选择器，最后文本正则
  let priceText = null;
  let priceEvidence = null;
  if (jsonld && jsonld.offers) {
    const offers = Array.isArray(jsonld.offers) ? jsonld.offers : [jsonld.offers];
    for (const o of offers) {
      if (o && (o.price || o.lowPrice)) {
        priceText = String(o.price || o.lowPrice);
        priceEvidence = 'jsonld:offers.price=' + priceText;
        break;
      }
    }
  }
  if (!priceText) {
    const v = pick(['.price', '[class*="price"]', '[id*="price"]', '.p-price', '.Price',
                    '[class*="Price"]', '[data-price]']);
    if (v) { priceText = v; priceEvidence = 'selector'; }
    const withData = document.querySelector('[data-price]');
    if (!priceText && withData) { priceText = withData.getAttribute('data-price'); priceEvidence = 'data-price'; }
  }
  if (!priceText) {
    const m = bodyText.match(/[¥￥]\s*([0-9]+(?:\.[0-9]{1,2})?)/);
    if (m) { priceText = m[1]; priceEvidence = 'body-text:¥'; }
  }
  if (priceEvidence) evidence['price'] = priceEvidence + ' :: ' + String(priceText).slice(0, 80);

  // 4) 店铺
  let shopName = pick(['.shop-name', '[class*="shop-name"]', '[class*="shopName"]',
                       '[class*="store-name"]', '[class*="seller"]', '.seller']);
  if (!shopName && jsonld && jsonld.seller && jsonld.seller.name) {
    shopName = clean(jsonld.seller.name); evidence['jsonld:seller.name'] = shopName;
  }
  const selfOperated = /自营/.test(bodyText.slice(0, 3000));

  // 5) 优惠文案（原样保留，不做解释）
  const couponTexts = [];
  const couponSel = document.querySelectorAll(
    '[class*="coupon"], [class*="quan"], [class*="ticket"], [class*="promotion"], [class*="activity"]'
  );
  for (const el of Array.from(couponSel).slice(0, 12)) {
    const t = clean(el.innerText);
    if (t && t.length >= 4 && t.length <= 80) couponTexts.push(t);
  }
  if (couponTexts.length) evidence['coupons'] = couponTexts.slice(0, 4).join(' | ');

  // 6) 政策文案
  const policyTexts = [];
  const policySel = document.querySelectorAll(
    '[class*="policy"], [class*="service"], [class*="after"], [class*="warranty"], [class*="promise"]'
  );
  for (const el of Array.from(policySel).slice(0, 12)) {
    const t = clean(el.innerText);
    if (t && t.length >= 4 && t.length <= 80) policyTexts.push(t);
  }
  if (policyTexts.length) evidence['policies'] = policyTexts.slice(0, 4).join(' | ');

  // 7) 规格/SKU
  const sku = pick(['.sku', '[class*="sku"]', '[class*="spec"]', '[class*="selected"]']);

  // 7b) 收货地：页面上"配送至"显示的是这个登录账号的默认地址。
  // 它和用户自己填的收货地可能不是一处 —— 两处都交给上层比对，
  // 不在这里替用户选一个。
  const regionSel = document.querySelectorAll(
    '[class*="region"], [class*="address"], [class*="location"], [class*="consignee"]'
  );
  let regionText = null;
  for (const el of Array.from(regionSel).slice(0, 6)) {
    const t = clean(el.innerText);
    if (t && /配送至|收货地?|送至/.test(t)) { regionText = t; break; }
  }
  if (regionText) evidence['region'] = regionText;

  // 8) 销量：兼容"已售 1200 件"与"1200 人付款"两种语序
  const salesMatch = bodyText.match(
    /([0-9][0-9,\.万]*)\+?\s*(?:件已售|人付款|销量|已售)/
  ) || bodyText.match(
    /(?:件已售|人付款|月销|销量|已售|评价)\s*([0-9][0-9,\.万]*)\+?/
  );
  const sales = salesMatch ? salesMatch[0] : null;
  if (sales) evidence['sales'] = sales;

  return {
    url: location.href,
    title: title || null,
    priceText: priceText || null,
    shopName: shopName || null,
    selfOperatedHint: selfOperated,
    skuText: sku || null,
    couponTexts: Array.from(new Set(couponTexts)).slice(0, 10),
    policyTexts: Array.from(new Set(policyTexts)).slice(0, 10),
    regionText: regionText,
    salesText: sales,
    evidence,
    bodyTextSample: bodyText.slice(0, 600),
  };
}
"""


@dataclass(frozen=True)
class Recipe:
    platform: Platform
    display_name: str
    home_url: str
    search_url_template: str
    # 需要登录才能看到的价格/券；未登录时先请求用户接管
    requires_login_for_price: bool = False
    notes: str = ""
    extra_js: Dict[str, str] = field(default_factory=dict)
    # 登录窗口打开的地址。默认跟首页一样，但有些平台首页在 Chromium 里
    # 会触发文件下载（抖音实测：haohuo.jinritemai.com 一打开就
    # "Page.goto: Download is starting"），goto 直接抛异常，用户看到的
    # 就是一个空白窗口，还以为功能坏了。这种平台单独指定一个能用的入口。
    login_url: str = ""

    def login_entry(self) -> str:
        return self.login_url or self.home_url


def _search(keyword: str) -> str:
    return quote_plus(keyword)


PLATFORM_RECIPES: Dict[Platform, Recipe] = {
    Platform.JD: Recipe(
        platform=Platform.JD,
        display_name="京东",
        home_url="https://www.jd.com",
        search_url_template="https://search.jd.com/Search?keyword={kw}&enc=utf-8",
        requires_login_for_price=True,
        notes="京东商品页价格与券多数需登录后展示；未登录会先请您在可见窗口登录。",
    ),
    Platform.TAOBAO: Recipe(
        platform=Platform.TAOBAO,
        display_name="淘宝",
        home_url="https://www.taobao.com",
        search_url_template="https://s.taobao.com/search?q={kw}",
        requires_login_for_price=True,
        notes="淘宝搜索页对未登录访客常要求扫码；可在可见窗口完成扫码后继续。",
    ),
    Platform.TMALL: Recipe(
        platform=Platform.TMALL,
        display_name="天猫",
        home_url="https://www.tmall.com",
        search_url_template="https://list.tmall.com/search_product.htm?q={kw}",
        requires_login_for_price=True,
        notes="天猫与淘宝共用同一登录关系（同一浏览器目录），结果仍按平台分别归属。",
    ),
    Platform.PDD: Recipe(
        platform=Platform.PDD,
        display_name="拼多多",
        home_url="https://mobile.pinduoduo.com",
        search_url_template="https://mobile.pinduoduo.com/search_result.html?search_key={kw}",
        requires_login_for_price=False,
        notes="拼多多商品页价格通常公开；已领券与国补资格需登录后才可见。",
    ),
    Platform.DOUYIN: Recipe(
        platform=Platform.DOUYIN,
        display_name="抖音电商",
        home_url="https://haohuo.jinritemai.com",
        # 实测（2026-09-25）：抖音商城首页在 Chromium 里一打开就触发文件下载，
        # goto 直接抛 "Page.goto: Download is starting"，登录窗口会停在空白页。
        # 抖音主站 www.douyin.com 能正常打开，登录窗口走这个地址，
        # 让用户至少能把账号登上。
        login_url="https://www.douyin.com",
        # 实测（2026-09-25）：/search?keyword= 和 /search_result.html 两条
        # 搜索路径都返回 502 Bad Gateway（TLB 网关错误页），站点本身活着但
        # 搜索全挂。这里保留地址但如实标注，不假装它能用；真正可用之前，
        # 抖音请走"手动提供商品链接"。
        search_url_template="https://haohuo.jinritemai.com/search?keyword={kw}",
        requires_login_for_price=True,
        notes=(
            "抖音商城搜索入口当前返回网关错误（502/504），暂不可用；"
            "已如实标注，不会用演示数据补齐。请改用其它平台，"
            "或直接提供抖音商品链接。"
        ),
    ),
}


def get_recipe(platform: Platform) -> Recipe:
    return PLATFORM_RECIPES[platform]


def search_url(platform: Platform, keyword: str) -> str:
    recipe = get_recipe(platform)
    return recipe.search_url_template.format(kw=_search(keyword))


def all_recipes() -> List[Recipe]:
    return [PLATFORM_RECIPES[p] for p in Platform]


def recipe_summary(platform: Platform) -> dict:
    """给前端的平台说明（不含任何内部脚本）。"""
    recipe = get_recipe(platform)
    from .profiles import profile_info

    profile = profile_info(platform)
    return {
        "platform": platform.value,
        "display_name": recipe.display_name,
        "home_url": recipe.home_url,
        "requires_login_for_price": recipe.requires_login_for_price,
        "notes": recipe.notes,
        "profile_group": profile.group,
        "profile_platforms": [p.value for p in profile.platforms],
        "profile_exists": profile.exists,
    }
