import { describe, expect, it } from "vitest";
import { PERSON_HUES, personHue } from "./personColor";

describe("personHue", () => {
  it("devolve sempre o mesmo matiz para a mesma pessoa", () => {
    expect(personHue("p-pm")).toBe(personHue("p-pm"));
    expect(personHue("  P-PM ")).toBe(personHue("p-pm"));
  });

  it("só usa matizes da paleta e distribui pessoas diferentes", () => {
    const hues = new Set<number>();
    for (let index = 0; index < 200; index += 1) {
      const hue = personHue(`pessoa-${index}`);
      expect(PERSON_HUES).toContain(hue);
      hues.add(hue);
    }
    expect(hues.size).toBeGreaterThanOrEqual(PERSON_HUES.length - 2);
  });
});
