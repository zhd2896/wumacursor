import { NODE_IDS, RuleEngine, finishGameByResign } from '../../domain/index';
import type { GameState, Move, NodeId, Player, TurnResult } from '../../domain/index';
import type { BoardState as BoardView } from '../../types/domain';
import { mapGameStateToView } from './game-state-mapper';

/** GameState is the sole authority; the other fields only describe the current UI interaction. */
export interface LocalGameSession {
  readonly initialState: GameState;
  readonly gameState: GameState;
  readonly turnHistory: readonly TurnResult[];
  readonly selectedNode: NodeId | null;
  readonly legalDestinations: readonly NodeId[];
  readonly lastMove: Move | null;
}

export interface LocalTapResult {
  readonly session: LocalGameSession;
  readonly turn: TurnResult | null;
  readonly error: string | null;
}

export function createLocalGameSession(firstPlayer: Player = 'A'): LocalGameSession {
  const initialState = RuleEngine.initializeGame({ firstPlayer });
  return {
    initialState,
    gameState: initialState,
    turnHistory: [],
    selectedNode: null,
    legalDestinations: [],
    lastMove: null,
  };
}

export function resignLocalGame(session: LocalGameSession, resigningPlayer: Player): LocalGameSession | null {
  if (session.gameState.game_status === 'FINISHED') return null;
  return { ...session, gameState: finishGameByResign(session.gameState, resigningPlayer),
    selectedNode: null, legalDestinations: [] };
}

export function undoLocalGame(session: LocalGameSession): LocalGameSession | null {
  if (session.gameState.game_status === 'FINISHED' || session.turnHistory.length === 0) return null;
  const turnHistory = session.turnHistory.slice(0, -1);
  const gameState = turnHistory.length > 0
    ? turnHistory[turnHistory.length - 1].state
    : session.initialState;
  const lastMove = turnHistory.length > 0 ? turnHistory[turnHistory.length - 1].move : null;
  return {
    ...session,
    gameState,
    turnHistory,
    selectedNode: null,
    legalDestinations: [],
    lastMove,
  };
}

export function getLocalBoardView(session: LocalGameSession): BoardView {
  return mapGameStateToView(session.gameState, {
    selectedNode: session.selectedNode,
    legalTargets: session.legalDestinations,
    lastMove: session.lastMove,
  }).board;
}

export function tapLocalGameNode(session: LocalGameSession, id: string): LocalTapResult {
  const unchanged: LocalTapResult = { session, turn: null, error: null };
  if (session.gameState.game_status === 'FINISHED') return unchanged;
  if (!NODE_IDS.includes(id as NodeId)) return unchanged;

  const nodeId = id as NodeId;
  const player = session.gameState.board.occupancy[nodeId];
  if (player === session.gameState.current_player) {
    return {
      session: {
        ...session,
        selectedNode: nodeId,
        legalDestinations: RuleEngine.getAllLegalMoves(session.gameState)
          .filter(move => move.from === nodeId)
          .map(move => move.to),
      },
      turn: null,
      error: null,
    };
  }

  if (session.selectedNode === null || !session.legalDestinations.includes(nodeId)) return unchanged;
  try {
    const turn = RuleEngine.executeTurn(session.gameState, { from: session.selectedNode, to: nodeId });
    return {
      session: {
        ...session,
        gameState: turn.state,
        turnHistory: [...session.turnHistory, turn],
        selectedNode: null,
        legalDestinations: [],
        lastMove: turn.move,
      },
      turn,
      error: null,
    };
  } catch {
    return { session, turn: null, error: '落子失败，请重新选择棋子' };
  }
}
