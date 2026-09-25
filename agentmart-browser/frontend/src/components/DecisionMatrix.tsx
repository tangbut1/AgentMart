import { type DecisionCell, type DecisionMatrixView } from "../lib/browserApi";
import { Badge } from "./ui";

/** 决策矩阵：把「买哪个平台」拆成用户能自己核对的几个维度。
 *
 *  分数由后端算好（app/domain/decision.py），这里只渲染、不重算 ——
 *  前端再算一遍就会出现两套权重，改了一处另一处不改，界面上的分和
 *  「综合首选」的结论就对不上了。
 *
 *  两条硬规则直接体现在界面上：跨平台比价那一列永远是「公开轨到手」；
 *  规格与基准不一致的行照常展示，但标注不参与赢家评选。
 */

const TONE_VAR: Record<DecisionCell["tone"], string> = {
  ok: "var(--ok)",
  warn: "var(--warn)",
  danger: "var(--danger)",
  muted: "var(--ink-3)",
};

const WEIGHT_LABEL: Record<string, string> = {
  price: "公开轨价格",
  service: "店铺售后",
  freshness: "数据新鲜度",
};

export default function DecisionMatrix({ matrix }: { matrix: DecisionMatrixView }) {
  if (matrix.rows.length === 0) {
    return (
      <p className="muted">
        还没有真实报价可以放进矩阵。演示数据不进入矩阵 —— 拿它算出来的排名是假的。
      </p>
    );
  }

  const columns = matrix.rows[0].cells;
  const weights = Object.entries(matrix.weights);

  return (
    <div className="stack gap-12">
      <div className="row gap-8 wrap small">
        <Badge tone="outline">当前权重：{matrix.priority_label}</Badge>
        {weights.map(([key, value]) => (
          <span key={key} className="muted">
            {WEIGHT_LABEL[key] ?? key} {Math.round(value * 100)}%
          </span>
        ))}
      </div>

      <div className="table-wrap">
        <table className="table table--dense table--responsive">
          <thead>
            <tr>
              <th className="td-num">排名</th>
              <th>平台 / 店铺</th>
              {columns.map((cell) => (
                <th key={cell.key}>{cell.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.rows.map((row) => (
              <tr key={row.offer_id} className={row.blocked ? "matrix-row--blocked" : undefined}>
                <td className="td-num num" data-label="排名">
                  {row.rank}
                </td>
                <td className="table-cell-main" data-label="平台 / 店铺">
                  <span className={`plat-dot plat-dot--${row.platform}`} aria-hidden="true" />
                  {row.platform_label}
                  {row.blocked && (
                    <Badge tone="danger" title="与组内基准规格不同，价格差里含规格差异">
                      规格不符 · 不参与评选
                    </Badge>
                  )}
                  <div className="table-cell-sub">
                    {row.shop_name ?? "店铺未知"} · {row.shop_type_label}
                  </div>
                  <div className="table-cell-sub">
                    <a className="link-out" href={row.url} target="_blank" rel="noreferrer noopener">
                      原页面
                    </a>
                  </div>
                </td>
                {row.cells.map((cell) => (
                  <td key={cell.key} data-label={cell.label}>
                    <div
                      className="matrix-cell__value"
                      style={{ color: TONE_VAR[cell.tone] }}
                      title={cell.note}
                    >
                      {cell.value}
                    </div>
                    <div className="table-cell-sub">{cell.note}</div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="small muted stack gap-4">
        {matrix.notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
    </div>
  );
}
