/** 一致性校验的 TypeScript 侧执行器。
 *
 *  读语料 JSON，跑一遍「build_offer → compute_price_breakdown → offerView」，
 *  把结果写成 JSON。Python 侧的 tests/test_extension_parity.py 对同一个
 *  语料跑同一套流程，然后逐字段比对两边输出。
 *
 *  用法：node extension/tests/parity-emit.ts <语料.json> <输出.json>
 *
 *  这个脚本本身不做断言 —— 断言放在 Python 测试里，那里能同时看到两边的
 *  结果，报错时也说得清是哪个字段、哪一条语料对不上。
 */

import { readFileSync, writeFileSync } from "node:fs";

import { buildOffer } from "../core/offer.ts";
import { computePriceBreakdown } from "../core/pricing.ts";
import { offerView } from "../core/serialize.ts";

interface CorpusCase {
  name: string;
  platform: Parameters<typeof buildOffer>[0];
  user_region: string | null;
  source_label?: string;
  fields: Parameters<typeof buildOffer>[1];
}

function main(): void {
  const [, , corpusPath, outPath] = process.argv;
  if (!corpusPath || !outPath) {
    process.stderr.write("usage: node parity-emit.ts <corpus.json> <out.json>\n");
    process.exit(2);
  }
  const corpus = JSON.parse(readFileSync(corpusPath, "utf8")) as { cases: CorpusCase[] };
  const output: Record<string, unknown> = {};

  for (const item of corpus.cases) {
    const { offer, problems } = buildOffer(item.platform, item.fields, {
      sourceLabel: item.source_label ?? "side-panel",
    });
    const breakdown = computePriceBreakdown({
      list_price: offer.list_price,
      shipping_fee: offer.shipping_fee,
      discounts: offer.discounts,
      data_status: offer.data_status,
    });
    output[item.name] = {
      view: offerView(offer, breakdown, {
        userRegion: item.user_region ?? null,
      }),
      problems,
    };
  }

  writeFileSync(outPath, `${JSON.stringify(output, null, 2)}\n`, "utf8");
  process.stdout.write(`emitted ${Object.keys(output).length} cases\n`);
}

main();
