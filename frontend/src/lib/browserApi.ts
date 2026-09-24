/** 个人浏览器版（/api/browser）的类型与请求封装。 */

export type BrowserPlatform = "jd" | "taobao" | "tmall" | "pdd" | "douyin";

export type TaskStatusCode =
  | "pending"
  | "running"
  | "waiting_user"
  | "waiting_confirm"
  | "completed"
  | "restricted"
  | "failed"
  | "cancelled";

export type BlockedReasonCode =
  | "captcha"
  | "risk_control"
  | "login_required"
  | "login_expired"
  | "rate_limited"
  | "navigation_failed"
  | "structure_unknown";

export type OriginCode =
  | "real_platform_page"
  | "user_provided"
  | "test_fixture"
  | "demo";

export type ActionKindCode =
  | "navigate"
  | "read"
  | "scroll"
  | "screenshot"
  | "wait_user"
  | "ask_confirm";

export interface Requirement {
  text: string;
  keyword: string;
  category: string | null;
  budget_min: number | null;
  budget_max: number | null;
  budget_approximate: boolean;
  brands: string[];
  region: string | null;
  scenarios: string[];
  include_reviews: boolean;
  unclear: string[];
}

export interface StepLog {
  seq: number;
  action: ActionKindCode;
  detail: string;
  at: string;
  url: string | null;
}

export interface PlatformState {
  platform: BrowserPlatform;
  display_name: string;
  status: TaskStatusCode;
  status_label: string;
  blocked_reason: BlockedReasonCode | null;
  blocked_reason_label: string | null;
  blocked_detail: string | null;
  origin: OriginCode;
  origin_label: string;
  steps: StepLog[];
  offer_count: number;
  problems: string[];
  model_calls: number;
  pages_visited: number;
  started_at: string | null;
  finished_at: string | null;
  profile_group: string;
  paused: boolean;
  urls: string[];
  recipe: {
    home_url: string;
    requires_login_for_price: boolean;
    notes: string;
  };
}

export interface ModelUsage {
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  vision_calls: number;
  estimated_cost: number;
  errors: string[];
}

export interface PendingQuestion {
  key: string;
  question: string;
  default?: string;
  asked_at?: string;
}

export interface TaskOptions {
  platforms: BrowserPlatform[];
  max_candidates: number;
  max_links: number;
  step_timeout_seconds: number;
  login_wait_seconds: number;
  max_task_seconds: number;
  max_model_calls: number;
  headless: boolean;
  slow_mo_ms: number;
  origin: OriginCode;
  origin_label: string;
  url_overrides: Record<string, string>;
  ask_review_question: boolean;
}

export interface TaskView {
  id: string;
  status: TaskStatusCode;
  status_label: string;
  summary_status: TaskStatusCode;
  summary_status_label: string;
  origin: OriginCode;
  origin_label: string;
  created_at: string;
  updated_at: string;
  requirement: Requirement;
  options: TaskOptions;
  platforms: PlatformState[];
  waiting_reason: string | null;
  pending_question: PendingQuestion | null;
  budget_exhausted: boolean;
  model_usage: ModelUsage;
  notes: string[];
  offer_count: number;
  group_count: number;
  /** 服务重启后从数据库重建的历史任务（编排器已不持有它） */
  restored?: boolean;
}

export interface DiscountView {
  kind: string;
  label: string;
  amount: string;
  percent: string | null;
  condition: string;
  condition_kind: "unconditional" | "conditional" | "unverifiable";
  condition_kind_label: string;
  region_limit: string | null;
  eligibility: string | null;
  source_url: string | null;
  verified_at: string | null;
  data_status: string;
  note: string | null;
}

export interface PriceLineView {
  label: string;
  kind: string;
  amount: string;
  condition_kind: string;
  condition_kind_label: string;
  condition: string;
  source_url: string | null;
  data_status: string;
  data_status_label: string;
}

export interface BreakdownView {
  list_price: string;
  shipping_fee: string;
  definite_total: string;
  potential_total: string;
  unverifiable_total: string;
  definite_discount: string;
  potential_discount: string;
  lines: PriceLineView[];
  applied_groups: string[];
  notes: string[];
}

export interface PolicyView {
  scope: string;
  scope_label: string;
  category: string;
  category_label: string;
  title: string;
  summary: string;
  data_status: string;
}

export interface OfferView {
  id: string;
  platform: BrowserPlatform;
  platform_label: string;
  title: string;
  url: string;
  source_url: string;
  shop_name: string | null;
  shop_type: string;
  shop_type_label: string;
  sku_text: string | null;
  sales_text: string | null;
  list_price: string;
  shipping_fee: string;
  discounts: DiscountView[];
  policies: PolicyView[];
  breakdown: BreakdownView;
  data_status: string;
  data_status_label: string;
  source: string;
  fetched_at: string | null;
  verified_at: string | null;
  credibility: number;
  affiliate: boolean;
  certainty: { level: string; label: string; note: string };
  is_demo: boolean;
  match_confidence: number | null;
  match_notes: string[];
}

export interface GroupView {
  id: string;
  title: string;
  brand: string | null;
  specs: Record<string, string | null>;
  confidence: number;
  warnings: string[];
  best_definite_price: string | null;
  offers: OfferView[];
}

export interface RecommendationOption {
  offer_id: string;
  platform: BrowserPlatform;
  platform_label: string;
  pick_type: string;
  headline: string;
  definite_total: string;
  potential_total: string;
  score: number;
  evidence: string[];
  conditions: string[];
  risks: string[];
}

export interface RecommendationView {
  canonical_id: string;
  summary: string;
  confidence: number;
  missing_data: string[];
  generated_at: string | null;
  options: RecommendationOption[];
}

export interface ResultView {
  task_id: string;
  origin: OriginCode;
  origin_label: string;
  groups: GroupView[];
  recommendation: RecommendationView | null;
  notes: string[];
  budget_exhausted: boolean;
  model_usage: ModelUsage;
}

export interface ModeInfo {
  mode: string;
  version: string;
  name: string;
  tagline: string;
  boundaries: string[];
  data_note: string;
}

export type LoginStateCode =
  | "logged_in"
  | "waiting_login"
  | "saved_unverified"
  | "failed"
  | "none";

export interface LoginWindowView {
  group: string;
  platforms: BrowserPlatform[];
  status: string;
  status_label: string;
  message: string;
  opened_at: string | null;
  last_checked_at: string | null;
}

export interface RecipeView {
  platform: BrowserPlatform;
  display_name: string;
  home_url: string;
  requires_login_for_price: boolean;
  notes: string;
  profile_group: string;
  profile_platforms: BrowserPlatform[];
  profile_exists: boolean;
  /** 诚实登录态：目录存在不等于已登录 */
  login_state: LoginStateCode;
  login_state_label: string;
  login_window: LoginWindowView;
}

export interface ProfileView {
  group: string;
  directory: string;
  platforms: BrowserPlatform[];
  exists: boolean;
}

export interface SessionView {
  group: string;
  busy: boolean;
  opened_at: string;
}

export interface PlatformStatusView {
  recipes: RecipeView[];
  profiles: ProfileView[];
  storage: { root: string; note: string; inside_repo: boolean };
  sessions: SessionView[];
  login_windows: LoginWindowView[];
}

export interface ModelConfigView {
  provider: string;
  base_url: string;
  model: string;
  api_key_configured: boolean;
  config_path: string;
  supports_vision: boolean;
  vision_verified_at: number | null;
  max_calls_per_task: number;
  max_cost_per_task: number;
  est_input_price_per_1k: number;
  est_output_price_per_1k: number;
  timeout_seconds: number;
  note: string;
}

export interface ModelTestView {
  ok: boolean;
  message: string;
  vision: boolean;
  vision_message?: string;
  usage?: ModelUsage;
}

export interface TaskSummary {
  id: string;
  status: TaskStatusCode;
  origin: OriginCode;
  requirement_text: string;
  offer_count: number;
  group_count: number;
  model_usage: ModelUsage;
  notes: string[];
  created_at: string | null;
  updated_at: string | null;
}

export interface TaskRecord extends TaskSummary {
  result: ResultView | null;
  options: TaskOptions | null;
  platforms: PlatformState[];
}

// ─── 请求 ──────────────────────────────────────────────

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      /* 保留默认错误信息 */
    }
    throw new BrowserApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export class BrowserApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "BrowserApiError";
    this.status = status;
  }
}

const BASE = "/api/browser";

export const browserApi = {
  mode(signal?: AbortSignal) {
    return request<ModeInfo>(`${BASE}/mode`, { signal });
  },

  platformStatus(signal?: AbortSignal) {
    return request<PlatformStatusView>(`${BASE}/platforms`, { signal });
  },

  openLogin(group: string) {
    return request<{
      group: string;
      status: string;
      status_label: string;
      message: string;
      platforms: BrowserPlatform[];
      boundaries: string[];
    }>(`${BASE}/platforms/${encodeURIComponent(group)}/login`, {
      method: "POST",
    });
  },

  closeLogin(group: string) {
    return request<{ group: string; closed: boolean; message: string }>(
      `${BASE}/platforms/${encodeURIComponent(group)}/login/close`,
      { method: "POST" },
    );
  },

  clearProfile(group: string) {
    return request<{ group: string; cleared: boolean; message: string }>(
      `${BASE}/platforms/${encodeURIComponent(group)}/clear`,
      { method: "POST" },
    );
  },

  modelConfig(signal?: AbortSignal) {
    return request<ModelConfigView>(`${BASE}/model`, { signal });
  },

  saveModelConfig(payload: Record<string, unknown>) {
    return request<ModelConfigView>(`${BASE}/model`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  deleteModelConfig() {
    return request<{ removed: boolean; message: string }>(`${BASE}/model`, {
      method: "DELETE",
    });
  },

  testModel() {
    return request<ModelTestView>(`${BASE}/model/test`, { method: "POST" });
  },

  modelUsage() {
    return request<ModelUsage>(`${BASE}/model/usage`);
  },

  parse(text: string) {
    return request<Requirement & { needs_followup: boolean }>(`${BASE}/parse`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
  },

  createTask(payload: {
    text: string;
    platforms?: BrowserPlatform[];
    options?: Record<string, unknown>;
  }) {
    return request<TaskView>(`${BASE}/tasks`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  listTasks(limit = 20) {
    return request<TaskSummary[]>(`${BASE}/tasks?limit=${limit}`);
  },

  task(taskId: string, signal?: AbortSignal) {
    return request<TaskView>(`${BASE}/tasks/${encodeURIComponent(taskId)}`, { signal });
  },

  taskResult(taskId: string, signal?: AbortSignal) {
    return request<ResultView>(
      `${BASE}/tasks/${encodeURIComponent(taskId)}/result`,
      { signal },
    );
  },

  taskRecord(taskId: string) {
    return request<TaskRecord>(`${BASE}/tasks/${encodeURIComponent(taskId)}/record`);
  },

  startTask(taskId: string) {
    return request<TaskView>(`${BASE}/tasks/${encodeURIComponent(taskId)}/start`, {
      method: "POST",
    });
  },

  answer(taskId: string, key: string, value: string) {
    return request<TaskView>(`${BASE}/tasks/${encodeURIComponent(taskId)}/answer`, {
      method: "POST",
      body: JSON.stringify({ key, value }),
    });
  },

  setReviews(taskId: string, value: boolean) {
    return request<TaskView>(`${BASE}/tasks/${encodeURIComponent(taskId)}/reviews`, {
      method: "POST",
      body: JSON.stringify({ value }),
    });
  },

  cancelTask(taskId: string) {
    return request<TaskView>(`${BASE}/tasks/${encodeURIComponent(taskId)}/cancel`, {
      method: "POST",
    });
  },

  cancelPlatform(taskId: string, platform: BrowserPlatform) {
    return request<TaskView>(
      `${BASE}/tasks/${encodeURIComponent(taskId)}/platforms/${platform}/cancel`,
      { method: "POST" },
    );
  },

  pausePlatform(taskId: string, platform: BrowserPlatform) {
    return request<TaskView>(
      `${BASE}/tasks/${encodeURIComponent(taskId)}/platforms/${platform}/pause`,
      { method: "POST" },
    );
  },

  resumePlatform(taskId: string, platform: BrowserPlatform) {
    return request<TaskView>(
      `${BASE}/tasks/${encodeURIComponent(taskId)}/platforms/${platform}/resume`,
      { method: "POST" },
    );
  },

  deleteTask(taskId: string) {
    return request<{ removed: boolean; id: string }>(
      `${BASE}/tasks/${encodeURIComponent(taskId)}`,
      { method: "DELETE" },
    );
  },
};
