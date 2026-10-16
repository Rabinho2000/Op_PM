import { useId } from "react";
import { useTheme } from "../theme/ThemeContext";
import { ThemePreference } from "../theme/theme";

export default function ThemeToggle({
  accessibleName,
  className = "",
}: {
  accessibleName: string;
  className?: string;
}) {
  const id = useId();
  const { preference, setPreference } = useTheme();

  return (
    <label className={`theme-toggle ${className}`} htmlFor={id}>
      <span>Aparência</span>
      <select
        id={id}
        aria-label={accessibleName}
        value={preference}
        onChange={(event) => setPreference(event.currentTarget.value as ThemePreference)}
      >
        <option value="light">Claro</option>
        <option value="dark">Escuro</option>
        <option value="system">Sistema</option>
      </select>
    </label>
  );
}
