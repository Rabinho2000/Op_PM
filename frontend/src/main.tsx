import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { ensureMsalReady } from "./auth/msal";

// ensureMsalReady() inicializa o MSAL e, se a app acabou de voltar de um
// loginRedirect, troca o código de autorização por tokens (PKCE) e marca
// a conta como ativa — tudo isto tem de acontecer antes da primeira
// renderização, para que App.tsx já veja a sessão (real ou de
// desenvolvimento) corretamente no primeiro render.
ensureMsalReady()
  .catch((err) => {
    // Falha a inicializar o MSAL (ex. configuração inválida) não deve
    // impedir a app de arrancar — o login de desenvolvimento (quando
    // ligado) e o ecrã de login continuam a funcionar; só o login real
    // Microsoft fica indisponível, com o erro visível na consola.
    console.error("Falha ao inicializar MSAL:", err);
  })
  .finally(() => {
    ReactDOM.createRoot(document.getElementById("root")!).render(
      <React.StrictMode>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </React.StrictMode>
    );
  });
