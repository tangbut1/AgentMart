import type { Offer, Policy, PolicyScope } from "../lib/api";
import {
  PLATFORM_LABEL,
  POLICY_SCOPE_LABEL,
  POLICY_SCOPE_NOTE,
  formatDate,
} from "../lib/format";
import { Badge, Icon, useIsDesktop } from "./ui";

const SCOPE_TONE: Record<PolicyScope, "ok" | "info" | "warn" | "muted"> = {
  platform_rule: "ok",
  shop_promise: "info",
  product_page_promise: "warn",
  pending_verification: "muted",
};

function ScopeBadge({ policy }: { policy: Policy }) {
  return (
    <Badge tone={SCOPE_TONE[policy.scope]} title={POLICY_SCOPE_NOTE[policy.scope]}>
      {POLICY_SCOPE_LABEL[policy.scope]}
    </Badge>
  );
}

function PolicyCell({ policy }: { policy: Policy }) {
  return (
    <div className="stack gap-6">
      <div className="row gap-6 wrap">
        <span style={{ fontWeight: 600 }}>{policy.title}</span>
        <ScopeBadge policy={policy} />
      </div>
      <div className="small" style={{ color: "var(--ink-2)", lineHeight: 1.6 }}>
        {policy.summary}
      </div>
      <div className="row gap-8 wrap" style={{ fontSize: 12, color: "var(--ink-3)" }}>
        {policy.region && <span>地区：{policy.region}</span>}
        {policy.updated_at && <span>更新 {formatDate(policy.updated_at)}</span>}
        {policy.source_url && (
          <a
            href={policy.source_url}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className="row gap-6 link-out"
          >
            <Icon name="external" size={11} />
            规则原文
          </a>
        )}
      </div>
    </div>
  );
}

/** 售后政策对比：按政策类别 × 平台/店铺展示，并标注每条政策的效力范围。 */
export default function PolicyTable({ offers }: { offers: Offer[] }) {
  const isDesktop = useIsDesktop();

  const categories = Array.from(
    new Set(offers.flatMap((o) => o.policies.map((p) => p.category))),
  ).sort();

  if (categories.length === 0) {
    return (
      <p className="muted small" style={{ padding: "8px 0" }}>
        各平台未提供可核验的售后政策结构化数据。请以下单前商品页与客服说明为准。
      </p>
    );
  }

  if (!isDesktop) {
    return (
      <div className="stack gap-12">
        {offers.map((offer) => (
          <div className="panel" key={offer.id}>
            <div className="panel__head">
              <span className={`plat-dot plat-dot--${offer.platform}`} aria-hidden="true" />
              <span style={{ fontWeight: 700 }}>{PLATFORM_LABEL[offer.platform]}</span>
              <span className="section-note">{offer.shop_name ?? "店铺未知"}</span>
            </div>
            <div className="panel__body stack gap-16">
              {categories.map((cat) => {
                const policy = offer.policies.find((p) => p.category === cat);
                if (!policy) {
                  return (
                    <div key={cat}>
                      <div className="section-note" style={{ marginBottom: 4 }}>
                        {cat}
                      </div>
                      <span className="muted small">未提供相关信息</span>
                    </div>
                  );
                }
                return (
                  <div key={cat}>
                    <div className="section-note" style={{ marginBottom: 4 }}>
                      {cat}
                    </div>
                    <PolicyCell policy={policy} />
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="table-wrap">
      <table className="table table--dense">
        <thead>
          <tr>
            <th style={{ width: 110 }}>政策类别</th>
            {offers.map((o) => (
              <th key={o.id}>
                <span className="row gap-6">
                  <span className={`plat-dot plat-dot--${o.platform}`} aria-hidden="true" />
                  {PLATFORM_LABEL[o.platform]}
                </span>
                <div className="table-cell-sub">{o.shop_name ?? "店铺未知"}</div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {categories.map((cat) => (
            <tr key={cat}>
              <td style={{ fontWeight: 600, verticalAlign: "top" }}>{cat}</td>
              {offers.map((o) => {
                const policy = o.policies.find((p) => p.category === cat);
                return (
                  <td key={o.id} style={{ minWidth: 220 }}>
                    {policy ? (
                      <PolicyCell policy={policy} />
                    ) : (
                      <span className="muted small">未提供相关信息</span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="tier-legend" style={{ flexDirection: "column", gap: 4 }}>
        <span className="tier-legend__item">
          <ScopeBadge
            policy={{ scope: "platform_rule" } as Policy}
          />
          平台规则：写在平台规则文件里，跨店铺普遍适用
        </span>
        <span className="tier-legend__item">
          <ScopeBadge policy={{ scope: "shop_promise" } as Policy} />
          店铺承诺：店铺自行声明，可能变更，需以店铺页面与客服确认为准
        </span>
        <span className="tier-legend__item">
          <ScopeBadge policy={{ scope: "product_page_promise" } as Policy} />
          商品页承诺：仅在该商品页展示，随活动上下架变化
        </span>
        <span className="tier-legend__item">
          <ScopeBadge policy={{ scope: "pending_verification" } as Policy} />
          待核实：尚未核实到一手规则，仅供参考
        </span>
      </div>
    </div>
  );
}
