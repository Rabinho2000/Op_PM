import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Fase 0: sem proxy para o backend configurado por omissão — o frontend usa
// VITE_API_BASE_URL (ver .env.example) para saber onde está a API. Em dev,
// aponta normalmente para http://localhost:8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
});
