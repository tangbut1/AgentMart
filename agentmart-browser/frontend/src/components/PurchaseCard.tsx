import { type OfferView } from "../lib/browserApi";
import { formatDateTime } from "../lib/format";
import { Badge, Icon, Notice, PriceFigure } from "./ui";

const CONDITION_TONE: Record<string, "ok" | "warn" | "danger"> = {
  unconditional: "ok",
  conditional: "warn",
  unverifiable: "danger",
};

export default function PurchaseCard({ offer }: { offer: OfferView }) {
  const { breakdown, certainty } = offer;
  const definite = Number(breakdown.definite_total || 0);
  const potential = Number(breakdown.potential_total || 0);

  return (
    <article className="purchase-card">
      <header className="purchase-card__head">
        <div className="stack gap-6">
          <div className="row gap-8 wrap">
            <span className={`plat-dot plat-dot--${offer.platform}`} aria-hidden="true" />
            <span className="small muted">{offer.platform_label}</span>
            {offer.shop_name && <span className="small">{offer.shop_name}</span>}
            {offer.shop_type_label && <Badge tone="outline">{offer.shop_type_label}</Badge>}
            {offer.is_demo && <Badge tone="danger">演示数据</Badge>}
          </div>
          <h3 className="purchase-card__title">
            <a href={offer.url} target="_blank" rel="noreferrer noopener">
              {offer.title}
            </a>
          </h3>
          {offer.sku_text && <div className="small muted">规格：{offer.sku_text}</div>}
        </div>
        <div className="purchase-card__price">
          <div className="small muted">确定可算部分</div>
          <PriceFigure value={definite} size="lg" />
          {potential !== definite && (
            <div className="small muted">
              含待确认优惠约 <span className="text-price">{potential.toFixed(2)}</span> 元
            </div>
          )}
        </div>
      </header>

      <div className="purchase-card__certainty">
        <Badge tone={certainty.level === "unverifiable" ? "danger" : "info"} dot>
          价格确定性：{certainty.label}
        </Badge>
        <span className="small muted">{certainty.note}</span>
      </div>

      <dl className="price-trio">
        <div className="price-trio__item">
          <dt className="price-trio__label">页面标价</dt>
          <dd className="num">{breakdown.list_price || "—"}</dd>
        </div>
        <div className="price-trio__item">
          <dt className="price-trio__label">运费</dt>
          <dd className="num">{breakdown.shipping_fee || "0.00"}</dd>
        </div>
        <div className="price-trio__item">
          <dt className="price-trio__label">确定可抵扣</dt>
          <dd className="num text-price">-{breakdown.definite_discount || "0.00"}</dd>
        </div>
        <div className="price-trio__item">
          <dt className="price-trio__label">待确认抵扣</dt>
          <dd className="num">-{breakdown.potential_discount || "0.00"}</dd>
        </div>
      </dl>

      {breakdown.lines.length > 0 && (
        <div className="table-wrap">
          <table className="table table--dense table--responsive">
            <thead>
              <tr>
                <th>优惠</th>
                <th>金额</th>
                <th>条件</th>
              </tr>
            </thead>
            <tbody>
              {breakdown.lines.map((line, index) => (
                <tr key={`${line.label}-${index}`}>
                  <td className="table-cell-main" data-label="优惠">
                    {line.label}
                  </td>
                  <td className="num" data-label="金额">
                    -{line.amount || "0.00"}
                  </td>
                  <td data-label="条件">
                    <Badge tone={CONDITION_TONE[line.condition_kind] ?? "muted"}>
                      {line.condition_kind_label}
                    </Badge>
                    {line.condition && <div className="small muted">{line.condition}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {offer.discounts.length > 0 && (
        <div className="stack gap-6">
          <div className="small muted">页面上识别到的优惠（逐条列出，未经验证不计入到手价）</div>
          <ul className="small">
            {offer.discounts.map((discount, index) => (
              <li key={`${discount.label}-${index}`}>
                <Badge tone={CONDITION_TONE[discount.condition_kind] ?? "muted"}>
                  {discount.condition_kind_label}
                </Badge>{" "}
                {discount.label}
                {discount.amount ? `（${discount.amount} 元）` : ""}
                {discount.condition ? ` — ${discount.condition}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      {offer.policies.length > 0 && (
        <div className="stack gap-6">
          <div className="small muted">售后与保障（区分是谁在承诺）</div>
          <ul className="small">
            {offer.policies.map((policy, index) => (
              <li key={`${policy.title}-${index}`}>
                <Badge tone="outline">{policy.scope_label}</Badge>{" "}
                <strong>{policy.title}</strong>
                {policy.summary ? ` — ${policy.summary}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      {offer.match_notes.length > 0 && (
        <Notice tone="warn" title="同款核对">
          <ul className="small">
            {offer.match_notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </Notice>
      )}

      <footer className="purchase-card__foot">
        <div className="small muted">
          来源：{offer.source} · 读取时间 {formatDateTime(offer.fetched_at)} · 可信度{" "}
          {Math.round((offer.credibility ?? 0) * 100)}%
        </div>
        <div className="row gap-8">
          {offer.source_url && (
            <a
              className="btn btn--secondary btn--sm"
              href={offer.source_url}
              target="_blank"
              rel="noreferrer noopener"
            >
              <Icon name="external" size={14} />
              去原平台购买
            </a>
          )}
        </div>
      </footer>

      <div className="small muted">
        优惠券请你自己在平台上领取；本工具不代领券、不代下单、不代付款。
      </div>
    </article>
  );
}
