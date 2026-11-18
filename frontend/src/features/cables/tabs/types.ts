import type { CabosEngine, Result, State } from "../engine";
import type { CableStudyUpdater } from "../useCableStudy";

export interface CableTabProps {
  state: State;
  result: Result;
  engine: CabosEngine;
  readOnly: boolean;
  apply: (updater: CableStudyUpdater, options?: { debounce?: boolean }) => void;
}
