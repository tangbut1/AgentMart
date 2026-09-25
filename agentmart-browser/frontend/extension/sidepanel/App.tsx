import { useCallback, useEffect, useMemo, useState } from "react";
import BrowserCompare from "../../src/components/BrowserCompare.tsx";
import PurchaseCard from "../../src/components/PurchaseCard.tsx";
import { Badge, Icon, Notice } from "../../src/components/ui.tsx";
import type {
  GroupView,
  OfferView,
} from "../../src/lib/browserApi.ts";
import { PLATFORM_LABELS, buildCompareGroups, modelTokens, otherPlatforms } from "../core/index.ts";
import type { Platform } from "../core/enums.ts";
import type { CompareResponse, ReadPageResponse } from "../protocol.ts";

/** 侧面板自己的状态在 chrome.storage.session 里留一份，
 *  关掉再打开不会全丢（service worker 被回收也不影响）。 */
const REGION_KEY = "agentmart.region";
const LAST_PAGE_KEY = "agentmart.lastPage";

interface LastPage {
  offer: OfferView;
  problems: string[];
  url: string;
  platform: Platform;
}

function send<T extends { ok: boolean }>(message: unknown): Promise<T> {
  return chrome.runtime.sendMessage(message) as Promise<T>;
}

export default function App() {
  const [primary, setPrimary] = useState<OfferView | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [pageError, setPageError] = useState<string | null>(null);
  const [region, setRegion] = useState("");
  const [keyword, setKeyword] = useState("");
  const [selected, setSelected] = useState<Platform[]>([]);
  const [groups, setGroups] = useState<GroupView[]>([]);
  const [unmatched, setUnmatched] = useState<OfferView[]>([]);
  const [notes, setNotes] = useState<string[]>([]);
  const [reading, setReading] = useState(false);
  const [comparing, setComparing] = useState<Platform | null>(null);

  useEffect(() => {
    void chrome.storage.session.get([REGION_KEY, LAST_PAGE_KEY]).then((store) => {
      const savedRegion = store[REGION_KEY];
      if (typeof savedRegion === "string") setRegion(savedRegion);
      const saved = store[LAST_PAGE_KEY] as LastPage | undefined;
      if (saved && saved.offer) {
        setPrimary(saved.offer);
        setProblems(saved.problems ?? []);
      }
    });
  }, []);

  const readCurrentPage = useCallback(async () => {
    setReading(true);
    setPageError(null);
    try {
      const response = await send<ReadPageResponse>({ type: "read-page" });
      if (!response.ok || !response.offer) {
        setPageError(response.reason ?? "读取失败");
        return;
      }
      setPrimary(response.offer);
      setProblems(response.problems ?? []);
      setKeyword(defaultKeyword(response.offer.title));
      const snapshot: LastPage = {
        offer: response.offer,
        problems: response.problems ?? [],
        url: response.url ?? "",
        platform: response.platform ?? "jd",
      };
      await chrome.storage.session.set({ [LAST_PAGE_KEY]: snapshot });
      if (response.problems && response.problems.length > 0) {
        setNotes((previous) => [...response.problems!, ...previous].slice(0, 40));
      }
    } catch (error) {
      setPageError(error instanceof Error ? error.message : String(error));
    } finally {
      setReading(false);
    }
  }, []);

  const saveRegion = useCallback((value: string) => {
    setRegion(value);
    void chrome.storage.session.set({ [REGION_KEY]: value });
  }, []);

  const platformOptions = useMemo<Platform[]>(() => {
    if (!primary) return [];
    return otherPlatforms(primary.platform);
  }, [primary]);

  useEffect(() => {
    setSelected((previous) => {
      const allowed = new Set(platformOptions);
      const kept = previous.filter((platform) => allowed.has(platform));
      return kept.length > 0 ? kept : platformOptions;
    });
  }, [platformOptions]);

  const startCompare = useCallback(async () => {
    if (!primary) return;
    setGroups([]);
    setUnmatched([]);
    setNotes([]);
    const collected: OfferView[] = [];
    const collectedNotes: string[] = [];
    for (const platform of selected) {
      setComparing(platform);
      try {
        const response = await send<CompareResponse>({
          type: "compare-platform",
          platform,
          keyword: keyword.trim() || primary.title,
          primaryTokens: modelTokens(primary.title + " " + (primary.sku_text ?? "")),
          maxProducts: 2,
        });
        collectedNotes.push(...response.problems);
        collected.push(...response.offers);
        setNotes([...collectedNotes]);
        setGroups([]);
      } catch (error) {
        collectedNotes.push(
          PLATFORM_LABELS[platform] + "：" + (error instanceof Error ? error.message : String(error)),
        );
        setNotes([...collectedNotes]);
      }
    }
    setComparing(null);
    if (collected.length === 0) return;

    // 认成同款的进对比表，没认出来的单独列，绝不混在一起
    const result = buildCompareGroups(primary, collected);
    setGroups(result.groups);
    setUnmatched(result.unmatched);
    if (result.unmatched.length > 0) {
      setNotes((previous) => [
        ...previous,
        `有 ${result.unmatched.length} 个结果没认成同款，已单独列在下面，没有并进对比表。`,
      ]);
    }
  }, [keyword, primary, selected]);

  return (
    <div className="sidepanel">
      <header className="sidepanel__head">
        <div className="row gap-8">
          <Icon name="scale" size={18} />
          <strong>购物参谋 · 侧边栏</strong>
        </div>
        <p className="small muted">
          只读当前页面并计算到手价。不领券、不加购、不代下单、不代付款；
          优惠需要您本人在平台上领取。
        </p>
      </header>

      <section className="sidepanel__section">
        <div className="row gap-8 wrap" style={{ justifyContent: "space-between" }}>
          <span className="small muted">当前页面</span>
          <button
            type="button"
            className="btn btn--secondary btn--sm"
            onClick={() => void readCurrentPage()}
            disabled={reading}
          >
            <Icon name="refresh" size={14} />
            {reading ? "读取中…" : primary ? "重新读取" : "读取这个页面"}
          </button>
        </div>
        {pageError && (
          <Notice tone="warn" title="没读到">
            {pageError}
          </Notice>
        )}
        {problems.length > 0 && (
          <Notice tone="warn" title="读取时发现的问题">
            <ul className="small">
              {problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          </Notice>
        )}
        {primary ? (
          <PurchaseCard offer={primary} />
        ) : (
          !pageError && (
            <p className="small muted">
              在京东/淘宝/天猫/拼多多/抖音的商品页上点「读取这个页面」。
            </p>
          )
        )}
      </section>

      {primary && (
        <section className="sidepanel__section">
          <div className="small muted">收货地（只用来判断补贴文案里的地区限制，不替您认定资格）</div>
          <input
            className="input"
            value={region}
            placeholder="例如：江苏"
            onChange={(event) => saveRegion(event.target.value)}
          />
        </section>
      )}

      {primary && (
        <section className="sidepanel__section">
          <div className="small muted">去别的平台找同款</div>
          <input
            className="input"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="搜索关键词"
          />
          <div className="row gap-6 wrap">
            {platformOptions.map((platform) => {
              const active = selected.includes(platform);
              return (
                <button
                  key={platform}
                  type="button"
                  className={`chip${active ? " chip--on" : ""}`}
                  aria-pressed={active}
                  onClick={() =>
                    setSelected((previous) =>
                      previous.includes(platform)
                        ? previous.filter((item) => item !== platform)
                        : [...previous, platform],
                    )
                  }
                >
                  {PLATFORM_LABELS[platform]}
                </button>
              );
            })}
          </div>
          <button
            type="button"
            className="btn btn--primary btn--sm"
            onClick={() => void startCompare()}
            disabled={comparing !== null || selected.length === 0}
          >
            <Icon name="search" size={14} />
            {comparing ? `正在看${PLATFORM_LABELS[comparing]}…` : "开始比价"}
          </button>
          <p className="small muted">
            会依次打开这几个平台的搜索页和商品页（都是您自己浏览器里的正常标签页，
            用您自己的登录态），读完自动关掉。跨平台是否同款只依据标题和规格文本判断。
          </p>
        </section>
      )}

      {notes.length > 0 && (
        <section className="sidepanel__section">
          <Notice tone="info" title="过程记录">
            <ul className="small">
              {notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </Notice>
        </section>
      )}

      {groups.length > 0 && (
        <section className="sidepanel__section sidepanel__scroll">
          <BrowserCompare groups={groups} />
        </section>
      )}

      {unmatched.length > 0 && (
        <section className="sidepanel__section">
          <div className="small muted">没认成同款的结果（请自行核对型号）</div>
          <ul className="small">
            {unmatched.map((offer) => (
              <li key={offer.id}>
                <Badge tone="outline">{offer.platform_label}</Badge>{" "}
                <a className="link-out" href={offer.url} target="_blank" rel="noreferrer noopener">
                  {offer.title}
                </a>
                <div className="muted">
                  确定到手 {offer.breakdown.definite_total} 元 · 标价{" "}
                  {offer.breakdown.list_price || "—"} 元
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <footer className="sidepanel__foot small muted">
        价格均来自您当前看到的页面文本。页面没写的不会替您补；补贴资格、优惠能否
        叠加，一律以平台结算页为准。
      </footer>
    </div>
  );
}

/** 用标题当默认搜索词：去掉常见营销后缀，避免搜出一堆广告。 */
function defaultKeyword(title: string): string {
  const cleaned = title
    .replace(/【[^】]*】/g, " ")
    .replace(/（[^）]*）/g, " ")
    .replace(/\([^)]*\)/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned.slice(0, 60);
}
