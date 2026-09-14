import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Configuração de testes separada de vite.config.ts (dev server) — Fase 1,
// fecho de hardening (D-033): só cobre lógica isolada do login de
// desenvolvimento (src/api/client.ts), não é uma suite de UI completa
// (sem Playwright/Cypress ainda — ver docs/PLAN.md).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
