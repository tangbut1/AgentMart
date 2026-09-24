/** 与后端 app/schemas.py 对齐的 TypeScript 类型。 */

export type Platform = "jd" | "taobao" | "tmall" | "pdd" | "douyin";
export type ReviewPlatform = "bilibili" | "douyin" | "user_submitted";

export type ShopType =
  | "self_operated"
  | "official_flagship"
  | "flagship"
  | "authorized"
  | "third_party"
  | "unknown";

export type DataStatus = "real" | "demo" | "stale" | "unverified";

export type DiscountKind =
  | "coupon"
  | "subsidy"
  | "activity"
  | "payment"
  | "trade_in"
  | "free_shipping";

export type ConditionKind = "unconditional" | "conditional" | "unverifiable";

export type PolicyScope =
  | "platform_rule"
  | "shop_promise"
  | "product_page_promise"
  | "pending_verification";

export type ConnectionStatus =
  | "connected"
  | "not_configured"
  | "error"
  | "rate_limited";

export type CurationStatus = "pending" | "verified" | "rejected" | "ai_summary";

export type CommercialRelation =
  | "none_disclosed"
  | "sponsored"
  | "affiliate"
  | "unknown";

export interface PlatformStatus {
  platform: Platform;
  adapter: string;
  status: ConnectionStatus;
  message: string;
  docs_url: string;
  required_env: string[];
}

export interface Discount {
  kind: DiscountKind;
  label: string;
  amount: string;
  condition: string;
  condition_kind: ConditionKind;
  stack_group: string | null;
  region_limit: string | null;
  eligibility: string | null;
  source_url: string | null;
  data_status: DataStatus;
}

export interface PriceLine {
  label: string;
  kind: DiscountKind;
  amount: string;
  condition_kind: ConditionKind;
  condition: string;
  source_url: string | null;
  data_status: DataStatus;
}

export interface PriceBreakdown {
  list_price: string;
  shipping_fee: string;
  lines: PriceLine[];
  definite_total: string;
  potential_total: string;
  unverifiable_total: string;
  applied_groups: string[];
  notes: string[];
}

export interface Policy {
  scope: PolicyScope;
  category: string;
  title: string;
  summary: string;
  source_url: string | null;
  updated_at: string | null;
  region: string | null;
  data_status: DataStatus;
}

export interface Offer {
  id: string;
  platform: Platform;
  platform_product_id: string;
  title: string;
  url: string;
  list_price: string;
  shop_name: string | null;
  shop_type: ShopType;
  shop_url: string | null;
  brand: string | null;
  sku_text: string | null;
  images: string[];
  sales_text: string | null;
  shipping_fee: string;
  region: string | null;
  affiliate: boolean;
  data_status: DataStatus;
  source: string;
  source_url: string | null;
  fetched_at: string | null;
  verified_at: string | null;
  credibility: number;
  match_confidence: number | null;
  match_notes: string[];
  discounts: Discount[];
  policies: Policy[];
  breakdown: PriceBreakdown | null;
}

export interface CanonicalProduct {
  id: string;
  title: string;
  brand: string | null;
  model: string | null;
  category: string | null;
  specs: Record<string, string | null>;
  confidence: number;
  warnings: string[];
  offers: Offer[];
  best_definite_price: string | null;
}

export interface PlatformSearchResult {
  platform: Platform;
  status: ConnectionStatus;
  message: string;
  offer_count: number;
  elapsed_ms: number;
}

export interface SearchResponse {
  keyword: string;
  is_link_query: boolean;
  link_notice: string | null;
  groups: CanonicalProduct[];
  platform_results: PlatformSearchResult[];
  has_real_data: boolean;
  demo_included: boolean;
  demo_notice: string | null;
  generated_at: string;
}

export interface CriteriaCheck {
  dimension: string;
  met: boolean;
  note: string;
}

export interface ReviewAssessment {
  checks: CriteriaCheck[];
  score: number;
  recommend_reference: boolean;
}

export interface Review {
  id: string;
  platform: ReviewPlatform;
  url: string;
  title: string;
  creator_name: string;
  creator_id: string | null;
  creator_url: string | null;
  cover_url: string | null;
  published_at: string | null;
  duration_seconds: number | null;
  view_count: number | null;
  like_count: number | null;
  model_tested: string | null;
  pros: string[];
  cons: string[];
  quotes: string[];
  test_evidence: string[];
  scenarios: string[];
  commercial_relation: CommercialRelation;
  curation_status: CurationStatus;
  curated_by: string | null;
  curated_at: string | null;
  curator_notes: string | null;
  ai_summary: string | null;
  ai_generated_at: string | null;
  data_status: DataStatus;
  fetched_at: string | null;
  related_models: string[];
  relevance_note: string | null;
  assessment: ReviewAssessment | null;
}

export interface RecommendationOption {
  offer_id: string;
  platform: Platform;
  pick_type: string;
  headline: string;
  definite_total: string;
  potential_total: string;
  score: number;
  evidence: string[];
  conditions: string[];
  risks: string[];
}

export interface Recommendation {
  canonical_id: string;
  options: RecommendationOption[];
  summary: string;
  confidence: number;
  missing_data: string[];
  generated_at: string | null;
}

export interface ProductDetailResponse {
  group: CanonicalProduct | null;
  reviews: Review[];
  recommendation: Recommendation | null;
  demo_included: boolean;
}

export interface CompareResponse {
  groups: CanonicalProduct[];
  reviews: Record<string, Review[]>;
  recommendations: Record<string, Recommendation>;
  has_real_data: boolean;
}

export interface DataSourceInfo {
  name: string;
  kind: string;
  status: string;
  description: string;
  last_updated: string | null;
  url: string | null;
}

export interface ReviewResolveResponse {
  ok: boolean;
  review: Review | null;
  error: string | null;
  notice: string | null;
}

// ─── 请求体 ──────────────────────────────────────────────

export interface RecommendationPreferences {
  budget_max?: number | null;
  priority?: "price" | "service" | "balanced";
  scenario?: string | null;
  region?: string | null;
}

export interface ReviewSubmitRequest {
  url: string;
  title?: string | null;
  creator_name?: string | null;
  model_tested?: string | null;
  pros?: string[];
  cons?: string[];
  quotes?: string[];
  test_evidence?: string[];
  scenarios?: string[];
  commercial_relation?: CommercialRelation;
  curator_notes?: string | null;
  related_models?: string[];
  submitter?: string;
}

const BASE = "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
      else if (body && typeof body.message === "string") detail = body.message;
    } catch {
      /* 保留默认错误信息 */
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export const api = {
  search(keyword: string, includeDemo = false, signal?: AbortSignal) {
    const q = new URLSearchParams({ keyword, include_demo: String(includeDemo) });
    return request<SearchResponse>(`/api/search?${q}`, { signal });
  },

  productDetail(
    params: {
      keyword: string;
      groupId: string;
      includeDemo?: boolean;
      prefs?: RecommendationPreferences;
    },
    signal?: AbortSignal,
  ) {
    const q = new URLSearchParams({
      keyword: params.keyword,
      group_id: params.groupId,
      include_demo: String(params.includeDemo ?? false),
    });
    if (params.prefs?.budget_max != null)
      q.set("budget_max", String(params.prefs.budget_max));
    if (params.prefs?.priority) q.set("priority", params.prefs.priority);
    if (params.prefs?.scenario) q.set("scenario", params.prefs.scenario);
    if (params.prefs?.region) q.set("region", params.prefs.region);
    return request<ProductDetailResponse>(`/api/products/detail?${q}`, { signal });
  },

  compare(
    keyword: string,
    groupIds: string[],
    includeDemo = false,
    prefs?: RecommendationPreferences,
  ) {
    return request<CompareResponse>("/api/compare", {
      method: "POST",
      body: JSON.stringify({
        keyword,
        group_ids: groupIds,
        include_demo: includeDemo,
        preferences: prefs ?? null,
      }),
    });
  },

  platforms(signal?: AbortSignal) {
    return request<PlatformStatus[]>("/api/platforms", { signal });
  },

  sources(signal?: AbortSignal) {
    return request<DataSourceInfo[]>("/api/sources", { signal });
  },

  reviews(params: { status?: string; includeDemo?: boolean } = {}, signal?: AbortSignal) {
    const q = new URLSearchParams();
    if (params.status) q.set("status", params.status);
    if (params.includeDemo) q.set("include_demo", "true");
    return request<Review[]>(`/api/reviews?${q}`, { signal });
  },

  resolveReview(url: string) {
    return request<ReviewResolveResponse>("/api/reviews/resolve", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
  },

  submitReview(body: ReviewSubmitRequest) {
    return request<Review>("/api/reviews", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
};
