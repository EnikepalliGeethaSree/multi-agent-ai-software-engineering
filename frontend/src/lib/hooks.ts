import { useCallback, useEffect, useRef, useState } from "react";

/** Fetch data, optionally re-polling while `shouldPoll(data)` is true. */
export function useApi<T>(
  load: () => Promise<T>,
  deps: unknown[],
  options: { pollMs?: number; shouldPoll?: (data: T) => boolean } = {},
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loadRef = useRef(load);
  loadRef.current = load;
  const optsRef = useRef(options);
  optsRef.current = options;

  const refresh = useCallback(async () => {
    try {
      const value = await loadRef.current();
      setData(value);
      setError(null);
      return value;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setLoading(true);
    const tick = async () => {
      const value = await refresh();
      const { pollMs, shouldPoll } = optsRef.current;
      if (!cancelled && pollMs && value !== null && (!shouldPoll || shouldPoll(value))) {
        timer = setTimeout(tick, pollMs);
      }
    };
    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, refresh, setData };
}

/** Re-render every `ms` (for live elapsed timers). */
export function useNow(ms = 1000, active = true): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms, active]);
  return now;
}

export type Theme = "system" | "light" | "dark";

export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const saved = localStorage.getItem("theme");
      return saved === "light" || saved === "dark" ? saved : "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    applyTheme(theme);
    try {
      localStorage.setItem("theme", theme);
    } catch {
      /* storage unavailable: theme still applies for this session */
    }
  }, [theme]);
  return [theme, setTheme];
}
