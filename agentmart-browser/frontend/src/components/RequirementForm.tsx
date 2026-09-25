import { useCallback, useMemo, useState } from "react";
import { browserApi, type Requirement } from "../lib/browserApi";
import { Notice } from "./ui";

/**
 * 结构化需求表单。
 *
 * 为什么以填表为主路径、自然语言只做辅助：价格是这个产品最不能出错的
 * 一项。让大模型解析「预算100到250之间」，它可能读成 max=100，也可能
 * 补一个句子里根本没有的数字 —— 那就是凭空造价。表单里用户自己敲的
 * 数字就是最终数字，不经过任何猜测，也永远可以在点「开始比价」之前
 * 亲眼核对。
 */

export interface RequirementFields {
  keyword: string;
  category: string;
  budget_min: string;
  budget_max: string;
  budget_approximate: boolean;
  brands: string;
  region: string;
  scenarios: string[];
}

export interface RequirementDraft {
  /** 用户自己写的一句话，可空 */
  text: string;
  /** 结构化字段，最终以它为准 */
  fields: RequirementFields;
}

export const EMPTY_FIELDS: RequirementFields = {
  keyword: "",
  category: "",
  budget_min: "",
  budget_max: "",
  budget_approximate: false,
  brands: "",
  region: "",
  scenarios: [],
};

export function toDraftPayload(draft: RequirementDraft) {
  const f = draft.fields;
  const fields: Record<string, unknown> = {};
  if (f.keyword.trim()) fields.keyword = f.keyword.trim();
  if (f.category.trim()) fields.category = f.category.trim();
  if (f.budget_min.trim()) fields.budget_min = Number(f.budget_min);
  if (f.budget_max.trim()) fields.budget_max = Number(f.budget_max);
  if (f.brands.trim()) fields.brands = f.brands;
  if (f.region.trim()) fields.region = f.region.trim();
  if (f.scenarios.length) fields.scenarios = f.scenarios;
  // 只有真填了预算才把「约」发过去，否则会覆盖掉从原话里解析出的近似标记
  if (f.budget_min.trim() || f.budget_max.trim()) {
    fields.budget_approximate = f.budget_approximate;
  }
  return { text: draft.text.trim(), fields };
}

const CATEGORIES = [
  "服装", "户外服装", "手机", "平板电脑", "笔记本电脑", "电脑", "显示器",
  "耳机", "音频设备", "智能穿戴", "影像设备", "网络设备", "外设", "家电",
  "母婴", "美妆",
];

const BRAND_OPTIONS = [
  "苹果", "华为", "小米", "Redmi", "OPPO", "vivo", "荣耀", "一加", "三星",
  "联想", "戴尔", "惠普", "华硕", "ThinkPad", "索尼", "Bose", "JBL",
  "耐克", "阿迪达斯", "安踏", "李宁", "探路者", "凯乐石", "伯希和",
  "骆驼", "迪卡侬", "优衣库", "无印良品", "飞利浦", "松下", "海尔",
];

const SCENARIO_OPTIONS = [
  "通勤", "徒步", "登山", "露营", "跑步", "骑行", "健身", "旅行", "出差",
  "日常", "办公", "学习", "游戏", "拍照", "摄影", "视频", "续航", "信号",
  "防水", "防雨", "防晒", "透气", "保暖", "轻薄", "静音", "护眼",
];

type Mode = "form" | "text";

const EXAMPLES = [
  "预算 500～800 元，买一件适合日常通勤和轻度徒步的冲锋衣，重视防雨和透气",
  "想买一部手机，预算 3000 元左右，重视续航和信号，看看有没有我能享受的国补",
  "索尼 WH-1000XM5，预算 2500 元，只算平台标价和店铺券，不要会员方案",
];

function describe(f: RequirementFields): string[] {
  const parts: string[] = [];
  if (f.keyword.trim()) parts.push(`搜索词「${f.keyword.trim()}」`);
  if (f.category.trim()) parts.push(`品类 ${f.category.trim()}`);
  const lo = f.budget_min.trim();
  const hi = f.budget_max.trim();
  const approx = f.budget_approximate ? "（约）" : "";
  if (lo && hi) parts.push(`预算 ${lo}–${hi} 元${approx}`);
  else if (hi) parts.push(`预算不超过 ${hi} 元${approx}`);
  else if (lo) parts.push(`预算不低于 ${lo} 元`);
  if (f.brands.trim()) parts.push(`品牌 ${f.brands.trim()}`);
  if (f.region.trim()) parts.push(`配送至${f.region.trim()}`);
  if (f.scenarios.length) parts.push(`在意 ${f.scenarios.join("、")}`);
  return parts;
}

function fieldsFromRequirement(r: Requirement): RequirementFields {
  return {
    keyword: r.keyword ?? "",
    category: r.category ?? "",
    budget_min: r.budget_min != null ? String(r.budget_min) : "",
    budget_max: r.budget_max != null ? String(r.budget_max) : "",
    budget_approximate: r.budget_approximate,
    brands: (r.brands ?? []).join("、"),
    region: r.region ?? "",
    scenarios: r.scenarios ?? [],
  };
}

interface Props {
  draft: RequirementDraft;
  onChange: (draft: RequirementDraft) => void;
  disabled?: boolean;
}

export function RequirementForm({ draft, onChange, disabled }: Props) {
  const [mode, setMode] = useState<Mode>("form");
  const [parsing, setParsing] = useState(false);
  const [parseNote, setParseNote] = useState<string | null>(null);
  const f = draft.fields;
  const preview = useMemo(() => describe(f), [f]);

  const patch = useCallback(
    (next: Partial<RequirementFields>) => onChange({ ...draft, fields: { ...f, ...next } }),
    [draft, f, onChange],
  );

  const toggleScenario = useCallback(
    (word: string) =>
      patch({
        scenarios: f.scenarios.includes(word)
          ? f.scenarios.filter((s) => s !== word)
          : [...f.scenarios, word],
      }),
    [f.scenarios, patch],
  );

  const prefillFromText = useCallback(async () => {
    const text = draft.text.trim();
    if (!text) {
      setParseNote("先写一句话，再用它填表。");
      return;
    }
    setParsing(true);
    setParseNote(null);
    try {
      const parsed = await browserApi.parse(text);
      onChange({
        text,
        fields: { ...EMPTY_FIELDS, ...fieldsFromRequirement(parsed) },
      });
      const unclear = (parsed.unclear ?? []).join("；");
      setParseNote(
        `已按这句话填好表单，请核对后再开始。` +
          (unclear ? `没能看懂的部分：${unclear}` : ""),
      );
      setMode("form");
    } catch (exc) {
      setParseNote(exc instanceof Error ? exc.message : "解析失败，请手动填写");
    } finally {
      setParsing(false);
    }
  }, [draft.text, onChange]);

  return (
    <div className="stack gap-16">
      <div className="row gap-8 wrap" style={{ alignItems: "center" }}>
        <button
          type="button"
          className={`chip${mode === "form" ? " chip--accent" : ""}`}
          aria-pressed={mode === "form"}
          onClick={() => setMode("form")}
        >
          填表（推荐）
        </button>
        <button
          type="button"
          className={`chip${mode === "text" ? " chip--accent" : ""}`}
          aria-pressed={mode === "text"}
          onClick={() => setMode("text")}
        >
          写一句话
        </button>
        <span className="field__hint" style={{ marginLeft: "auto" }}>
          填表最稳：数字是你自己敲的，不会被猜错
        </span>
      </div>

      {mode === "text" ? (
        <div className="stack gap-12">
          <div className="field">
            <label className="field__label" htmlFor="req-text">
              用一句话描述
            </label>
            <textarea
              id="req-text"
              className="textarea"
              rows={3}
              disabled={disabled}
              value={draft.text}
              placeholder="例如：预算 500～800 元，买一件适合日常通勤和轻度徒步的冲锋衣，重视防雨和透气"
              onChange={(e) => onChange({ ...draft, text: e.target.value })}
            />
            <div className="field__hint">
              这句话只用来<strong>自动填好下面的表单</strong>，最终以表单为准。
              填完请核对一遍再开始比价。
            </div>
          </div>
          <div className="row gap-8 wrap">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                className="btn btn--ghost btn--sm"
                disabled={disabled}
                onClick={() => onChange({ ...draft, text: example })}
              >
                {example.slice(0, 16)}…
              </button>
            ))}
          </div>
          <div className="row gap-8">
            <button
              type="button"
              className="btn btn--secondary"
              onClick={prefillFromText}
              disabled={parsing || disabled}
            >
              {parsing ? "解析中…" : "解析并填到表单"}
            </button>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => setMode("form")}
            >
              改成手动填表
            </button>
          </div>
          {parseNote && <Notice tone="info">{parseNote}</Notice>}
        </div>
      ) : (
        <div className="stack gap-16">
          <div className="grid-2">
            <div className="field">
              <label className="field__label" htmlFor="req-keyword">
                要买什么（搜索词）
              </label>
              <input
                id="req-keyword"
                className="input"
                disabled={disabled}
                value={f.keyword}
                placeholder="例如：西装 / 降噪耳机 / WH-1000XM5"
                onChange={(e) => patch({ keyword: e.target.value })}
              />
              <div className="field__hint">
                会原样作为关键词在各平台搜索。带型号就搜型号，结果最准。
              </div>
            </div>
            <div className="field">
              <label className="field__label" htmlFor="req-category">
                品类（可选）
              </label>
              <select
                id="req-category"
                className="select"
                disabled={disabled}
                value={f.category}
                onChange={(e) => patch({ category: e.target.value })}
              >
                <option value="">不指定</option>
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <div className="field__hint">用于归类与横向对比，不参与搜索词。</div>
            </div>
          </div>

          <div className="stack gap-8">
            <div className="field__label">预算（元，可选）</div>
            <div className="row gap-8 wrap" style={{ alignItems: "flex-end" }}>
              <div className="field" style={{ maxWidth: 150 }}>
                <label className="field__label" htmlFor="req-bmin">
                  最低
                </label>
                <input
                  id="req-bmin"
                  className="input"
                  type="number"
                  min={0}
                  inputMode="numeric"
                  disabled={disabled}
                  value={f.budget_min}
                  placeholder="不限"
                  onChange={(e) => patch({ budget_min: e.target.value })}
                />
              </div>
              <div className="field" style={{ maxWidth: 150 }}>
                <label className="field__label" htmlFor="req-bmax">
                  最高
                </label>
                <input
                  id="req-bmax"
                  className="input"
                  type="number"
                  min={0}
                  inputMode="numeric"
                  disabled={disabled}
                  value={f.budget_max}
                  placeholder="不限"
                  onChange={(e) => patch({ budget_max: e.target.value })}
                />
              </div>
              <label className="checkbox" style={{ marginBottom: 10 }}>
                <input
                  type="checkbox"
                  disabled={disabled}
                  checked={f.budget_approximate}
                  onChange={(e) => patch({ budget_approximate: e.target.checked })}
                />
                约数（左右 / 上下）
              </label>
            </div>
            <div className="field__hint">
              只填「最高」表示不超过这个价；两个都填表示落在这个区间。超预算的商品会被剔除并说明原因。
            </div>
          </div>

          <div className="field">
            <label className="field__label" htmlFor="req-brands">
              指定品牌（可选）
            </label>
            <input
              id="req-brands"
              className="input"
              disabled={disabled}
              value={f.brands}
              placeholder="例如：索尼、Bose；不填则不限制"
              onChange={(e) => patch({ brands: e.target.value })}
            />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="req-region">
              配送地区（可选）
            </label>
            <input
              id="req-region"
              className="input"
              disabled={disabled}
              value={f.region}
              placeholder="例如：广东省深圳市"
              onChange={(e) => patch({ region: e.target.value })}
            />
            <div className="field__hint">
              不同地区能看到的价格、优惠和售后可能不同，填上会更准。
            </div>
          </div>

          <div className="stack gap-8">
            <div className="field__label">在意的点（可多选，可选）</div>
            <div className="row gap-8 wrap">
              {SCENARIO_OPTIONS.map((word) => {
                const active = f.scenarios.includes(word);
                return (
                  <button
                    key={word}
                    type="button"
                    className={`chip${active ? " chip--accent" : ""}`}
                    aria-pressed={active}
                    disabled={disabled}
                    onClick={() => toggleScenario(word)}
                  >
                    {word}
                  </button>
                );
              })}
            </div>
            <div className="field__hint">
              这些只用于筛选和推荐排序，不会拼进平台搜索词。
            </div>
          </div>

          {BRAND_OPTIONS.length > 0 && !f.brands.trim() && (
            <div className="row gap-8 wrap">
              <span className="field__hint">常用品牌：</span>
              {BRAND_OPTIONS.slice(0, 10).map((b) => (
                <button
                  key={b}
                  type="button"
                  className="btn btn--ghost btn--sm"
                  disabled={disabled}
                  onClick={() => patch({ brands: f.brands ? `${f.brands}、${b}` : b })}
                >
                  {b}
                </button>
              ))}
            </div>
          )}

          {draft.text.trim() && (
            <Notice tone="info" title="同时保留了你写的原话">
              {draft.text.trim()}
            </Notice>
          )}
        </div>
      )}

      <div className="panel__body panel__body--flush" style={{ paddingTop: 4 }}>
        <div className="field__label">即将执行</div>
        {preview.length ? (
          <p className="mono small" style={{ margin: 0 }}>
            {preview.join(" ｜ ")}
          </p>
        ) : (
          <p className="muted small" style={{ margin: 0 }}>
            还没有填任何条件。至少填一个「要买什么」。
          </p>
        )}
      </div>
    </div>
  );
}
