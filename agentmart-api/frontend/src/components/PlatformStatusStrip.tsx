import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { PlatformStatus } from "../lib/api";
import { CONNECTION_STATUS_LABEL, PLATFORM_LABEL } from "../lib/format";
import { Badge, Icon } from "./ui";

function toneFor(status: PlatformStatus["status"]) {
  if (status === "connected") return "ok" as const;
  if (status === "rate_limited") return "warn" as const;
  if (status === "error") return "danger" as const;
  return "muted" as const;
}

/** 平台接入状态条：首页与数据来源页共用。 */
export default function PlatformStatusStrip({
  compact = false,
}: {
  compact?: boolean;
}) {
  const [statuses, setStatuses] = useState<PlatformStatus[] | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    api
      .platforms(ac.signal)
      .then(setStatuses)
      .catch(() => setStatuses([]));
    return () => ac.abort();
  }, []);

  if (statuses === null) {
    return (
      <div className="status-strip" aria-busy="true">
        {[0, 1, 2, 3, 4].map((i) => (
          <span className="status-item" key={i}>
            <span className="skeleton" style={{ width: 52, height: 12 }} />
          </span>
        ))}
      </div>
    );
  }

  if (statuses.length === 0) {
    return (
      <p className="small muted row gap-6">
        <Icon name="alert" size={13} />
        无法获取平台接入状态（后端未启动？）
      </p>
    );
  }

  return (
    <div className="status-strip">
      {statuses.map((s) => (
        <span className="status-item" key={s.platform} title={s.message}>
          <span className={`plat-dot plat-dot--${s.platform}`} aria-hidden="true" />
          <span className="status-item__name">{PLATFORM_LABEL[s.platform]}</span>
          <Badge tone={toneFor(s.status)} dot>
            {CONNECTION_STATUS_LABEL[s.status]}
          </Badge>
          {!compact && s.status !== "connected" && (
            <span className="status-item__text">
              需配置 {s.required_env.slice(0, 2).join(" / ")}
              {s.required_env.length > 2 ? " 等" : ""}
            </span>
          )}
        </span>
      ))}
    </div>
  );
}
