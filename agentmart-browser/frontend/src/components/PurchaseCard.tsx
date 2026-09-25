import { type OfferView } from "../lib/browserApi";
import { formatDateTime } from "../lib/format";
import CouponTreePanel from "./CouponTreePanel";
import { Badge, Icon, Notice, PriceFigure } from "./ui";

const CONDITION_TONE: Record<string, "ok" | "warn" | "danger"> = {
  unconditional: "ok",
  conditional: "warn",
  unverifiable: "danger",
};

// 防套路：买前必须先确认的用 danger，明显影响决策的用 warn，
// 页面没显示的（那只是"没看到"）用 muted —— 视觉上就要分出
// "页面写了"和"页面没写"两种证据强度。
const TRAP_SEVERITY_TONE: Record<string, "danger" | "warn" | "muted"> = {
  blocker: "danger",
  major: "warn",
  minor: "muted",
};

export default function PurchaseCard({ offer }: { offer: OfferView }) {
  const { breakdown, certainty, coupon_tree: tree } = offer;
  const definite = Number(breakdown.definite_total || 0);
  const potential = Number(breakdown.potential_total || 0);
  // 库里可能存着旧版本生成的结果，那会儿还没有双轨和优惠券树。缺字段时
  // 不能拿 0 顶上 —— 「公开轨 0.00 元」是编出来的数，只能说明没有这一段。
  const publicTotal = breakdown.public_total == null ? null : Number(breakdown.public_total);
  const accountGap = breakdown.account_gap == null ? null : Number(breakdown.account_gap);
  const traps = offer.traps ?? [];
  const stated = traps.filter((t) => t.basis === "page_text");
  const notShown = traps.filter((t) => t.basis !== "page_text");
  const scenarios = offer.subsidy?.scenarios;

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
          <div className="small muted">我的轨到手</div>
          <PriceFigure value={definite} size="lg" />
          {publicTotal !== null && publicTotal !== definite && (
            <div className="small muted">
              公开轨 <span className="text-price">{publicTotal.toFixed(2)}</span> 元
              （谁来看都成立，跨平台比这一轨）
            </div>
          )}
          {accountGap !== null && accountGap > 0 && (
            <div className="small muted">
              其中 {accountGap.toFixed(2)} 元来自你账号下已显示可用的券
            </div>
          )}
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

      {tree ? (
        <details className="coupon-tree-details">
          <summary className="small muted">
            优惠券树：这个到手价是怎么来的（{offer.discounts.length} 条优惠）
          </summary>
          <div className="mt-8">
            <CouponTreePanel tree={tree} />
          </div>
        </details>
      ) : (
        <div className="small muted">
          这条记录是旧版本生成的，没有优惠券树；上面的到手价仍是按当时页面上的证据算的。
        </div>
      )}

      {stated.length > 0 && (
        <Notice
          tone={offer.worst_trap_severity === "blocker" ? "danger" : "warn"}
          title="防套路：页面写明的限制"
        >
          <div className="small muted">
            以下都是商品页上的原文，不是推测。价格低往往正是低在这里。
          </div>
          <ul className="stack gap-8 mt-8">
            {stated.map((trap, index) => (
              <li key={`${trap.kind}-${index}`} className="stack gap-4">
                <div className="row gap-8 wrap">
                  <Badge tone={TRAP_SEVERITY_TONE[trap.severity] ?? "muted"} dot>
                    {trap.severity_label}
                  </Badge>
                  <strong>{trap.label}</strong>
                </div>
                <div className="small">{trap.detail}</div>
                {trap.evidence && (
                  <div className="small muted">页面原文：「{trap.evidence}」</div>
                )}
                {trap.question && (
                  <div className="small">
                    <Icon name="review" size={13} /> 要你确认：{trap.question}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Notice>
      )}

      {notShown.length > 0 && (
        <details>
          <summary className="small muted">
            页面没写、需要你自己确认的事（{notShown.length}）
          </summary>
          <div className="small muted mt-8">
            下面是"没看到"，不等于"没有"。下单前在商品页核对一下。
          </div>
          <ul className="small stack gap-4 mt-8">
            {notShown.map((trap, index) => (
              <li key={`${trap.kind}-${index}`}>
                <strong>{trap.label}</strong> — {trap.detail}
                {trap.question && <div className="muted">{trap.question}</div>}
              </li>
            ))}
          </ul>
        </details>
      )}

      {offer.subsidy && (
        <Notice tone="warn" title="补贴：两种情形都算给你看">
          <div className="small">
            {offer.subsidy.reason}
            {offer.subsidy.region_source === "page" && (
              <span className="muted">
                （收货地取自商品页"配送至"，不是你自己填的）
              </span>
            )}
          </div>
          {scenarios && (
            <div className="row gap-16 wrap mt-8">
              <div>
                <div className="small muted">确定要付</div>
                <PriceFigure value={Number(scenarios.without_subsidy)} />
              </div>
              <div>
                <div className="small muted">仅当你符合补贴资格</div>
                <PriceFigure value={Number(scenarios.with_subsidy ?? 0)} />
              </div>
            </div>
          )}
          <div className="small muted mt-8">{scenarios?.note}</div>
          {offer.subsidy.questions.length > 0 && (
            <ul className="small stack gap-4 mt-8">
              {offer.subsidy.questions.map((question) => (
                <li key={question}>
                  <Icon name="review" size={13} /> {question}
                </li>
              ))}
            </ul>
          )}
        </Notice>
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
