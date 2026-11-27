// Cor determinística por pessoa para os avatares do Planeamento: a mesma
// pessoa tem sempre o mesmo matiz, em qualquer vista, sem guardar nada.
// Os matizes estão afastados entre si; luminosidade e saturação são fixas no
// CSS (claro/escuro), pelo que o contraste não depende do matiz escolhido.
export const PERSON_HUES = [8, 28, 48, 92, 150, 172, 196, 214, 240, 266, 292, 330] as const;

function hashString(value: string): number {
  // FNV-1a de 32 bits: simples, estável entre sessões e sem dependências.
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash >>> 0;
}

/** Matiz (0–360) estável para uma pessoa; usar o id e, na falta dele, o nome. */
export function personHue(key: string): number {
  return PERSON_HUES[hashString(key.trim().toLowerCase()) % PERSON_HUES.length];
}
