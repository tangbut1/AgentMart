/** 个人浏览器版的展示层格式化（单一来源，避免各处硬编码中文）。 */
import type { BrowserPlatform } from "./browserApi";

export const PLATFORM_LABEL: Record<BrowserPlatform, string> = {
  jd: "京东",
  taobao: "淘宝",
  tmall: "天猫",
  pdd: "拼多多",
  douyin: "抖音商城",
};

export const PLATFORM_ORDER: BrowserPlatform[] = ["jd", "taobao", "tmall", "pdd", "douyin"];

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${formatDate(iso)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 相对时间：今天 / N 天前 / 日期。 */
export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "时间未知";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "时间未知";
  const now = Date.now();
  const diff = now - d.getTime();
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diff < minute) return "刚刚";
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前`;
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`;
  if (diff < 30 * day) return `${Math.floor(diff / day)} 天前`;
  return formatDate(iso);
}

/** 判断字符串是否像 URL（首页两种输入模式用）。 */
export function looksLikeUrl(text: string): boolean {
  return /^https?:\/\/\S+$/i.test(text.trim());
}

export function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
