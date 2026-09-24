import { useCallback, useEffect, useState } from "react";
import {
  browserApi,
  type ModelConfigView,
  type ModelTestView,
  type PlatformStatusView,
} from "../lib/browserApi";
import { PLATFORM_LABEL } from "../lib/format";
import { Badge, Icon, Notice, Segmented } from "../components/ui";

interface ModelForm {
  provider: string;
  base_url: string;
  model: string;
  api_key: string;
  max_calls_per_task: number;
  max_cost_per_task: number;
  timeout_seconds: number;
  note: string;
}

const EMPTY_FORM: ModelForm = {
  provider: "openai-compatible",
  base_url: "",
  model: "",
  api_key: "",
  max_calls_per_task: 40,
  max_cost_per_task: 0,
  timeout_seconds: 60,
  note: "",
};

export default function BrowserSettingsPage() {
  const [tab, setTab] = useState<"platforms" | "model">("platforms");
  const [status, setStatus] = useState<PlatformStatusView | null>(null);
  const [config, setConfig] = useState<ModelConfigView | null>(null);
  const [form, setForm] = useState<ModelForm>(EMPTY_FORM);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ModelTestView | null>(null);

  const reload = useCallback(() => {
    browserApi.platformStatus().then(setStatus).catch(() => undefined);
    browserApi
      .modelConfig()
      .then((cfg) => {
        setConfig(cfg);
        setForm((prev) => ({
          ...prev,
          provider: cfg.provider,
          base_url: cfg.base_url,
          model: cfg.model,
          max_calls_per_task: cfg.max_calls_per_task,
          max_cost_per_task: cfg.max_cost_per_task,
          timeout_seconds: cfg.timeout_seconds,
          note: cfg.note ?? "",
        }));
      })
      .catch(() => undefined);
  }, []);

  useEffect(reload, [reload]);

  const clearProfile = useCallback(
    async (group: string) => {
      setBusy(true);
      setError(null);
      try {
        const res = await browserApi.clearProfile(group);
        setMessage(res.message);
        reload();
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "清除失败");
      } finally {
        setBusy(false);
      }
    },
    [reload],
  );

  const saveModel = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      setBusy(true);
      setError(null);
      setMessage(null);
      try {
        const payload: Record<string, unknown> = {
          provider: form.provider,
          base_url: form.base_url,
          model: form.model,
          max_calls_per_task: form.max_calls_per_task,
          max_cost_per_task: form.max_cost_per_task,
          timeout_seconds: form.timeout_seconds,
          note: form.note,
        };
        if (form.api_key.trim()) payload.api_key = form.api_key.trim();
        const saved = await browserApi.saveModelConfig(payload);
        setConfig(saved);
        setForm((prev) => ({ ...prev, api_key: "" }));
        setMessage("已保存到本机配置文件（Key 不会显示，也不会进入前端产物或日志）");
        setTestResult(null);
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "保存失败");
      } finally {
        setBusy(false);
      }
    },
    [form],
  );

  const testModel = useCallback(async () => {
    setTesting(true);
    setError(null);
    setTestResult(null);
    try {
      const res = await browserApi.testModel();
      setTestResult(res);
      reload();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "测试失败");
    } finally {
      setTesting(false);
    }
  }, [reload]);

  const deleteModel = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await browserApi.deleteModelConfig();
      setMessage(res.message);
      setForm(EMPTY_FORM);
      setConfig(null);
      reload();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除失败");
    } finally {
      setBusy(false);
    }
  }, [reload]);

  return (
    <div className="stack gap-24">
      <header className="stack gap-8">
        <h1 className="page-title">平台与模型设置</h1>
        <p className="page-lede">
          浏览器登录状态和模型 Key 都只保存在本机用户目录，不在仓库里，也不会进入前端产物。
          每一项都可以随时清除。
        </p>
        <Segmented<"platforms" | "model">
          value={tab}
          label="设置分类"
          onChange={setTab}
          options={[
            { value: "platforms", label: "平台与登录态" },
            { value: "model", label: "模型（自带 Key）" },
          ]}
        />
      </header>

      {message && <Notice tone="ok">{message}</Notice>}
      {error && <Notice tone="danger">{error}</Notice>}

      {tab === "platforms" && (
        <div className="stack gap-16">
          <section className="panel">
            <div className="panel__head">
              <span style={{ color: "var(--primary)" }}>
                <Icon name="shield" size={18} />
              </span>
              <h2 className="section-title" style={{ fontSize: 17 }}>
                登录态存放位置
                <span className="section-note">
                  {status ? status.storage.root : "读取中…"}
                </span>
              </h2>
            </div>
            <div className="panel__body stack gap-12">
              <p className="small">{status?.storage.note}</p>
              <div className="table-wrap">
                <table className="table table--dense table--responsive">
                  <thead>
                    <tr>
                      <th>登录组</th>
                      <th>覆盖平台</th>
                      <th>状态</th>
                      <th>目录</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(status?.profiles ?? []).map((profile) => (
                      <tr key={profile.group}>
                        <td className="table-cell-main" data-label="登录组">
                          {profile.group}
                        </td>
                        <td data-label="覆盖平台">
                          {profile.platforms
                            .map((p) => PLATFORM_LABEL[p] ?? p)
                            .join("、")}
                        </td>
                        <td data-label="状态">
                          {profile.exists ? (
                            <Badge tone="ok" dot>
                              已保存登录态
                            </Badge>
                          ) : (
                            <Badge tone="muted">空</Badge>
                          )}
                        </td>
                        <td className="small muted mono" data-label="目录">
                          {profile.directory}
                        </td>
                        <td data-label="操作">
                          <button
                            type="button"
                            className="btn btn--ghost btn--sm"
                            disabled={busy || !profile.exists}
                            onClick={() => clearProfile(profile.group)}
                          >
                            清除登录态
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Notice tone="warn" title="关于淘宝与天猫">
                两者在国内是同一套账号体系，因此共用同一个浏览器目录（也就是同一次登录）。
                但商品来源、店铺和结果在任务里仍然分开记录，不会混为一谈。
              </Notice>
            </div>
          </section>

          <section className="panel">
            <div className="panel__head">
              <span style={{ color: "var(--primary)" }}>
                <Icon name="info" size={18} />
              </span>
              <h2 className="section-title" style={{ fontSize: 17 }}>
                各平台的取价方式
              </h2>
            </div>
            <div className="panel__body">
              <div className="table-wrap">
                <table className="table table--dense table--responsive">
                  <thead>
                    <tr>
                      <th>平台</th>
                      <th>首页</th>
                      <th>取价是否需要登录</th>
                      <th>说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(status?.recipes ?? []).map((recipe) => (
                      <tr key={recipe.platform}>
                        <td className="table-cell-main" data-label="平台">
                          <span className={`plat-dot plat-dot--${recipe.platform}`} aria-hidden="true" />
                          {recipe.display_name}
                        </td>
                        <td className="small" data-label="首页">
                          <a
                            className="link-out"
                            href={recipe.home_url}
                            target="_blank"
                            rel="noreferrer noopener"
                          >
                            {recipe.home_url}
                          </a>
                        </td>
                        <td data-label="取价是否需要登录">
                          {recipe.requires_login_for_price ? "需要" : "不强制"}
                        </td>
                        <td className="small muted" data-label="说明">
                          {recipe.notes}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>

          <section className="panel">
            <div className="panel__head">
              <span style={{ color: "var(--primary)" }}>
                <Icon name="clock" size={18} />
              </span>
              <h2 className="section-title" style={{ fontSize: 17 }}>
                当前打开的浏览器会话
              </h2>
            </div>
            <div className="panel__body">
              {(status?.sessions ?? []).length === 0 ? (
                <p className="muted small">现在没有打开的浏览器窗口。任务开始时才会拉起。</p>
              ) : (
                <ul className="small">
                  {(status?.sessions ?? []).map((session) => (
                    <li key={session.group}>
                      {session.group} — {session.busy ? "正在执行任务" : "空闲"}（打开于{" "}
                      {session.opened_at}）
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </div>
      )}

      {tab === "model" && (
        <div className="stack gap-16">
          <section className="panel">
            <div className="panel__head">
              <span style={{ color: "var(--primary)" }}>
                <Icon name="review" size={18} />
              </span>
              <h2 className="section-title" style={{ fontSize: 17 }}>
                模型连接（自带 Key）
                <span className="section-note">
                  {config?.api_key_configured ? "已配置 Key" : "尚未配置 Key"}
                </span>
              </h2>
            </div>
            <div className="panel__body stack gap-12">
              <Notice tone="info" title="模型用来做什么">
                只有在页面结构变化、定位失败或价格文字不清时，才会把裁剪后的必要页面内容发给模型，
                并且会与页面原文交叉核对。看不到 cookie 和登录态。没有配置 Key
                时，比价仍可运行，只是缺少这一层兜底。
              </Notice>
              <Notice tone="warn" title="Key 的存放与风险">
                保存后写入本机文件 {config?.config_path ?? "~/.agentmart/model.json"}，
                仅当前用户可读写。它不会进入前端产物、Git 提交或普通日志；
                需要时可以用下面的「删除本地模型配置」一键清除。
              </Notice>

              <form className="stack gap-16" onSubmit={saveModel}>
                <div className="grid-2">
                  <div className="field">
                    <label className="field__label" htmlFor="m-base">
                      接口地址（OpenAI 兼容）
                    </label>
                    <input
                      id="m-base"
                      className="input"
                      value={form.base_url}
                      placeholder="https://api.example.com/v1"
                      onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                    />
                    <div className="field__hint">只支持 http/https，且不能指向本机或内网地址。</div>
                  </div>
                  <div className="field">
                    <label className="field__label" htmlFor="m-model">
                      模型名称
                    </label>
                    <input
                      id="m-model"
                      className="input"
                      value={form.model}
                      placeholder="例如 gpt-4o-mini / qwen-vl-max"
                      onChange={(e) => setForm({ ...form, model: e.target.value })}
                    />
                  </div>
                </div>

                <div className="field">
                  <label className="field__label" htmlFor="m-key">
                    API Key{config?.api_key_configured ? "（已配置，留空表示不变）" : ""}
                  </label>
                  <input
                    id="m-key"
                    className="input"
                    type="password"
                    autoComplete="off"
                    value={form.api_key}
                    placeholder={config?.api_key_configured ? "••••••••（已保存）" : "sk-…"}
                    onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                  />
                  <div className="field__hint">
                    只从你本人的输入或环境变量读取；界面上任何时候都不回显已保存的 Key。
                  </div>
                </div>

                <div className="grid-2">
                  <div className="field">
                    <label className="field__label" htmlFor="m-calls">
                      单个任务最多调用次数
                    </label>
                    <input
                      id="m-calls"
                      className="input"
                      type="number"
                      min={1}
                      max={500}
                      value={form.max_calls_per_task}
                      onChange={(e) =>
                        setForm({ ...form, max_calls_per_task: Number(e.target.value) })
                      }
                    />
                    <div className="field__hint">用完后任务会停下并展示已取得的证据。</div>
                  </div>
                  <div className="field">
                    <label className="field__label" htmlFor="m-cost">
                      单个任务费用上限（元，0 表示不设）
                    </label>
                    <input
                      id="m-cost"
                      className="input"
                      type="number"
                      min={0}
                      step="0.1"
                      value={form.max_cost_per_task}
                      onChange={(e) =>
                        setForm({ ...form, max_cost_per_task: Number(e.target.value) })
                      }
                    />
                    <div className="field__hint">按估算单价推算，仅作上限参考，不等于最终账单。</div>
                  </div>
                </div>

                <div className="row gap-8 wrap">
                  <button type="submit" className="btn btn--primary" disabled={busy}>
                    保存配置
                  </button>
                  <button
                    type="button"
                    className="btn btn--secondary"
                    disabled={testing}
                    onClick={testModel}
                  >
                    {testing ? "测试中…" : "测试连接与视觉能力"}
                  </button>
                  <button
                    type="button"
                    className="btn btn--ghost"
                    disabled={busy || !config?.api_key_configured}
                    onClick={deleteModel}
                  >
                    删除本地模型配置（含 Key）
                  </button>
                </div>
              </form>

              {testResult && (
                <Notice tone={testResult.ok ? "ok" : "danger"} title={testResult.ok ? "连接成功" : "连接失败"}>
                  <div>{testResult.message}</div>
                  {testResult.vision_message && <div className="small">{testResult.vision_message}</div>}
                  <div className="small muted mt-8">
                    视觉能力：{testResult.vision ? "可用" : "不可用"}。
                    不可用时不会让模型"假装看"网页，只按页面文字字段取数。
                  </div>
                </Notice>
              )}

              {config && (
                <div className="small muted">
                  当前状态：{config.api_key_configured ? "Key 已配置" : "未配置 Key"} · 视觉能力
                  {config.supports_vision ? "已确认可用" : "未确认/不可用"} · 单任务上限{" "}
                  {config.max_calls_per_task} 次调用
                </div>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
