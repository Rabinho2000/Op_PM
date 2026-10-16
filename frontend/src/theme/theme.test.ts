import { afterEach, describe, expect, it, vi } from "vitest";
import {
  applyTheme,
  getThemeState,
  readPreference,
  resolveTheme,
  setPreference,
  subscribeTheme,
  THEME_STORAGE_KEY,
} from "./theme";

type MediaListener = (event: MediaQueryListEvent) => void;
const restoreCallbacks: Array<() => void> = [];

function installMatchMedia(initialMatches: boolean) {
  let matches = initialMatches;
  const listeners = new Set<MediaListener>();
  const query = {
    media: "(prefers-color-scheme: dark)",
    get matches() {
      return matches;
    },
    onchange: null,
    addEventListener: vi.fn((_type: string, listener: MediaListener) => listeners.add(listener)),
    removeEventListener: vi.fn((_type: string, listener: MediaListener) => listeners.delete(listener)),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  } as unknown as MediaQueryList;
  const original = window.matchMedia;
  Object.defineProperty(window, "matchMedia", { configurable: true, value: vi.fn(() => query) });
  restoreCallbacks.push(() => Object.defineProperty(window, "matchMedia", { configurable: true, value: original }));

  return {
    query,
    setMatches(value: boolean) {
      matches = value;
      for (const listener of [...listeners]) listener({ matches: value } as MediaQueryListEvent);
    },
  };
}

afterEach(() => {
  while (restoreCallbacks.length) restoreCallbacks.pop()?.();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.style.colorScheme = "";
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", "#1e7a4b");
  vi.restoreAllMocks();
});

describe("preferência e resolução do tema", () => {
  it("usa Sistema quando a preferência está ausente ou inválida", () => {
    expect(readPreference()).toBe("system");
    localStorage.setItem(THEME_STORAGE_KEY, "sepia");
    expect(readPreference()).toBe("system");
  });

  it.each(["light", "dark", "system"] as const)("lê a preferência válida %s", (preference) => {
    localStorage.setItem(THEME_STORAGE_KEY, preference);
    expect(readPreference()).toBe(preference);
  });

  it("resolve Sistema para claro e escuro", () => {
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });

  it("aplica data-theme, color-scheme e a meta theme-color", () => {
    const meta = document.createElement("meta");
    meta.name = "theme-color";
    document.head.append(meta);

    applyTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.style.colorScheme).toBe("dark");
    expect(meta.content).toBe("#101d1a");

    meta.remove();
  });

  it("recupera-se de exceções ao ler e gravar localStorage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage indisponível");
    });
    expect(readPreference()).toBe("system");
    vi.restoreAllMocks();

    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage indisponível");
    });
    expect(() => setPreference("dark")).not.toThrow();
    expect(getThemeState()).toMatchObject({ preference: "dark", effective: "dark" });
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});

describe("subscrições", () => {
  it("não falha quando matchMedia não existe", () => {
    const original = window.matchMedia;
    Object.defineProperty(window, "matchMedia", { configurable: true, value: undefined });
    restoreCallbacks.push(() => Object.defineProperty(window, "matchMedia", { configurable: true, value: original }));

    setPreference("system");
    const unsubscribe = subscribeTheme(() => undefined);
    expect(getThemeState().effective).toBe("light");
    unsubscribe();
  });

  it("só reage a mudanças do sistema enquanto a preferência é Sistema", () => {
    const media = installMatchMedia(false);
    setPreference("dark");
    const observed: string[] = [];
    const unsubscribe = subscribeTheme((state) => observed.push(`${state.preference}:${state.effective}`));

    expect(media.query.addEventListener).not.toHaveBeenCalled();
    setPreference("system");
    expect(media.query.addEventListener).toHaveBeenCalledTimes(1);
    media.setMatches(true);
    expect(getThemeState()).toMatchObject({ preference: "system", effective: "dark" });

    setPreference("light");
    expect(media.query.removeEventListener).toHaveBeenCalledTimes(1);
    media.setMatches(false);
    expect(getThemeState()).toMatchObject({ preference: "light", effective: "light" });
    expect(observed).toContain("system:dark");
    unsubscribe();
  });

  it("sincroniza alterações recebidas pelo evento storage", () => {
    setPreference("dark");
    const unsubscribe = subscribeTheme(() => undefined);
    window.dispatchEvent(new StorageEvent("storage", { key: THEME_STORAGE_KEY, newValue: "light" }));
    expect(getThemeState()).toMatchObject({ preference: "light", effective: "light" });
    unsubscribe();
  });

  it("remove os listeners de storage e do sistema quando a subscrição termina", () => {
    const media = installMatchMedia(false);
    setPreference("system");
    const removeStorage = vi.spyOn(window, "removeEventListener");
    const unsubscribe = subscribeTheme(() => undefined);

    unsubscribe();
    expect(media.query.removeEventListener).toHaveBeenCalledTimes(1);
    expect(removeStorage).toHaveBeenCalledWith("storage", expect.any(Function));
  });
});
