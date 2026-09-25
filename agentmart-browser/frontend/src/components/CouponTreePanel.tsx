import { type CouponTreeView } from "../lib/browserApi";
import { Badge, Icon, PriceFigure } from "./ui";

const CONDITION_TONE: Record<string, "ok" | "warn" | "danger"> = {
  unconditional: "ok",
  conditional: "warn",
  unverifiable: "danger",
};

/** 一条优惠在价格里的真实身份。
 *
 *  不能只看 counted —— 它只说明"没被同层互斥挤掉"。一张没写"已领取"的
 *  店铺券 counted 也是 true，但它进的是潜在价，不是确定价。混为一谈就会
 *  把"可能能减"讲成"已经减了"。
 */
type EntryTrack = "public" | "account" | "potential" | "beaten" | "demo";

function entryTrack(entry: CouponTreeView["layers"][number]["entries"][number]): EntryTrack {
  if (!entry.counted) return "beaten";
  if (entry.data_status === "demo") return "demo";
  if (entry.kind === "trade_in") return "potential";
  if (entry.condition_kind !== "unconditional") return "potential";
  return entry.certainty === "account_coupon" ? "account" : "public";
}

const TRACK_NOTE: Record<EntryTrack, string> = {
  public: "计入公开轨：谁来看都成立",
  account: "计入我的轨：页面显示我这个账号已可用",
  potential: "满足条件才成立，未计入确定价",
  beaten: "同层互斥，未计入",
  demo: "演示数据，不计入",
};

const TRACK_TONE: Record<EntryTrack, "ok" | "warn" | "muted"> = {
  public: "ok",
  account: "warn",
  potential: "warn",
  beaten: "muted",
  demo: "muted",
};

function beatenText(entry: CouponTreeView["layers"][number]["entries"][number]): string {
  if (entry.beaten_by) return `与「${entry.beaten_by}」同层互斥，未计入`;
  return "同层互斥，未计入";
}

/** 优惠券树 + 双轨净价。
 *
 *  为什么要分两个轨：跨平台比价时如果混进"我账号里的券"，比出来的是账号
 *  差异而不是商品差异。公开轨谁看都成立，我的轨才是我真正要付的钱。
 */
export default function CouponTreePanel({ tree }: { tree: CouponTreeView }) {
  const gap = Number(tree.account_gap || 0);
  const shownLayers = tree.layers.filter((layer) => layer.entries.length > 0);
  const beatenCount = shownLayers.reduce(
    (total, layer) => total + layer.entries.filter((entry) => !entry.counted).length,
    0,
  );

  return (
    <div className="coupon-tree">
      <div className="coupon-tree__tracks">
        <div className="track">
          <div className="track__label">公开轨到手</div>
          <PriceFigure value={tree.public_total} size="md" />
          <div className="small muted">只算谁来看都成立的抵扣，跨平台比价看这一轨</div>
        </div>
        <div className="track">
          <div className="track__label">我的轨到手</div>
          <PriceFigure value={tree.account_total} size="md" />
          {gap > 0 ? (
            <div className="small">
              比公开轨低 <span className="text-price">{gap.toFixed(2)}</span> 元 ——
              来自你账号下已显示可用的券，未登录时拿不到
            </div>
          ) : (
            <div className="small muted">这个账号没有额外可用的券，或页面没显示</div>
          )}
        </div>
      </div>

      {tree.stacking_confidence === "inferred" && (
        <div className="small muted coupon-tree__inferred">
          <Icon name="info" size={13} />{" "}
          各层能否叠加是按优惠所属层级推断的，页面没有逐一说明；最终可叠加项以平台结算页为准。
        </div>
      )}

      {shownLayers.length === 0 ? (
        <div className="small muted">这一页没有识别到优惠信息。</div>
      ) : (
        <div className="coupon-tree__layers">
          {shownLayers.map((layer) => (
            <section className="tree-layer" key={layer.layer}>
              <header className="tree-layer__head">
                <strong>{layer.layer_label}</strong>
                <span className="small muted num">
                  公开 -{layer.public_amount || "0.00"} · 我的 -{layer.account_amount || "0.00"}
                </span>
              </header>
              <ul className="tree-layer__entries">
                {layer.entries.map((entry, index) => {
                  const track = entryTrack(entry);
                  return (
                    <li
                      key={`${entry.label}-${index}`}
                      className={`tree-entry${track === "beaten" ? " tree-entry--dropped" : ""}`}
                    >
                      <div className="tree-entry__top">
                        <span className="tree-entry__label">{entry.label}</span>
                        <span
                          className={`num${
                            track === "public" || track === "account" ? " text-price" : " muted"
                          }`}
                        >
                          -{entry.amount || "0.00"}
                        </span>
                      </div>
                      <div className="row gap-6 wrap tree-entry__meta">
                        <Badge tone={CONDITION_TONE[entry.condition_kind] ?? "muted"}>
                          {entry.condition_kind_label}
                        </Badge>
                        {entry.certainty_label && (
                          <span className="small muted">{entry.certainty_label}</span>
                        )}
                        <span className={`small track-note track-note--${TRACK_TONE[track]}`}>
                          {track === "beaten" ? beatenText(entry) : TRACK_NOTE[track]}
                        </span>
                      </div>
                      {entry.condition && <div className="small muted">{entry.condition}</div>}
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      )}

      {beatenCount > 0 && (
        <div className="small muted">
          有 {beatenCount} 条优惠因为和同层更优的一项互斥而没有计入。它们仍然列在上面 ——
          挤掉了哪一张，必须让你看见。
        </div>
      )}

      {tree.notes.length > 0 && (
        <ul className="small muted coupon-tree__notes">
          {tree.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
