import { useCallback, useState } from "react";
import {
  type PlatformState,
  type TaskView,
  browserApi,
} from "../lib/browserApi";
import { Badge, Icon, Notice } from "./ui";

const STATUS_TONE: Record<string, "ok" | "warn" | "danger" | "info" | "muted" | "outline"> = {
  pending: "muted",
  running: "info",
  waiting_user: "warn",
  waiting_confirm: "warn",
  completed: "ok",
  restricted: "danger",
  failed: "danger",
  cancelled: "muted",
};

const ACTION_LABEL: Record<string, string> = {
  navigate: "打开页面",
  read: "读取字段",
  scroll: "滚动加载",
  screenshot: "截图取证",
  wait_user: "等待您",
  ask_confirm: "请求确认",
  mutating: "写操作",
};

function PlatformActions({
  task,
  state,
  onChanged,
}: {
  task: TaskView;
  state: PlatformState;
  onChanged: (next: TaskView) => void;
}) {
  const [busy, setBusy] = useState(false);

  const run = useCallback(
    async (fn: () => Promise<TaskView>) => {
      setBusy(true);
      try {
        onChanged(await fn());
      } catch {
        /* 错误由轮询到的状态体现 */
      } finally {
        setBusy(false);
      }
    },
    [onChanged],
  );

  const terminal = ["completed", "restricted", "failed", "cancelled"].includes(state.status);

  // 历史快照里的平台已不由编排器持有，暂停/继续/取消都没有意义
  if (task.restored) return null;

  return (
    <div className="row gap-8 wrap">
      {state.paused ? (
        <button
          type="button"
          className="btn btn--secondary btn--sm"
          disabled={busy}
          onClick={() => run(() => browserApi.resumePlatform(task.id, state.platform))}
        >
          继续该平台
        </button>
      ) : (
        !terminal && (
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            disabled={busy}
            onClick={() => run(() => browserApi.pausePlatform(task.id, state.platform))}
          >
            暂停
          </button>
        )
      )}
      {!terminal && (
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          disabled={busy}
          onClick={() => run(() => browserApi.cancelPlatform(task.id, state.platform))}
        >
          取消该平台
        </button>
      )}
    </div>
  );
}

export default function BrowserPlatformCard({
  task,
  state,
  onChanged,
}: {
  task: TaskView;
  state: PlatformState;
  onChanged: (next: TaskView) => void;
}) {
  const [open, setOpen] = useState(false);
  const tone = STATUS_TONE[state.status] ?? "muted";

  return (
    <section className="panel">
      <div className="panel__head">
        <span className={`plat-dot plat-dot--${state.platform}`} aria-hidden="true" />
        <h3 className="section-title" style={{ fontSize: 16 }}>
          {state.display_name}
          <span className="section-note">
            {state.profile_group === "taobao" && state.platform === "tmall"
              ? "与淘宝共用登录关系"
              : `登录组：${state.profile_group}`}
          </span>
        </h3>
        <div className="panel__actions">
          <Badge tone={tone} dot>
            {state.status_label}
          </Badge>
        </div>
      </div>
      <div className="panel__body stack gap-12">
        <div className="row gap-16 wrap small muted">
          <span>
            <Icon name="price" size={13} /> 商品 {state.offer_count} 条
          </span>
          <span>
            <Icon name="link" size={13} /> 页面 {state.pages_visited} 个
          </span>
          <span>
            <Icon name="review" size={13} /> 模型调用 {state.model_calls} 次
          </span>
          {state.started_at && <span>开始 {state.started_at}</span>}
          {state.finished_at && <span>结束 {state.finished_at}</span>}
        </div>

        {state.status === "waiting_user" && (
          <Notice tone="warn" title="需要您接管">
            {state.takeover
              ? state.takeover.message
              : `${state.blocked_reason_label ?? "需要您操作"}：${
                  state.blocked_detail ??
                  "请在弹出来的浏览器窗口里自己完成登录或验证，完成后这里会自动继续。"
                }`}
            <div className="mt-8 small">
              窗口里就是平台官方页面，我不会代填账号密码、不记录短信验证码、也不尝试绕过验证码。
              处理完我会自动接着比价，不需要你重新开始。
            </div>
          </Notice>
        )}

        {state.status === "restricted" && (
          <Notice tone="danger" title="该平台本次未完成">
            {state.blocked_reason_label ?? "平台限制"}：
            {state.blocked_detail ?? "平台阻止了自动访问"}
            <div className="mt-8 small">
              已停止该平台的自动操作，没有用演示数据补齐。你可以在设置里清除登录态后重试，
              或把商品链接和优惠信息手动贴给我。
            </div>
          </Notice>
        )}

        {state.problems.length > 0 && (
          <details open={state.problems.length <= 3}>
            <summary className="small muted">待核实说明（{state.problems.length}）</summary>
            <ul className="small muted">
              {state.problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          </details>
        )}

        <div>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
          >
            {open ? "收起执行记录" : `查看执行记录（${state.steps.length}）`}
          </button>
        </div>

        {open && (
          <ol className="step-log">
            {state.steps.map((step) => (
              <li key={step.seq} className="step-log__item">
                <span className="step-log__time num">{step.at}</span>
                <span className="step-log__action">
                  {ACTION_LABEL[step.action] ?? step.action}
                </span>
                <span className="step-log__detail">{step.detail}</span>
              </li>
            ))}
          </ol>
        )}

        {state.urls.length > 0 && (
          <details>
            <summary className="small muted">本次访问过的页面（{state.urls.length}）</summary>
            <ul className="small">
              {state.urls.map((url) => (
                <li key={url}>
                  <a
                    className="link-out"
                    href={url}
                    target="_blank"
                    rel="noreferrer noopener"
                    title={url}
                  >
                    {url}
                  </a>
                </li>
              ))}
            </ul>
          </details>
        )}

        <PlatformActions task={task} state={state} onChanged={onChanged} />
      </div>
    </section>
  );
}
