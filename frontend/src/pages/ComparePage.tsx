import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { CompareResponse } from "../lib/api";
import { api } from "../lib/api";
import { PLATFORM_LABEL, SHOP_TYPE_LABEL, displayLowestPrice, formatCount, formatMoney } from "../lib/format";
import { Badge, EmptyState, Icon, Notice, PriceFigure, useIsDesktop } from "../components/ui";

function bestPrice(g: CompareResponse["groups"][number]) {
  return displayLowestPrice(g).value;
}

function isDemoPrice(g: CompareResponse["groups"][number]) {
  return displayLowestPrice(g).demo;
}

function lowestOffer(g: CompareResponse["groups"][number]) {
  const sorted = [...g.offers].sort((a, b) =>
    Number(a.breakdown?.definite_total ?? a.list_price) -
    Number(b.breakdown?.definite_total ?? b.list_price),
  );
  return sorted[0];
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="compare-row">
      <span className="compare-row__label">{label}</span>
      <span className="compare-row__value">{children}</span>
    </div>
  );
}

function CompareCards({ data }: { data: CompareResponse }) {
  return (
    <div className="compare-grid">
      {data.groups.map((g) => {
        const rec = data.recommendations[g.id];
        const reviews = data.reviews[g.id] ?? [];
        const best = rec?.options.find((o) => o.pick_type === "best_overall");
        return (
          <div className="compare-col" key={g.id}>
            <div className="row gap-8 wrap" style={{ justifyContent: "space-between" }}>
              <Badge tone={g.confidence >= 0.75 ? "ok" : "warn"}>
                置信度 {Math.round(g.confidence * 100)}%
              </Badge>
              {g.offers.some((o) => o.data_status === "demo") && <Badge tone="price">含演示</Badge>}
            </div>
            <div className="compare-col__title">
              <Link to={`/product?q=${encodeURIComponent(g.title)}&id=${g.id}`}>{g.title}</Link>
            </div>
            <div className="price-figure price-figure--md">
              <PriceFigure value={bestPrice(g)} size="md" />
              {isDemoPrice(g) && (
                <div className="mt-8">
                  <Badge tone="price">演示</Badge>
                </div>
              )}
            </div>
            <Row label="购买选项">{g.offers.length} 个</Row>
            <Row label="覆盖平台">
              {Array.from(new Set(g.offers.map((o) => o.platform)))
                .map((p) => PLATFORM_LABEL[p])
                .join(" / ")}
            </Row>
            <Row label="最低价渠道">
              {lowestOffer(g)
                ? `${PLATFORM_LABEL[lowestOffer(g).platform]} · ${SHOP_TYPE_LABEL[lowestOffer(g).shop_type]}`
                : "—"}
            </Row>
            <Row label="相关评测">{reviews.length > 0 ? `${reviews.length} 条` : "暂无"}</Row>
            {best && (
              <>
                <Row label="首选渠道">{PLATFORM_LABEL[best.platform]}</Row>
                <Row label="首选理由">
                  <span style={{ whiteSpace: "normal", textAlign: "left" }}>{best.headline}</span>
                </Row>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}

function CompareTable({ data }: { data: CompareResponse }) {
  const metrics: { label: string; render: (g: CompareResponse["groups"][number]) => React.ReactNode }[] =
    [
      {
        label: "最低确定到手价",
        render: (g) => <PriceFigure value={bestPrice(g)} size="md" />,
      },
      {
        label: "购买选项数",
        render: (g) => <span className="num">{g.offers.length} 个</span>,
      },
      {
        label: "覆盖平台",
        render: (g) =>
          Array.from(new Set(g.offers.map((o) => o.platform)))
            .map((p) => PLATFORM_LABEL[p])
            .join(" / "),
      },
      {
        label: "最低价渠道",
        render: (g) =>
          lowestOffer(g)
            ? `${PLATFORM_LABEL[lowestOffer(g).platform]} · ${SHOP_TYPE_LABEL[lowestOffer(g).shop_type]}`
            : "—",
      },
      {
        label: "潜在到手价（最低）",
        render: (g) => {
          const o = lowestOffer(g);
          const b = o?.breakdown;
          if (!b) return "—";
          return Number(b.potential_total) < Number(b.definite_total) ? (
            <span style={{ color: "var(--warn)" }} className="num">
              ¥{formatMoney(b.potential_total)}
            </span>
          ) : (
            <span className="muted">同确定价</span>
          );
        },
      },
      {
        label: "无法核实的优惠（最低）",
        render: (g) => {
          const o = lowestOffer(g);
          const b = o?.breakdown;
          return b && Number(b.unverifiable_total) > 0 ? (
            <span className="num muted">≈ ¥{formatMoney(b.unverifiable_total)}</span>
          ) : (
            <span className="muted">—</span>
          );
        },
      },
      {
        label: "售后政策（保修示例）",
        render: (g) => {
          const withPolicy = g.offers.find((o) =>
            o.policies.some((p) => p.category.includes("保修") || p.category.includes("质保")),
          );
          const policy = withPolicy?.policies.find(
            (p) => p.category.includes("保修") || p.category.includes("质保"),
          );
          return policy ? (
            <span title={policy.summary}>{policy.summary.slice(0, 40)}…</span>
          ) : (
            <span className="muted">未提供结构化数据</span>
          );
        },
      },
      {
        label: "相关评测",
        render: (g) => {
          const n = (data.reviews[g.id] ?? []).length;
          return n > 0 ? `${n} 条` : <span className="muted">暂无</span>;
        },
      },
      {
        label: "综合首选",
        render: (g) => {
          const best = data.recommendations[g.id]?.options.find(
            (o) => o.pick_type === "best_overall",
          );
          return best ? (
            <span>
              <strong>{PLATFORM_LABEL[best.platform]}</strong>
              <span className="muted small"> · {best.headline.slice(0, 24)}…</span>
            </span>
          ) : (
            <span className="muted">数据不足</span>
          );
        },
      },
      {
        label: "评测最高播放",
        render: (g) => {
          const views = (data.reviews[g.id] ?? [])
            .map((r) => r.view_count ?? 0)
            .reduce((a, b) => Math.max(a, b), 0);
          return views > 0 ? `${formatCount(views)} 播放` : <span className="muted">—</span>;
        },
      },
    ];

  return (
    <div className="table-wrap">
      <table className="table table--dense table--zebra">
        <thead>
          <tr>
            <th style={{ width: 150 }}>对比项</th>
            {data.groups.map((g) => (
              <th key={g.id}>
                <Link to={`/product?q=${encodeURIComponent(g.title)}&id=${g.id}`}>
                  {g.title}
                </Link>
                <div className="table-cell-sub">
                  {g.brand ?? ""} {g.model ?? ""}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {metrics.map((m) => (
            <tr key={m.label}>
              <td style={{ fontWeight: 600 }}>{m.label}</td>
              {data.groups.map((g) => (
                <td key={g.id}>{m.render(g)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ComparePage() {
  const [params] = useSearchParams();
  const keyword = params.get("q") ?? "";
  const ids = (params.get("ids") ?? "").split(",").filter(Boolean);
  const includeDemo = params.get("demo") === "1";

  const [data, setData] = useState<CompareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const isDesktop = useIsDesktop();

  useEffect(() => {
    if (!keyword || ids.length === 0) return;
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setLoading(true);
    setError(null);
    api
      .compare(keyword, ids.slice(0, 5), includeDemo)
      .then((res) => setData(res))
      .catch((e) => {
        if ((e as Error).name !== "AbortError") setError((e as Error).message);
      })
      .finally(() => !ac.signal.aborted && setLoading(false));
    return () => ac.abort();
  }, [keyword, ids.join(","), includeDemo]);

  if (!keyword || ids.length === 0) {
    return (
      <EmptyState
        icon={<Icon name="table" size={20} />}
        title="还没有选择要对比的商品"
        desc="在搜索结果页勾选「加入对比」（2-5 个同款组），再点击「对比已选 N 项」。"
        actions={
          <Link className="btn btn--primary btn--sm" to="/">
            去搜索商品
          </Link>
        }
      />
    );
  }

  return (
    <div className="stack gap-16">
      <div className="detail-head">
        <nav className="breadcrumb" aria-label="面包屑">
          <Link to="/">首页</Link>
          <span>/</span>
          <Link to={`/search?q=${encodeURIComponent(keyword)}${includeDemo ? "&demo=1" : ""}`}>
            搜索结果
          </Link>
          <span>/</span>
          <span>横向对比</span>
        </nav>
        <h1 className="detail-title">横向对比</h1>
        <p className="page-lede">
          「{keyword}」下 {ids.length} 个同款组的价格、渠道、政策与评测对照。
          价格为确定到手价；潜在与待核验金额单独列出，不混入结论。
        </p>
        {includeDemo && (
          <Notice tone="demo" title="当前对比包含演示数据">
            演示价格为虚构数据，不参与购买建议。
          </Notice>
        )}
      </div>

      {error && (
        <Notice tone="danger" title="对比失败">
          <p>{error}</p>
        </Notice>
      )}

      {loading && (
        <div className="panel">
          <div className="panel__body">
            <span className="skeleton" style={{ display: "block", height: 180 }} />
          </div>
        </div>
      )}

      {!loading && data && (
        <>
          {data.groups.length < 2 && (
            <Notice tone="warn" title="可对比的商品组不足">
              找到 {data.groups.length} 个商品组。规格不同（容量 / 版本 / 成色）的商品不会合并，
              请返回搜索结果调整关键词或勾选更多组。
            </Notice>
          )}
          {data.groups.length > 0 &&
            (isDesktop ? <CompareTable data={data} /> : <CompareCards data={data} />)}
          {!data.has_real_data && (
            <Notice tone="warn" title="当前没有真实价格数据">
              平台开放接口未接入，以下均为演示数据。真实数据需要配置平台开发者凭据，
              详见数据来源页。
            </Notice>
          )}
        </>
      )}
    </div>
  );
}
