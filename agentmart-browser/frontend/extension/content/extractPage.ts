/** 在商品页上下文里执行的只读抽取。
 *
 *  与后端 app/browser/recipes.py 的 JS_PRODUCT_FIELDS 是同一套规则：先
 *  JSON-LD，再常见选择器，最后文本正则；抽不到就留空并记下证据来源。
 *
 *  约束（写死在实现里，不靠调用方自觉）：
 *  - 只读。不点任何按钮、不提交表单、不领券、不下单；
 *  - 不读输入框内容、不读 cookie、不读任何账号信息；
 *  - 不修改页面 DOM。
 *
 *  这个函数会被 chrome.scripting.executeScript 注入，所以必须是自包含的
 *  （不能引用模块里的其它东西），并且返回的值要能结构化克隆。
 */

export interface ExtractedPage {
  url: string;
  title: string | null;
  priceText: string | null;
  priceSource: "dom";
  shopName: string | null;
  selfOperatedHint: boolean;
  skuText: string | null;
  couponTexts: string[];
  policyTexts: string[];
  regionText: string | null;
  salesText: string | null;
  evidence: Record<string, string>;
}

export function extractProductPage(): ExtractedPage {
  const clean = (value: unknown): string =>
    String(value ?? "")
      .replace(/\s+/g, " ")
      .trim();
  const evidence: Record<string, string> = {};
  const pick = (selectors: readonly string[]): string | null => {
    for (const selector of selectors) {
      const element = document.querySelector(selector);
      if (element) {
        const text = clean(element.textContent);
        if (text) {
          evidence[selector] = text.slice(0, 200);
          return text;
        }
      }
    }
    return null;
  };

  // 1) JSON-LD（最可靠的结构化来源）
  let jsonld: Record<string, unknown> | null = null;
  const scripts = document.querySelectorAll('script[type="application/ld+json"]');
  for (const script of Array.from(scripts)) {
    try {
      const data = JSON.parse(script.textContent ?? "") as unknown;
      const nodes = Array.isArray(data) ? data : [data];
      for (const node of nodes) {
        const record = node as Record<string, unknown> | null;
        const kind = record ? record["@type"] : undefined;
        if (record && (kind === "Product" || kind === "product")) {
          jsonld = record;
          break;
        }
      }
    } catch {
      /* 忽略单个脚本解析失败 */
    }
    if (jsonld) break;
  }
  if (jsonld) evidence["jsonld:Product"] = JSON.stringify(jsonld).slice(0, 300);

  const bodyText = clean(document.body ? document.body.textContent : "").slice(0, 20000);

  // 2) 标题
  let title = clean(document.title);
  const ogTitle = document.querySelector('meta[property="og:title"]');
  if (ogTitle && ogTitle.getAttribute("content")) {
    title = clean(ogTitle.getAttribute("content"));
    evidence["meta:og:title"] = title;
  }
  const h1 = document.querySelector("h1");
  if (h1 && clean(h1.textContent).length > 4) {
    title = clean(h1.textContent);
    evidence["h1"] = title;
  }
  if (jsonld && typeof jsonld.name === "string") {
    title = clean(jsonld.name);
    evidence["jsonld:name"] = title;
  }

  // 3) 价格：优先 JSON-LD offers，再常见选择器，最后文本正则
  let priceText: string | null = null;
  let priceEvidence: string | null = null;
  const offers = jsonld ? jsonld.offers : undefined;
  if (offers) {
    const list = Array.isArray(offers) ? offers : [offers];
    for (const entry of list) {
      const record = entry as Record<string, unknown> | null;
      const price = record ? (record.price ?? record.lowPrice) : undefined;
      if (price) {
        priceText = String(price);
        priceEvidence = `jsonld:offers.price=${priceText}`;
        break;
      }
    }
  }
  if (!priceText) {
    const v = pick([
      ".price",
      '[class*="price"]',
      '[id*="price"]',
      ".p-price",
      ".Price",
      '[class*="Price"]',
      "[data-price]",
    ]);
    if (v) {
      priceText = v;
      priceEvidence = "selector";
    }
    const withData = document.querySelector("[data-price]");
    if (!priceText && withData) {
      priceText = withData.getAttribute("data-price");
      priceEvidence = "data-price";
    }
  }
  if (!priceText) {
    const match = bodyText.match(/[¥￥]\s*([0-9]+(?:\.[0-9]{1,2})?)/);
    if (match) {
      priceText = match[1];
      priceEvidence = "body-text:¥";
    }
  }
  if (priceEvidence) {
    evidence.price = `${priceEvidence} :: ${String(priceText).slice(0, 80)}`;
  }

  // 4) 店铺
  let shopName = pick([
    ".shop-name",
    '[class*="shop-name"]',
    '[class*="shopName"]',
    '[class*="store-name"]',
    '[class*="seller"]',
    ".seller",
  ]);
  const seller = jsonld ? (jsonld.seller as Record<string, unknown> | undefined) : undefined;
  if (!shopName && seller && typeof seller.name === "string") {
    shopName = clean(seller.name);
    evidence["jsonld:seller.name"] = shopName;
  }
  const selfOperated = /自营/.test(bodyText.slice(0, 3000));

  // 5) 优惠文案（原样保留，不做解释）
  const couponTexts: string[] = [];
  const couponSel = document.querySelectorAll(
    '[class*="coupon"], [class*="quan"], [class*="ticket"], [class*="promotion"], [class*="activity"]',
  );
  for (const element of Array.from(couponSel).slice(0, 12)) {
    const text = clean(element.textContent);
    if (text && text.length >= 4 && text.length <= 80) couponTexts.push(text);
  }
  if (couponTexts.length) {
    evidence.coupons = couponTexts.slice(0, 4).join(" | ");
  }

  // 6) 政策文案
  const policyTexts: string[] = [];
  const policySel = document.querySelectorAll(
    '[class*="policy"], [class*="service"], [class*="after"], [class*="warranty"], [class*="promise"]',
  );
  for (const element of Array.from(policySel).slice(0, 12)) {
    const text = clean(element.textContent);
    if (text && text.length >= 4 && text.length <= 80) policyTexts.push(text);
  }
  if (policyTexts.length) {
    evidence.policies = policyTexts.slice(0, 4).join(" | ");
  }

  // 7) 规格/SKU
  const sku = pick([".sku", '[class*="sku"]', '[class*="spec"]', '[class*="selected"]']);

  // 7b) 收货地：页面上"配送至"显示的是这个登录账号的默认地址。
  // 它和用户自己填的收货地可能不是一处 —— 两处都交给上层比对，
  // 不在这里替用户选一个。
  const regionSel = document.querySelectorAll(
    '[class*="region"], [class*="address"], [class*="location"], [class*="consignee"]',
  );
  let regionText: string | null = null;
  for (const element of Array.from(regionSel).slice(0, 6)) {
    const text = clean(element.textContent);
    if (text && /配送至|收货地?|送至/.test(text)) {
      regionText = text;
      break;
    }
  }
  if (regionText) evidence.region = regionText;

  // 8) 销量：兼容"已售 1200 件"与"1200 人付款"两种语序
  const salesMatch =
    bodyText.match(/([0-9][0-9,.万]*)\+?\s*(?:件已售|人付款|销量|已售)/) ??
    bodyText.match(/(?:件已售|人付款|月销|销量|已售|评价)\s*([0-9][0-9,.万]*)\+?/);
  const sales = salesMatch ? salesMatch[0] : null;
  if (sales) evidence.sales = sales;

  return {
    url: location.href,
    title: title || null,
    priceText: priceText || null,
    priceSource: "dom",
    shopName: shopName || null,
    selfOperatedHint: selfOperated,
    skuText: sku || null,
    couponTexts: Array.from(new Set(couponTexts)).slice(0, 10),
    policyTexts: Array.from(new Set(policyTexts)).slice(0, 10),
    regionText,
    salesText: sales,
    evidence,
  };
}

export interface ExtractedLink {
  url: string;
  title: string;
}

/** 从搜索结果页收集可能的商品链接。只读，与后端 JS_PRODUCT_LINKS 同规则。 */
export function extractProductLinks(maxLinks: number): ExtractedLink[] {
  const out: ExtractedLink[] = [];
  const seen = new Set<string>();
  const anchors = Array.from(document.querySelectorAll<HTMLAnchorElement>("a[href]"));
  for (const anchor of anchors) {
    const href = anchor.href || "";
    if (!/^https?:/.test(href)) continue;
    if (seen.has(href)) continue;
    const title = (anchor.textContent || anchor.getAttribute("title") || "").trim();
    if (title.length < 6) continue;
    // 只收看起来像商品详情页的链接
    const looksLikeItem =
      /item\.|\/product[./]|\/detail\/|\/goods\/|\/sku\/|id=\d{4,}|\/p\/|haohuo\./.test(href);
    if (!looksLikeItem) continue;
    seen.add(href);
    out.push({ url: href, title: title.slice(0, 120) });
    if (out.length >= maxLinks) break;
  }
  return out;
}
