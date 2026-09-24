import type { Offer, PriceBreakdown } from "../lib/api";
import {
  CONDITION_KIND_LABEL,
  DISCOUNT_KIND_LABEL,
  formatMoney,
  hostOf,
} from "../lib/format";
import { Badge, Icon, PriceFigure } from "./ui";

/** 到手价拆解：标价 → 各项优惠（含条件与来源）→ 三档合计。 */
export default function OfferBreakdown({
  offer,
  breakdown,
}: {
  offer: Offer;
  breakdown: PriceBreakdown;
}) {
  const lines = breakdown.lines;
  const hasPotentialGap =
    Number(breakdown.potential_total) < Number(breakdown.definite_total);

  return (
    <div className="breakdown">
      <div className="breakdown__row">
        <span className="breakdown__label">商品标价</span>
        <span className="breakdown__amount breakdown__amount--plus num">
          ¥{formatMoney(breakdown.list_price)}
        </span>
      </div>

      {Number(breakdown.shipping_fee) > 0 ? (
        <div className="breakdown__row">
          <span className="breakdown__label">
            运费
            <span className="breakdown__cond">由商品页抓取时的运费信息决定</span>
          </span>
          <span className="breakdown__amount breakdown__amount--plus num">
            + ¥{formatMoney(breakdown.shipping_fee)}
          </span>
        </div>
      ) : (
        <div className="breakdown__row">
          <span className="breakdown__label">运费</span>
          <span className="breakdown__amount num">包邮 / 未标注</span>
        </div>
      )}

      {lines.map((line, i) => (
        <div className="breakdown__row" key={`${line.label}-${i}`}>
          <span className="breakdown__label">
            <span className="row gap-6 wrap">
              <span>
                {DISCOUNT_KIND_LABEL[line.kind] ?? line.kind} · {line.label}
              </span>
              <Badge
                tone={
                  line.condition_kind === "unconditional"
                    ? "ok"
                    : line.condition_kind === "conditional"
                      ? "warn"
                      : "muted"
                }
              >
                {CONDITION_KIND_LABEL[line.condition_kind]}
              </Badge>
              {line.data_status === "demo" && <Badge tone="price">演示</Badge>}
              {line.source_url && (
                <a
                  href={line.source_url}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className="row gap-6"
                  style={{ fontSize: 12, color: "var(--ink-3)" }}
                  title={`来源：${line.source_url}`}
                >
                  <Icon name="external" size={11} />
                  {hostOf(line.source_url)}
                </a>
              )}
            </span>
            {line.condition && (
              <span className="breakdown__cond">条件：{line.condition}</span>
            )}
          </span>
          <span
            className={`breakdown__amount num ${
              line.condition_kind === "unverifiable"
                ? "breakdown__amount--muted"
                : "breakdown__amount--minus"
            }`}
          >
            {line.condition_kind === "unverifiable" ? "≈ " : "− "}¥
            {formatMoney(line.amount)}
          </span>
        </div>
      ))}

      {lines.length === 0 && (
        <div className="breakdown__row">
          <span className="breakdown__label">
            未发现可核验的优惠
            <span className="breakdown__cond">
              可能原因：平台未开放优惠接口，或该商品当前无活动
            </span>
          </span>
          <span className="breakdown__amount breakdown__amount--muted">—</span>
        </div>
      )}

      <div className="breakdown__row breakdown__row--total">
        <span className="breakdown__label">
          确定到手价
          <span className="breakdown__cond">
            无条件优惠 + 运费，已实际计入
          </span>
        </span>
        <span className="num" style={{ color: "var(--price-deep)" }}>
          <PriceFigure value={breakdown.definite_total} size="md" />
        </span>
      </div>

      {hasPotentialGap && (
        <div className="breakdown__row">
          <span className="breakdown__label">
            潜在到手价
            <span className="breakdown__cond">
              满足全部条件后才可能达到，条件未满足则为确定到手价
            </span>
          </span>
          <span className="breakdown__amount num" style={{ color: "var(--warn)" }}>
            ¥{formatMoney(breakdown.potential_total)}
          </span>
        </div>
      )}

      {Number(breakdown.unverifiable_total) > 0 && (
        <div className="breakdown__row">
          <span className="breakdown__label">
            无法核实的优惠
            <span className="breakdown__cond">
              未能通过接口或规则核实，不计入任何到手价
            </span>
          </span>
          <span className="breakdown__amount breakdown__amount--muted num">
            ≈ ¥{formatMoney(breakdown.unverifiable_total)}
          </span>
        </div>
      )}

      {breakdown.applied_groups.length > 0 && (
        <div className="breakdown__row">
          <span className="breakdown__label">互斥组</span>
          <span className="row gap-6 wrap">
            {breakdown.applied_groups.map((g) => (
              <span className="chip" key={g}>
                {g}
              </span>
            ))}
          </span>
        </div>
      )}

      {breakdown.notes.length > 0 && (
        <ul className="breakdown__notes">
          {breakdown.notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}

      <div className="row gap-12 wrap small muted mt-8">
        <span>店铺：{offer.shop_name ?? "未知"}</span>
        {offer.sku_text && <span>规格：{offer.sku_text}</span>}
        {offer.affiliate && (
          <Badge tone="outline" title="该链接可能包含推广返利">
            推广链接
          </Badge>
        )}
      </div>
    </div>
  );
}
