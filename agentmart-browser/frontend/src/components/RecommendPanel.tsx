import { type GroupView, type RecommendationView } from "../lib/browserApi";
import BrowserRecommendation from "./BrowserRecommendation";
import DecisionMatrix from "./DecisionMatrix";
import { Icon, Notice } from "./ui";

/** 购买建议页：每个同款商品组各自给一条建议和一张决策矩阵。
 *
 *  按组给，而不是整个任务只给一条 —— 用户搜「冲锋衣」时，结果里往往
 *  混着三合一、软壳、单层好几款，混成一条建议等于把不同商品拿来
 *  比谁更值。旧记录只有第一条建议，退回单组渲染，不假装有多组。
 */
export default function RecommendPanel({
  groups,
  recommendations,
  originLabel,
}: {
  groups: GroupView[];
  recommendations: RecommendationView[];
  originLabel: string;
}) {
  if (recommendations.length === 0) {
    return (
      <BrowserRecommendation recommendation={null} originLabel={originLabel} />
    );
  }

  return (
    <div className="stack gap-24">
      {recommendations.map((rec, index) => {
        const group = groups[index];
        return (
          <section className="stack gap-12" key={rec.canonical_id}>
            <h3 className="section-title" style={{ fontSize: 16 }}>
              {group?.title ?? "商品组"}
              <span className="section-note">
                {group ? `${group.offers.length} 个平台报价` : ""}
                {rec.matrix ? ` · 权重：${rec.matrix.priority_label}` : ""}
              </span>
            </h3>
            <BrowserRecommendation recommendation={rec} originLabel={originLabel} />
            {rec.matrix && (
              <div className="panel">
                <div className="panel__head">
                  <span style={{ color: "var(--primary)" }}>
                    <Icon name="table" size={18} />
                  </span>
                  <h3 className="section-title" style={{ fontSize: 16 }}>
                    决策矩阵
                    <span className="section-note">
                      每一维单独列出来，你可以自己核对后改权重
                    </span>
                  </h3>
                </div>
                <div className="panel__body">
                  <DecisionMatrix matrix={rec.matrix} />
                </div>
              </div>
            )}
            {group?.warnings.length ? (
              <Notice tone="warn" title="规格核对提醒">
                <ul className="small">
                  {group.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </Notice>
            ) : null}
          </section>
        );
      })}
    </div>
  );
}
