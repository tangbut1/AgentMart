/** 侧边栏读「购物会话记忆池」。
 *
 *  直接读 chrome.storage.session 并监听 onChanged，不经过 service worker：
 *  池子是 background 写的，侧边栏只是个读者。少一跳消息，关标签页后侧边栏
 *  的更新也更快（DoD 要求 200ms 内）。
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { SESSION_POOL_KEY } from "../background/session.ts";
import {
  emptyPool,
  revivePool,
  type SessionPool,
} from "../core/session.ts";
import type { GetSessionResponse } from "../protocol.ts";

function readPool(): Promise<SessionPool> {
  return chrome.storage.session
    .get(SESSION_POOL_KEY)
    .then((store) => revivePool(store[SESSION_POOL_KEY]))
    .catch(() => emptyPool());
}

export interface UseSessionPool {
  pool: SessionPool;
  /** 打开侧边栏时主动问一次，补上 storage 事件还没到的那一小段 */
  refresh: () => void;
}

export function useSessionPool(): UseSessionPool {
  const [pool, setPool] = useState<SessionPool>(emptyPool);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const refresh = useCallback(() => {
    // 先走一次消息：service worker 刚被唤醒、storage 还没落盘时能立刻拿到
    void (async (): Promise<void> => {
      let next: SessionPool | null = null;
      try {
        const response = (await chrome.runtime.sendMessage({
          type: "get-session",
        })) as GetSessionResponse | undefined;
        if (response && response.ok) next = response.pool;
      } catch {
        /* service worker 没醒：退回复读 storage */
      }
      if (next === null) {
        try {
          next = await readPool();
        } catch {
          next = emptyPool();
        }
      }
      if (mounted.current) setPool(next);
    })();
  }, []);

  useEffect(() => {
    refresh();

    // 已经挂在 storage.session 上，不需要再判断是哪个 area
    const onChange = (changes: Record<string, chrome.storage.StorageChange>): void => {
      const change = changes[SESSION_POOL_KEY];
      if (!change) return;
      if (mounted.current) setPool(revivePool(change.newValue));
    };
    chrome.storage.session.onChanged.addListener(onChange);
    return () => {
      chrome.storage.session.onChanged.removeListener(onChange);
    };
  }, [refresh]);

  return { pool, refresh };
}
