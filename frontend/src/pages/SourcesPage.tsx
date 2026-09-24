import { useEffect, useState } from "react";
import type { DataSourceInfo, PlatformStatus } from "../lib/api";
import { api } from "../lib/api";
import {
  CONNECTION_STATUS_LABEL,
  PLATFORM_LABEL,
  formatDateTime,
  formatRelativeTime,
} from "../lib/format";
import { Badge, EmptyState, Icon, Notice, useIsDesktop } from "../components/ui";

const KIND_LABEL: Record<string, string> = {
  platform_api: "平台开放接口",
  review_metadata: "评测公开元数据",
  curated: "人工整理",
  demo: "演示数据",
};

const METHODS = [
  {
    title: "同款匹配：规格不一致绝不合并",
    body: "系统从商品标题提取品牌、型号词、容量、版本、成色与套装信息。容量 / 版本 / 成色 / 套装不同属于硬冲突，不会合并为同一商品，而是分别成组并给出提示；仅颜色不同会给出软提示。",
  },
  {
    title: "到手价三层：确定 / 潜在 / 待核验",
    body: "无条件成立的抵扣计入「确定到手价」；需要满足条件（如满减门槛、新用户、指定支付方式）的抵扣计入「潜在到手价」；无法核实的金额单独列示，不计入任何到手价。",
  },
  {
    title: "优惠互斥组：同组只取最优",
    body: "平台规则中常规定「优惠券与活动价不可叠加」。数据源声明的互斥组内只保留金额最高的一项，被舍弃的项目在拆解中注明原因。以旧换新永远只作为条件性抵扣展示。",
  },
  {
    title: "购买建议：价格、售后与数据可信度加权",
    body: "价格分按相对价差折算（价差 25% 以内线性衰减），售后分来自店铺类型与政策覆盖，数据分来自真实数据比例与新鲜度。超出预算的选项会被大幅降分而不是直接隐藏。每个建议都附带依据、生效条件与风险。",
  },
  {
    title: "评测五维评估",
    body: "是否实测该型号、是否提供测试方法与可复核数据、是否说明使用条件与局限、是否披露商业合作关系、观点是否有足够内容支撑。五项全部满足且评分达标才会标记「建议参考」。",
  },
];

function PlatformStatusTable({ statuses }: { statuses: PlatformStatus[] }) {
  return (
    <div className="table-wrap panel">
      <table className="table table--dense">
        <thead>
          <tr>
            <th>平台</th>
            <th>状态</th>
            <th>适配器</th>
            <th>需要的环境变量</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          {statuses.map((s) => (
            <tr key={s.platform}>
              <td>
                <span className="row gap-6">
                  <span className={`plat-dot plat-dot--${s.platform}`} aria-hidden="true" />
                  <strong>{PLATFORM_LABEL[s.platform]}</strong>
                </span>
              </td>
              <td>
                <Badge
                  tone={
                    s.status === "connected" ? "ok" : s.status === "error" ? "danger" : "muted"
                  }
                  dot
                >
                  {CONNECTION_STATUS_LABEL[s.status]}
                </Badge>
              </td>
              <td className="mono small">{s.adapter}</td>
              <td>
                <div className="row gap-6 wrap">
                  {s.required_env.map((e) => (
                    <span className="chip mono" key={e}>
                      {e}
                    </span>
                  ))}
                </div>
              </td>
              <td className="small" style={{ color: "var(--ink-2)", maxWidth: 320 }}>
                {s.message}
                {s.docs_url && (
                  <>
                    {" "}
                    <a href={s.docs_url} target="_blank" rel="noopener noreferrer nofollow">
                      开放平台文档
                    </a>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PlatformStatusCards({ statuses }: { statuses: PlatformStatus[] }) {
  return (
    <div className="stack gap-12">
      {statuses.map((s) => (
        <div className="panel" key={s.platform}>
          <div className="panel__body stack gap-8">
            <div className="row gap-8 wrap" style={{ justifyContent: "space-between" }}>
              <span className="row gap-6">
                <span className={`plat-dot plat-dot--${s.platform}`} aria-hidden="true" />
                <strong>{PLATFORM_LABEL[s.platform]}</strong>
              </span>
              <Badge
                tone={s.status === "connected" ? "ok" : s.status === "error" ? "danger" : "muted"}
                dot
              >
                {CONNECTION_STATUS_LABEL[s.status]}
              </Badge>
            </div>
            <div className="small muted">适配器 {s.adapter}</div>
            <div className="row gap-6 wrap">
              {s.required_env.map((e) => (
                <span className="chip mono" key={e}>
                  {e}
                </span>
              ))}
            </div>
            <div className="small" style={{ color: "var(--ink-2)" }}>
              {s.message}
              {s.docs_url && (
                <>
                  {" "}
                  <a href={s.docs_url} target="_blank" rel="noopener noreferrer nofollow">
                    开放平台文档
                  </a>
                </>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function SourcesPage() {
  const [sources, setSources] = useState<DataSourceInfo[] | null>(null);
  const [statuses, setStatuses] = useState<PlatformStatus[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isDesktop = useIsDesktop();

  useEffect(() => {
    const ac = new AbortController();
    Promise.all([api.sources(ac.signal), api.platforms(ac.signal)])
      .then(([s, p]) => {
        setSources(s);
        setStatuses(p);
      })
      .catch((e) => {
        if ((e as Error).name !== "AbortError") setError((e as Error).message);
      });
    return () => ac.abort();
  }, []);

  return (
    <div className="stack gap-24">
      <div className="detail-head">
        <h1 className="detail-title">数据来源与可信度</h1>
        <p className="page-lede">
          这个页面说明每个数字从哪来、多久更新一次、哪些平台尚未接入、
          以及系统如何计算到手价与购买建议。演示数据与真实数据严格分离。
        </p>
      </div>

      {error && (
        <Notice tone="danger" title="加载失败">
          {error}
        </Notice>
      )}

      <section className="stack gap-12">
        <h2 className="section-title">
          平台接入状态
          <span className="section-note">需要开发者凭据的接口，未配置时返回「未接入」而非虚构数据</span>
        </h2>
        {statuses === null ? (
          <div className="panel">
            <div className="panel__body">
              <span className="skeleton" style={{ display: "block", height: 60 }} />
            </div>
          </div>
        ) : isDesktop ? (
          <PlatformStatusTable statuses={statuses} />
        ) : (
          <PlatformStatusCards statuses={statuses} />
        )}
      </section>

      <section className="stack gap-12">
        <h2 className="section-title">
          数据来源清单
          <span className="section-note">每条数据在商品详情中同样标注来源与采集时间</span>
        </h2>
        {sources === null ? (
          <div className="panel">
            <div className="panel__body">
              <span className="skeleton" style={{ display: "block", height: 120 }} />
            </div>
          </div>
        ) : sources.length === 0 ? (
          <div className="panel">
            <EmptyState title="暂无数据来源信息" desc="后端未返回数据来源清单。" />
          </div>
        ) : (
          <div className="panel">
            {sources.map((s) => (
              <div className="source-row" key={s.name}>
                <div className="source-row__main">
                  <div className="source-row__name">
                    {s.name}
                    <Badge
                      tone={
                        s.kind === "demo"
                          ? "price"
                          : s.status === "active"
                            ? "ok"
                            : "muted"
                      }
                    >
                      {KIND_LABEL[s.kind] ?? s.kind}
                    </Badge>
                    {s.kind === "demo" && <Badge tone="price">虚构数据</Badge>}
                  </div>
                  <div className="source-row__desc">{s.description}</div>
                  <div className="row gap-12 wrap small muted mt-8">
                    {s.last_updated && (
                      <span title={s.last_updated}>
                        更新于 {formatDateTime(s.last_updated)}（{formatRelativeTime(s.last_updated)}）
                      </span>
                    )}
                    {s.url && (
                      <a href={s.url} target="_blank" rel="noopener noreferrer nofollow">
                        查看来源
                      </a>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="stack gap-12">
        <h2 className="section-title">
          计算方法
          <span className="section-note">价格、匹配、推荐的规则都写在后端 domain 层并有单元测试覆盖</span>
        </h2>
        <div className="panel">
          <div className="panel__body method-list">
            {METHODS.map((m, i) => (
              <div className="method-item" key={m.title}>
                <span className="method-item__num" aria-hidden="true">
                  {i + 1}
                </span>
                <div className="method-item__body">
                  <strong>{m.title}</strong>
                  <br />
                  {m.body}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="stack gap-12">
        <h2 className="section-title">
          诚实的边界
          <span className="section-note">系统明确不做的事</span>
        </h2>
        <div className="grid-2">
          <Notice tone="warn" title="不抓取需登录的商品页面">
            平台商品页的个性化价格、登录后优惠券、下单流程中的最终优惠，需要账号环境才能看到。
            系统只使用开放接口与公开规则，不绕过登录、验证码与反爬机制。
          </Notice>
          <Notice tone="warn" title="不生成评测结论">
            系统不抓取视频内容、不生成创作者观点。评测的标题、UP 主、播放量等元数据可自动解析；
            优缺点、原文摘录、测试证据由整理人填写并署名，AI 归纳单独标注。
          </Notice>
          <Notice tone="warn" title="不承诺价格准确">
            到手价基于接口返回的标价与已声明优惠计算，实际以下单时页面显示为准。
            无法核实的金额（如地区补贴、以旧换新残值）只列示，不计入。
          </Notice>
          <Notice tone="warn" title="演示数据不参与结论">
            演示价格为虚构数据，只在勾选「包含演示数据」后展示，带有明显标记，
            并且在只有演示数据时购买建议会直接说明数据不足。
          </Notice>
        </div>
      </section>

      <p className="small muted row gap-6">
        <Icon name="info" size={13} />
        后端接口文档：<a href="/docs" target="_blank" rel="noopener noreferrer">/docs</a>（Swagger UI）
      </p>
    </div>
  );
}
