import { useState } from "react";
import { useNavigate } from "react-router-dom";
import PlatformStatusStrip from "../components/PlatformStatusStrip";
import SearchBox from "../components/SearchBox";
import { Icon, Notice } from "../components/ui";

const PRINCIPLES = [
  {
    icon: "shield",
    title: "只呈现可核验的数据",
    desc: "价格、优惠与政策来自平台开放接口或公开规则，每条都带来源与采集时间；核验不了的项目单独列出，绝不编造。",
  },
  {
    icon: "price",
    title: "到手价分三层讲清楚",
    desc: "无条件抵扣、满足条件才成立的抵扣、无法核实的抵扣，分别计入「确定 / 潜在 / 待核验」三档，能不能叠加一目了然。",
  },
  {
    icon: "review",
    title: "评测看方法，不只看结论",
    desc: "按是否实测该型号、是否给出可复核数据、是否说明局限、是否披露商业关系五个维度评估每条评测，观点与原文摘录分开呈现。",
  },
];

const QUESTIONS = [
  "哪个平台能买到同款，各自标价、券、补贴、活动与支付优惠是多少？",
  "这些优惠各自需要什么条件，哪些不能叠加，实际会付多少钱？",
  "哪些金额核验不了，可能的原因是什么？",
  "各平台在退换、保修、发票、正品保障上有什么差别，是谁在承诺？",
  "专业评测怎么说，优点、不足、适合谁，创作者是否披露了商业关系？",
  "综合价格、售后、数据新鲜度与我的预算，买哪一家更合适，为什么？",
];

export default function HomePage() {
  const navigate = useNavigate();
  const [includeDemo, setIncludeDemo] = useState(false);

  const go = (keyword: string) => {
    const q = new URLSearchParams({ q: keyword });
    if (includeDemo) q.set("demo", "1");
    navigate(`/search?${q.toString()}`);
  };

  return (
    <div className="stack gap-24">
      <section className="hero">
        <div className="hero__eyebrow">
          <Icon name="scale" size={14} />
          跨平台智能购物决策
        </div>
        <h1 className="hero__title">
          把五个平台的价格、优惠和政策，
          <br />
          放到<em>同一张桌子</em>上比较。
        </h1>
        <p className="hero__lede">
          输入商品名称、型号或链接，购物参谋会检索京东、淘宝、天猫、拼多多、抖音商城的
          开放接口数据，把到手价拆成「确定 / 潜在 / 待核验」三档，对照售后政策差异，
          并汇总可核验的专业评测，给出有依据、有条件的购买建议。
        </p>

        <div className="hero__search">
          <SearchBox
            demoChecked={includeDemo}
            onDemoChange={setIncludeDemo}
            onSearch={go}
            autoFocus
          />
        </div>
      </section>

      <section className="stack gap-12">
        <div className="row gap-12 wrap" style={{ justifyContent: "space-between" }}>
          <h2 className="section-title">
            平台接入状态
            <span className="section-note">未接入的平台不会显示任何价格，也不会用演示数据冒充</span>
          </h2>
        </div>
        <PlatformStatusStrip />
      </section>

      <section>
        <div className="hero__principles">
          {PRINCIPLES.map((p) => (
            <div className="principle" key={p.title}>
              <div className="principle__icon" aria-hidden="true">
                <Icon name={p.icon as "shield"} size={16} />
              </div>
              <div className="principle__title">{p.title}</div>
              <p className="principle__desc">{p.desc}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel__head">
          <span style={{ color: "var(--primary)" }}>
            <Icon name="info" size={18} />
          </span>
          <h2 className="section-title">
            购物参谋回答的六个问题
            <span className="section-note">也是每个商品详情页的组织顺序</span>
          </h2>
        </div>
        <div className="panel__body">
          <ol className="question-list">
            {QUESTIONS.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ol>
        </div>
      </section>

      <section className="stack gap-12">
        <h2 className="section-title">
          数据从哪来
          <span className="section-note">
            平台开放接口 · 公开规则文件 · 人工整理的评测 · 严格隔离的演示数据
          </span>
        </h2>
        <Notice tone="info" title="关于演示数据">
          平台未接入时，界面会出现「未接入 / 暂无可核验数据」的提示，而不是虚构的价格。
          只有在勾选「包含演示数据」后才会展示虚构示例，用于查看界面与计算逻辑；
          演示数据带有明显标记，不参与任何购买建议。详见{" "}
          <a href="#/sources">数据来源页</a>。
        </Notice>
      </section>
    </div>
  );
}
