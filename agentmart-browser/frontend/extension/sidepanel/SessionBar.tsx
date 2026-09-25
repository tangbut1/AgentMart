/** 「正在对比 N 个标签页」指示条。
 *
 *  这一条是阶段一的门面：用户什么都不用点，侧边栏一打开就知道自己开着哪几个
 *  平台的同款页。点哪一项就跳回哪个标签页。
 *
 *  两条硬规矩：
 *  1. 型号只有部分重合的组，必须带着「规格可能不同」的提醒展示，不能默默
 *     摆成一副「这两口价可以比」的样子；
 *  2. 没有价格的条目照样列出（用户可能就是要切回那个页面），但标注「没读到价」。
 */

import type { SessionTabView } from "../core/session.ts";
import { PLATFORM_LABELS } from "../core/enums.ts";
import { Icon } from "../../src/components/ui.tsx";

interface SessionBarProps {
  tabs: SessionTabView[];
  /** 池子分了几组同款。只有一组时才说「正在对比」。 */
  clusterCount: number;
  onFocus: (tabId: number) => void;
}

export default function SessionBar({ tabs, clusterCount, onFocus }: SessionBarProps) {
  if (tabs.length === 0) return null;

  const partial = tabs.some((tab) => tab.modelPartial);
  // 一个标签页谈不上「对比」；分属好几款时也不能说正在对比
  const headline =
    clusterCount <= 1 && tabs.length > 1
      ? `正在对比 ${tabs.length} 个标签页（同一款）`
      : `已识别 ${tabs.length} 个商品页，分属 ${clusterCount} 款`;

  return (
    <section className="sidepanel__section">
      <div className="row gap-8 wrap" style={{ justifyContent: "space-between" }}>
        <span className="small muted">{headline}</span>
        <span className="small muted">点一下跳回那个页面</span>
      </div>
      <div className="row gap-6 wrap sessionbar">
        {tabs.map((tab) => (
          <button
            key={tab.tabId}
            type="button"
            className={`chip chip--tab${tab.isActive ? " chip--on" : ""}`}
            aria-pressed={tab.isActive}
            title={`${PLATFORM_LABELS[tab.platform]}：${tab.title}`}
            onClick={() => onFocus(tab.tabId)}
          >
            {tab.isActive && <Icon name="check" size={12} />}
            <span>{tab.platformLabel}</span>
            {tab.isActive && <span className="sessionbar__now">当前</span>}
            {!tab.hasPrice && <span className="sessionbar__now">没读到价</span>}
          </button>
        ))}
      </div>
      {partial && (
        <p className="small warn">
          这几个页面里有的型号和组内其他页面只有部分重合，规格可能不同，
          下面的对比请以两边商品页为准。
        </p>
      )}
    </section>
  );
}
