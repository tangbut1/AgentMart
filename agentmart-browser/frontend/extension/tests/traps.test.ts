/** 防套路：识别顺序、去重与「未显示」措辞。
 *
 *  规矩：没有页面证据就不说有坑；证据是否定式的按限制报；页面没提的按
 *  「未显示」报并配一个待确认问题。宁可少报一个坑，不能把保护讲成坑。
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { detectTraps, summarizeTraps, trapBasisLabel, trapSeverityLabel, worstSeverity } from "../core/traps.ts";

function kinds(traps: ReturnType<typeof detectTraps>): string[] {
  return traps.map((t) => t.kind);
}

describe("detectTraps 顺序与去重", () => {
  it("激活后退是 blocker 且排最前", () => {
    const traps = detectTraps({
      policy_texts: ["激活后不支持7天无理由退货", "运费险"],
    });
    assert.equal(traps[0].kind, "activation_locked");
    assert.equal(traps[0].severity, "blocker");
    assert.equal(traps[0].basis, "page_text");
    assert.ok(traps[0].evidence.includes("激活"));
  });

  it("非国行只看政策栏/规格/标题三处", () => {
    const fromTitle = detectTraps({ policy_texts: ["7天无理由退货", "运费险"], title: "iPhone 16 港版" });
    assert.ok(kinds(fromTitle).includes("non_mainland"));
    const fromSku = detectTraps({ policy_texts: [], sku_text: "版本：港版" });
    assert.ok(kinds(fromSku).includes("non_mainland"));
    // 优惠文案不在三处之内，不报
    assert.ok(!kinds(detectTraps({ policy_texts: [], coupon_texts: ["港版可用"] })).includes("non_mainland"));
  });

  it("标题里同时有国行和非国行说法时照样报，不替用户判定", () => {
    const traps = detectTraps({ policy_texts: [], title: "国行正品 港版同款 便宜300" });
    assert.ok(kinds(traps).includes("non_mainland"));
  });

  it("「特价商品不退不换」只报 special_no_return，不重复报 no_return_window", () => {
    const traps = detectTraps({ policy_texts: ["特价商品不退不换", "运费险"] });
    assert.equal(kinds(traps).filter((k) => k === "no_return_window").length, 0);
    const special = traps.find((t) => t.kind === "special_no_return");
    assert.ok(special);
    assert.equal(special.severity, "major");
  });

  it("页面已写「不退不换」时不再问「支持7天无理由吗」", () => {
    const traps = detectTraps({ policy_texts: ["特价商品不退不换", "运费险"] });
    assert.ok(!traps.some((t) => t.question.includes("7 天无理由退货吗")));
    assert.ok(!traps.some((t) => t.label.includes("未显示7天无理由")));
  });

  it("两句不同的否定证据会分别报（去重只针对同一句原文）", () => {
    const traps = detectTraps({
      policy_texts: ["本商品不支持7天无理由退货", "清仓尾货不予退换", "运费险"],
    });
    assert.ok(kinds(traps).includes("no_return_window"));
    assert.ok(kinds(traps).includes("special_no_return"));
  });

  it("政策栏完全没有「7天无理由」时报「未显示」并配待确认问题", () => {
    const traps = detectTraps({ policy_texts: ["全国联保", "可开发票"] });
    const noReturn = traps.find((t) => t.kind === "no_return_window");
    assert.ok(noReturn);
    assert.equal(noReturn.basis, "not_shown");
    assert.equal(noReturn.severity, "minor");
    assert.equal(noReturn.evidence, "");
    assert.ok(noReturn.question.length > 0);
    // 「未显示」绝不能被写成「不支持」
    assert.ok(!noReturn.label.includes("不支持"));
  });

  it("有正面的 7 天无理由时不再报「未显示」", () => {
    const traps = detectTraps({ policy_texts: ["7天无理由退货"] });
    assert.ok(!kinds(traps).includes("no_return_window"));
  });

  it("没有运费险时报「未显示」，有就不再报", () => {
    assert.ok(kinds(detectTraps({ policy_texts: ["7天无理由退货"] })).includes("no_freight_insurance"));
    assert.ok(
      !kinds(detectTraps({ policy_texts: ["7天无理由退货", "退货运费险"] })).includes(
        "no_freight_insurance",
      ),
    );
  });

  it("补贴只看优惠文案，报「资格未核实」", () => {
    const traps = detectTraps({ policy_texts: ["7天无理由退货"], coupon_texts: ["国补15% 限江苏省"] });
    const subsidy = traps.find((t) => t.kind === "subsidy_unverified");
    assert.ok(subsidy);
    assert.equal(subsidy.severity, "major");
    assert.ok(subsidy.question.includes("资格"));
  });

  it("空输入也给出「未显示」类提示，不返回空数组假装没问题", () => {
    const traps = detectTraps({ policy_texts: [] });
    assert.ok(kinds(traps).includes("no_return_window"));
    assert.ok(kinds(traps).includes("no_freight_insurance"));
  });

  it("空文案会被过滤，不当成证据", () => {
    const traps = detectTraps({ policy_texts: ["", "   ", null as unknown as string] });
    assert.ok(traps.every((t) => t.basis === "not_shown"));
  });
});

describe("严重程度与摘要", () => {
  it("worstSeverity 取最严重的一个", () => {
    const traps = detectTraps({
      policy_texts: ["激活后不支持7天无理由退货", "运费险"],
    });
    assert.equal(worstSeverity(traps), "blocker");
  });

  it("没有坑时返回 null", () => {
    assert.equal(worstSeverity([]), null);
  });

  it("摘要先列 blocker 再列 major，最后统计待确认项", () => {
    const traps = detectTraps({
      policy_texts: ["激活后不支持7天无理由退货", "特价商品不退不换"],
      coupon_texts: ["国补15%"],
    });
    const summary = summarizeTraps(traps);
    assert.ok(summary.startsWith("激活后不支持退换"));
    assert.ok(summary.includes("特价/清仓商品不退不换"));
    // 没有运费险 → 一条 minor → 计入"待确认"
    assert.ok(summary.includes("另有 1 项待确认"));
  });

  it("一个坑都没有时的措辞", () => {
    assert.equal(summarizeTraps([]), "页面未发现明显的退换或版本限制");
  });

  it("标签与证据出处都有中文说明", () => {
    assert.equal(trapSeverityLabel("blocker"), "买前必须先确认");
    assert.equal(trapSeverityLabel("major"), "明显影响决策");
    assert.equal(trapSeverityLabel("minor"), "值得知道");
    assert.equal(trapBasisLabel("page_text"), "页面原文");
    assert.equal(trapBasisLabel("not_shown"), "页面未显示");
  });
});
