import type { Review } from "../lib/api";
import {
  COMMERCIAL_RELATION_LABEL,
  CURATION_STATUS_LABEL,
  REVIEW_PLATFORM_LABEL,
  formatCount,
  formatDate,
  formatDateTime,
  formatDuration,
  formatRelativeTime,
} from "../lib/format";
import { Badge, Icon } from "./ui";

function CriteriaChecklist({ review }: { review: Review }) {
  if (!review.assessment || review.assessment.checks.length === 0) return null;
  return (
    <ul className="criteria-list">
      {review.assessment.checks.map((c) => (
        <li key={c.dimension}>
          <span
            className={`criteria-list__mark criteria-list__mark--${c.met ? "yes" : "no"}`}
            aria-hidden="true"
          >
            {c.met ? "✓" : "—"}
          </span>
          <span>
            <strong style={{ fontWeight: 600 }}>{c.dimension}</strong>
            {c.note && <span className="muted"> · {c.note}</span>}
            <span className="sr-only">{c.met ? "（满足）" : "（未满足）"}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

export default function ReviewCard({ review }: { review: Review }) {
  const a = review.assessment;
  return (
    <article className="panel review-card">
      <div className="review-card__head">
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="row gap-6 wrap" style={{ marginBottom: 6 }}>
            <span className={`plat-dot plat-dot--${review.platform}`} aria-hidden="true" />
            <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--ink-2)" }}>
              {REVIEW_PLATFORM_LABEL[review.platform]}
            </span>
            <span className="review-card__meta">{review.creator_name}</span>
            {review.curation_status === "verified" ? (
              <Badge tone="ok" dot>
                已核实
              </Badge>
            ) : (
              <Badge tone="warn" dot>
                {CURATION_STATUS_LABEL[review.curation_status]}
              </Badge>
            )}
            {review.data_status === "demo" && <Badge tone="price">演示数据</Badge>}
            {review.commercial_relation !== "none_disclosed" && (
              <Badge
                tone={review.commercial_relation === "unknown" ? "muted" : "warn"}
                title="创作者与品牌之间可能存在商业关系，结论需谨慎参考"
              >
                商业关系：{COMMERCIAL_RELATION_LABEL[review.commercial_relation]}
              </Badge>
            )}
          </div>

          <h3 className="review-card__title">
            <a href={review.url} target="_blank" rel="noopener noreferrer nofollow">
              {review.title}
            </a>
          </h3>

          <div className="review-card__meta mt-8">
            {review.published_at && <span>发布 {formatDate(review.published_at)}</span>}
            {review.duration_seconds != null && (
              <span>时长 {formatDuration(review.duration_seconds)}</span>
            )}
            {review.view_count != null && <span>{formatCount(review.view_count)} 播放</span>}
            {review.like_count != null && <span>{formatCount(review.like_count)} 点赞</span>}
            {review.model_tested && <span>测试型号：{review.model_tested}</span>}
          </div>
        </div>

        {a && (
          <div style={{ textAlign: "right", flexShrink: 0 }}>
            <div className="small muted">参考价值</div>
            <div className="num" style={{ fontSize: 20, fontWeight: 700, color: "var(--primary-deep)" }}>
              {Math.round(a.score * 100)}
            </div>
            <div style={{ fontSize: 12, color: "var(--ink-3)" }}>
              {a.recommend_reference ? "建议参考" : "参考需谨慎"}
            </div>
          </div>
        )}
      </div>

      <CriteriaChecklist review={review} />

      {(review.pros.length > 0 || review.cons.length > 0) && (
        <div className="pros-cons">
          {review.pros.length > 0 && (
            <div className="pros-cons__col pros-cons__col--pros">
              <div className="pros-cons__title">
                <Icon name="check" size={13} />
                优点（整理自评测内容）
              </div>
              <ul>
                {review.pros.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ul>
            </div>
          )}
          {review.cons.length > 0 && (
            <div className="pros-cons__col pros-cons__col--cons">
              <div className="pros-cons__title">
                <Icon name="alert" size={13} />
                不足与注意事项
              </div>
              <ul>
                {review.cons.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {review.quotes.length > 0 && (
        <div>
          <div className="section-note" style={{ marginBottom: 6 }}>
            原文摘录（未改写）
          </div>
          {review.quotes.map((q, i) => (
            <blockquote className="quote" key={i}>
              “{q}”
              <span className="quote__source">
                —— {review.creator_name} ·{" "}
                <a href={review.url} target="_blank" rel="noopener noreferrer nofollow">
                  查看原视频
                </a>
              </span>
            </blockquote>
          ))}
        </div>
      )}

      {review.test_evidence.length > 0 && (
        <div>
          <div className="section-note" style={{ marginBottom: 6 }}>
            测试方法与可复核数据
          </div>
          <div className="row gap-6 wrap">
            {review.test_evidence.map((e, i) => (
              <span className="chip chip--accent" key={i}>
                {e}
              </span>
            ))}
          </div>
        </div>
      )}

      {review.scenarios.length > 0 && (
        <div>
          <div className="section-note" style={{ marginBottom: 6 }}>
            适用场景 / 人群
          </div>
          <div className="row gap-6 wrap">
            {review.scenarios.map((s, i) => (
              <span className="chip" key={i}>
                {s}
              </span>
            ))}
          </div>
        </div>
      )}

      {review.ai_summary && (
        <div className="notice notice--info">
          <span className="notice__icon" aria-hidden="true">
            <Icon name="info" size={15} />
          </span>
          <div className="notice__body">
            <div className="notice__title">
              AI 归纳（非创作者原话，仅供参考）
              {review.ai_generated_at && (
                <span className="muted small"> · 生成于 {formatDateTime(review.ai_generated_at)}</span>
              )}
            </div>
            {review.ai_summary}
          </div>
        </div>
      )}

      <div
        className="row gap-12 wrap small muted"
        style={{ borderTop: "1px solid var(--line)", paddingTop: 10 }}
      >
        {review.curated_at && <span>整理于 {formatDate(review.curated_at)}</span>}
        {review.curated_by && <span>整理人：{review.curated_by}</span>}
        {review.curator_notes && <span>整理备注：{review.curator_notes}</span>}
        {review.fetched_at && <span>元数据采集 {formatRelativeTime(review.fetched_at)}</span>}
        {review.relevance_note && <span>关联说明：{review.relevance_note}</span>}
      </div>
    </article>
  );
}
