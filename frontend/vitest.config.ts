import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Configuração de testes separada de vite.config.ts (dev server) — cobre
// tanto a lógica isolada do login de desenvolvimento (D-033) como a
// suite de UI da Fase 1.5 (D-039); setupFiles estende `expect` com os
// matchers do jest-dom usados pelos testes de componentes.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
  },
});
