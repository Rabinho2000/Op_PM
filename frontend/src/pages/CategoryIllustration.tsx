import { useEffect, useState } from "react";
import { normalizeSearchText } from "../utils/text";

type Props = {
  category: string;
  imageUrl?: string | null;
};

function Artwork({ category }: { category: string }) {
  const key = normalizeSearchText(category).replace(/[^a-z0-9]/g, "");
  if (key.includes("painel") || key.includes("modulo")) {
    return <>
      <path className="inventory-illustration__accent" d="M36 18h88l10 56H26z" />
      <path d="M45 27h18l2 12H43zm24 0h18l2 12H71zm24 0h18l2 12H95zM40 45h20l2 13H38zm26 0h20l2 13H64zm26 0h20l2 13H90z" />
      <path d="m20 82 120 0M80 75v12m-18 0h36M39 88l-9 8m91-8 9 8" />
    </>;
  }
  if (key.includes("inversor")) {
    return <>
      <rect className="inventory-illustration__accent" x="49" y="12" width="62" height="77" rx="8" />
      <rect x="61" y="23" width="38" height="20" rx="3" />
      <path d="M69 32h22m-11-4v8M64 56h32m-32 9h20m-20 9h27M62 89v7m36-7v7" />
      <circle cx="101" cy="56" r="3" />
    </>;
  }
  if (key.includes("bateria")) {
    return <>
      <rect className="inventory-illustration__accent" x="32" y="26" width="96" height="58" rx="7" />
      <path d="M128 43h8v24h-8M48 42h22m-11-11v22m21 6h30m-30 8h21" />
      <path d="m91 35-9 17h11l-7 17 19-23H94l8-11z" />
    </>;
  }
  if (key.includes("estrutura")) {
    return <>
      <path className="inventory-illustration__accent" d="m27 69 48-42 58 42M30 69h103M46 69l-8 24m79-24 8 24M50 51h57M58 43h40M69 34h18" />
      <path d="m43 74 4 18m67-18-4 18M30 94h19m58 0h20" />
      <circle cx="75" cy="27" r="3" />
    </>;
  }
  if (key.includes("cabosdc")) {
    return <>
      <circle className="inventory-illustration__accent" cx="58" cy="53" r="27" />
      <circle cx="58" cy="53" r="17" />
      <circle cx="58" cy="53" r="7" />
      <path className="inventory-illustration__red" d="M79 68c14 17 25 18 38 9 8-6 11-14 11-24V38" />
      <path d="M82 39c15-15 29-12 36 0 5 9 3 17-1 23" />
      <path className="inventory-illustration__red" d="M121 31v-8m-5 0h10" />
      <path d="M114 60v9m-5 0h10" />
      <path d="M48 81h20m-10 0v8" />
    </>;
  }
  if (key.includes("cabosac")) {
    return <>
      <path className="inventory-illustration__accent" d="M37 26c0 25 10 45 28 45h18c15 0 22-10 22-23V35" />
      <path d="M44 26c0 19 9 34 23 34h16c8 0 12-5 12-12V35" />
      <path d="M30 17h15v12H30zM92 20h15v15H92zM34 17v-6m6 6v-6m55 13h-9m9 5h-9" />
      <path d="M100 71v17m-12 0h24m-18 0v8m12-8v8" />
    </>;
  }
  if (key.includes("protec") || key.includes("quadro")) {
    return <>
      <rect className="inventory-illustration__accent" x="31" y="15" width="98" height="75" rx="5" />
      <path d="M43 27h74M43 79h74" />
      <rect x="47" y="37" width="19" height="28" rx="3" /><rect x="72" y="37" width="19" height="28" rx="3" /><rect x="97" y="37" width="19" height="28" rx="3" />
      <path d="M56 43v12m25-12v12m25-12v12M52 96h56" />
    </>;
  }
  if (key.includes("conector")) {
    return <>
      <path className="inventory-illustration__accent" d="M26 43h38v15h-8v13h-9V58H26zM134 43H96v15h8v13h9V58h21z" />
      <path d="M64 47h32v8H64zM70 60h20m-16 7h12M38 43V32h14v11m56 0V32H94v11" />
      <path d="m35 32 4-8h12l4 8m39 0 4-8h12l4 8" />
    </>;
  }
  if (key.includes("monitorizacao") || key.includes("comunicacao")) {
    return <>
      <rect className="inventory-illustration__accent" x="38" y="51" width="84" height="39" rx="6" />
      <path d="M52 63h56m-56 9h39M80 51V37m-12 0a17 17 0 0 1 24 0m-33-8a30 30 0 0 1 42 0" />
      <circle cx="108" cy="78" r="3" /><path d="M80 90v6m-14 0h28" />
    </>;
  }
  if (key.includes("consumivel")) {
    return <>
      <path className="inventory-illustration__accent" d="M34 36h92v55H34z" />
      <path d="M34 47h92M48 36v-9h64v9m-63 28 18 0m-9-9v18m35-17 12 0m-6-6v12" />
      <path d="m63 82 5-9 5 9m16-1 5-6 5 6" />
    </>;
  }
  return <>
    <path className="inventory-illustration__accent" d="M31 37 80 15l49 22v52H31z" />
    <path d="M31 37h98M55 48h50m-50 9h35m-35 9h42M43 89V37m74 52V37" />
    <path d="M70 15v15m-8-8h16" />
  </>;
}

export default function CategoryIllustration({ category, imageUrl }: Props) {
  const [imageFailed, setImageFailed] = useState(false);
  useEffect(() => setImageFailed(false), [imageUrl]);

  if (imageUrl && !imageFailed) {
    return <img className="inventory-illustration inventory-illustration--photo" src={imageUrl} alt="" role="presentation" onError={() => setImageFailed(true)} />;
  }

  return (
    <svg
      className="inventory-illustration"
      data-testid="category-illustration"
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 160 110"
      fill="none"
      stroke="currentColor"
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <Artwork category={category} />
    </svg>
  );
}
