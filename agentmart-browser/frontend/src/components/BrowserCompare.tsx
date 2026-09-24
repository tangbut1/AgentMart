import { type GroupView } from "../lib/browserApi";
import { formatDateTime } from "../lib/format";
import { Badge, Notice } from "./ui";

/** 同规格横向对比：先确认是不是同一款，再比价。 */
export default function BrowserCompare({ groups }: { groups: GroupView[] }) {
  if (groups.length === 0) {
    return <p className="muted">还没有可对比的商品组。</p>;
  }

  return (
    <div className="stack gap-16">
      {groups.map((group) => (
        <section className="panel" key={group.id}>
          <div className="panel__head">
            <span style={{ color: "var(--primary)" }}>
              <Badge tone="outline">同款置信度 {Math.round(group.confidence * 100)}%</Badge>
            </span>
            <h3 className="section-title" style={{ fontSize: 16 }}>
              {group.title}
              <span className="section-note">
                {group.offers.length} 个平台报价 · 最低确定价{" "}
                {group.best_definite_price ?? "—"} 元
              </span>
            </h3>
          </div>
          <div className="panel__body stack gap-12">
            {group.warnings.length > 0 && (
              <Notice tone="warn" title="规格核对提醒">
                <ul className="small">
                  {group.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </Notice>
            )}

            <div className="table-wrap">
              <table className="table table--dense table--responsive">
                <thead>
                  <tr>
                    <th>平台 / 店铺</th>
                    <th>标价</th>
                    <th>确定到手</th>
                    <th>含待确认优惠</th>
                    <th>价格确定性</th>
                    <th>售后</th>
                    <th>读取时间</th>
                    <th>链接</th>
                  </tr>
                </thead>
                <tbody>
                  {group.offers.map((offer) => (
                    <tr key={offer.id}>
                      <td className="table-cell-main" data-label="平台 / 店铺">
                        <span className={`plat-dot plat-dot--${offer.platform}`} aria-hidden="true" />
                        {offer.platform_label}
                        <div className="table-cell-sub">{offer.shop_name ?? "—"}</div>
                      </td>
                      <td className="num" data-label="标价">
                        {offer.breakdown.list_price || "—"}
                      </td>
                      <td className="num text-price" data-label="确定到手">
                        {offer.breakdown.definite_total}
                      </td>
                      <td className="num" data-label="含待确认优惠">
                        {offer.breakdown.potential_total}
                      </td>
                      <td data-label="价格确定性">
                        <Badge
                          tone={offer.certainty.level === "unverifiable" ? "danger" : "info"}
                        >
                          {offer.certainty.label}
                        </Badge>
                      </td>
                      <td className="small" data-label="售后">
                        {offer.policies.length > 0
                          ? offer.policies.map((p) => p.title).join("、")
                          : "页面未显示"}
                      </td>
                      <td className="small muted" data-label="读取时间">
                        {formatDateTime(offer.fetched_at)}
                      </td>
                      <td data-label="链接">
                        <a
                          className="link-out"
                          href={offer.url}
                          target="_blank"
                          rel="noreferrer noopener"
                        >
                          原页面
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="small muted">
              同一行里的价格只对应同一平台同一商品；跨平台的优惠不会互相叠加，也不会把 A
              平台的券算到 B 平台的商品上。
            </div>
          </div>
        </section>
      ))}
    </div>
  );
}
