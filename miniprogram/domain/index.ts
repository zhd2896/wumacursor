/** Logical game nodes. UI coordinates and drawing segments are separate data. */
export const NODE_IDS = [
  'P01', 'P02', 'P03', 'P04', 'P05', 'P06', 'P07', 'P08', 'P09', 'P10',
  'P11', 'P12', 'P13', 'P14', 'P15', 'P16', 'P17', 'P18', 'P19', 'P20',
  'P21', 'P22', 'P23', 'P24', 'P25', 'P26', 'P27', 'P28', 'P29',
] as const;

export type NodeId = typeof NODE_IDS[number];
export interface Node { readonly id: NodeId }
export interface BoardLine { readonly id: string; readonly nodes: readonly NodeId[] }
export interface BoardTopology { readonly nodes: readonly Node[]; readonly lines: readonly BoardLine[] }
export interface BoardGraph {
  neighbors(id: NodeId): readonly NodeId[];
  areAdjacent(from: NodeId, to: NodeId): boolean;
}

/** The project's complete, authoritative set of straight lines. Order matters. */
export const STANDARD_TOPOLOGY: BoardTopology = {
  nodes: NODE_IDS.map(id => ({ id })),
  lines: [
    { id: 'H1', nodes: ['P01', 'P02', 'P03', 'P04', 'P05'] },
    { id: 'H2', nodes: ['P06', 'P07', 'P08', 'P09', 'P10'] },
    { id: 'H3', nodes: ['P11', 'P12', 'P13', 'P14', 'P15'] },
    { id: 'H4', nodes: ['P16', 'P17', 'P18', 'P19', 'P20'] },
    { id: 'H5', nodes: ['P21', 'P22', 'P23', 'P24', 'P25'] },
    { id: 'V1', nodes: ['P01', 'P06', 'P11', 'P16', 'P21'] },
    { id: 'V2', nodes: ['P02', 'P07', 'P12', 'P17', 'P22'] },
    { id: 'V3', nodes: ['P29', 'P27', 'P03', 'P08', 'P13', 'P18', 'P23'] },
    { id: 'V4', nodes: ['P04', 'P09', 'P14', 'P19', 'P24'] },
    { id: 'V5', nodes: ['P05', 'P10', 'P15', 'P20', 'P25'] },
    { id: 'D1', nodes: ['P01', 'P07', 'P13', 'P19', 'P25'] },
    { id: 'D2', nodes: ['P03', 'P09', 'P15'] },
    { id: 'D3', nodes: ['P11', 'P17', 'P23'] },
    { id: 'D4', nodes: ['P05', 'P09', 'P13', 'P17', 'P21'] },
    { id: 'D5', nodes: ['P03', 'P07', 'P11'] },
    { id: 'D6', nodes: ['P15', 'P19', 'P23'] },
    { id: 'T1', nodes: ['P26', 'P27', 'P28'] },
    { id: 'T2', nodes: ['P29', 'P26'] },
    { id: 'T3', nodes: ['P26', 'P03'] },
    { id: 'T4', nodes: ['P29', 'P28'] },
    { id: 'T5', nodes: ['P28', 'P03'] },
  ],
};

/** Build direct, undirected adjacency from consecutive nodes of each line. */
export function createBoardGraph(topology: BoardTopology): BoardGraph {
  const adjacency = new Map<NodeId, Set<NodeId>>(topology.nodes.map(node => [node.id, new Set<NodeId>()]));
  for (const line of topology.lines) {
    for (let index = 1; index < line.nodes.length; index++) {
      const from = line.nodes[index - 1];
      const to = line.nodes[index];
      adjacency.get(from)!.add(to);
      adjacency.get(to)!.add(from);
    }
  }
  return {
    neighbors: id => [...(adjacency.get(id) ?? [])],
    areAdjacent: (from, to) => adjacency.get(from)?.has(to) ?? false,
  };
}

export const STANDARD_GRAPH = createBoardGraph(STANDARD_TOPOLOGY);

/** Return a path only when both endpoints lie on the same declared line. */
export function findBoardLinePath(
  from: NodeId,
  to: NodeId,
  topology: BoardTopology,
): { lineId: string; nodes: NodeId[] } | null {
  if (from === to) return null;
  for (const line of topology.lines) {
    const start = line.nodes.indexOf(from);
    const end = line.nodes.indexOf(to);
    if (start < 0 || end < 0) continue;
    const nodes = start < end
      ? line.nodes.slice(start, end + 1)
      : line.nodes.slice(end, start + 1).reverse();
    return { lineId: line.id, nodes };
  }
  return null;
}

/** A supplied sequence must be contiguous within one declared line. */
export function isOnSingleBoardLine(path: readonly NodeId[], topology: BoardTopology): boolean {
  if (path.length < 2) return false;
  return topology.lines.some(line => {
    const start = line.nodes.indexOf(path[0]);
    if (start < 0) return false;
    return [1, -1].some(direction => path.every((id, index) => line.nodes[start + index * direction] === id));
  });
}

export type Player = 'A' | 'B';

/** The sole source of current board occupancy, including empty legal nodes. */
export interface BoardState {
  readonly occupancy: Readonly<Record<NodeId, Player | null>>;
}

export interface PlayerState {
  readonly reserve_count: number;
}

export type WinnerReason = 'CAPTURE_ALL' | 'TEMPLE_TRAP' | 'LONE_PIECE_IMMOBILIZED' | 'RESIGN';
export type GameStatus = 'PLAYING' | 'FINISHED';

export interface GameState {
  readonly board: BoardState;
  readonly players: Readonly<Record<Player, PlayerState>>;
  readonly first_player: Player;
  readonly current_player: Player;
  readonly game_status: GameStatus;
  readonly winner: Player | null;
  readonly winner_reason: WinnerReason | null;
}

export function finishGameByResign(state: GameState, resigningPlayer: Player): GameState {
  if (state.game_status === 'FINISHED') return state;
  const winner: Player = resigningPlayer === 'A' ? 'B' : 'A';
  return { ...state, game_status: 'FINISHED', winner, winner_reason: 'RESIGN' };
}

export function getPieceAt(board: BoardState, node: NodeId): Player | null {
  return board.occupancy[node];
}

export function getPlayerNodes(board: BoardState, player: Player): NodeId[] {
  return NODE_IDS.filter(node => board.occupancy[node] === player);
}

export function countPieces(board: BoardState, player: Player): number {
  return getPlayerNodes(board, player).length;
}

export function createInitialGameState(
  { firstPlayer = 'A' }: { firstPlayer?: Player } = {},
): GameState {
  const occupancy = {} as Record<NodeId, Player | null>;
  for (const node of NODE_IDS) occupancy[node] = null;
  for (const node of ['P01', 'P06', 'P11', 'P16', 'P21'] as const) occupancy[node] = 'A';
  for (const node of ['P05', 'P10', 'P15', 'P20', 'P25'] as const) occupancy[node] = 'B';

  return {
    board: { occupancy },
    players: { A: { reserve_count: 4 }, B: { reserve_count: 4 } },
    first_player: firstPlayer,
    current_player: firstPlayer,
    game_status: 'PLAYING',
    winner: null,
    winner_reason: null,
  };
}

export interface Move {
  readonly from: NodeId;
  readonly to: NodeId;
}

/** Scan declared lines only; a second shared line may be clear when the first is blocked. */
export function findClearBoardLinePath(
  board: BoardState,
  from: NodeId,
  to: NodeId,
  topology: BoardTopology = STANDARD_TOPOLOGY,
): { lineId: string; nodes: NodeId[] } | null {
  if (from === to) return null;
  for (const line of topology.lines) {
    const start = line.nodes.indexOf(from);
    const end = line.nodes.indexOf(to);
    if (start < 0 || end < 0) continue;
    const nodes = start < end
      ? line.nodes.slice(start, end + 1)
      : line.nodes.slice(end, start + 1).reverse();
    if (nodes.slice(1, -1).every(node => board.occupancy[node] === null)) {
      return { lineId: line.id, nodes };
    }
  }
  return null;
}

export function isLegalBasicMove(state: GameState, move: Move): boolean {
  return getPieceAt(state.board, move.from) === state.current_player
    && getPieceAt(state.board, move.to) === null
    && findClearBoardLinePath(state.board, move.from, move.to) !== null;
}

export function getLegalDestinations(state: GameState, from: NodeId): NodeId[] {
  return NODE_IDS.filter(to => isLegalBasicMove(state, { from, to }));
}

export function getLegalMoves(state: GameState): Move[] {
  const moves: Move[] = [];
  for (const from of getPlayerNodes(state.board, state.current_player)) {
    for (const to of getLegalDestinations(state, from)) moves.push({ from, to });
  }
  return moves;
}

/** Move only the piece; capture, reserves and turn switching belong to later stages. */
export function applyBasicMove(state: GameState, move: Move): GameState {
  if (!isLegalBasicMove(state, move)) throw new Error('Illegal basic move');
  return {
    ...state,
    board: {
      occupancy: {
        ...state.board.occupancy,
        [move.from]: null,
        [move.to]: state.current_player,
      },
    },
  };
}

export type BoardLineId = BoardLine['id'];
export type CaptureType = 'CLAMP' | 'CARRY';

export interface CapturePattern {
  readonly capture_type: CaptureType;
  readonly line_id: BoardLineId;
  readonly segment_nodes: readonly [NodeId, NodeId, NodeId];
  readonly attacker_nodes: readonly NodeId[];
  readonly captured_nodes: readonly NodeId[];
  readonly created_by_move: boolean;
}

/** Other pieces anywhere on the complete line invalidate this three-node pattern. */
export function checkLineExclusive(
  state: GameState,
  lineId: BoardLineId,
  patternNodes: readonly NodeId[],
): boolean {
  const line = STANDARD_TOPOLOGY.lines.find(item => item.id === lineId);
  const patternSet = new Set(patternNodes);
  if (!line || patternNodes.length !== 3 || patternSet.size !== 3) return false;
  if (!patternNodes.every(node => line.nodes.includes(node))) return false;
  return line.nodes.every(node => patternSet.has(node) || getPieceAt(state.board, node) === null);
}

/** Scan each declared line's consecutive three-node windows in stable line order. */
export function detectValidCapturePatterns(state: GameState, player: Player): CapturePattern[] {
  const opponent: Player = player === 'A' ? 'B' : 'A';
  const patterns: CapturePattern[] = [];
  for (const line of STANDARD_TOPOLOGY.lines) {
    for (let index = 0; index + 2 < line.nodes.length; index++) {
      const segment_nodes: [NodeId, NodeId, NodeId] = [
        line.nodes[index], line.nodes[index + 1], line.nodes[index + 2],
      ];
      const [left, middle, right] = segment_nodes.map(node => getPieceAt(state.board, node));
      let capture_type: CaptureType | null = null;
      if (left === player && middle === opponent && right === player) capture_type = 'CLAMP';
      if (left === opponent && middle === player && right === opponent) capture_type = 'CARRY';
      if (!capture_type || !checkLineExclusive(state, line.id, segment_nodes)) continue;
      patterns.push({
        capture_type,
        line_id: line.id,
        segment_nodes,
        attacker_nodes: capture_type === 'CLAMP'
          ? [segment_nodes[0], segment_nodes[2]] : [segment_nodes[1]],
        captured_nodes: capture_type === 'CLAMP'
          ? [segment_nodes[1]] : [segment_nodes[0], segment_nodes[2]],
        created_by_move: false,
      });
    }
  }
  return patterns;
}

function capturePatternIdentity(pattern: CapturePattern): string {
  return [
    pattern.capture_type,
    pattern.line_id,
    pattern.segment_nodes.join(','),
    pattern.captured_nodes.join(','),
  ].join('|');
}

/** A new pattern is valid after the move but absent before it. No piece-location shortcut. */
function subtractCapturePatterns(
  beforePatterns: readonly CapturePattern[],
  afterPatterns: readonly CapturePattern[],
): CapturePattern[] {
  const beforeIds = new Set(beforePatterns.map(capturePatternIdentity));
  return afterPatterns
    .filter(pattern => !beforeIds.has(capturePatternIdentity(pattern)))
    .map(pattern => ({ ...pattern, created_by_move: true }));
}

export function detectNewCapturePatterns(
  beforeState: GameState,
  afterMoveState: GameState,
  player: Player,
): CapturePattern[] {
  return subtractCapturePatterns(
    detectValidCapturePatterns(beforeState, player),
    detectValidCapturePatterns(afterMoveState, player),
  );
}

export type CaptureFailureReason =
  | 'NONE'
  | 'INSUFFICIENT_RESERVE'
  | 'TWO_PIECES_CANNOT_CARRY'
  | 'LAST_PIECE_CANNOT_CLAMP'
  | 'NOT_NEW_PATTERN'
  | 'LINE_HAS_EXTRA_PIECES';

export interface CaptureResult {
  readonly patterns: readonly CapturePattern[];
  readonly captured_nodes: readonly NodeId[];
  readonly replacement_nodes: readonly NodeId[];
  readonly required_reserve: number;
  readonly reserve_used: number;
  readonly was_applied: boolean;
  readonly failure_reason: CaptureFailureReason;
}

/** Filter each pattern using the opponent's on-board count after the normal move. */
export function filterCapturePatterns(
  afterMoveState: GameState,
  attacker: Player,
  patterns: readonly CapturePattern[],
): CapturePattern[] {
  const opponent: Player = attacker === 'A' ? 'B' : 'A';
  const opponentCount = countPieces(afterMoveState.board, opponent);
  return patterns.filter(pattern =>
    !(opponentCount === 2 && pattern.capture_type === 'CARRY')
    && !(opponentCount === 1 && pattern.capture_type === 'CLAMP')
  );
}

/** Resolve the supplied new patterns once; the normal move has already happened. */
export function resolveCaptures(
  afterMoveState: GameState,
  attacker: Player,
  newPatterns: readonly CapturePattern[],
): { state: GameState; result: CaptureResult } {
  const eligiblePatterns = filterCapturePatterns(afterMoveState, attacker, newPatterns);
  if (eligiblePatterns.length === 0) {
    const opponent: Player = attacker === 'A' ? 'B' : 'A';
    const opponentCount = countPieces(afterMoveState.board, opponent);
    let failure_reason: CaptureFailureReason = 'NONE';
    if (newPatterns.length > 0 && opponentCount === 2) failure_reason = 'TWO_PIECES_CANNOT_CARRY';
    if (newPatterns.length > 0 && opponentCount === 1) failure_reason = 'LAST_PIECE_CANNOT_CLAMP';
    return {
      state: afterMoveState,
      result: {
        patterns: [], captured_nodes: [], replacement_nodes: [],
        required_reserve: 0, reserve_used: 0, was_applied: false, failure_reason,
      },
    };
  }

  const capturedNodes: NodeId[] = [];
  const seen = new Set<NodeId>();
  for (const pattern of eligiblePatterns) {
    for (const node of pattern.captured_nodes) {
      if (!seen.has(node)) {
        seen.add(node);
        capturedNodes.push(node);
      }
    }
  }
  const requiredReserve = capturedNodes.length;
  const opponent: Player = attacker === 'A' ? 'B' : 'A';
  if (requiredReserve === 0 || capturedNodes.some(node => getPieceAt(afterMoveState.board, node) !== opponent)) {
    throw new Error('Capture pattern contains a node not occupied by the opponent');
  }
  if (afterMoveState.players[attacker].reserve_count < requiredReserve) {
    return {
      state: afterMoveState,
      result: {
        patterns: eligiblePatterns, captured_nodes: [], replacement_nodes: [],
        required_reserve: requiredReserve, reserve_used: 0, was_applied: false,
        failure_reason: 'INSUFFICIENT_RESERVE',
      },
    };
  }

  const occupancy = { ...afterMoveState.board.occupancy };
  for (const node of capturedNodes) occupancy[node] = attacker;
  return {
    state: {
      ...afterMoveState,
      board: { occupancy },
      players: {
        ...afterMoveState.players,
        [attacker]: { reserve_count: afterMoveState.players[attacker].reserve_count - requiredReserve },
      },
    },
    result: {
      patterns: eligiblePatterns,
      captured_nodes: capturedNodes,
      replacement_nodes: [...capturedNodes],
      required_reserve: requiredReserve,
      reserve_used: requiredReserve,
      was_applied: true,
      failure_reason: 'NONE',
    },
  };
}

/** P03 is the entrance on the main board, not a temple interior node. */
export const TEMPLE_NODES: readonly NodeId[] = ['P26', 'P27', 'P28', 'P29'];

export interface WinnerResult {
  readonly winner: Player;
  readonly reason: WinnerReason;
}

/** Call only after the capture stage has completed or been cancelled. */
export function checkCaptureAll(state: GameState, attacker: Player): WinnerResult | null {
  const opponent: Player = attacker === 'A' ? 'B' : 'A';
  return countPieces(state.board, opponent) === 0
    ? { winner: attacker, reason: 'CAPTURE_ALL' }
    : null;
}

/** Only the player whose turn has begun can lose for an immobilized lone piece. */
export function checkLonePieceImmobilized(state: GameState): WinnerResult | null {
  if (state.game_status !== 'PLAYING') return null;
  const trappedPlayer = state.current_player;
  const nodes = getPlayerNodes(state.board, trappedPlayer);
  if (nodes.length !== 1 || getLegalMoves(state).length !== 0) return null;
  return {
    winner: trappedPlayer === 'A' ? 'B' : 'A',
    reason: TEMPLE_NODES.includes(nodes[0]) ? 'TEMPLE_TRAP' : 'LONE_PIECE_IMMOBILIZED',
  };
}

export function isTempleTrapped(state: GameState, player: Player): boolean {
  return state.current_player === player
    && checkLonePieceImmobilized(state)?.reason === 'TEMPLE_TRAP';
}

/** Preserve the temple-only query for existing callers. */
export function checkTempleTrap(state: GameState): WinnerResult | null {
  const result = checkLonePieceImmobilized(state);
  return result?.reason === 'TEMPLE_TRAP' ? result : null;
}

/** One real turn, composed from the existing move, pattern and capture rules. */
export interface TurnResult {
  readonly move: Move;
  readonly before_state: GameState;
  readonly board_before: BoardState;
  readonly board_after: BoardState;
  readonly reserve_before: Readonly<Record<Player, number>>;
  readonly reserve_after: Readonly<Record<Player, number>>;
  /** Kept for callers of the Phase 7 executeTurn API. */
  readonly capture: CaptureResult;
  readonly captures: CaptureResult;
  readonly winner: Player | null;
  readonly winner_reason: WinnerReason | null;
  readonly game_over: boolean;
  readonly state: GameState;
}

export function executeTurn(
  state: GameState,
  move: Move,
): TurnResult {
  return executeTurnWithPatterns(state, move, null);
}

/** Execute sibling turns with their common pre-move patterns calculated once. */
export function executeTurns(state: GameState, moves: readonly Move[]): TurnResult[] {
  if (moves.length === 0) return [];
  if (state.game_status === 'FINISHED') throw new Error('Game already finished');
  const beforePatterns = detectValidCapturePatterns(state, state.current_player);
  return moves.map(move => executeTurnWithPatterns(state, move, beforePatterns));
}

function executeTurnWithPatterns(
  state: GameState,
  move: Move,
  sharedBeforePatterns: readonly CapturePattern[] | null,
): TurnResult {
  if (state.game_status === 'FINISHED') throw new Error('Game already finished');
  if (!isLegalBasicMove(state, move)) throw new Error('Illegal basic move');

  const beforeState: GameState = {
    ...state,
    board: { occupancy: { ...state.board.occupancy } },
    players: {
      A: { reserve_count: state.players.A.reserve_count },
      B: { reserve_count: state.players.B.reserve_count },
    },
  };
  const attacker = beforeState.current_player;
  const beforePatterns = sharedBeforePatterns ?? detectValidCapturePatterns(beforeState, attacker);
  const afterMove = applyBasicMove(beforeState, move);
  const afterPatterns = detectValidCapturePatterns(afterMove, attacker);
  const newPatterns = subtractCapturePatterns(beforePatterns, afterPatterns);
  const resolution = resolveCaptures(afterMove, attacker, newPatterns);

  const captureAll = checkCaptureAll(resolution.state, attacker);
  let finalState: GameState;
  if (captureAll) {
    finalState = {
      ...resolution.state,
      game_status: 'FINISHED',
      winner: captureAll.winner,
      winner_reason: captureAll.reason,
    };
  } else {
    const nextPlayer: Player = attacker === 'A' ? 'B' : 'A';
    const afterSwitch: GameState = { ...resolution.state, current_player: nextPlayer };
    const immobilized = checkLonePieceImmobilized(afterSwitch);
    finalState = immobilized
      ? {
        ...afterSwitch,
        game_status: 'FINISHED',
        winner: immobilized.winner,
        winner_reason: immobilized.reason,
      }
      : afterSwitch;
  }

  return {
    move: { from: move.from, to: move.to },
    before_state: beforeState,
    board_before: beforeState.board,
    board_after: finalState.board,
    reserve_before: { A: beforeState.players.A.reserve_count, B: beforeState.players.B.reserve_count },
    reserve_after: { A: finalState.players.A.reserve_count, B: finalState.players.B.reserve_count },
    capture: resolution.result,
    captures: resolution.result,
    winner: finalState.winner,
    winner_reason: finalState.winner_reason,
    game_over: finalState.game_status === 'FINISHED',
    state: finalState,
  };
}

/** The shared rules entry point for future UI, AI and API callers. */
const getPlayableMoves = (state: GameState): Move[] =>
  state.game_status === 'PLAYING' ? getLegalMoves(state) : [];

/** Query a hypothetical turn for either player without changing the supplied state. */
const getPlayableMovesForPlayer = (state: GameState, player: Player): Move[] =>
  getPlayableMoves(state.current_player === player ? state : { ...state, current_player: player });

const getStandardLinePath = (from: NodeId, to: NodeId) =>
  findBoardLinePath(from, to, STANDARD_TOPOLOGY);

export const RuleEngine = {
  initializeGame: createInitialGameState,
  validateMove: (state: GameState, move: Move): boolean =>
    state.game_status === 'PLAYING' && isLegalBasicMove(state, move),
  getLegalMoves: getPlayableMoves,
  getAllLegalMoves: getPlayableMoves,
  getAllLegalMovesForPlayer: getPlayableMovesForPlayer,
  findCommonLine: getStandardLinePath,
  getPath: getStandardLinePath,
  isPathClear: (board: BoardState, from: NodeId, to: NodeId): boolean =>
    findClearBoardLinePath(board, from, to) !== null,
  applyNormalMove: applyBasicMove,
  detectAllCapturePatterns: detectValidCapturePatterns,
  detectClampPatterns: (state: GameState, player: Player): CapturePattern[] =>
    detectValidCapturePatterns(state, player).filter(pattern => pattern.capture_type === 'CLAMP'),
  detectCarryPatterns: (state: GameState, player: Player): CapturePattern[] =>
    detectValidCapturePatterns(state, player).filter(pattern => pattern.capture_type === 'CARRY'),
  isContinuousThree: (nodes: readonly NodeId[]): boolean =>
    nodes.length === 3 && isOnSingleBoardLine(nodes, STANDARD_TOPOLOGY),
  checkLineExclusive,
  detectNewCapturePatterns,
  filterNewPatterns: detectNewCapturePatterns,
  filterSpecialCaptureRules: filterCapturePatterns,
  resolveCapture: resolveCaptures,
  checkCaptureAll,
  checkTempleTrap,
  checkLonePieceImmobilized,
  checkWinner: (state: GameState): WinnerResult | null =>
    state.game_status === 'FINISHED' && state.winner !== null && state.winner_reason !== null
      ? { winner: state.winner, reason: state.winner_reason }
      : null,
  executeTurn,
  executeTurns,
} as const;
