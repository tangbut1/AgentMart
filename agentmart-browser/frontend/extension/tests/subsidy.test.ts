/** 国补：两种情形都算出来、都标清楚，绝不合并成一个数。 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { interpretSubsidyText, subsidyFitLabel, subsidyScenarios } from "../core/subsidy.ts";

describe("interpretSubsidyText", () => {
  it("没有补贴关键词就返回 null（不猜）", () => {
    assert.equal(interpretSubsidyText("满1000减100 已领取"), null);
    assert.equal(interpretSubsidyText(""), null);
  });

  it("百分比与地区限制分别取出", () => {
    const reading = interpretSubsidyText("国补15% 限江苏省用户", "江苏省");
    assert.ok(reading);
    assert.equal(reading.percent?.text, "15");
    // 「限」后面用前瞻收边界，拿到的是核心地名「江苏」而不是「江苏省」
    assert.equal(reading.region_limit, "江苏");
    assert.equal(reading.fit, "region_matches");
  });

  it("金额原文保留，不做两位小数补齐", () => {
    const reading = interpretSubsidyText("国家补贴 减500元");
    assert.ok(reading);
    assert.equal(reading.amount, 50000);
    assert.equal(reading.amount_text, "500");
  });

  it("「江苏省」和「江苏」能对上，「江苏」和「南京」对不上", () => {
    assert.equal(interpretSubsidyText("国补15% 限江苏省", "江苏省")?.fit, "region_matches");
    assert.equal(interpretSubsidyText("国补15% 限江苏", "江苏省")?.fit, "region_matches");
    assert.equal(interpretSubsidyText("国补15% 限江苏省", "南京市")?.fit, "region_conflicts");
  });

  it("没填收货地时不判定，改成提问", () => {
    const reading = interpretSubsidyText("国补15% 限江苏省用户", null);
    assert.ok(reading);
    assert.equal(reading.fit, "unknown");
    assert.ok(reading.reason.includes("还没有填写收货地"));
    assert.ok(reading.questions.some((q) => q.includes("江苏")));
  });

  it("页面没写地区限制时也要问资格", () => {
    const reading = interpretSubsidyText("国补15%", "江苏省");
    assert.ok(reading);
    assert.equal(reading.region_limit, null);
    assert.equal(reading.fit, "unknown");
    assert.ok(reading.questions.length > 0);
  });

  it("地区不一致时给出说明", () => {
    const reading = interpretSubsidyText("国补15% 限江苏省", "浙江省");
    assert.ok(reading);
    assert.equal(reading.fit, "region_conflicts");
    assert.ok(reading.reason.includes("浙江省"));
  });

  it("标签", () => {
    assert.equal(subsidyFitLabel("region_matches"), "地区与您填写的一致");
    assert.equal(subsidyFitLabel("region_conflicts"), "地区与您填写的不一致");
    assert.equal(subsidyFitLabel("unknown"), "页面未写地区限制");
  });
});

describe("subsidyScenarios", () => {
  it("没有可量化补贴时返回 null，不硬凑一个数", () => {
    assert.equal(subsidyScenarios(100000, null), null);
    assert.equal(subsidyScenarios(100000, interpretSubsidyText("百亿补贴 限时抢购")), null);
  });

  it("按比例算：两个价都摆出来，补贴不进确定价", () => {
    const reading = interpretSubsidyText("国补15%", "江苏省");
    const scenarios = subsidyScenarios(499900, reading);
    assert.ok(scenarios);
    // 4999.00 × 15% = 749.85 → 4999.00 - 749.85 = 4249.15
    assert.equal(scenarios.with_subsidy, 424915);
    assert.equal(scenarios.without_subsidy, 499900);
    assert.ok(scenarios.note.includes("4999.00"));
    assert.ok(scenarios.note.includes("749.85"));
    assert.ok(scenarios.note.includes("不代您认定"));
  });

  it("按比例算时用银行家舍入（与后端 Decimal.quantize 一致）", () => {
    // 2.30 × 15% = 0.345 → 0.34（不是 0.35）
    const reading = interpretSubsidyText("国补15%");
    const scenarios = subsidyScenarios(230, reading);
    assert.ok(scenarios);
    assert.equal(scenarios.with_subsidy, 196);
    assert.ok(scenarios.note.includes("0.34"));
  });

  it("直接写金额时按金额算，展示用页面原文", () => {
    const reading = interpretSubsidyText("国家补贴 减500元");
    const scenarios = subsidyScenarios(499900, reading);
    assert.ok(scenarios);
    assert.equal(scenarios.with_subsidy, 449900);
    assert.ok(scenarios.note.includes("预计再减 500 元"));
    // 不做成 "500.00"
    assert.ok(!scenarios.note.includes("500.00"));
  });

  it("补贴超过确定价时右侧截到 0，不留负数", () => {
    const reading = interpretSubsidyText("国家补贴 减5000元");
    const scenarios = subsidyScenarios(499900, reading);
    assert.ok(scenarios);
    assert.equal(scenarios.with_subsidy, 0);
  });

  it("地区对不上时在说明里追加提醒", () => {
    const reading = interpretSubsidyText("国补15% 限江苏省", "浙江省");
    const scenarios = subsidyScenarios(499900, reading);
    assert.ok(scenarios);
    assert.ok(scenarios.note.includes("地区与您填写的收货地不一致"));
  });

  it("地区一致时不追加那句提醒", () => {
    const reading = interpretSubsidyText("国补15% 限江苏省", "江苏省");
    const scenarios = subsidyScenarios(499900, reading);
    assert.ok(scenarios);
    assert.ok(!scenarios.note.includes("不一致"));
  });
});
