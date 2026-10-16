export type ThemePreference = "light" | "dark" | "system";
export type EffectiveTheme = "light" | "dark";

export interface ThemeState {
  preference: ThemePreference;
  effective: EffectiveTheme;
}

export const THEME_STORAGE_KEY = "op_pm_theme_v1";
const SYSTEM_THEME_QUERY = "(prefers-color-scheme: dark)";
const THEME_COLORS: Record<EffectiveTheme, string> = {
  light: "#1e7a4b",
  dark: "#101d1a",
};

type ThemeSubscriber = (state: ThemeState) => void;

let state: ThemeState | null = null;
const subscribers = new Set<ThemeSubscriber>();
let storageListening = false;
let mediaQuery: MediaQueryList | null = null;

function isThemePreference(value: string | null): value is ThemePreference {
  return value === "light" || value === "dark" || value === "system";
}

export function readPreference(): ThemePreference {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemePreference(value) ? value : "system";
  } catch {
    return "system";
  }
}

export function resolveTheme(preference: ThemePreference, systemDark: boolean): EffectiveTheme {
  if (preference === "system") return systemDark ? "dark" : "light";
  return preference;
}

export function applyTheme(effective: EffectiveTheme): void {
  if (typeof document === "undefined") return;

  const root = document.documentElement;
  root.dataset.theme = effective;
  root.style.colorScheme = effective;
  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", THEME_COLORS[effective]);
}

function readSystemDark(): boolean {
  try {
    return typeof window.matchMedia === "function" && window.matchMedia(SYSTEM_THEME_QUERY).matches;
  } catch {
    return false;
  }
}

function notifySubscribers(): void {
  if (!state) return;
  for (const subscriber of subscribers) subscriber(state);
}

function stopMediaListener(): void {
  if (!mediaQuery) return;
  try {
    if (typeof mediaQuery.removeEventListener === "function") {
      mediaQuery.removeEventListener("change", handleSystemChange);
    } else {
      mediaQuery.removeListener(handleSystemChange);
    }
  } catch {
    // Um browser sem suporte completo a MediaQueryList não bloqueia o tema atual.
  }
  mediaQuery = null;
}

function synchronizeListeners(): void {
  if (typeof window === "undefined") return;

  if (subscribers.size === 0) {
    if (storageListening) {
      window.removeEventListener("storage", handleStorageChange);
      storageListening = false;
    }
    stopMediaListener();
    return;
  }

  if (!storageListening) {
    window.addEventListener("storage", handleStorageChange);
    storageListening = true;
  }

  if (state?.preference !== "system") {
    stopMediaListener();
    return;
  }
  if (mediaQuery) return;

  try {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(SYSTEM_THEME_QUERY);
    if (typeof query.addEventListener === "function") {
      query.addEventListener("change", handleSystemChange);
    } else {
      query.addListener(handleSystemChange);
    }
    mediaQuery = query;
  } catch {
    mediaQuery = null;
  }
}

function updateState(preference: ThemePreference, systemDark = readSystemDark()): void {
  state = { preference, effective: resolveTheme(preference, systemDark) };
  applyTheme(state.effective);
  synchronizeListeners();
  notifySubscribers();
}

function handleSystemChange(event: MediaQueryListEvent): void {
  if (state?.preference === "system") updateState("system", event.matches);
}

function handleStorageChange(event: StorageEvent): void {
  if (event.key !== null && event.key !== THEME_STORAGE_KEY) return;
  updateState(isThemePreference(event.newValue) ? event.newValue : "system");
}

export function getThemeState(): ThemeState {
  if (!state) {
    const preference = readPreference();
    state = { preference, effective: resolveTheme(preference, readSystemDark()) };
    applyTheme(state.effective);
  }
  return state;
}

export function setPreference(preference: ThemePreference): void {
  const safePreference = isThemePreference(preference) ? preference : "system";
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, safePreference);
  } catch {
    // A preferência continua aplicada nesta sessão mesmo sem armazenamento.
  }
  updateState(safePreference);
}

export function subscribeTheme(subscriber: ThemeSubscriber): () => void {
  getThemeState();
  subscribers.add(subscriber);
  synchronizeListeners();
  return () => {
    subscribers.delete(subscriber);
    synchronizeListeners();
  };
}
