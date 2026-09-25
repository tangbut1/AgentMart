/** 从标题/规格文本里挑出「像型号」的 token。
 *
 *  单独拆一个模块而不是放在 grouping.ts 里：常驻内容脚本也要用它算指纹，
 *  而 grouping.ts 会连带把 pricing.ts 那一套到手价计算拖进内容脚本的产物里。
 *  放在这里，内容脚本只打包这一小块。
 */

/** 这些词是规格或营销词，不是型号 —— 拿它们当同款依据会把不同商品归到一起。 */
const GENERIC_TOKENS = new Set([
  "5G", "4G", "WIFI", "WLAN", "TYPE-C", "TYPEC", "USB", "HDMI", "BLUETOOTH", "NFC",
  "PLUS", "PRO", "MAX", "ULTRA", "MINI", "LITE", "NEW", "SE", "AIR",
  "128GB", "256GB", "512GB", "1TB", "2TB", "64GB", "32GB",
  "2023", "2024", "2025", "2026",
  "BLACK", "WHITE", "BLUE", "GREEN", "PINK", "GOLD", "SILVER", "GRAY",
  "黑", "白", "蓝", "绿", "粉", "金", "银", "灰",
]);

/** 容量写法先摘掉：不摘的话「Pro 256GB」会被当成「PRO256GB」这个型号。 */
const STORAGE_RE = /(?<![\d.])(\d{1,4})\s*(GB|TB|MB|G|T)(?![\w.])/gi;

/** 「单词 + 数字」型号：iPhone 15、Galaxy S24、AirPods Pro 2。
 *
 *  数字后面不能紧跟单位 —— MacBook Air「13.6英寸」是屏幕尺寸不是型号，
 *  电池「5000mAh」、重量「1.5kg」同理。 */
const WORD_NUM_RE =
  /([A-Za-z]{2,}|[A-Za-z]\d)\s+(\d{1,4}[A-Za-z]{0,6})(?!\.\d)(?!\s*(?:英寸|寸|厘米|米|毫米|mm|cm|kg|克|瓦|w|wh|小时|分钟|年|月|日|款|代|核|hz|bit))\b/gi;

/** 字母数字型号（WH-1000XM5 / A3092）。必须以字母开头 —— 以数字开头的
 *  串基本是尺寸、容量、参数（13.6、5000mAh），不是型号。 */
const TOKEN_RE = /[A-Za-z][A-Za-z0-9]*(?:[-–][A-Za-z0-9]+)*[A-Za-z0-9]*/g;

/** 从标题/规格里挑出「像型号」的 token：含数字、长度够、不是通用词。 */
export function modelTokens(text: string): string[] {
  const source = (text ?? "").replace(STORAGE_RE, " ");
  const tokens: string[] = [];
  const push = (token: string): void => {
    if (token.length < 3) return;
    if (!/[0-9]/.test(token)) return; // 型号里几乎总有数字
    if (GENERIC_TOKENS.has(token)) return;
    if (!tokens.includes(token)) tokens.push(token);
  };

  for (const raw of source.match(TOKEN_RE) ?? []) {
    push(raw.replace(/^[+\-.]+|[+\-.]+$/g, "").toUpperCase());
  }
  for (const match of source.matchAll(WORD_NUM_RE)) {
    push((match[1] + match[2]).toUpperCase());
  }
  return tokens;
}

/** 两侧型号 token 的交集。认不出同款的唯一判据就是这个。 */
export function sharedModelTokens(a: readonly string[], b: readonly string[]): string[] {
  return a.filter((token) => b.includes(token));
}
