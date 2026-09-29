import { NODE_IDS } from '../../domain/index';
import type { CaptureResult, GameState, Move, NodeId, Player } from '../../domain/index';
import { boardLines, boardNodes } from '../../mock/game';
import type { BoardPiece, BoardState as BoardView } from '../../types/domain';

export interface BoardInteraction {
  readonly selectedNode: NodeId | null;
  readonly legalTargets: readonly NodeId[];
  readonly lastMove: Move | null;
  readonly lastCapture?: CaptureResult | null;
}

export interface GameViewModel {
  readonly board: BoardView;
  readonly currentPlayer: Player;
  readonly reserve: Readonly<Record<Player, number>>;
  readonly gameOver: boolean;
  readonly winner: Player | null;
  readonly winnerMessage: string;
}

const reasonMessages: Readonly<Record<NonNullable<GameState['winner_reason']>, string>> = {
  CAPTURE_ALL: '对方棋子已全部被吃',
  TEMPLE_TRAP: '对方孤棋被困于庙宇',
  LONE_PIECE_IMMOBILIZED: '对方孤棋无路可走',
  RESIGN: '对方认输',
};

export function mapGameStateToView(
  state: GameState,
  interaction: BoardInteraction = { selectedNode: null, legalTargets: [], lastMove: null },
): GameViewModel {
  const targets = new Set(interaction.legalTargets);
  const captured = new Set(interaction.lastCapture?.was_applied ? interaction.lastCapture.captured_nodes : []);
  const replacement = new Set(interaction.lastCapture?.was_applied ? interaction.lastCapture.replacement_nodes : []);
  const nodes = boardNodes.map(node => ({ ...node, legalTarget: targets.has(node.id as NodeId),
    captured: captured.has(node.id as NodeId), replacement: replacement.has(node.id as NodeId) }));
  const coordinates = new Map(boardNodes.map(node => [node.id, node]));
  const pieces: BoardPiece[] = [];
  for (const nodeId of NODE_IDS) {
    const player = state.board.occupancy[nodeId];
    if (player === null) continue;
    const point = coordinates.get(nodeId)!;
    pieces.push({
      id: `${player}-${nodeId}`, nodeId, x: point.x, y: point.y,
      side: player === 'A' ? 'black' : 'red',
      state: interaction.lastMove?.to === nodeId ? 'lastMove' : 'normal',
    });
  }
  return {
    board: { nodes, lines: boardLines, pieces,
      ...(interaction.lastMove ? { recommendedFrom: interaction.lastMove.from,
        recommendedTo: interaction.lastMove.to } : {}),
      ...(interaction.selectedNode ? { selectedId: interaction.selectedNode } : {}) },
    currentPlayer: state.current_player,
    reserve: { A: state.players.A.reserve_count, B: state.players.B.reserve_count },
    gameOver: state.game_status === 'FINISHED',
    winner: state.winner,
    winnerMessage: state.winner_reason ? reasonMessages[state.winner_reason] : '',
  };
}
