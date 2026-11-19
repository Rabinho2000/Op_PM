import { Card, EmptyState, LoadingState } from "../../../components/ui";
import { useExportRunner } from "../download";
import { BoardCard } from "../boards/BoardCard";
import type { CableTabProps } from "./types";
import { useEngineValue } from "../useEngineValue";

export default function QuadrosTab({ state, result, engine }: CableTabProps) {
  const runner = useExportRunner();
  const view = useEngineValue(async () => {
    const boards = (await engine.views.boards(state, result))?.boards ?? [];
    const fronts = await Promise.all(boards.map(async (board) => {
      try {
        return typeof engine.views.boardFront === "function" ? await engine.views.boardFront(state, result, board.node) : null;
      } catch {
        return null;
      }
    }));
    return { boards, fronts };
  }, [engine, result, state]);
  const boards = view.value?.boards ?? [];
  const fronts = view.value?.fronts ?? [];

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
        {!view.value && view.pending ? (
          <LoadingState label="A calcular os quadros…" rows={3} />
        ) : boards.length === 0 ? (
          <EmptyState title="Sem quadros para sugerir" text="Ligue os inversores a um quadro no separador Cabos AC para ver a composição." icon="folder" />
        ) : (
          <div className="cable-boards-list">{boards.map((board, index) => <BoardCard key={`${board.node}-${index}`} board={board} frontSvg={fronts[index] ?? null} />)}</div>
        )}
      </Card>
    </div>
  );
}
