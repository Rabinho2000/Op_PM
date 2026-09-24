// Utilitários de teste: monta um componente com router, sessão fixa
// (sem pedidos a /me) e notificações — como na aplicação real.
import { render } from "@testing-library/react";
import { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { HealthResponse, MeResponse } from "../api/client";
import { ToastProvider } from "../components/Toast";
import { StaticSessionProvider } from "../session/SessionContext";

export function renderWithProviders(
  ui: ReactElement,
  {
    me = null,
    health = null,
    route = "/",
    path,
  }: { me?: MeResponse | null; health?: HealthResponse | null; route?: string; path?: string } = {}
) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <StaticSessionProvider me={me} health={health}>
        <ToastProvider>
          {path ? (
            <Routes>
              <Route path={path} element={ui} />
            </Routes>
          ) : (
            ui
          )}
        </ToastProvider>
      </StaticSessionProvider>
    </MemoryRouter>
  );
}
