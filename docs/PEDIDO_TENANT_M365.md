# Pedido de configuração Microsoft Entra ID — Op_PM

> Texto para enviar a quem administra o Microsoft 365. Responde à pergunta
> bloqueante nº 1 de `OPEN_QUESTIONS.md`. Os nomes das variáveis vêm de
> `backend/app/config.py` e `frontend/.env.example`.

**Assunto: Pedido de configuração Microsoft Entra ID para a aplicação Op_PM**

Precisamos de duas *app registrations* no tenant e de alguns valores de volta.
Não é preciso instalar nada.

## 1. App registration da API (backend)

- Nome sugerido: `Op_PM API`. Tipo de conta: só este tenant (single tenant).
- Em *Expose an API*, definir o *Application ID URI* como
  `api://<client-id-da-API>`.
- Criar o âmbito delegado **`access_as_user`**, com consentimento por
  administradores e utilizadores.
- Em *Manifest*, confirmar `requestedAccessTokenVersion: 2`. Sem isto o
  backend rejeita o token.

## 2. App registration da SPA (frontend)

- Nome sugerido: `Op_PM Web`. Plataforma: **Single-page application** (não
  "Web"), com Authorization Code + PKCE e **sem client secret**.
- *Redirect URIs*: `http://localhost:5173` (desenvolvimento) e o URL de staging
  quando existir, por exemplo `https://<domínio-de-staging>`.
- Em *API permissions*, adicionar `Op_PM API → access_as_user` (delegada) e a
  `User.Read` do Graph, e dar **consentimento de administrador**.

## 3. Utilizadores

- Os utilizadores de teste têm de existir no tenant com o **mesmo email** que
  está registado na aplicação. O primeiro login associa a conta ao email, e
  uma diferença faz falhar o login.
- Preciso de saber **quem é o primeiro Administrador** e uma lista de 3 a 5
  pessoas para o piloto (idealmente um Administrador, um Chefe, um PM e um
  Comercial, para testar as permissões).

## 4. Para a fase seguinte (Graph)

Não é urgente agora, mas convém já pedir ou combinar:

- Âmbitos delegados do Graph: `Mail.Send`, `Calendars.ReadWrite`,
  `Files.ReadWrite`. Precisam de consentimento de administrador.
- Caixa de correio a usar para os envios, e que calendários partilhados
  contam (pergunta 4).
- Se a política do tenant permite envio "em nome de" outro utilizador.

## 5. O que nos devolvem

| Valor | Onde é usado |
|---|---|
| Tenant ID | `ENTRA_TENANT_ID` e `VITE_ENTRA_TENANT_ID` |
| Client ID da API | `ENTRA_CLIENT_ID` |
| Client ID da SPA | `VITE_ENTRA_CLIENT_ID` |
| Âmbito completo `api://<client-id-da-API>/access_as_user` | `ENTRA_REQUIRED_SCOPE` e `VITE_ENTRA_API_SCOPE` |

**Não enviem client secrets por email nem chat.** Para o login não é preciso
nenhum. Se um dia for preciso (Graph em modo aplicação), combina-se um canal
seguro.

---

## Notas internas (não enviar)

- Se a organização tiver políticas de acesso condicional ou MFA obrigatório,
  convém avisar o administrador. Não bloqueia nada, mas o primeiro login pode
  pedir passos extra.
- O ponto 4 é opcional para desbloquear o login. Só os pontos 1, 2 e 3 são
  precisos para isso.
- O domínio de staging (pergunta 25) ainda não existe. Enquanto não houver,
  basta o redirect `localhost` e acrescenta-se o outro depois, sem refazer
  nada.
