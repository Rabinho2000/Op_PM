import { useState } from "react";

// Logótipo Solcor, igual ao da plataforma original (solcor-gestao.html):
// imagem servida por solcor.pt, com o símbolo SVG como recurso quando a
// imagem não carrega (sem rede, demonstração offline). A imagem não é
// guardada no repositório.
export const SOLCOR_LOGO_URL = "https://www.solcor.pt/solcor-logo.png";

export function SolcorLogo({ height = 26 }: { height?: number }) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <span className="solcor-logo solcor-logo--fallback" style={{ height }}>
        <svg viewBox="0 0 24 24" fill="none" width={height - 4} height={height - 4} aria-hidden="true">
          <path
            d="M12 2v6M12 16v6M2 12h6M16 12h6M5 5l3 3M16 16l3 3M19 5l-3 3M8 16l-3 3"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          />
          <circle cx="12" cy="12" r="3.4" fill="currentColor" />
        </svg>
        <span className="solcor-logo__word">Solcor</span>
      </span>
    );
  }

  return (
    <img
      className="solcor-logo"
      src={SOLCOR_LOGO_URL}
      alt="Solcor"
      style={{ height }}
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
}
