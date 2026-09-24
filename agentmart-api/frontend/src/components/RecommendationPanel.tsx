import type {
  CanonicalProduct,
  Recommendation,
  RecommendationPreferences,
} from "../lib/api";
import { PICK_TYPE_LABEL, PLATFORM_LABEL, formatMoney } from "../lib/format";
import { Badge, Icon, Notice, PriceFigure, ScoreBar } from "./ui";

const PICK_ORDER = ["best_overall", "cheapest", "safest"];

function PrefControls({
  prefs,
  onChange,
}: {
  prefs: RecommendationPreferences;
  onChange: (p: RecommendationPreferences) => void;
}) {
  return (
    <div className="rec-controls">
      <div className="field" style={{ maxWidth: 170 }}>
        <label className="field__label" htmlFor="budget">
          预算上限（元）
        </label>
        <input
          id="budget"
          className="input num"
          type="number"
          min={0}
          step={100}
          placeholder="不限"
          value={prefs.budget_max ?? ""}
          onChange={(e) =>
            onChange({
              ...prefs,
              budget_max: e.target.value === "" ? null : Number(e.target.value),
            })
          }
        />
      </div>

      <div className="field">
        <span className="field__label">决策偏好</span>
        <div className="segmented" role="radiogroup" aria-label="决策偏好">
          {[
            { value: "price" as const, label: "更省钱" },
            { value: "service" as const, label: "更稳妥" },
            { value: "balanced" as const, label: "平衡" },
          ].map((o) => (
            <button
              key={o.value}
              type="button"
              role="radio"
              aria-checked={(prefs.priority ?? "balanced") === o.value}
              className="segmented__option"
              onClick={() => onChange({ ...prefs, priority: o.value })}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      <div className="field" style={{ flex: 1, minWidth: 200 }}>
        <label className="field__label" htmlFor="scenario">
          使用场景（可选）
        </label>
        <input
          id="scenario"
          className="input"
          type="text"
          maxLength={60}
          placeholder="例如：给长辈用 / 经常出差 / 学生自用"
          value={prefs.scenario ?? ""}
          onChange={(e) =>
            onChange({ ...prefs, scenario: e.target.value || null })
          }
        />
        <span className="field__hint">
          场景只用于推荐说明的措辞，不会改变价格与政策数据
        </span>
      </div>
    </div>
  );
}

function OptionCard({
  option,
  group,
  isBest,
}: {
  option: Recommendation["options"][number];
  group: CanonicalProduct;
  isBest: boolean;
}) {
  const offer = group.offers.find((o) => o.id === option.offer_id);
  return (
    <div className={`rec-card${isBest ? " rec-card--best" : ""}`}>
      <div className="row gap-8 wrap" style={{ justifyContent: "space-between" }}>
        <Badge tone={isBest ? "ok" : "muted"}>
          {PICK_TYPE_LABEL[option.pick_type] ?? option.pick_type}
        </Badge>
        <span className="row gap-6 small muted">
          <span className={`plat-dot plat-dot--${option.platform}`} aria-hidden="true" />
          {PLATFORM_LABEL[option.platform]}
        </span>
      </div>

      <div className="rec-card__headline">{option.headline}</div>

      <div className="rec-card__price">
        <PriceFigure value={option.definite_total} size="md" />
        {Number(option.potential_total) < Number(option.definite_total) && (
          <span className="small" style={{ color: "var(--warn)" }}>
            潜在 ¥{formatMoney(option.potential_total)}
          </span>
        )}
      </div>

      <div>
        <div className="row gap-8" style={{ justifyContent: "space-between" }}>
          <span className="rec-card__section-title">综合评分</span>
          <span className="num small" style={{ fontWeight: 700 }}>
            {Math.round(option.score * 100)}
          </span>
        </div>
        <div className="mt-8">
          <ScoreBar value={option.score} label={`${option.headline} 评分`} />
        </div>
      </div>

      {option.evidence.length > 0 && (
        <div>
          <div className="rec-card__section-title">依据</div>
          <ul className="rec-list rec-list--evidence">
            {option.evidence.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      {option.conditions.length > 0 && (
        <div>
          <div className="rec-card__section-title">生效条件</div>
          <ul className="rec-list rec-list--conditions">
            {option.conditions.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      )}

      {option.risks.length > 0 && (
        <div>
          <div className="rec-card__section-title">风险与不确定</div>
          <ul className="rec-list rec-list--risks">
            {option.risks.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {offer && (
        <a
          className="btn btn--secondary btn--sm btn--block mt-8"
          href={offer.url}
          target="_blank"
          rel="noopener noreferrer nofollow"
        >
          <Icon name="external" size={13} />
          前往{PLATFORM_LABEL[offer.platform]}
          {offer.affiliate ? "（推广链接）" : ""}
        </a>
      )}
    </div>
  );
}

export default function RecommendationPanel({
  group,
  recommendation,
  prefs,
  onPrefsChange,
}: {
  group: CanonicalProduct;
  recommendation: Recommendation | null;
  prefs: RecommendationPreferences;
  onPrefsChange: (p: RecommendationPreferences) => void;
}) {
  const options = [...(recommendation?.options ?? [])].sort(
    (a, b) => PICK_ORDER.indexOf(a.pick_type) - PICK_ORDER.indexOf(b.pick_type),
  );

  return (
    <section className="panel" aria-labelledby="rec-title">
      <div className="panel__head">
        <span style={{ color: "var(--primary)" }}>
          <Icon name="scale" size={18} />
        </span>
        <h2 className="section-title" id="rec-title">
          购买建议
          <span className="section-note">依据价格、优惠条件、售后与数据可信度综合计算</span>
        </h2>
      </div>

      <PrefControls prefs={prefs} onChange={onPrefsChange} />

      <div className="panel__body stack gap-16">
        {recommendation && (
          <>
            <Notice
              tone={
                recommendation.options.length === 0
                  ? "warn"
                  : recommendation.confidence >= 0.7
                    ? "info"
                    : "warn"
              }
              title="建议说明"
            >
              <p>{recommendation.summary}</p>
              {recommendation.missing_data.length > 0 && (
                <ul className="rec-list rec-list--conditions mt-8">
                  {recommendation.missing_data.map((m, i) => (
                    <li key={i}>{m}</li>
                  ))}
                </ul>
              )}
              <p className="small muted mt-8">
                数据置信度 {Math.round(recommendation.confidence * 100)}% · 计算时间{" "}
                {recommendation.generated_at
                  ? new Date(recommendation.generated_at).toLocaleString("zh-CN")
                  : "—"}
                。建议仅供参考，最终价格以商品页实时显示与下单流程为准。
              </p>
            </Notice>

            {options.length > 0 && (
              <div className="rec-cards">
                {options.map((o) => (
                  <OptionCard
                    key={o.pick_type}
                    option={o}
                    group={group}
                    isBest={o.pick_type === "best_overall"}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
