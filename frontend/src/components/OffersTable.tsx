import { Fragment, useState } from "react";
import type { CanonicalProduct, Offer } from "../lib/api";
import {
  PLATFORM_LABEL,
  SHOP_TYPE_LABEL,
  formatRelativeTime,
} from "../lib/format";
import OfferBreakdown from "./OfferBreakdown";
import { Badge, Icon, PriceFigure, useIsDesktop } from "./ui";

function PlatformCell({ platform }: { platform: Offer["platform"] }) {
  return (
    <span className="row gap-6">
      <span className={`plat-dot plat-dot--${platform}`} aria-hidden="true" />
      <span style={{ fontWeight: 600 }}>{PLATFORM_LABEL[platform]}</span>
    </span>
  );
}

function DataStatusBadge({ offer }: { offer: Offer }) {
  if (offer.data_status === "demo") return <Badge tone="price">演示数据</Badge>;
  if (offer.data_status === "stale") return <Badge tone="warn">数据可能过期</Badge>;
  if (offer.data_status === "unverified") return <Badge tone="muted">未核实</Badge>;
  return null;
}

function SourceCell({ offer }: { offer: Offer }) {
  return (
    <div className="row gap-8 wrap" style={{ fontSize: 12.5 }}>
      <a
        href={offer.url}
        target="_blank"
        rel="noopener noreferrer nofollow"
        className="row gap-6"
      >
        <Icon name="external" size={12} />
        商品页
      </a>
      <span className="muted" title={offer.fetched_at ?? undefined}>
        采集 {formatRelativeTime(offer.fetched_at)}
      </span>
    </div>
  );
}

function PriceTrio({ offer }: { offer: Offer }) {
  const b = offer.breakdown;
  const hasGap = b && Number(b.potential_total) < Number(b.definite_total);
  return (
    <div className="price-trio">
      <div className="price-trio__item">
        <span className="price-trio__label">确定到手价</span>
        <PriceFigure value={b?.definite_total ?? offer.list_price} size="md" />
      </div>
      {hasGap && (
        <div className="price-trio__item">
          <span className="price-trio__label">潜在到手价</span>
          <span
            className="num"
            style={{ color: "var(--warn)", fontWeight: 600 }}
          >
            ¥{b.potential_total}
          </span>
        </div>
      )}
      <div className="price-trio__item">
        <span className="price-trio__label">标价</span>
        <PriceFigure value={offer.list_price} size="sm" strike />
      </div>
    </div>
  );
}

function MobileOffers({ group }: { group: CanonicalProduct }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  return (
    <div className="stack gap-12">
      {group.offers.map((offer) => {
        const open = expanded === offer.id;
        return (
          <div className="panel" key={offer.id}>
            <div className="panel__body stack gap-12">
              <div
                className="row gap-8 wrap"
                style={{ justifyContent: "space-between" }}
              >
                <PlatformCell platform={offer.platform} />
                <div className="row gap-6 wrap">
                  <DataStatusBadge offer={offer} />
                  {offer.affiliate && <Badge tone="outline">推广链接</Badge>}
                </div>
              </div>

              <div>
                <div className="offer-row__title">{offer.title}</div>
                <div className="offer-row__shop">
                  <span>{offer.shop_name ?? "店铺未知"}</span>
                  <span className="chip">{SHOP_TYPE_LABEL[offer.shop_type]}</span>
                </div>
              </div>

              <PriceTrio offer={offer} />

              <div className="row gap-8 wrap">
                <button
                  type="button"
                  className="btn btn--secondary btn--sm"
                  aria-expanded={open}
                  onClick={() => setExpanded(open ? null : offer.id)}
                >
                  {open ? "收起拆解" : "查看到手价拆解"}
                </button>
                <SourceCell offer={offer} />
              </div>

              {open && offer.breakdown && (
                <div style={{ borderTop: "1px solid var(--line)", paddingTop: 12 }}>
                  <OfferBreakdown offer={offer} breakdown={offer.breakdown} />
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function DesktopOffers({ group }: { group: CanonicalProduct }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  return (
    <div className="table-wrap">
      <table className="table table--dense table--zebra">
        <thead>
          <tr>
            <th>平台 / 店铺</th>
            <th className="td-num">标价</th>
            <th className="td-num">确定到手价</th>
            <th className="td-num">潜在到手价</th>
            <th className="td-num">待核验优惠</th>
            <th>来源与时效</th>
            <th aria-label="价格拆解" />
          </tr>
        </thead>
        <tbody>
          {group.offers.map((offer) => {
            const open = expanded === offer.id;
            const b = offer.breakdown;
            return (
              <Fragment key={offer.id}>
                <tr>
                  <td>
                    <div className="table-cell-main row gap-6">
                      <PlatformCell platform={offer.platform} />
                      <DataStatusBadge offer={offer} />
                      {offer.affiliate && (
                        <Badge tone="outline" title="该链接可能包含推广返利">
                          推广
                        </Badge>
                      )}
                    </div>
                    <div className="table-cell-sub">
                      {offer.shop_name ?? "店铺未知"} ·{" "}
                      {SHOP_TYPE_LABEL[offer.shop_type]}
                    </div>
                  </td>
                  <td className="td-num">
                    <PriceFigure value={offer.list_price} size="sm" strike />
                  </td>
                  <td className="td-num">
                    <PriceFigure
                      value={b?.definite_total ?? offer.list_price}
                      size="md"
                    />
                  </td>
                  <td className="td-num">
                    {b && Number(b.potential_total) < Number(b.definite_total) ? (
                      <span
                        className="num"
                        style={{ color: "var(--warn)", fontWeight: 600 }}
                      >
                        ¥{b.potential_total}
                      </span>
                    ) : (
                      <span className="muted">同左</span>
                    )}
                  </td>
                  <td className="td-num">
                    {b && Number(b.unverifiable_total) > 0 ? (
                      <span className="num muted">≈ ¥{b.unverifiable_total}</span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td>
                    <SourceCell offer={offer} />
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      aria-expanded={open}
                      onClick={() => setExpanded(open ? null : offer.id)}
                    >
                      {open ? "收起" : "拆解"}
                    </button>
                  </td>
                </tr>
                {open && b && (
                  <tr>
                    <td colSpan={7} style={{ background: "var(--surface-sunken)" }}>
                      <OfferBreakdown offer={offer} breakdown={b} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      <div className="tier-legend">
        <span className="tier-legend__item">
          <span className="tier-swatch tier-swatch--definite" />
          确定到手价：无条件优惠 + 运费，实际可预期
        </span>
        <span className="tier-legend__item">
          <span className="tier-swatch tier-swatch--potential" />
          潜在到手价：满足条件后才可能达到
        </span>
        <span className="tier-legend__item">
          <span className="tier-swatch tier-swatch--unverifiable" />
          待核验：无法核实，不计入到手价
        </span>
      </div>
    </div>
  );
}

/** 跨平台购买选项：桌面密集表格 / 移动端卡片，数据一致。 */
export default function OffersTable({ group }: { group: CanonicalProduct }) {
  const isDesktop = useIsDesktop();
  return isDesktop ? <DesktopOffers group={group} /> : <MobileOffers group={group} />;
}
