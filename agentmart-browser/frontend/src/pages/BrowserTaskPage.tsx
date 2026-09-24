import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import BrowserCompare from "../components/BrowserCompare";
import BrowserPlatformCard from "../components/BrowserPlatformCard";
import BrowserRecommendation from "../components/BrowserRecommendation";
import PurchaseCard from "../components/PurchaseCard";
import { Badge, Icon, Notice, Segmented, Skeleton } from "../components/ui";
import {
  browserApi,
  type ResultView,
  type TaskView,
} from "../lib/browserApi";
import { formatDateTime } from "../lib/format";

type Tab = "cards" | "compare" | "recommend" | "notes";

const TERMINAL = ["completed", "restricted", "failed", "cancelled"];
const POLL_MS = 1500;

export default function BrowserTaskPage() {
  const { taskId = "" } = useParams();
  const [task, setTask] = useState<TaskView | null>(null);
  const [result, setResult] = useState<ResultView | null>(null);
  const [tab, setTab] = useState<Tab>("cards");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [recordNote, setRecordNote] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const loadResult = useCallback(
    async (id: string, signal?: AbortSignal) => {
      try {
        setResult(await browserApi.taskResult(id, signal));
      } catch {
        setResult(null);
      }
    },
    [],
  );

  useEffect(() => {
    if (!taskId) return;
    const controller = new AbortController();
    let alive = true;

    const tick = async () => {
      try {
        const next = await browserApi.task(taskId, controller.signal);
        if (!alive) return;
        setTask(next);
        if (TERMINAL.includes(next.summary_status)) {
          await loadResult(taskId, controller.signal);
          if (pollRef.current) window.clearTimeout(pollRef.current);
          pollRef.current = null;
          return;
        }
      } catch (exc) {
        if (!alive) return;
        // 内存里没有（服务重启过）时退回数据库记录
        try {
          const record = await browserApi.taskRecord(taskId);
          if (!alive) return;
          setRecordNote("该任务已随上次服务重启结束，以下为落库的历史记录。");
          setResult(record.result ?? null);
          setError(null);
        } catch {
          setError(exc instanceof Error ? exc.message : "任务不存在");
        }
        if (pollRef.current) window.clearTimeout(pollRef.current);
        pollRef.current = null;
        return;
      }
      pollRef.current = window.setTimeout(tick, POLL_MS);
    };

    void tick();
    return () => {
      alive = false;
      controller.abort();
      if (pollRef.current) window.clearTimeout(pollRef.current);
      pollRef.current = null;
    };
  }, [taskId, loadResult]);

  const act = useCallback(
    async (fn: () => Promise<TaskView>) => {
      setBusy(true);
      setError(null);
      try {
        setTask(await fn());
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "操作失败");
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const answer = useCallback(
    async (value: string) => {
      if (!task) return;
      setBusy(true);
      setError(null);
      try {
        setTask(await browserApi.answer(task.id, task.pending_question?.key ?? "", value));
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "提交失败");
      } finally {
        setBusy(false);
      }
    },
    [task],
  );

  if (error && !task) {
    return (
      <div className="stack gap-16">
        <Notice tone="danger" title="打不开这个任务">
          {error}
        </Notice>
      </div>
    );
  }

  if (!task) {
    return (
      <div className="stack gap-16">
        <Skeleton height={28} width={280} />
        <Skeleton height={160} />
        <Skeleton height={160} />
      </div>
    );
  }

  const waiting = task.summary_status === "waiting_user";
  // 只有"运行中"才禁用开始按钮。"待开始"恰恰是最该让用户点的时候——
  // 之前把 pending 也算成 running，按钮从任务创建那刻起就是灰的，
  // 显示"执行中…"却什么都不会发生。
  const running = task.summary_status === "running";
  const canAct = !TERMINAL.includes(task.summary_status) && !task.restored;
  // 后端理应给全字段，但老记录/异常路径可能缺；缺了就按 0 显示，
  // 不能让一个数字把整页打成白屏
  const usage = {
    calls: task.model_usage?.calls ?? 0,
    vision_calls: task.model_usage?.vision_calls ?? 0,
    estimated_cost: task.model_usage?.estimated_cost ?? 0,
    errors: task.model_usage?.errors ?? [],
  };

  return (
    <div className="stack gap-24">
      <header className="stack gap-12">
        <div className="row gap-12 wrap" style={{ justifyContent: "space-between" }}>
          <div className="stack gap-6">
            <div className="row gap-8 wrap">
              <Badge tone={TERMINAL.includes(task.summary_status) ? "muted" : "info"} dot>
                {task.summary_status_label}
              </Badge>
              <Badge tone="outline">{task.origin_label}</Badge>
              <span className="small muted">
                创建于 {formatDateTime(task.created_at)} · 更新于 {formatDateTime(task.updated_at)}
              </span>
            </div>
            <h1 className="page-title">{task.requirement.text}</h1>
            <div className="row gap-8 wrap small muted">
              <span>搜索词：{task.requirement.keyword}</span>
              {task.requirement.budget_max && (
                <span>
                  预算：{task.requirement.budget_min ?? 0}～{task.requirement.budget_max} 元
                  {task.requirement.budget_approximate ? "（约）" : ""}
                </span>
              )}
              {task.requirement.scenarios.length > 0 && (
                <span>在意：{task.requirement.scenarios.join("、")}</span>
              )}
            </div>
          </div>
          <div className="row gap-8 wrap">
            {canAct && (
              <>
                <button
                  type="button"
                  className="btn btn--primary btn--sm"
                  disabled={busy || running}
                  onClick={() => act(() => browserApi.startTask(task.id))}
                >
                  <Icon name="refresh" size={14} />
                  {running ? "执行中…" : "开始 / 继续"}
                </button>
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  disabled={busy}
                  onClick={() => act(() => browserApi.cancelTask(task.id))}
                >
                  取消整个任务
                </button>
              </>
            )}
          </div>
        </div>

        {task.waiting_reason && (
          <Notice tone="warn" title={task.summary_status_label}>
            {task.waiting_reason}
          </Notice>
        )}

        {task.pending_question && (
          <Notice tone="warn" title="需要你决定">
            {task.pending_question.question}
            <div className="row gap-8 mt-8">
              <button
                type="button"
                className="btn btn--primary btn--sm"
                disabled={busy}
                onClick={() => answer("要")}
              >
                要，加入专业评测
              </button>
              <button
                type="button"
                className="btn btn--secondary btn--sm"
                disabled={busy}
                onClick={() => answer("不要")}
              >
                不要，只看价格和政策
              </button>
            </div>
            <div className="small muted mt-8">
              默认关闭。开启后只会整理可核验来源的评测线索，不会用热门视频替代你自己的预算和规格要求。
            </div>
          </Notice>
        )}

        {waiting && (
          <Notice tone="warn" title="等你在官方页面操作">
            弹出来的浏览器窗口里就是平台官方页面。请自己完成登录、扫码或验证；
            我不会代填账号密码、不记录短信验证码、也不尝试识别或绕过验证码。
            完成后这里会自动继续。
          </Notice>
        )}

        {task.budget_exhausted && (
          <Notice tone="warn" title="已达到本次预算上限">
            已停止进一步调用与浏览，下面只是已经取得的证据，不会继续消耗你的额度。
          </Notice>
        )}

        {error && <Notice tone="danger">{error}</Notice>}
        {task.restored && (
          <Notice tone="info" title="这是历史记录">
            服务重启后编排器不再持有这个任务，以下是从本地数据库读回的快照，
            只能查看、不能继续执行。想看新的结果请重新发起一次任务。
          </Notice>
        )}
        {recordNote && <Notice tone="info">{recordNote}</Notice>}

        <div className="row gap-16 wrap small muted">
          <span>
            <Icon name="price" size={13} /> 真实商品 {task.offer_count} 条
          </span>
          <span>
            <Icon name="review" size={13} /> 模型调用 {usage.calls} 次
            {usage.vision_calls > 0 && `（其中视觉 ${usage.vision_calls} 次）`}
          </span>
          <span>
            估算费用 ¥{usage.estimated_cost.toFixed(4)}（仅为估算，不等于最终账单）
          </span>
          {usage.errors.length > 0 && (
            <span className="text-price">模型调用失败 {usage.errors.length} 次</span>
          )}
        </div>
      </header>

      <section className="stack gap-12">
        <h2 className="section-title">
          各平台分别进展到哪一步
          <span className="section-note">
            单平台失败不影响其它平台；被限制的平台会说明原因，不会用演示数据补齐
          </span>
        </h2>
        <div className="grid-2">
          {task.platforms.map((state) => (
            <BrowserPlatformCard
              key={state.platform}
              task={task}
              state={state}
              onChanged={setTask}
            />
          ))}
        </div>
      </section>

      <section className="stack gap-12">
        <div className="row gap-12 wrap" style={{ justifyContent: "space-between" }}>
          <h2 className="section-title">
            比价结果
            <span className="section-note">
              {result ? `${result.groups.length} 个同款商品组` : "读取中…"}
            </span>
          </h2>
          <Segmented<Tab>
            value={tab}
            label="结果视图"
            onChange={setTab}
            options={[
              { value: "cards", label: "购买卡片" },
              { value: "compare", label: "横向对比" },
              { value: "recommend", label: "购买建议" },
              { value: "notes", label: "说明与证据" },
            ]}
          />
        </div>

        {!result ? (
          <Skeleton height={220} />
        ) : (
          <>
            {tab === "cards" && (
              <div className="stack gap-16">
                {result.groups.length === 0 ? (
                  <Notice tone="info" title="还没有可展示的商品">
                    等平台返回真实商品后，这里会出现一张张购买卡片：规格、店铺、原价、每一项优惠、
                    确定/待确认到手价、确定性等级、读取时间和原平台链接。
                  </Notice>
                ) : (
                  result.groups.flatMap((group) =>
                    group.offers.map((offer) => (
                      <PurchaseCard key={offer.id} offer={offer} />
                    )),
                  )
                )}
              </div>
            )}

            {tab === "compare" && <BrowserCompare groups={result.groups} />}

            {tab === "recommend" && (
              <BrowserRecommendation
                recommendation={result.recommendation}
                originLabel={result.origin_label}
              />
            )}

            {tab === "notes" && (
              <div className="stack gap-12">
                <Notice tone="info" title="数据来源">
                  本次结果的数据来源：{result.origin_label}。测试夹具与演示数据会单独标注，
                  绝不混入真实推荐。
                </Notice>
                {result.notes.length > 0 && (
                  <section className="panel">
                    <div className="panel__head">
                      <span style={{ color: "var(--primary)" }}>
                        <Icon name="info" size={18} />
                      </span>
                      <h3 className="section-title" style={{ fontSize: 16 }}>
                        执行过程中的说明
                      </h3>
                    </div>
                    <div className="panel__body">
                      <ul className="small">
                        {result.notes.map((note) => (
                          <li key={note}>{note}</li>
                        ))}
                      </ul>
                    </div>
                  </section>
                )}
                <section className="panel">
                  <div className="panel__head">
                    <span style={{ color: "var(--primary)" }}>
                      <Icon name="shield" size={18} />
                    </span>
                    <h3 className="section-title" style={{ fontSize: 16 }}>
                      价格确定性是怎么分档的
                    </h3>
                  </div>
                  <div className="panel__body">
                    <ol className="method-list">
                      <li className="method-item">
                        <span className="method-item__num">1</span>
                        <span className="method-item__body">
                          页面公开标价 —— 只说明页面显示多少，不代表你能拿到。
                        </span>
                      </li>
                      <li className="method-item">
                        <span className="method-item__num">2</span>
                        <span className="method-item__body">
                          账号可见的已领券/可用券 —— 只有在页面上确实看到它适用于该商品才算。
                        </span>
                      </li>
                      <li className="method-item">
                        <span className="method-item__num">3</span>
                        <span className="method-item__body">
                          满足条件后的预计价 —— 门槛、适用范围、能否叠加都核对过才计入。
                        </span>
                      </li>
                      <li className="method-item">
                        <span className="method-item__num">4</span>
                        <span className="method-item__body">
                          结算页待支付金额 —— 需要你亲自确认，本版本不会替你进结算页。
                        </span>
                      </li>
                    </ol>
                    <div className="small muted mt-8">
                      任何一档核验不了就只列示、不计入到手价。最终实际价格一律以原平台结算页为准。
                    </div>
                  </div>
                </section>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}
