/** 侧面板 ↔ service worker 之间的消息协议。
 *
 *  侧面板是唯一的编排者：它一次只问一个平台，service worker 负责开标签页、
 *  等加载、跑只读抽取、关标签页。这样 service worker 不需要长期存活，
 *  MV3 把它回收也不会打断用户的操作。
 */

import type { OfferView } from "../src/lib/browserApi.ts";
import type { ExtractedPage } from "./content/extractPage.ts";
import type { Platform } from "./core/enums.ts";

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

export type ExtensionRequest =
  | ReadPageRequest
  | CompareRequest
  | PingRequest;

export type ExtensionResponse = ReadPageResponse | CompareResponse | { ok: true; pong: true };
