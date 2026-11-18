import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import CategoryIllustration from "./CategoryIllustration";

describe("ilustração de categoria", () => {
  it("desenha uma ilustração acessível apenas pelo nome visível", () => {
    render(<CategoryIllustration category="Cabos DC" />);
    expect(screen.getByTestId("category-illustration")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByTestId("category-illustration").querySelectorAll("path,circle,rect").length).toBeGreaterThan(0);
  });

  it("usa uma imagem personalizada e volta à ilustração se ela falhar", () => {
    render(<CategoryIllustration category="Inversores" imageUrl="/custom/inverter.jpg" />);
    const image = screen.getByRole("presentation");
    expect(image).toHaveAttribute("src", "/custom/inverter.jpg");
    fireEvent.error(image);
    expect(screen.getByTestId("category-illustration")).toBeInTheDocument();
  });
});
