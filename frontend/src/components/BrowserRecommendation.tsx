import { type RecommendationView } from "../lib/browserApi";
import { formatDateTime } from "../lib/format";
import { Badge, Icon, Notice, ScoreBar } from "./ui";

const PICK_TONE: Record<string, "ok" | "info" | "outline"> = {
  best_overall: "ok",
  cheapest: "info",
  safest_service: "outline",
};

export default function BrowserRecommendation({
  recommendation,
  originLabel,
}: {
  recommendation: RecommendationView | null;
  originLabel: string;
}) {
  if (!recommendation) {
    return (
      <Notice tone="info" title="还没有形成建议">
        等至少一个平台返回真实商品后，这里会给出「综合首选 / 最便宜 / 售后更稳妥」三种方案，
        以及不推荐的理由。
      </Notice>
    );
  }

  return (
    <div className="stack gap-16">
      <section className="panel">
        <div className="panel__head">
          <span style={{ color: "var(--primary)" }}>
            <Icon name="scale" size={18} />
          </span>
          <h3 className="section-title" style={{ fontSize: 16 }}>
            结论
            <span className="section-note">数据来源：{originLabel}</span>
          </h3>
        </div>
        <div className="panel__body stack gap-12">
          <p>{recommendation.summary}</p>
          <div className="row gap-16 wrap">
            <div className="stack gap-6" style={{ minWidth: 200 }}>
              <span className="small muted">结论置信度</span>
              <ScoreBar value={recommendation.confidence} label="结论置信度" />
              <span className="num small">{Math.round(recommendation.confidence * 100)}%</span>
            </div>
            {recommendation.generated_at && (
              <span className="small muted">生成于 {formatDateTime(recommendation.generated_at)}</span>
            )}
          </div>
          {recommendation.missing_data.length > 0 && (
            <Notice tone="warn" title="还缺这些信息">
              <ul className="small">
                {recommendation.missing_data.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </Notice>
          )}
        </div>
      </section>

      <div className="rec-cards">
        {recommendation.options.map((option) => (
          <article className={`rec-card${option.pick_type === "best_overall" ? " rec-card--best" : ""}`} key={option.offer_id}>
            <div className="rec-card__tag">
              <Badge tone={PICK_TONE[option.pick_type] ?? "muted"}>
                {option.pick_type === "best_overall"
                  ? "综合首选"
                  : option.pick_type === "cheapest"
                    ? "最便宜方案"
                    : option.pick_type === "safest_service"
                      ? "售后更稳妥"
                      : option.pick_type}
              </Badge>
            </div>
            <div className="rec-card__headline">{option.headline}</div>
            <div className="rec-card__price">
              <PriceText value={option.definite_total} />
              {option.potential_total !== option.definite_total && (
                <span className="small muted">含待确认优惠约 {option.potential_total}</span>
              )}
            </div>
            <div className="rec-card__section-title">依据</div>
            <ul className="rec-list rec-list--evidence">
              {option.evidence.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            {option.conditions.length > 0 && (
              <>
                <div className="rec-card__section-title">成立条件</div>
                <ul className="rec-list rec-list--conditions">
                  {option.conditions.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </>
            )}
            {option.risks.length > 0 && (
              <>
                <div className="rec-card__section-title">风险与不建议的理由</div>
                <ul className="rec-list rec-list--risks">
                  {option.risks.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </>
            )}
            <div className="small muted">
              {option.platform_label} · 评分 {option.score.toFixed(2)}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function PriceText({ value }: { value: string }) {
  const n = Number(value);
  return (
    <span className="price-figure price-figure--md">
      {Number.isFinite(n) && n > 0 ? (
        <>
          <span className="price-figure__sym">¥</span>
          <span className="price-figure__int">{n.toFixed(2)}</span>
        </>
      ) : (
        <span className="price-figure__int">—</span>
      )}
    </span>
  );
}
