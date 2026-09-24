import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  browserApi,
  type BrowserPlatform,
  type ModeInfo,
  type PlatformStatusView,
  type TaskSummary,
} from "../lib/browserApi";
import { PLATFORM_LABEL } from "../lib/format";
import { Badge, Icon, Notice, Segmented, type BadgeTone } from "../components/ui";

const ALL_PLATFORMS: BrowserPlatform[] = ["jd", "taobao", "tmall", "pdd", "douyin"];

const EXAMPLES = [
  "预算 500～800 元，买一件适合日常通勤和轻度徒步的冲锋衣，重视防雨和透气",
  "想买一部手机，预算 3000 元左右，重视续航和信号，看看有没有我能享受的国补",
  "索尼 WH-1000XM5，预算 2500 元，只算平台标价和店铺券，不要会员方案",
];

type Mode = "browser" | "api";

function loginTone(state?: string): BadgeTone {
  if (state === "logged_in") return "ok";
  if (state === "waiting_login" || state === "failed") return "warn";
  // verified_before：本机探测到过已登录，但不是此刻的确认，用 info 而不是 ok
  if (state === "verified_before") return "info";
  if (state === "saved_unverified") return "muted";
  return "warn";
}

export default function BrowserHomePage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("browser");
  const [text, setText] = useState("");
  const [platforms, setPlatforms] = useState<BrowserPlatform[]>(ALL_PLATFORMS);
  const [maxCandidates, setMaxCandidates] = useState(6);
  const [info, setInfo] = useState<ModeInfo | null>(null);
  const [status, setStatus] = useState<PlatformStatusView | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 正在操作的平台组（打开/关闭登录窗口），用于禁用按钮
  const [loginBusy, setLoginBusy] = useState<string | null>(null);
  // 登录窗口的操作结果（成功也用这个显示，不用 error）
  const [loginNote, setLoginNote] = useState<string | null>(null);

  const reloadStatus = useCallback((signal?: AbortSignal) => {
    return browserApi
      .platformStatus(signal)
      .then(setStatus)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    browserApi.mode(controller.signal).then(setInfo).catch(() => undefined);
    reloadStatus(controller.signal);
    browserApi.listTasks(8).then(setTasks).catch(() => undefined);
    return () => controller.abort();
  }, [reloadStatus]);

  // 有登录窗口开着时勤一点刷新，让用户一登完就看到「已登录」
  const hasOpenWindow = (status?.login_windows ?? []).some((w) =>
    ["opening", "waiting_login", "logged_in"].includes(w.status),
  );
  useEffect(() => {
    if (!hasOpenWindow) return undefined;
    const timer = window.setInterval(() => reloadStatus(), 2500);
    return () => window.clearInterval(timer);
  }, [hasOpenWindow, reloadStatus]);

  const openLogin = useCallback(
    async (group: string) => {
      setLoginBusy(group);
      setError(null);
      setLoginNote(null);
      try {
        const result = await browserApi.openLogin(group);
        setLoginNote(
          `已弹出浏览器窗口：${result.message} 请在那个窗口里自己完成登录或扫码，` +
            "登好后这里会显示「已登录」。",
        );
        await reloadStatus();
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "打开登录窗口失败");
      } finally {
        setLoginBusy(null);
      }
    },
    [reloadStatus],
  );

  const closeLogin = useCallback(
    async (group: string) => {
      setLoginBusy(group);
      setError(null);
      setLoginNote(null);
      try {
        const result = await browserApi.closeLogin(group);
        setLoginNote(result.message);
        await reloadStatus();
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "关闭登录窗口失败");
      } finally {
        setLoginBusy(null);
      }
    },
    [reloadStatus],
  );

  const togglePlatform = useCallback((platform: BrowserPlatform) => {
    setPlatforms((prev) =>
      prev.includes(platform) ? prev.filter((p) => p !== platform) : [...prev, platform],
    );
  }, []);

  const start = useCallback(async () => {
    const trimmed = text.trim();
    if (!trimmed) {
      setError("请先描述你想买什么");
      return;
    }
    if (platforms.length === 0) {
      setError("至少选择一个平台");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const task = await browserApi.createTask({
        text: trimmed,
        platforms,
        options: { max_candidates: maxCandidates },
      });
      navigate(`/browser/task/${task.id}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "创建任务失败");
    } finally {
      setBusy(false);
    }
  }, [text, platforms, maxCandidates, navigate]);

  // 只有"从未登进去过"的平台才算没登录。verified_before 是本机探测到过
  // 已登录的，不该再弹"还没登录"的警告——用户刚登好却被说没登，很困惑。
  const notLoggedIn = (status?.recipes ?? []).filter(
    (r) =>
      r.login_state !== "logged_in" &&
      r.login_state !== "waiting_login" &&
      r.login_state !== "verified_before",
  );

  return (
    <div className="stack gap-24">
      <section className="stack gap-12">
        <div className="row gap-12 wrap" style={{ justifyContent: "space-between" }}>
          <div>
            <div className="hero__eyebrow">
              <Icon name="shield" size={14} />
              购物参谋 AgentMart · 个人浏览器版
            </div>
            <h1 className="hero__title" style={{ fontSize: "clamp(26px, 3.4vw, 40px)" }}>
              用你自己的登录会话，
              <br />
              在五个平台<em>同台比价</em>。
            </h1>
          </div>
          <Segmented<Mode>
            value={mode}
            label="使用模式"
            onChange={setMode}
            options={[
              { value: "browser", label: "个人浏览器版" },
              { value: "api", label: "官方 API 架构版" },
            ]}
          />
        </div>

        {mode === "browser" ? (
          <p className="hero__lede">
            在你自己登录好的浏览器窗口里读取商品、价格、账号可见的优惠和售后政策，
            计算到手价并横向比较。你随时可以暂停、接管或取消任何一个平台。
          </p>
        ) : (
          <div className="stack gap-12">
            <p className="hero__lede">
              官方 API 架构版通过平台开放接口取数，不依赖你的浏览器会话。
              当前五平台均未取得开放平台授权，因此不会显示任何价格。
            </p>
            <Notice tone="warn" title="电商官方 API 未实际授权接入">
              这一版保留完整的适配器、计价与推荐架构，用于将来取得资质或预算后接入；
              现在打开只会看到「未接入」，不会用演示数据冒充真实报价。
            </Notice>
            <div>
              <button type="button" className="btn btn--secondary" onClick={() => navigate("/")}>
                打开官方 API 架构版界面
              </button>
            </div>
          </div>
        )}
      </section>

      {mode === "browser" && (
        <>
          <section className="panel">
            <div className="panel__head">
              <span style={{ color: "var(--primary)" }}>
                <Icon name="search" size={18} />
              </span>
              <h2 className="section-title">
                说清楚你要买什么
                <span className="section-note">预算、用途、在意的点，用大白话写就行</span>
              </h2>
            </div>
            <div className="panel__body stack gap-16">
              <div className="field">
                <label className="field__label" htmlFor="req-text">
                  购物需求
                </label>
                <textarea
                  id="req-text"
                  className="textarea"
                  rows={3}
                  value={text}
                  placeholder="例如：预算 500～800 元，买一件适合日常通勤和轻度徒步的冲锋衣，重视防雨和透气"
                  onChange={(e) => setText(e.target.value)}
                />
                <div className="field__hint">
                  只有影响判断的信息缺失时才会向你追问；配送地区、品类、预算会被自动识别。
                </div>
              </div>

              <div className="row gap-8 wrap">
                {EXAMPLES.map((example) => (
                  <button
                    key={example}
                    type="button"
                    className="btn btn--ghost btn--sm"
                    onClick={() => setText(example)}
                  >
                    {example.slice(0, 18)}…
                  </button>
                ))}
              </div>

              <div className="stack gap-8">
                <div className="field__label">参与比价的平台</div>
                <div className="row gap-8 wrap">
                  {ALL_PLATFORMS.map((platform) => {
                    const active = platforms.includes(platform);
                    return (
                      <button
                        key={platform}
                        type="button"
                        className={`chip${active ? " chip--accent" : ""}`}
                        aria-pressed={active}
                        onClick={() => togglePlatform(platform)}
                      >
                        <span className={`plat-dot plat-dot--${platform}`} aria-hidden="true" />
                        {PLATFORM_LABEL[platform]}
                      </button>
                    );
                  })}
                </div>
                <div className="field__hint">
                  淘宝与天猫共用同一个登录关系，但商品来源与结果仍会分开记录。
                </div>
              </div>

              <div className="row gap-16 wrap" style={{ alignItems: "flex-end" }}>
                <div className="field" style={{ maxWidth: 220 }}>
                  <label className="field__label" htmlFor="max-candidates">
                    每个平台最多看几个商品
                  </label>
                  <select
                    id="max-candidates"
                    className="select"
                    value={maxCandidates}
                    onChange={(e) => setMaxCandidates(Number(e.target.value))}
                  >
                    {[3, 6, 10, 15].map((n) => (
                      <option key={n} value={n}>
                        {n} 个
                      </option>
                    ))}
                  </select>
                  <div className="field__hint">看得越多越全，也越慢、越容易触发平台限制。</div>
                </div>
                <button
                  type="button"
                  className="btn btn--primary"
                  onClick={start}
                  disabled={busy}
                >
                  <Icon name="search" size={15} />
                  {busy ? "创建中…" : "开始比价"}
                </button>
              </div>

              {error && <Notice tone="danger">{error}</Notice>}
            </div>
          </section>

          {info && (
            <section className="panel">
              <div className="panel__head">
                <span style={{ color: "var(--primary)" }}>
                  <Icon name="shield" size={18} />
                </span>
                <h2 className="section-title">
                  这个版本能做什么、不做什么
                  <span className="section-note">{info.tagline}</span>
                </h2>
              </div>
              <div className="panel__body stack gap-12">
                <ul className="method-list">
                  {info.boundaries.map((line) => (
                    <li className="method-item" key={line}>
                      <span className="method-item__num">
                        <Icon name="check" size={13} />
                      </span>
                      <span className="method-item__body">{line}</span>
                    </li>
                  ))}
                </ul>
                <Notice tone="info" title="数据来源">
                  {info.data_note}
                </Notice>
              </div>
            </section>
          )}

          <section className="panel">
            <div className="panel__head">
              <span style={{ color: "var(--primary)" }}>
                <Icon name="shield" size={18} />
              </span>
              <h2 className="section-title">
                第一步：在各平台登录你自己的账号
                <span className="section-note">
                  账号密码由你本人在官方页面输入，我不代填、不记录
                </span>
              </h2>
              <div className="panel__actions">
                <button
                  type="button"
                  className="btn btn--secondary btn--sm"
                  onClick={() => reloadStatus()}
                  disabled={loginBusy !== null}
                >
                  刷新状态
                </button>
              </div>
            </div>
            <div className="panel__body stack gap-12">
              <div className="table-wrap">
                <table className="table table--dense table--responsive">
                  <thead>
                    <tr>
                      <th>平台</th>
                      <th>登录态</th>
                      <th>取价是否需要登录</th>
                      <th>操作</th>
                      <th>说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ALL_PLATFORMS.map((platform) => {
                      const recipe = status?.recipes.find((r) => r.platform === platform);
                      const group = recipe?.profile_group ?? platform;
                      const window = recipe?.login_window;
                      const windowOpen =
                        window !== undefined &&
                        window.status !== "idle" &&
                        ["opening", "waiting_login", "logged_in"].includes(window.status);
                      const busy = loginBusy === group;
                      return (
                        <tr key={platform}>
                          <td className="table-cell-main" data-label="平台">
                            <span className={`plat-dot plat-dot--${platform}`} aria-hidden="true" />
                            {PLATFORM_LABEL[platform]}
                          </td>
                          <td data-label="登录态">
                            <Badge
                              tone={loginTone(recipe?.login_state)}
                              dot
                            >
                              {recipe?.login_state_label ?? "读取中…"}
                            </Badge>
                            {windowOpen && window.message && (
                              <div className="muted small" style={{ marginTop: 4 }}>
                                {window.message}
                              </div>
                            )}
                          </td>
                          <td data-label="取价是否需要登录">
                            {recipe?.requires_login_for_price ? "需要" : "不强制"}
                          </td>
                          <td data-label="操作">
                            {windowOpen ? (
                              <button
                                type="button"
                                className="btn btn--secondary btn--sm"
                                onClick={() => closeLogin(group)}
                                disabled={busy}
                              >
                                {busy ? "处理中…" : "关闭窗口"}
                              </button>
                            ) : (
                              <button
                                type="button"
                                className="btn btn--primary btn--sm"
                                onClick={() => openLogin(group)}
                                disabled={busy}
                              >
                                {busy ? "正在打开…" : "登录"}
                              </button>
                            )}
                          </td>
                          <td className="muted small" data-label="说明">
                            {recipe ? recipe.notes : "读取中…"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {loginNote && <Notice tone="info">{loginNote}</Notice>}
              {notLoggedIn.length > 0 && (
                <Notice tone="warn" title="这些平台还没登录">
                  {notLoggedIn.map((r) => r.display_name).join("、")}{" "}
                  还没有可用的登录态。点右边的「登录」会弹出一个可见的浏览器窗口，
                  请你在官方页面自己完成登录或扫码；我不会代填账号密码，也不会记录验证码。
                  登录窗口开着的时候，对应平台不会自动开始比价。
                </Notice>
              )}
            </div>
          </section>

          <section className="panel">
            <div className="panel__head">
              <span style={{ color: "var(--primary)" }}>
                <Icon name="table" size={18} />
              </span>
              <h2 className="section-title">
                最近的比价任务
                <span className="section-note">刷新页面后历史任务依然可见</span>
              </h2>
            </div>
            <div className="panel__body">
              {tasks.length === 0 ? (
                <p className="muted">还没有任务。上面的需求框就是入口。</p>
              ) : (
                <ul className="rec-list">
                  {tasks.map((task) => (
                    <li key={task.id}>
                      <button
                        type="button"
                        className="clickable-panel"
                        style={{ width: "100%", textAlign: "left" }}
                        onClick={() => navigate(`/browser/task/${task.id}`)}
                      >
                        <div className="row gap-12 wrap" style={{ justifyContent: "space-between" }}>
                          <span className="table-cell-main">{task.requirement_text}</span>
                          <span className="row gap-8">
                            <Badge tone="muted">{task.offer_count} 条商品</Badge>
                            <Badge tone="outline">{task.created_at ?? "—"}</Badge>
                          </span>
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
