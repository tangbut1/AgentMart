/** 把会话池里的条目变成侧边栏能直接渲染的 OfferView。
 *
 *  单独放一个模块、不并进 core/session.ts：后者要被常驻内容脚本引用，
 *  而这里这一串会连带把 subsidy / traps / pricing 全拖进内容脚本的产物里。
 *  内容脚本只需要 looksLikeProductPage。
 */

import type { GroupView, OfferView } from "../../src/lib/browserApi.ts";
import { buildCompareGroups } from "./grouping.ts";
import { buildOffer } from "./offer.ts";
import { computePriceBreakdown } from "./pricing.ts";
import { offerView } from "./serialize.ts";
import type { SessionEntry, SessionPool } from "./session.ts";

export function entryToOfferView(entry: SessionEntry, userRegion: string): OfferView | null {
  if (!entry.fields) return null;
  const built = buildOffer(entry.platform, entry.fields, {
    sourceLabel: "session-pool",
    fetchedAt: new Date(entry.lastActiveAt).toISOString(),
  });
  const breakdown = computePriceBreakdown({
    list_price: built.offer.list_price,
    shipping_fee: built.offer.shipping_fee,
    discounts: built.offer.discounts,
    data_status: built.offer.data_status,
  });
  return offerView(built.offer, breakdown, { userRegion: userRegion.trim() || null });
}

/** 挑出用来当对比基准的那一组，和组内除基准外的条目。
 *
 *  优先级：
 *  1. 用户手动「读取」过的页面还在池子里 → 用它当基准，尊重用户自己的选择；
 *  2. 当前活动标签页所在的组；
 *  3. 条目最多的那组（活动标签页不在池子里时，比如刚打开侧边栏）。
 *
 *  认不出同款的页面各自成组，所以「挑一组」这一步不会把不同的商品混起来。 */
function pickGroup(
  pool: SessionPool,
  primary: OfferView | null,
): { anchor: SessionEntry; others: SessionEntry[] } | null {
  if (pool.clusters.length === 0) return null;

  if (primary) {
    const group = pool.clusters.find((item) =>
      Object.values(item.tabs).some(
        (entry) => entry.url === primary.url && entry.platform === primary.platform,
      ),
    );
    if (group) {
      // 用户自己读过的那个页面当基准，剩下的按最近活跃排。
      // 不能用 byRecent[0]：那会把用户刚打开侧边栏前最后激活的那个标签页
      // 顶成基准，用户手动读的那一页反而被挤到「其他」里去。
      const entries = byRecent(group);
      const anchorIndex = entries.findIndex(
        (entry) => entry.url === primary.url && entry.platform === primary.platform,
      );
      if (anchorIndex >= 0) {
        const anchor = entries[anchorIndex];
        return { anchor, others: entries.filter((_, index) => index !== anchorIndex) };
      }
      return { anchor: entries[0], others: entries.slice(1) };
    }
  }

  const active = pool.clusters.find((item) => item.tabs[pool.activeTabId ?? -1] !== undefined);
  const group =
    active ??
    [...pool.clusters].sort((a, b) => Object.keys(b.tabs).length - Object.keys(a.tabs).length)[0];
  const entries = byRecent(group);
  return { anchor: entries[0], others: entries.slice(1) };
}

function byRecent(cluster: { tabs: Record<number, SessionEntry> }): SessionEntry[] {
  return Object.values(cluster.tabs).sort((a, b) => b.lastActiveAt - a.lastActiveAt);
}

/** 阶段一的核心承诺：用户一次都不点，侧边栏打开就并排摆好同款。
 *
 *  返回空数组的情形只有两种：池子是空的，或者那一组里除基准外没有别的
 *  可比较条目。绝不会返回一个把不同商品混在一起的组。 */
export function autoCompareFromPool(
  pool: SessionPool,
  primary: OfferView | null,
  userRegion: string,
): GroupView[] {
  const picked = pickGroup(pool, primary);
  if (!picked) return [];

  const primaryOffer =
    primary && picked.anchor.url === primary.url && picked.anchor.platform === primary.platform
      ? primary
      : entryToOfferView(picked.anchor, userRegion);
  if (!primaryOffer) return [];

  const others = picked.others
    .map((entry) => entryToOfferView(entry, userRegion))
    .filter((offer): offer is OfferView => offer !== null);
  if (others.length === 0) return [];
  return buildCompareGroups(primaryOffer, others).groups;
}
