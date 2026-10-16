import html from "../../index.html?raw";
import { afterEach, describe, expect, it } from "vitest";
import { resolveTheme, ThemePreference, THEME_STORAGE_KEY } from "./theme";

const bootstrap = html.match(/<script data-theme-bootstrap>([\s\S]*?)<\/script>/)?.[1];
const originalMatchMedia = Object.getOwnPropertyDescriptor(window, "matchMedia");
const originalLocalStorage = Object.getOwnPropertyDescriptor(window, "localStorage");

if (!bootstrap) throw new Error("Não foi encontrado o bootstrap de tema no index.html.");

const cases: Array<{ preference: ThemePreference; saved: string | null; systemDark: boolean }> = [
  { preference: "system", saved: null, systemDark: false },
  { preference: "system", saved: null, systemDark: true },
  { preference: "system", saved: "invalid", systemDark: false },
  { preference: "system", saved: "invalid", systemDark: true },
  { preference: "light", saved: "light", systemDark: false },
  { preference: "light", saved: "light", systemDark: true },
  { preference: "dark", saved: "dark", systemDark: false },
  { preference: "dark", saved: "dark", systemDark: true },
  { preference: "system", saved: "system", systemDark: false },
  { preference: "system", saved: "system", systemDark: true },
];

function restoreWindowProperty(name: "matchMedia" | "localStorage", descriptor?: PropertyDescriptor): void {
  if (descriptor) Object.defineProperty(window, name, descriptor);
  else Reflect.deleteProperty(window, name);
}

afterEach(() => {
  restoreWindowProperty("matchMedia", originalMatchMedia);
  restoreWindowProperty("localStorage", originalLocalStorage);
  localStorage.clear();
  document.head.replaceChildren();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.style.colorScheme = "";
});

describe("bootstrap síncrono do tema", () => {
  it.each(cases)("é equivalente a resolveTheme para $preference (sistema escuro: $systemDark)", (testCase) => {
    localStorage.clear();
    if (testCase.saved !== null) localStorage.setItem(THEME_STORAGE_KEY, testCase.saved);
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: () => ({ matches: testCase.systemDark }),
    });
    document.head.innerHTML = '<meta name="theme-color" content="#1e7a4b">';

    window.eval(bootstrap);

    const expected = resolveTheme(testCase.preference, testCase.systemDark);
    expect(document.documentElement.dataset.theme).toBe(expected);
    expect(document.documentElement.style.colorScheme).toBe(expected);
    expect(document.querySelector('meta[name="theme-color"]')?.getAttribute("content")).toBe(
      expected === "dark" ? "#101d1a" : "#1e7a4b",
    );
  });

  it("não propaga exceção se localStorage não estiver acessível", () => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new Error("storage indisponível");
      },
    });
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: () => ({ matches: true }),
    });
    document.head.innerHTML = '<meta name="theme-color" content="#1e7a4b">';

    expect(() => window.eval(bootstrap)).not.toThrow();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
