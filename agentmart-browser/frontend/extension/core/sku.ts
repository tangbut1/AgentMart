/** SKU 级规格同步：让「价格」始终对应「同一个规格」。
 *
 *  与后端 app/domain/sku.py 逐条对应，共用 tests/corpus/page-fields.json
 *  语料对跑（见 tests/test_extension_parity.py）。
 *
 *  很多平台把颜色、尺码只放在规格选择器里，标题里不写。标题相同的两件商品，
 *  一个选的是黑色 L、一个是蓝色 M，标题签名完全一致 —— 不处理的话它们会被
 *  合成一组、并排比价，把 200 元的规格差价算成平台差异，用户会以为
 *  「另一平台同款便宜 200」，买回来发现不是自己要的那个规格。
 */

/** 同一种颜色的各种写法。顺序无关，但每个别称只应出现在一个键下。
 *  长别名优先匹配，否则「曜石黑」会被切成「曜石」+「黑」。 */
const COLOR_SYNONYMS: Record<string, string[]> = {
  黑: ["曜石黑", "星空黑", "暗夜黑", "深空黑", "磨砂黑", "亮黑色", "纯黑色", "钛黑色", "幻夜黑", "极夜黑", "墨黑", "碳素黑", "黑色", "黑"],
  白: ["月光白", "珍珠白", "云白色", "陶瓷白", "乳白色", "纯白色", "白色", "白"],
  灰: ["深空灰", "太空灰", "钛灰色", "烟灰色", "高级灰", "灰色", "灰"],
  银: ["银色", "银河银", "冰河银", "银"],
  金: ["钛金色", "香槟金", "沙金色", "流沙金", "金色", "金"],
  蓝: ["海蓝色", "天蓝色", "远峰蓝", "湖光蓝", "宝石蓝", "深蓝色", "蓝色", "蓝"],
  绿: ["苍岭绿", "翡翠绿", "松林绿", "墨绿色", "绿色", "绿"],
  粉: ["樱花粉", "蜜桃粉", "玫瑰粉", "粉色", "粉"],
  紫: ["淡紫色", "暗紫色", "紫色", "紫"],
  橙: ["橘色", "橙色", "落日橙", "橙"],
  黄: ["柠檬黄", "明黄色", "黄色", "黄"],
  红: ["珊瑚色", "中国红", "酒红色", "红色", "红"],
};

const COLOR_BY_ALIAS: Record<string, string> = {};
for (const [canonical, aliases] of Object.entries(COLOR_SYNONYMS)) {
  for (const alias of aliases) COLOR_BY_ALIAS[alias] = canonical;
}
const COLOR_ALIASES_BY_LEN = Object.keys(COLOR_BY_ALIAS).sort((a, b) => b.length - a.length);

const COLOR_EN: Record<string, string> = {
  black: "黑", white: "白", gray: "灰", grey: "灰", silver: "银",
  gold: "金", blue: "蓝", green: "绿", pink: "粉", purple: "紫",
  red: "红", orange: "橙", yellow: "黄",
};

/** 字母尺码。两侧都要求不是字母数字 —— 这样 "5G"、"S24"、"M330"、"1.5L"
 *  都不会被误当成尺码（与后端 matching.py 的 _SIZE_RE 同一套边界约定）。 */
const ALPHA_SIZE_RE = /(?<![A-Za-z0-9])(X{0,3}S|X{0,3}M|X{0,3}L)(?![A-Za-z0-9])/gi;
/** 数字尺码：42码 / 42 码 / 尺码42 */
const NUM_SIZE_RE = /(?<!\d)(\d{2,3})\s*(?:码|号)/g;
/** 号型：175/96A */
const EU_SIZE_RE = /(?<!\d)(\d{3}\/\d{2,3}[A-D])/g;
/** 尺码后面跟这些词时是营销词不是尺码：「S级音质」「M系列」 */
const SIZE_MARKETING_RE = /^[级系列款版]/;
/** 容量写法。后端 _STORAGE_RE 同款：字母数字后不接单词字符和小数点 */
const STORAGE_RE = /(?<![\d.])(\d{1,4})\s*(GB|TB|MB|G|T)(?![\w.])/gi;

const STORAGE_UNIT: Record<string, string> = { G: "GB", T: "TB", GB: "GB", TB: "TB", MB: "MB" };

const VERSION_PATTERNS: Array<[RegExp, string]> = [
  [/国行|大陆行货|大陆版|国内行货/, "cn"],
  [/港版|港行|香港行货/, "hk"],
  [/美版|美行/, "us"],
  [/日版|日行/, "jp"],
  [/欧版|英版|德版|欧行/, "eu"],
  [/海外版|国际版|全球版|水货|跨境/, "oversea"],
];

const CONDITION_PATTERNS: Array<[RegExp, string]> = [
  [/二手|9成新|99新|95新|8成新|闲置|已激活使用/, "used"],
  [/官翻|官换机|翻新| refurbished/, "refurbished"],
  [/全新|未拆封|未激活|正品全新/, "new"],
];

const BUNDLE_RE = /套装|礼盒|套餐|含.{0,6}(配件|保护套|键盘|鼠标|充电器)/;

const VERSION_LABELS: Record<string, string> = {
  cn: "国行", hk: "港版", us: "美版", jp: "日版", eu: "欧版", oversea: "海外版",
};
const CONDITION_LABELS: Record<string, string> = {
  new: "全新", used: "二手", refurbished: "翻新",
};

export interface SkuSpec {
  raw: string;
  color: string | null;
  sizes: string[];
  storage: string | null;
  version: string | null;
  condition: string | null;
  bundle: boolean;
}

function normalizeStorage(num: string, unit: string): string {
  const u = unit.toUpperCase();
  return `${num}${STORAGE_UNIT[u] ?? u}`;
}

function isPlausibleStorage(num: string, unit: string): boolean {
  // "5G" 是网络制式不是 5GB；裸写 G/T 时至少两位才可能是存储容量
  if (["GB", "TB", "MB"].includes(unit.toUpperCase())) return true;
  return num.length >= 2;
}

function findColor(text: string): string | null {
  for (const alias of COLOR_ALIASES_BY_LEN) {
    const re = new RegExp(`(?<![A-Za-z])${escapeRegExp(alias)}(?![A-Za-z])`, "i");
    if (re.test(text)) return COLOR_BY_ALIAS[alias];
  }
  const lowered = text.toLowerCase();
  for (const [word, canonical] of Object.entries(COLOR_EN)) {
    if (new RegExp(`(?<![A-Za-z])${word}(?![A-Za-z])`).test(lowered)) return canonical;
  }
  return null;
}

function findSizes(text: string): string[] {
  const found: string[] = [];
  for (const match of text.matchAll(ALPHA_SIZE_RE)) {
    // 「S级」「M系列」是营销词不是尺码
    if (SIZE_MARKETING_RE.test(text.slice(match.index! + match[0].length))) continue;
    const value = match[1].toUpperCase();
    if (!found.includes(value)) found.push(value);
  }
  for (const match of text.matchAll(NUM_SIZE_RE)) {
    if (!found.includes(match[1])) found.push(match[1]);
  }
  for (const match of text.matchAll(EU_SIZE_RE)) {
    if (!found.includes(match[1])) found.push(match[1]);
  }
  return found;
}

function findStorage(text: string): string | null {
  const values: string[] = [];
  for (const [, num, unit] of text.matchAll(STORAGE_RE)) {
    if (!isPlausibleStorage(num, unit)) continue;
    values.push(normalizeStorage(num, unit));
  }
  if (values.length === 0) return null;
  const sizeKey = (value: string): number => {
    const num = value.slice(0, -2);
    const unit = value.slice(-2).toUpperCase();
    return Number(num) * (unit === "TB" ? 1024 : 1);
  };
  // 取最大值：'12GB+256GB' 里 12GB 是内存，256GB 才是存储
  return values.reduce((a, b) => (sizeKey(b) > sizeKey(a) ? b : a));
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function parseSku(text: string | null | undefined): SkuSpec {
  const raw = (text ?? "").trim();
  if (!raw) {
    return { raw: "", color: null, sizes: [], storage: null, version: null, condition: null, bundle: false };
  }
  const spec: SkuSpec = {
    raw,
    color: findColor(raw),
    sizes: findSizes(raw),
    storage: findStorage(raw),
    version: null,
    condition: null,
    bundle: BUNDLE_RE.test(raw),
  };
  for (const [pattern, version] of VERSION_PATTERNS) {
    if (pattern.test(raw)) { spec.version = version; break; }
  }
  for (const [pattern, condition] of CONDITION_PATTERNS) {
    if (pattern.test(raw)) { spec.condition = condition; break; }
  }
  return spec;
}

export function skuSpecIsEmpty(spec: SkuSpec): boolean {
  return !(spec.color || spec.sizes.length || spec.storage || spec.version
    || spec.condition || spec.bundle);
}

/** 主尺码：多个尺码时取字典序最小的，保证同一输入永远得到同一输出。 */
export function skuSize(spec: SkuSpec): string | null {
  if (spec.sizes.length === 0) return null;
  return [...spec.sizes].sort()[0];
}

/** 给界面用的一句话规格描述。空规格返回空串。 */
export function describeSku(spec: SkuSpec): string {
  if (skuSpecIsEmpty(spec)) return "";
  const parts: string[] = [];
  if (spec.color) parts.push(`${spec.color}色`);
  const size = skuSize(spec);
  if (size) parts.push(`${size}${/^\d+$/.test(size) ? "码" : ""}`);
  if (spec.storage) parts.push(spec.storage);
  if (spec.version) parts.push(VERSION_LABELS[spec.version] ?? spec.version);
  if (spec.condition) parts.push(CONDITION_LABELS[spec.condition] ?? spec.condition);
  if (spec.bundle) parts.push("套装");
  return parts.join(" ");
}

/** 规格层面的硬冲突。null 表示没有硬冲突。
 *
 *  尺码/容量/版本/成色/套装不同就是不同 SKU，价格不可比；
 *  颜色不同不构成冲突（同款不同色可以并排，但界面要写明颜色不同）。 */
export function hardSkuConflict(a: SkuSpec, b: SkuSpec): string | null {
  const sameSizes =
    a.sizes.length === b.sizes.length && [...a.sizes].sort().join() === [...b.sizes].sort().join();
  if (a.sizes.length > 0 && b.sizes.length > 0 && !sameSizes) {
    return `尺码不同（${[...a.sizes].sort().join("/")} / ${[...b.sizes].sort().join("/")}）`;
  }
  if (a.storage && b.storage && a.storage !== b.storage) {
    return `容量不同（${a.storage} / ${b.storage}）`;
  }
  if (a.version && b.version && a.version !== b.version) {
    return `版本不同（${a.version} / ${b.version}）`;
  }
  if (a.condition && b.condition && a.condition !== b.condition) {
    return `成色不同（${a.condition} / ${b.condition}）`;
  }
  if (a.bundle !== b.bundle) return "套装与单品混在一起";
  return null;
}

/** 两个规格之间的关系：matched / variant / unknown。 */
export function skuRelation(a: SkuSpec, b: SkuSpec): "matched" | "variant" | "unknown" {
  if (skuSpecIsEmpty(a) || skuSpecIsEmpty(b)) return "unknown";
  if (hardSkuConflict(a, b)) return "variant";
  if (a.color && b.color && a.color !== b.color) return "variant";
  return "matched";
}

export const SKU_SYNC_LABELS: Record<string, string> = {
  matched: "规格一致",
  variant: "规格不同",
  unknown: "未读到规格",
};
