/** 侧面板 ↔ service worker 之间的消息协议。
 *
 *  侧面板是唯一的编排者：它一次只问一个平台，service worker 负责开标签页、
 *  等加载、跑只读抽取、关标签页。这样 service worker 不需要长期存活，
 *  MV3 把它回收也不会打断用户的操作。
 *
 *  会话记忆池是另一条线：内容脚本主动上报指纹，service worker 维护池子，
 *  侧面板直接读 chrome.storage.session，不需要来回问。
 */

import type { OfferView } from "../src/lib/browserApi.ts";
import type { ExtractedPage } from "./content/extractPage.ts";
import type { PageFields } from "./core/offer.ts";
import type { Platform } from "./core/enums.ts";
import type { SessionPool } from "./core/session.ts";

export interface ReadPageRequest {
  type: "read-page";
  /** 指定标签页；不传则取当前窗口当前标签页 */
  tabId?: number;
}

export interface ReadPageResponse {
  ok: boolean;
  /** 读不到时不编原因，逐条说明卡在哪 */
  reason?: string;
  url?: string;
  platform?: Platform | null;
  offer?: OfferView;
  problems?: string[];
  fields?: ExtractedPage;
}

export interface CompareRequest {
  type: "compare-platform";
  platform: Platform;
  keyword: string;
  /** 主角商品的型号特征，用来在搜索结果里挑同款 */
  primaryTokens: string[];
  /** 每个平台最多打开几个商品页 */
  maxProducts?: number;
}

export interface CompareResponse {
  ok: boolean;
  platform: Platform;
  /** 认成同款的商品 */
  offers: OfferView[];
  /** 每一步的说明：开了哪些页、为什么跳过 */
  problems: string[];
  reason?: string;
}

export interface PingRequest {
  type: "ping";
}

/** 内容脚本上报的商品页指纹。sender.tab.id 就是它属于哪个标签页 ——
 *  内容脚本拿不到自己的 tabId，只能由 service worker 从 sender 上取。 */
export interface PageFingerprintMessage {
  type: "page-fingerprint";
  /** 这次上报的由头，排查「为什么没报」时看 */
  reason: "load" | "history" | "popstate" | "title";
  /** 这个页面是不是商品详情页。不是的话 service worker 会把该标签页从池子里拿掉。 */
  isProduct: boolean;
  fields: PageFields;
}

/** 侧面板要当前池子。 */
export interface GetSessionRequest {
  type: "get-session";
}

export interface GetSessionResponse {
  ok: boolean;
  pool: SessionPool;
}

/** 池子变了，通知侧面板刷新。 */
export interface SessionChangedMessage {
  type: "session-changed";
  pool: SessionPool;
}

/** 侧面板让用户点一下跳到某个标签页。 */
export interface FocusTabRequest {
  type: "focus-tab";
  tabId: number;
}

export type ExtensionRequest =
  | ReadPageRequest
  | CompareRequest
  | PingRequest
  | GetSessionRequest
  | FocusTabRequest;

export type ExtensionResponse =
  | ReadPageResponse
  | CompareResponse
  | { ok: true; pong: true }
  | GetSessionResponse
  | { ok: boolean };

/** service worker 收到、但不属于「请求-响应」的那一类。 */
export type ExtensionNotification = PageFingerprintMessage | SessionChangedMessage;
