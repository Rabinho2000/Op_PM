import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from "react";
import {
  getThemeState,
  setPreference as savePreference,
  subscribeTheme,
  ThemePreference,
  ThemeState,
} from "./theme";

interface ThemeContextValue extends ThemeState {
  setPreference: (preference: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState(getThemeState);

  useEffect(() => subscribeTheme(setState), []);

  const value = useMemo<ThemeContextValue>(
    () => ({ ...state, setPreference: savePreference }),
    [state],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  const [localState, setLocalState] = useState(getThemeState);

  useEffect(() => {
    if (context) return undefined;
    setLocalState(getThemeState());
    return subscribeTheme(setLocalState);
  }, [Boolean(context)]);

  const localValue = useMemo<ThemeContextValue>(
    () => ({ ...localState, setPreference: savePreference }),
    [localState],
  );

  return context ?? localValue;
}
