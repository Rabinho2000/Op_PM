const EMPTY_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1" viewBox="0 0 1 1" aria-label="Esquema vazio"></svg>';

/**
 * The engine currently emits only these SVG primitives. Keep this list narrow:
 * the sanitizer is a boundary, not a general-purpose SVG normalizer.
 */
const ELEMENT_ATTRIBUTES: Readonly<Record<string, ReadonlySet<string>>> = {
  svg: new Set(["xmlns", "width", "height", "viewbox", "font-family", "role", "aria-label"]),
  title: new Set(),
  g: new Set(["transform"]),
  line: new Set(["x1", "y1", "x2", "y2", "stroke", "stroke-width", "stroke-dasharray"]),
  path: new Set(["d", "stroke", "stroke-width", "fill"]),
  rect: new Set(["x", "y", "width", "height", "rx", "fill", "stroke", "stroke-width", "stroke-dasharray"]),
  circle: new Set(["cx", "cy", "r", "fill", "stroke", "stroke-width"]),
  ellipse: new Set(["cx", "cy", "rx", "ry", "fill", "stroke", "stroke-width"]),
  text: new Set(["x", "y", "font-size", "fill", "font-weight", "text-anchor"]),
};

const LOCAL_URL = /^url\(\s*#[A-Za-z0-9_.:-]+\s*\)$/;
const UNSAFE_SCHEME = /(?:javascript|data):/i;

function normaliseUri(value: string): string {
  let decoded = value;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const next = decodeURIComponent(decoded);
      if (next === decoded) break;
      decoded = next;
    } catch {
      break;
    }
  }
  return decoded.replace(/[\u0000-\u0020\u007f]+/g, "").toLowerCase();
}

function hasUnsafeReference(value: string): boolean {
  const normalised = normaliseUri(value);
  if (UNSAFE_SCHEME.test(normalised)) return true;
  const urls = normalised.match(/url\([^)]*\)/gi) ?? [];
  return urls.some((url) => !LOCAL_URL.test(url));
}

function removeUnsafeNodes(root: Element): void {
  const nodes = [root, ...Array.from(root.querySelectorAll("*"))];
  for (const node of nodes) {
    const localName = (node.localName || node.tagName).toLowerCase();
    const allowedAttributes = ELEMENT_ATTRIBUTES[localName];
    if (!allowedAttributes) {
      if (node !== root) node.remove();
      continue;
    }

    for (const attribute of Array.from(node.attributes)) {
      const name = attribute.name.toLowerCase();
      const namespace = localName === "svg" && name === "xmlns";
      const allowedNamespace = namespace && attribute.value === "http://www.w3.org/2000/svg";
      if ((!allowedAttributes.has(name) && !allowedNamespace) || hasUnsafeReference(attribute.value)) {
        node.removeAttribute(attribute.name);
      }
    }
  }
}

/** Sanitises engine SVG output before it reaches the DOM. */
export function sanitizeSvg(markup: string): string {
  if (typeof markup !== "string" || !markup.trim() || typeof DOMParser === "undefined" || typeof XMLSerializer === "undefined") {
    return EMPTY_SVG;
  }

  try {
    // XML parsers reject NUL characters before we can inspect a javascript URI.
    const document = new DOMParser().parseFromString(markup.replace(/\u0000/g, ""), "image/svg+xml");
    const parserError = document.getElementsByTagName("parsererror")[0];
    const root = document.documentElement;
    if (parserError || !root || (root.localName || root.tagName).toLowerCase() !== "svg") return EMPTY_SVG;
    removeUnsafeNodes(root);
    return new XMLSerializer().serializeToString(root);
  } catch {
    return EMPTY_SVG;
  }
}

export { EMPTY_SVG };
