import { useMemo } from "react";
import { Card, EmptyState } from "../../../components/ui";
import { useExportRunner } from "../download";
import type { BoardView } from "../engine";
import { BoardCard } from "../boards/BoardCard";
import type { CableTabProps } from "./types";

export default function QuadrosTab({ state, result, engine }: CableTabProps) {
  const runner = useExportRunner();
  const boards = useMemo<BoardView[]>(() => {
    try {
      return engine.views.boards(state, result)?.boards ?? [];
    } catch {
      return [];
    }
  }, [engine, result, state]);

  return (
    <div className="cable-tab cable-tab--boards">
      <Card
        title="Sugestão de quadros"
        icon="folder"
        actions={boards.length > 0 ? (
          <button type="button" className="btn btn--sm" onClick={() => void runner.run(() => engine.exports.bomPdf(state, result))} disabled={runner.isGenerating}>
            {runner.isGenerating ? runner.label : "Orçamento PDF"}
          </button>
        ) : undefined}
      >
        <p className="muted cable-tab__hint">
          Para cada quadro: a aparelhagem, os cabos que lá entram e a envolvente mínima onde tudo cabe com espaço para curvar e ligar os cabos. O raio de curvatura usado é ≈ 10 × Ø (cabos rígidos XV/LXV; os flexíveis RV-K/RZ1-K admitem cerca de metade); diâmetros e capacidade dos bornes são aproximados e devem ser confirmados no catálogo.
        </p>
        {boards.length === 0 ? (
          <EmptyState title="Sem quadros para sugerir" text="Ligue os inversores a um quadro no separador Cabos AC para ver a composição." icon="folder" />
        ) : (
          <div className="cable-boards-list">{boards.map((board, index) => <BoardCard key={`${board.node}-${index}`} board={board} />)}</div>
        )}
      </Card>
    </div>
  );
}
