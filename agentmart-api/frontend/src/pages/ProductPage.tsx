import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type {
  ProductDetailResponse,
  RecommendationPreferences,
  Review,
} from "../lib/api";
import { api } from "../lib/api";
import {
  DATA_STATUS_LABEL,
  PLATFORM_LABEL,
  formatDateTime,
  formatPercent,
  formatRelativeTime,
  displayLowestPrice,
} from "../lib/format";
import OffersTable from "../components/OffersTable";
import PolicyTable from "../components/PolicyTable";
import RecommendationPanel from "../components/RecommendationPanel";
import ReviewCard from "../components/ReviewCard";
import { Badge, EmptyState, Icon, Notice, PriceFigure, Skeleton, useIsDesktop } from "../components/ui";

type TabKey = "offers" | "policies" | "reviews" | "sources";

const TABS: { key: TabKey; label: string }[] = [
  { key: "offers", label: "跨平台购买选项" },
  { key: "policies", label: "售后政策对照" },
  { key: "reviews", label: "专业评测" },
  { key: "sources", label: "数据来源与时效" },
];

function ReviewsSection({ reviews, demoIncluded }: { reviews: Review[]; demoIncluded: boolean }) {
  if (reviews.length === 0) {
    return (
      <div className="panel">
        <EmptyState
          icon={<Icon name="review" size={20} />}
          title="还没有与该型号关联的评测"
          desc={
            demoIncluded
              ? "演示评测已随演示数据一起展示（如开启）。真实评测需要人工整理提交：粘贴 B 站或抖音链接，系统可自动解析公开元数据，观点与优缺点由整理人填写并署名。"
              : "系统不会自动抓取或生成评测结论。你可以在评测页提交公开链接并人工整理优缺点，整理内容会标注来源、整理人与整理时间。"
          }
          actions={
            <Link className="btn btn--primary btn--sm" to="/reviews">
              去提交 / 整理评测
            </Link>
          }
        />
      </div>
    );
  }
  return (
    <div className="stack gap-12">
      {reviews.map((r) => (
        <ReviewCard key={r.id} review={r} />
      ))}
    </div>
  );
}

function SourcesCards({ detail }: { detail: ProductDetailResponse }) {
  const group = detail.group!;
  return (
    <div className="stack gap-12">
      {group.offers.map((o) => (
        <div className="panel" key={o.id}>
          <div className="panel__body stack gap-8">
            <div className="row gap-8 wrap" style={{ justifyContent: "space-between" }}>
              <strong>{PLATFORM_LABEL[o.platform] ?? o.platform}</strong>
              <Badge
                tone={o.data_status === "real" ? "ok" : o.data_status === "demo" ? "price" : "warn"}
              >
                {DATA_STATUS_LABEL[o.data_status]}
              </Badge>
            </div>
            <div className="small muted">来源：{o.source || "—"}</div>
            <div className="row gap-12 wrap small">
              <span className="muted">采集 {formatRelativeTime(o.fetched_at)}</span>
              <span className="muted">
                核验 {o.verified_at ? formatDateTime(o.verified_at) : "未核验"}
              </span>
              <span className="num">可信度 {formatPercent(o.credibility)}</span>
            </div>
            <a href={o.url} target="_blank" rel="noopener noreferrer nofollow" className="row gap-6 small">
              <Icon name="external" size={12} />
              查看原始链接
            </a>
          </div>
        </div>
      ))}
      <p className="small muted">
        价格与优惠由平台开放接口返回后按统一模型入库；「采集时间」为最近一次成功获取的时间，
        超过 24 小时未更新的数据在推荐时会被降权。演示数据的可信度不参与任何结论。
      </p>
    </div>
  );
}

function SourcesTable({ detail }: { detail: ProductDetailResponse }) {
  const group = detail.group!;
  return (
    <div className="table-wrap">
      <table className="table table--dense">
        <thead>
          <tr>
            <th>平台</th>
            <th>数据来源</th>
            <th>采集时间</th>
            <th>最近核验</th>
            <th className="td-num">可信度</th>
            <th>原始链接</th>
          </tr>
        </thead>
        <tbody>
          {group.offers.map((o) => (
            <tr key={o.id}>
              <td style={{ fontWeight: 600 }}>{o.platform}</td>
              <td>
                <div className="row gap-6 wrap">
                  <Badge
                    tone={o.data_status === "real" ? "ok" : o.data_status === "demo" ? "price" : "warn"}
                  >
                    {DATA_STATUS_LABEL[o.data_status]}
                  </Badge>
                  <span className="small muted">{o.source || "—"}</span>
                </div>
              </td>
              <td className="num small" title={o.fetched_at ?? undefined}>
                {formatRelativeTime(o.fetched_at)}
              </td>
              <td className="num small">
                {o.verified_at ? formatDateTime(o.verified_at) : "未核验"}
              </td>
              <td className="td-num num">{formatPercent(o.credibility)}</td>
              <td>
                <a href={o.url} target="_blank" rel="noopener noreferrer nofollow" className="row gap-6">
                  <Icon name="external" size={12} />
                  {o.platform}
                </a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="small muted" style={{ padding: "10px 14px" }}>
        价格与优惠由平台开放接口返回后按统一模型入库；「采集时间」为最近一次成功获取的时间，
        超过 24 小时未更新的数据在推荐时会被降权。演示数据的可信度不参与任何结论。
      </p>
    </div>
  );
}

export default function ProductPage() {
  const [params] = useSearchParams();
  const keyword = params.get("q") ?? "";
  const groupId = params.get("id") ?? "";
  const includeDemo = params.get("demo") === "1";

  const [detail, setDetail] = useState<ProductDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<TabKey>("offers");
  const [prefs, setPrefs] = useState<RecommendationPreferences>({ priority: "balanced" });
  const abortRef = useRef<AbortController | null>(null);
  const isDesktop = useIsDesktop();

  const load = useCallback(async () => {
    if (!keyword || !groupId) return;
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setLoading(true);
    setError(null);
    try {
      const res = await api.productDetail(
        { keyword, groupId, includeDemo, prefs },
        ac.signal,
      );
      setDetail(res);
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      setError((e as Error).message || "加载失败");
    } finally {
      if (!ac.signal.aborted) setLoading(false);
    }
  }, [keyword, groupId, includeDemo, prefs]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keyword, groupId, includeDemo]);

  const changePrefs = (p: RecommendationPreferences) => {
    setPrefs(p);
  };

  useEffect(() => {
    // 偏好变化去抖后重新请求推荐（价格/政策数据由后端复用缓存）
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefs]);

  if (!keyword || !groupId) {
    return (
      <EmptyState
        title="缺少商品信息"
        desc="请从搜索结果页进入商品详情。"
        actions={<Link className="btn btn--primary btn--sm" to="/">回到首页</Link>}
      />
    );
  }

  if (error) {
    return (
      <Notice tone="danger" title="加载失败">
        <p>{error}</p>
        <div className="row gap-8 mt-8">
          <button type="button" className="btn btn--secondary btn--sm" onClick={load}>
            重试
          </button>
          <Link className="btn btn--secondary btn--sm" to={`/search?q=${encodeURIComponent(keyword)}`}>
            返回搜索结果
          </Link>
        </div>
      </Notice>
    );
  }

  if (loading && !detail) {
    return (
      <div className="stack gap-16">
        <Skeleton width="45%" height={28} />
        <Skeleton width="70%" height={16} />
        <div className="panel">
          <div className="panel__body stack gap-12">
            <Skeleton height={120} />
            <Skeleton width="60%" height={16} />
          </div>
        </div>
      </div>
    );
  }

  if (!detail?.group) {
    return (
      <EmptyState
        icon={<Icon name="search" size={20} />}
        title="未找到该商品组"
        desc="可能搜索缓存已过期或参数不完整，请重新检索。"
        actions={
          <Link className="btn btn--primary btn--sm" to={`/search?q=${encodeURIComponent(keyword)}`}>
            重新检索
          </Link>
        }
      />
    );
  }

  const group = detail.group;
  const specEntries = Object.entries(group.specs).filter(([, v]) => v);
  const SPEC_LABEL: Record<string, string> = {
    storage: "容量",
    color: "颜色",
    version: "版本",
    condition: "成色",
    bundle: "套装",
  };
  const lowest = displayLowestPrice(group);

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
          <span>商品详情</span>
        </nav>

        <div className="detail-title-row">
          <div style={{ minWidth: 0, flex: 1 }}>
            <h1 className="detail-title">{group.title}</h1>
            <div className="detail-specs mt-8">
              {group.brand && <span className="chip chip--accent">{group.brand}</span>}
              {group.model && <span className="chip">{group.model}</span>}
              {specEntries.map(([k, v]) => (
                <span className="chip" key={k}>
                  {SPEC_LABEL[k] ?? k}：{v}
                </span>
              ))}
              <Badge
                tone={group.confidence >= 0.75 ? "ok" : group.confidence >= 0.5 ? "warn" : "muted"}
                title="由型号词、容量、版本、成色等维度综合计算的同款匹配置信度"
              >
                匹配置信度 {Math.round(group.confidence * 100)}%
              </Badge>
              {group.offers.some((o) => o.data_status === "demo") && (
                <Badge tone="price">含演示数据</Badge>
              )}
            </div>
          </div>
          <div style={{ textAlign: "right", flexShrink: 0 }}>
            <div className="price-trio__label">最低确定到手价</div>
            {lowest.value ? (
              <>
                <PriceFigure value={lowest.value} size="lg" />
                {lowest.demo && (
                  <div className="mt-8">
                    <Badge tone="price">演示数据</Badge>
                  </div>
                )}
              </>
            ) : (
              <span className="muted">暂无可核验价格</span>
            )}
            <div className="small muted">{group.offers.length} 个购买选项</div>
          </div>
        </div>

        {group.warnings.length > 0 && (
          <Notice tone="warn" title="规格匹配提示：以下商品可能并非完全同款">
            <ul className="rec-list rec-list--conditions">
              {group.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </Notice>
        )}

        {detail.demo_included && (
          <Notice tone="demo" title="当前详情包含演示数据">
            演示价格为虚构数据，仅用于展示界面与计算逻辑，不参与购买建议。
          </Notice>
        )}
      </div>

      <RecommendationPanel
        group={group}
        recommendation={detail.recommendation}
        prefs={prefs}
        onPrefsChange={changePrefs}
      />

      <div>
        <div className="detail-tabs" role="tablist" aria-label="商品信息分区">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              id={`tab-${t.key}`}
              aria-selected={tab === t.key}
              aria-controls={`panel-${t.key}`}
              className="detail-tab"
              onClick={() => setTab(t.key)}
            >
              {t.label}
              {t.key === "reviews" && detail.reviews.length > 0 && (
                <span className="muted"> ({detail.reviews.length})</span>
              )}
              {t.key === "offers" && (
                <span className="muted"> ({group.offers.length})</span>
              )}
            </button>
          ))}
        </div>

        <div
          className="mt-16"
          role="tabpanel"
          id={`panel-${tab}`}
          aria-labelledby={`tab-${tab}`}
        >
          {tab === "offers" && (
            <div className="stack gap-12">
              {group.offers.length === 0 ? (
                <EmptyState title="该平台筛选下没有购买选项" />
              ) : (
                <OffersTable group={group} />
              )}
            </div>
          )}
          {tab === "policies" && <PolicyTable offers={group.offers} />}
          {tab === "reviews" && (
            <ReviewsSection reviews={detail.reviews} demoIncluded={detail.demo_included} />
          )}
          {tab === "sources" &&
            (isDesktop ? <SourcesTable detail={detail} /> : <SourcesCards detail={detail} />)}
        </div>
      </div>
    </div>
  );
}
