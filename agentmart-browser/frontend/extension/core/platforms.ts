/** 平台识别与搜索地址，与后端 app/browser/recipes.py 的 PLATFORM_RECIPES 一致。
 *
 *  扩展认平台只靠 URL：认不出来就当「不是商品页」，不猜。
 */

import type { Platform } from "./enums.ts";

export interface PlatformRecipe {
  platform: Platform;
  display_name: string;
  home_url: string;
  search_url_template: string;
  requires_login_for_price: boolean;
  notes: string;
  /** URL 里出现这些片段就认为是这个平台 */
  hosts: string[];
}

export const PLATFORM_RECIPES: readonly PlatformRecipe[] = [
  {
    platform: "jd",
    display_name: "京东",
    home_url: "https://www.jd.com",
    search_url_template: "https://search.jd.com/Search?keyword={kw}&enc=utf-8",
    requires_login_for_price: true,
    notes: "京东商品页价格与券多数需登录后展示；未登录会先请您在可见窗口登录。",
    hosts: ["jd.com", "3.cn", "jd.hk"],
  },
  {
    platform: "taobao",
    display_name: "淘宝",
    home_url: "https://www.taobao.com",
    search_url_template: "https://s.taobao.com/search?q={kw}",
    requires_login_for_price: true,
    notes: "淘宝搜索页对未登录访客常要求扫码；可在可见窗口完成扫码后继续。",
    hosts: ["taobao.com", "tmall.com"],
  },
  {
    platform: "tmall",
    display_name: "天猫",
    home_url: "https://www.tmall.com",
    search_url_template: "https://list.tmall.com/search_product.htm?q={kw}",
    requires_login_for_price: true,
    notes: "天猫与淘宝共用同一登录关系，结果仍按平台分别归属。",
    hosts: ["tmall.com"],
  },
  {
    platform: "pdd",
    display_name: "拼多多",
    home_url: "https://mobile.pinduoduo.com",
    search_url_template: "https://mobile.pinduoduo.com/search_result.html?search_key={kw}",
    requires_login_for_price: false,
    notes: "拼多多商品页价格通常公开；已领券与国补资格需登录后才可见。",
    hosts: ["pinduoduo.com", "yangkeduo.com"],
  },
  {
    platform: "douyin",
    display_name: "抖音电商",
    home_url: "https://haohuo.jinritemai.com",
    search_url_template: "https://haohuo.jinritemai.com/search?keyword={kw}",
    requires_login_for_price: true,
    notes: "抖音商城搜索入口当前返回网关错误（502/504），暂不可用；已如实标注，不会用演示数据补齐。",
    hosts: ["jinritemai.com", "douyin.com"],
  },
];

/** 从 URL 认出平台。认不出来返回 null。 */
export function platformFromUrl(url: string): Platform | null {
  let host: string;
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch {
    return null;
  }
  // 天猫要在淘宝之前判断：tmall.com 也出现在淘宝的 hosts 里
  if (host.includes("tmall.com")) return "tmall";
  for (const recipe of PLATFORM_RECIPES) {
    if (recipe.hosts.some((candidate) => host.includes(candidate))) return recipe.platform;
  }
  return null;
}

export function recipeFor(platform: Platform): PlatformRecipe {
  const recipe = PLATFORM_RECIPES.find((item) => item.platform === platform);
  if (!recipe) throw new Error(`unknown platform: ${platform}`);
  return recipe;
}

export function searchUrl(platform: Platform, keyword: string): string {
  return recipeFor(platform).search_url_template.replace(
    "{kw}",
    encodeURIComponent(keyword),
  );
}

/** 除主角平台外，还支持比价的平台。 */
export function otherPlatforms(primary: Platform): Platform[] {
  return PLATFORM_RECIPES.map((recipe) => recipe.platform).filter(
    (platform) => platform !== primary,
  );
}
