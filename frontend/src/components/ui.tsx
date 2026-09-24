import { type ReactNode, useEffect, useState } from "react";

/* ─── 媒体查询（用于密集表格在移动端 reorganize 而非简单缩小） ── */

/**
 * 以真实布局视口宽度判断断点。
 * 某些嵌入式浏览器环境里多次调用 window.matchMedia 会返回状态不一致的
 * MediaQueryList 实例，因此这里统一用 documentElement.clientWidth 推导，
 * 与 CSS 媒体查询使用的视口口径一致。
 */
export function useMediaQuery(query: string): boolean {
  const evaluate = () => {
    if (typeof window === "undefined") return false;
    const min = /min-width:\s*(\d+)px/.exec(query);
    const max = /max-width:\s*(\d+)px/.exec(query);
    const width = document.documentElement.clientWidth;
    if (min && max) return width >= Number(min[1]) && width <= Number(max[1]);
    if (min) return width >= Number(min[1]);
    if (max) return width <= Number(max[1]);
    return window.matchMedia ? window.matchMedia(query).matches : false;
  };

  const [matches, setMatches] = useState(evaluate);

  useEffect(() => {
    const onChange = () => setMatches(evaluate());
    onChange();
    window.addEventListener("resize", onChange);
    window.addEventListener("orientationchange", onChange);
    return () => {
      window.removeEventListener("resize", onChange);
      window.removeEventListener("orientationchange", onChange);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  return matches;
}

export const useIsDesktop = () => useMediaQuery("(min-width: 861px)");

/* ─── 图标（细线 SVG，避免 emoji 的随意感） ──────────────────── */

type IconName =
  | "search"
  | "link"
  | "check"
  | "alert"
  | "info"
  | "external"
  | "back"
  | "scale"
  | "shield"
  | "clock"
  | "refresh"
  | "table"
  | "review"
  | "price";

const PATHS: Record<IconName, ReactNode> = {
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-3.5-3.5" />
    </>
  ),
  link: (
    <>
      <path d="M10 13a5 5 0 0 0 7.07 0l2.12-2.12a5 5 0 0 0-7.07-7.07L11 4.93" />
      <path d="M14 11a5 5 0 0 0-7.07 0L4.81 13.12a5 5 0 0 0 7.07 7.07L13 19.07" />
    </>
  ),
  check: <path d="M4 12.5l5 5L20 6.5" />,
  alert: (
    <>
      <path d="M12 4L2.5 20h19L12 4z" />
      <path d="M12 10v4.5" />
      <circle cx="12" cy="17" r="0.6" fill="currentColor" stroke="none" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5" />
      <circle cx="12" cy="7.8" r="0.6" fill="currentColor" stroke="none" />
    </>
  ),
  external: (
    <>
      <path d="M14 4h6v6" />
      <path d="M20 4L10 14" />
      <path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" />
    </>
  ),
  back: <path d="M15 5l-7 7 7 7" />,
  scale: (
    <>
      <path d="M12 4v16" />
      <path d="M6 8h12" />
      <path d="M6 8l-2.5 6h5L6 8z" />
      <path d="M18 8l-2.5 6h5L18 8z" />
      <path d="M8 20h8" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3z" />
      <path d="M9 12l2 2 4-4" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.5 2" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 11a8 8 0 1 0-2.34 5.66" />
      <path d="M20 5v6h-6" />
    </>
  ),
  table: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 9.5h18M9.5 9.5V20" />
    </>
  ),
  review: (
    <>
      <rect x="3" y="4" width="18" height="14" rx="2" />
      <path d="M8 8.5h8M8 12h5" />
      <path d="M10.5 21l1.5-3 1.5 3" />
    </>
  ),
  price: (
    <>
      <path d="M12 3v18" />
      <path d="M16.5 7.5c-.6-1.4-2.1-2-4-2-2.2 0-3.8 1-3.8 2.8 0 1.8 1.6 2.5 3.8 3 2.2.5 4 1.2 4 3.2 0 1.9-1.8 3-4.2 3-2.1 0-3.6-.8-4.2-2.2" />
    </>
  ),
};

export function Icon({
  name,
  size = 16,
  className,
}: {
  name: IconName;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      {PATHS[name]}
    </svg>
  );
}

/* ─── 徽章 ─────────────────────────────────────────────────── */

export type BadgeTone =
  | "ok"
  | "warn"
  | "danger"
  | "info"
  | "price"
  | "muted"
  | "outline";

export function Badge({
  tone = "muted",
  dot = false,
  children,
  title,
}: {
  tone?: BadgeTone;
  dot?: boolean;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className={`badge badge--${tone}`} title={title}>
      {dot && <span className="badge__dot" />}
      {children}
    </span>
  );
}

/* ─── 提示条 ───────────────────────────────────────────────── */

export function Notice({
  tone = "info",
  title,
  icon,
  children,
}: {
  tone?: "info" | "warn" | "danger" | "demo";
  title?: string;
  icon?: ReactNode;
  children?: ReactNode;
}) {
  const iconMap = { info: "info", warn: "alert", danger: "alert", demo: "alert" } as const;
  return (
    <div className={`notice notice--${tone}`} role="note">
      <span className="notice__icon" aria-hidden="true">
        {icon ?? <Icon name={iconMap[tone]} size={15} />}
      </span>
      <div className="notice__body">
        {title && <div className="notice__title">{title}</div>}
        {children}
      </div>
    </div>
  );
}

/* ─── 价格数字 ─────────────────────────────────────────────── */

export function PriceFigure({
  value,
  size = "md",
  strike = false,
  prefix = "¥",
}: {
  value: string | number | null | undefined;
  size?: "sm" | "md" | "lg";
  strike?: boolean;
  prefix?: string;
}) {
  const n = value == null ? NaN : Number(value);
  const valid = Number.isFinite(n);
  const fixed = valid ? n.toFixed(2) : "0.00";
  const [int, frac] = fixed.split(".");
  return (
    <span
      className={`price-figure price-figure--${size}${strike ? " price-figure--strike" : ""}`}
    >
      {valid && prefix && <span className="price-figure__sym">{prefix}</span>}
      <span className="price-figure__int">
        {valid ? Number(int).toLocaleString("zh-CN") : "—"}
      </span>
      {valid && frac !== "00" && <span className="price-figure__frac">.{frac}</span>}
    </span>
  );
}

/* ─── 加载骨架 ─────────────────────────────────────────────── */

export function Skeleton({
  width,
  height = 14,
  radius,
  className = "",
}: {
  width?: number | string;
  height?: number | string;
  radius?: number | string;
  className?: string;
}) {
  return (
    <span
      className={`skeleton ${className}`}
      style={{
        display: "block",
        width: width ?? "100%",
        height,
        borderRadius: radius,
      }}
    />
  );
}

/* ─── 空状态 ───────────────────────────────────────────────── */

export function EmptyState({
  icon = "search",
  title,
  desc,
  actions,
}: {
  icon?: ReactNode;
  title: string;
  desc?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-state__icon" aria-hidden="true">
        {icon}
      </div>
      <div className="empty-state__title">{title}</div>
      {desc && <div className="empty-state__desc">{desc}</div>}
      {actions && <div className="row gap-8 wrap" style={{ justifyContent: "center" }}>{actions}</div>}
    </div>
  );
}

/* ─── 分段控件 ─────────────────────────────────────────────── */

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label?: string;
}) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          className="segmented__option"
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* ─── 评分条 ───────────────────────────────────────────────── */

export function ScoreBar({ value, label }: { value: number; label?: string }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div
      className="score-bar"
      role="meter"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label ?? "评分"}
    >
      <div className="score-bar__fill" style={{ width: `${pct}%` }} />
    </div>
  );
}
