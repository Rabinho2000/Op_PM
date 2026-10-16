import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ThemeProvider } from "../theme/ThemeContext";
import { setPreference, THEME_STORAGE_KEY } from "../theme/theme";
import ThemeToggle from "./ThemeToggle";

afterEach(() => {
  localStorage.clear();
});

describe("ThemeToggle", () => {
  it("expõe um nome acessível e permite escolher o tema pelo teclado", () => {
    setPreference("system");
    render(
      <ThemeProvider>
        <ThemeToggle accessibleName="Aparência para teste" />
      </ThemeProvider>,
    );

    const selector = screen.getByRole("combobox", { name: "Aparência para teste" });
    selector.focus();
    expect(document.activeElement).toBe(selector);
    fireEvent.keyDown(selector, { key: "ArrowDown" });
    fireEvent.change(selector, { target: { value: "dark" } });

    expect(selector).toHaveValue("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("funciona e altera o tema quando não está dentro de ThemeProvider", () => {
    setPreference("system");
    render(<ThemeToggle accessibleName="Aparência sem provider" />);

    const selector = screen.getByRole("combobox", { name: "Aparência sem provider" });
    fireEvent.change(selector, { target: { value: "dark" } });

    expect(selector).toHaveValue("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
