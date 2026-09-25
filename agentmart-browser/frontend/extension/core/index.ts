/** 扩展核心逻辑的出口。
 *
 *  这些模块不碰 DOM、不碰 chrome.*，因此既能在侧面板里跑，也能在 Node 里
 *  直接跑单元测试（node --test extension/tests/），并与 Python 侧的实现做
 *  逐字段比对。
 */

export * from "./enums.ts";
export * from "./money.ts";
export * from "./text.ts";
export * from "./discount.ts";
export * from "./traps.ts";
export * from "./subsidy.ts";
export * from "./pricing.ts";
export * from "./model.ts";
export * from "./offer.ts";
export * from "./serialize.ts";
export * from "./grouping.ts";
export * from "./platforms.ts";
