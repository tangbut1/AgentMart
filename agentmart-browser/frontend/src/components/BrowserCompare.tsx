import { type GroupView } from "../lib/browserApi";
import { formatDateTime } from "../lib/format";
import { Badge, Notice } from "./ui";

/** 规格同步状态 → 徽章色调。
 *
 *  variant 用 danger：这不是「信息不全」，是「这一行根本不能和别行比大小」，
 *  和「没读到规格」（warn）在证据强度上是两件事，不能都画成黄色。 */
const SKU_TONE: Record<string, "ok" | "warn" | "danger" | "muted"> = {
  matched: "ok",
  variant: "danger",
  unknown: "warn",
};

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
                {group.offers.length} 个平台报价 · 公开轨最低{" "}
                {group.best_public_price ?? "—"} 元
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
                    <th>规格</th>
                    <th>标价</th>
                    <th>公开轨到手</th>
                    <th>我的轨到手</th>
                    <th>含待确认优惠</th>
                    <th>价格确定性</th>
                    <th>售后 / 坑</th>
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
                      <td data-label="规格">
                        {/* 规格不一致时，这一行的价格对应的是另一个规格。
                            不标出来的话，用户会把 200 元的价差当成平台差价。 */}
                        <Badge tone={SKU_TONE[offer.sku_sync] ?? "muted"}>
                          {offer.sku_sync_label}
                        </Badge>
                        <div className="table-cell-sub">
                          {offer.sku_spec ?? offer.sku_text ?? "页面未读到规格"}
                        </div>
                      </td>
                      <td className="num" data-label="标价">
                        {offer.breakdown.list_price || "—"}
                      </td>
                      <td className="num" data-label="公开轨到手">
                        {/* 旧版本存的结果没有这一轨，不能拿 0 顶一个「谁看都成立」的价 */}
                        {offer.breakdown.public_total ?? "—"}
                        {Number(offer.breakdown.account_gap) > 0 && (
                          <div className="table-cell-sub">
                            含账号券 {offer.breakdown.account_gap} 元
                          </div>
                        )}
                      </td>
                      <td className="num text-price" data-label="我的轨到手">
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
                      <td className="small" data-label="售后/坑">
                        {/* 限制和保障必须分开排：以前把"激活后不支持7天无理由"
                            和"7天无理由"一列出来，用户根本分不清哪条是保护。 */}
                        {offer.traps.filter((t) => t.severity !== "minor").length >
                        0 && (
                          <div className="row gap-4 wrap">
                            {offer.traps
                              .filter((t) => t.severity !== "minor")
                              .map((trap, index) => (
                                <Badge
                                  key={`${trap.kind}-${index}`}
                                  tone={trap.severity === "blocker" ? "danger" : "warn"}
                                >
                                  {trap.label}
                                </Badge>
                              ))}
                          </div>
                        )}
                        <div className="muted">
                          {offer.policies.length > 0
                            ? offer.policies.map((p) => p.title).join("、")
                            : "页面未显示保障信息"}
                        </div>
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
              平台的券算到 B 平台的商品上。比平台请看"公开轨到手"——那一轨只算谁来看都成立的
              抵扣；"我的轨到手"里含你账号下已显示可用的券，未登录时拿不到，两个平台账号不同
              也会让它变低。
            </div>
          </div>
        </section>
      ))}
    </div>
  );
}
