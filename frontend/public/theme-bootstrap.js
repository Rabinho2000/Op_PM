// Aplica o tema (claro/escuro) antes do primeiro paint, sem flash.
// É um ficheiro externo e não um <script> inline para a CSP (script-src 'self')
// não precisar de 'unsafe-inline'. Carregado de forma síncrona no <head>.
(() => {
  try {
    const root = document.documentElement;
    let preference = "system";
    try {
      const saved = window.localStorage.getItem("op_pm_theme_v1");
      if (saved === "light" || saved === "dark" || saved === "system") preference = saved;
    } catch {}
    let systemDark = false;
    try {
      systemDark = typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
    } catch {}
    const theme = preference === "system" ? (systemDark ? "dark" : "light") : preference;
    root.dataset.theme = theme;
    root.style.colorScheme = theme;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "dark" ? "#101d1a" : "#1e7a4b");
  } catch {}
})();
