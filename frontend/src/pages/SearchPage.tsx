import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { CanonicalProduct, Platform, SearchResponse } from "../lib/api";
import { api } from "../lib/api";
import { PLATFORM_LABEL, displayLowestPrice } from "../lib/format";
import PlatformStatusStrip from "../components/PlatformStatusStrip";
import SearchBox from "../components/SearchBox";
import {
  Badge,
  EmptyState,
  Icon,
  Notice,
  PriceFigure,
  Skeleton,
} from "../components/ui";

const SPEC_LABEL: Record<string, string> = {
  storage: "容量",
  color: "颜色",
  version: "版本",
  condition: "成色",
  bundle: "套装",
};

function GroupCard({
  group,
  keyword,
  includeDemo,
  checked,
  onToggleCompare,
}: {
  group: CanonicalProduct;
  keyword: string;
  includeDemo: boolean;
  checked: boolean;
  onToggleCompare: () => void;
}) {
  const specEntries = Object.entries(group.specs).filter(([, v]) => v);
  const reviewCount = (group as CanonicalProduct & { reviews?: unknown[] }).reviews?.length ?? 0;
  const platforms = Array.from(new Set(group.offers.map((o) => o.platform)));
  const lowest = displayLowestPrice(group);

  return (
    <div className="panel group-card">
      <div className="group-card__body">
        <div className="group-card__top">
          <div style={{ minWidth: 0, flex: 1 }}>
            <div className="row gap-6 wrap" style={{ marginBottom: 6 }}>
              {group.brand && <span className="chip chip--accent">{group.brand}</span>}
              {group.model && <span className="chip">{group.model}</span>}
              <Badge
                tone={group.confidence >= 0.75 ? "ok" : group.confidence >= 0.5 ? "warn" : "muted"}
                title="同款匹配置信度：由型号词、容量、版本、成色等维度综合计算"
              >
                匹配置信度 {Math.round(group.confidence * 100)}%
              </Badge>
              {group.offers.some((o) => o.data_status === "demo") && (
                <Badge tone="price">含演示数据</Badge>
              )}
            </div>
            <h3 className="group-card__title">{group.title}</h3>
            {specEntries.length > 0 && (
              <div className="group-card__specs mt-8">
                {specEntries.map(([k, v]) => (
                  <span className="chip" key={k}>
                    {SPEC_LABEL[k] ?? k}：{v}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div style={{ textAlign: "right", flexShrink: 0 }}>
            <div className="price-trio__label">最低确定到手价</div>
            {lowest.value ? (
              <>
                <PriceFigure value={lowest.value} size="lg" />
                {lowest.demo && (
                  <div>
                    <Badge tone="price">演示</Badge>
                  </div>
                )}
              </>
            ) : (
              <span className="muted">暂无</span>
            )}
            <div className="small muted">{group.offers.length} 个购买选项</div>
          </div>
        </div>

        {group.warnings.length > 0 && (
          <Notice tone="warn" title="规格匹配提示">
            <ul className="rec-list rec-list--conditions">
              {group.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </Notice>
        )}

        <div className="group-card__foot">
          <div className="platform-list">
            {platforms.map((p) => {
              const offer = group.offers.find((o) => o.platform === p)!;
              return (
                <span
                  className={`platform-pill${
                    offer.breakdown &&
                    lowest.value &&
                    offer.breakdown.definite_total === lowest.value
                      ? " platform-pill--best"
                      : ""
                  }`}
                  key={p}
                >
                  <span className={`plat-dot plat-dot--${p}`} aria-hidden="true" />
                  {PLATFORM_LABEL[p]}
                  {offer.data_status === "demo" && " · 演示"}
                </span>
              );
            })}
          </div>
          {reviewCount > 0 && (
            <span className="row gap-6 small muted">
              <Icon name="review" size={13} />
              {reviewCount} 条相关评测
            </span>
          )}
          <div className="row gap-8" style={{ marginLeft: "auto" }}>
            <label className="checkbox">
              <input type="checkbox" checked={checked} onChange={onToggleCompare} />
              加入对比
            </label>
            <Link
              className="btn btn--primary btn--sm"
              to={`/product?q=${encodeURIComponent(keyword)}&id=${group.id}${
                includeDemo ? "&demo=1" : ""
              }`}
            >
              查看详情
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="stack gap-16">
      {[0, 1, 2].map((i) => (
        <div className="panel" key={i}>
          <div className="panel__body stack gap-12">
            <Skeleton width="38%" height={20} />
            <Skeleton width="72%" height={15} />
            <Skeleton width="55%" height={15} />
            <div className="row gap-8">
              <Skeleton width={92} height={30} radius={6} />
              <Skeleton width={92} height={30} radius={6} />
              <Skeleton width={92} height={30} radius={6} />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function SearchPage() {
  const [params, setParams] = useSearchParams();
  const keyword = params.get("q") ?? "";
  const includeDemo = params.get("demo") === "1";

  const [data, setData] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [platformFilter, setPlatformFilter] = useState<Platform | "all">("all");
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const runSearch = useCallback(
    async (q: string, demo: boolean) => {
      if (!q) return;
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;
      setLoading(true);
      setError(null);
      try {
        const res = await api.search(q, demo, ac.signal);
        setData(res);
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        setError((e as Error).message || "检索失败");
      } finally {
        if (!ac.signal.aborted) setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (keyword) runSearch(keyword, includeDemo);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keyword, includeDemo]);

  const onSearch = (q: string) => {
    const next = new URLSearchParams({ q });
    if (includeDemo) next.set("demo", "1");
    setParams(next);
    setCompareIds([]);
  };

  const onDemoChange = (v: boolean) => {
    const next = new URLSearchParams({ q: keyword });
    if (v) next.set("demo", "1");
    setParams(next);
  };

  const groups = useMemo(() => {
    if (!data) return [];
    if (platformFilter === "all") return data.groups;
    return data.groups
      .map((g) => ({
        ...g,
        offers: g.offers.filter((o) => o.platform === platformFilter),
      }))
      .filter((g) => g.offers.length > 0);
  }, [data, platformFilter]);

  const availablePlatforms = useMemo(() => {
    if (!data) return [] as Platform[];
    return Array.from(new Set(data.groups.flatMap((g) => g.offers.map((o) => o.platform))));
  }, [data]);

  if (!keyword) {
    return (
      <div className="stack gap-24">
        <SearchBox
          demoChecked={includeDemo}
          onDemoChange={(v) => {
            const next = new URLSearchParams();
            if (v) next.set("demo", "1");
            setParams(next);
          }}
          onSearch={onSearch}
          autoFocus
        />
        <EmptyState
          icon={<Icon name="search" size={20} />}
          title="输入商品名称或型号开始比较"
          desc="也可以在首页直接粘贴商品链接。系统会到各平台开放接口检索同款，并标注每条数据的来源与时效。"
        />
      </div>
    );
  }

  return (
    <div className="stack gap-16">
      <SearchBox
        initialKeyword={keyword}
        initialMode={keyword.startsWith("http") ? "link" : "keyword"}
        loading={loading}
        demoChecked={includeDemo}
        onDemoChange={onDemoChange}
        onSearch={onSearch}
      />

      {data?.is_link_query && data.link_notice && (
        <Notice tone="info" title="链接检索说明">
          {data.link_notice}
        </Notice>
      )}

      {data?.demo_included && (
        <Notice tone="demo" title="当前结果包含演示数据">
          {data.demo_notice ??
            "演示价格为虚构数据，仅用于展示界面与计算逻辑，不参与购买建议，也不会与真实数据混排。"}
        </Notice>
      )}

      {error && (
        <Notice tone="danger" title="检索失败">
          <p>{error}</p>
          <button
            type="button"
            className="btn btn--secondary btn--sm mt-8"
            onClick={() => runSearch(keyword, includeDemo)}
          >
            <Icon name="refresh" size={13} />
            重试
          </button>
        </Notice>
      )}

      {loading && <LoadingSkeleton />}

      {!loading && data && (
        <>
          <section className="panel">
            <div className="panel__head">
              <span style={{ color: "var(--primary)" }}>
                <Icon name="table" size={17} />
              </span>
              <h2 className="section-title">
                检索结果
                <span className="section-note">
                  「{data.keyword}」 · {data.groups.length} 个同款组 ·{" "}
                  {data.has_real_data ? "含真实接口数据" : "暂无真实接口数据"}
                </span>
              </h2>
              <div className="panel__actions">
                {compareIds.length >= 2 && (
                  <Link
                    className="btn btn--primary btn--sm"
                    to={`/compare?q=${encodeURIComponent(data.keyword)}&ids=${compareIds.join(",")}${
                      includeDemo ? "&demo=1" : ""
                    }`}
                  >
                    对比已选 {compareIds.length} 项
                  </Link>
                )}
              </div>
            </div>
            <div className="panel__body stack gap-12">
              <div className="row gap-8 wrap">
                {data.platform_results.map((r) => (
                  <span className="chip" key={r.platform} title={r.message}>
                    <span className={`plat-dot plat-dot--${r.platform}`} aria-hidden="true" />
                    {PLATFORM_LABEL[r.platform]}：
                    {r.offer_count > 0 ? `${r.offer_count} 条` : "无数据"}
                  </span>
                ))}
              </div>
              {!data.has_real_data && (
                <Notice tone="warn" title="当前没有真实价格数据">
                  <p>
                    五个平台的开放接口都需要申请开发者凭据后才能返回真实数据。
                    未配置时系统返回「未接入」而不是虚构价格。
                  </p>
                  <div className="row gap-8 wrap mt-8">
                    {!includeDemo && (
                      <button
                        type="button"
                        className="btn btn--secondary btn--sm"
                        onClick={() => onDemoChange(true)}
                      >
                        查看演示数据（虚构）
                      </button>
                    )}
                    <Link className="btn btn--secondary btn--sm" to="/sources">
                      查看需要申请哪些凭据
                    </Link>
                  </div>
                </Notice>
              )}
            </div>
          </section>

          {availablePlatforms.length > 1 && (
            <div className="row gap-8 wrap">
              <span className="small muted">平台筛选：</span>
              <button
                type="button"
                className="chip"
                aria-pressed={platformFilter === "all"}
                onClick={() => setPlatformFilter("all")}
              >
                全部
              </button>
              {availablePlatforms.map((p) => (
                <button
                  key={p}
                  type="button"
                  className="chip"
                  aria-pressed={platformFilter === p}
                  onClick={() => setPlatformFilter(p)}
                >
                  <span className={`plat-dot plat-dot--${p}`} aria-hidden="true" />
                  {PLATFORM_LABEL[p]}
                </button>
              ))}
            </div>
          )}

          {groups.length === 0 ? (
            <div className="panel">
              <EmptyState
                icon={<Icon name="search" size={20} />}
                title={data.has_real_data ? "没有匹配的商品组" : "暂无可核验数据"}
                desc={
                  data.has_real_data
                    ? "调整关键词（建议补品牌与完整型号）后再试。规格不同（容量 / 版本 / 成色）的商品不会被合并，而是分别成组。"
                    : "平台接口未接入，且未开启演示数据。可前往数据来源页查看需要申请的凭据，或开启演示数据查看界面效果。"
                }
                actions={
                  <>
                    <Link className="btn btn--secondary btn--sm" to="/sources">
                      数据来源与凭据说明
                    </Link>
                    {!includeDemo && (
                      <button
                        type="button"
                        className="btn btn--secondary btn--sm"
                        onClick={() => onDemoChange(true)}
                      >
                        开启演示数据
                      </button>
                    )}
                  </>
                }
              />
            </div>
          ) : (
            <div className="stack gap-12">
              {groups.map((g) => (
                <GroupCard
                  key={g.id}
                  group={g}
                  keyword={keyword}
                  includeDemo={includeDemo}
                  checked={compareIds.includes(g.id)}
                  onToggleCompare={() =>
                    setCompareIds((prev) =>
                      prev.includes(g.id)
                        ? prev.filter((x) => x !== g.id)
                        : prev.length < 5
                          ? [...prev, g.id]
                          : prev,
                    )
                  }
                />
              ))}
            </div>
          )}
        </>
      )}

      <section className="stack gap-12">
        <h2 className="section-title">
          平台接入状态
          <span className="section-note">实时读取后端适配器配置</span>
        </h2>
        <PlatformStatusStrip compact />
      </section>
    </div>
  );
}
