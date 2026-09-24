import { useState, type FormEvent } from "react";
import { Icon } from "./ui";

const EXAMPLES = ["索尼 WH-1000XM5", "iPhone 15 Pro 256G", "石头 P10 Pro"];

export default function SearchBox({
  initialKeyword = "",
  initialMode = "keyword",
  loading = false,
  demoChecked,
  onDemoChange,
  onSearch,
  autoFocus = false,
}: {
  initialKeyword?: string;
  initialMode?: "keyword" | "link";
  loading?: boolean;
  demoChecked: boolean;
  onDemoChange: (v: boolean) => void;
  onSearch: (keyword: string) => void;
  autoFocus?: boolean;
}) {
  const [mode, setMode] = useState<"keyword" | "link">(initialMode);
  const [text, setText] = useState(initialKeyword);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const q = text.trim();
    if (q) onSearch(q);
  };

  return (
    <form className="searchbox" onSubmit={submit} role="search">
      <div className="row gap-8 wrap" style={{ justifyContent: "space-between" }}>
        <div className="segmented" role="radiogroup" aria-label="搜索方式">
          <button
            type="button"
            role="radio"
            aria-checked={mode === "keyword"}
            className="segmented__option"
            onClick={() => setMode("keyword")}
          >
            <span className="row gap-6">
              <Icon name="search" size={13} />
              名称 / 型号
            </span>
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={mode === "link"}
            className="segmented__option"
            onClick={() => setMode("link")}
          >
            <span className="row gap-6">
              <Icon name="link" size={13} />
              商品链接
            </span>
          </button>
        </div>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={demoChecked}
            onChange={(e) => onDemoChange(e.target.checked)}
          />
          包含演示数据
          <span className="muted">（虚构价格，仅用于查看界面）</span>
        </label>
      </div>

      <div className="searchbox__row">
        <label className="sr-only" htmlFor="search-input">
          {mode === "keyword" ? "商品名称或型号" : "商品链接"}
        </label>
        <input
          id="search-input"
          className="input"
          type={mode === "link" ? "url" : "text"}
          inputMode={mode === "link" ? "url" : "text"}
          placeholder={
            mode === "keyword"
              ? "输入商品名称或型号，例如：索尼 WH-1000XM5"
              : "粘贴商品页链接，例如：https://item.jd.com/100012043978.html"
          }
          value={text}
          autoFocus={autoFocus}
          maxLength={200}
          onChange={(e) => setText(e.target.value)}
        />
        <button
          className="btn btn--primary"
          type="submit"
          disabled={loading || text.trim().length === 0}
        >
          {loading ? "检索中…" : "开始比较"}
        </button>
      </div>

      {mode === "keyword" && (
        <div className="searchbox__meta">
          <span className="small muted">试试：</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              className="chip"
              onClick={() => {
                setText(ex);
                onSearch(ex);
              }}
            >
              {ex}
            </button>
          ))}
        </div>
      )}

      {mode === "link" && (
        <p className="searchbox__meta small muted">
          <Icon name="info" size={13} /> 平台商品页需要登录才能查看，
          系统不会抓取商品页内容；链接仅用于提取关键词，再到各平台开放接口检索同款。
        </p>
      )}
    </form>
  );
}
