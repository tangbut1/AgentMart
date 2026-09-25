/** 金额解析与舍入。
 *
 *  重点不是"能解析"，而是**和后端 Python 的 Decimal 语义一致**：
 *  银行家舍入（half-even）、两位小数展示、以及 parseMoney 与
 *  decimalToCents 的有意分歧（见下）。
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  decimalStr,
  decimalToCents,
  divRoundHalfEven,
  formatMoney,
  moneyOrEmpty,
  parseMoney,
  rational,
} from "../core/money.ts";

describe("parseMoney", () => {
  it("带货币符号优先", () => {
    assert.equal(parseMoney("¥3299.00"), 329900);
    assert.equal(parseMoney("￥12.5"), 1250);
    assert.equal(parseMoney("价格 ¥99.9 元"), 9990);
  });

  it("没有货币符号时取第一个数值", () => {
    assert.equal(parseMoney("2899.00"), 289900);
  });

  it("去掉半角与全角千分位", () => {
    assert.equal(parseMoney("1,234.56"), 123456);
    assert.equal(parseMoney("1，234.56"), 123456);
  });

  it("解析不了就返回 null，不猜", () => {
    assert.equal(parseMoney(null), null);
    assert.equal(parseMoney(undefined), null);
    assert.equal(parseMoney(""), null);
    assert.equal(parseMoney("   "), null);
    assert.equal(parseMoney("价格面议"), null);
  });

  it("零不算价格（页面没价格时不能拿 0 冒充）", () => {
    assert.equal(parseMoney("0"), null);
    assert.equal(parseMoney("0.00"), null);
  });

  it("负号不在数值匹配里，和 Python 的正则行为一致", () => {
    // 两侧的正则都只吃 [0-9.]+，"-5" 会解析成 5.00。
    // 真实页面上不会出现负的标价，这里只锁住行为不漂移。
    assert.equal(parseMoney("-5"), 500);
  });

  it("超过上限的天价不采信", () => {
    assert.equal(parseMoney("100000001"), null);
    assert.equal(parseMoney("100000000"), 10000000000);
  });

  it("小数超过两位时按分截断，不四舍五入到第三位", () => {
    // Python 的正则也只吃两位小数
    assert.equal(parseMoney("1.239"), 123);
  });
});

describe("decimalToCents", () => {
  it("与 parseMoney 的区别是故意的：不过滤正负", () => {
    // 后端 interpret_coupon_text 用裸 Decimal()，"满100减0" 得到 0 而不是
    // None，分支走向不一样。这里必须能表示 0。
    assert.equal(decimalToCents("0"), 0);
    assert.equal(decimalToCents("100"), 10000);
    assert.equal(decimalToCents("99.5"), 9950);
  });
});

describe("formatMoney", () => {
  it("按分转两位小数的元", () => {
    assert.equal(formatMoney(0), "0.00");
    assert.equal(formatMoney(5), "0.05");
    assert.equal(formatMoney(329900), "3299.00");
    assert.equal(formatMoney(123456789), "1234567.89");
  });

  it("负数保留符号", () => {
    assert.equal(formatMoney(-50), "-0.50");
    assert.equal(formatMoney(-10100), "-101.00");
  });

  it("不加千分位（和后端 str(Decimal) 一致）", () => {
    assert.equal(formatMoney(123456700), "1234567.00");
  });

  it("moneyOrEmpty：None → 空串", () => {
    assert.equal(moneyOrEmpty(null), "");
    assert.equal(moneyOrEmpty(undefined), "");
    assert.equal(moneyOrEmpty(1999), "19.99");
  });
});

describe("divRoundHalfEven", () => {
  it("正好一半时取偶数侧 —— 这是和 Python Decimal.quantize 对齐的关键", () => {
    // 42.5 → 42（偶数），不是 43
    assert.equal(divRoundHalfEven(42500, 1000), 42);
    // 43.5 → 44（偶数）
    assert.equal(divRoundHalfEven(43500, 1000), 44);
    // 3450/100 = 34.5 → 34
    assert.equal(divRoundHalfEven(3450, 100), 34);
    // 3550/100 = 35.5 → 36
    assert.equal(divRoundHalfEven(3550, 100), 36);
  });

  it("不是一半时正常靠近", () => {
    assert.equal(divRoundHalfEven(42501, 1000), 43);
    assert.equal(divRoundHalfEven(42499, 1000), 42);
  });

  it("整除时原样返回", () => {
    assert.equal(divRoundHalfEven(42000, 1000), 42);
    assert.equal(divRoundHalfEven(0, 1000), 0);
  });

  it("分母必须为正", () => {
    assert.throws(() => divRoundHalfEven(1, 0));
    assert.throws(() => divRoundHalfEven(1, -1));
  });
});

describe("rational / decimalStr", () => {
  it("百分比按精确有理数保存，不经过浮点", () => {
    const r = rational("8.5");
    assert.equal(r.num, 85);
    assert.equal(r.den, 10);
    assert.equal(r.text, "8.5");
  });

  it("展示文本等于 Python str(Decimal(x))", () => {
    assert.equal(decimalStr("8.5"), "8.5");
    assert.equal(decimalStr("8.50"), "8.50");
    assert.equal(decimalStr("15"), "15");
    assert.equal(decimalStr("0"), "0");
    assert.equal(decimalStr("007"), "7");
    assert.equal(decimalStr("0.50"), "0.50");
  });

  it("整数百分比 den 为 1", () => {
    assert.equal(rational("15").den, 1);
    assert.equal(rational("15").num, 15);
  });
});
