import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import { NODE_IDS, RuleEngine, createInitialGameState } from '../miniprogram/domain/index.ts';
import { boardNodes, boardLines, initialPieces } from '../miniprogram/mock/game.ts';

// Node's test runner needs help resolving the extensionless imports used by WeChat.
registerHooks({
  resolve(specifier, context, nextResolve) {
    try {
      return nextResolve(specifier, context);
    } catch (error) {
      if (specifier.startsWith('.') && context.parentURL &&
          (error as NodeJS.ErrnoException).code === 'ERR_MODULE_NOT_FOUND') {
        const tsUrl = new URL(`${specifier}.ts`, context.parentURL);
        if (existsSync(tsUrl)) return nextResolve(tsUrl.href, context);
      }
      throw error;
    }
  },
});

const {
  createLocalGameSession,
  getLocalBoardView,
  resignLocalGame,
  tapLocalGameNode,
  undoLocalGame,
} = await import('../miniprogram/pages/game/local-game.ts');

function sessionWithPieces(
  pieces: Record<string, 'A' | 'B'>,
  { reserveA = 4, reserveB = 4 } = {},
) {
  const session = createLocalGameSession();
  const occupancy = { ...session.gameState.board.occupancy };
  for (const id of NODE_IDS) occupancy[id] = null;
  for (const [id, player] of Object.entries(pieces)) {
    occupancy[id as typeof NODE_IDS[number]] = player;
  }
  return {
    ...session,
    gameState: {
      ...session.gameState,
      board: { occupancy },
      players: { A: { reserve_count: reserveA }, B: { reserve_count: reserveB } },
    },
  };
}

test('visual nodes use canonical IDs while preserving the existing physical layout', () => {
  assert.deepEqual(new Set(boardNodes.map(node => node.id)), new Set(NODE_IDS));
  assert.equal(boardNodes.find(node => node.id === 'P01')?.y, 35);
  assert.equal(boardNodes.find(node => node.id === 'P25')?.y, 81);
  assert.equal(boardNodes.find(node => node.id === 'P29')?.y, 12);
  assert.equal(boardNodes.find(node => node.id === 'P26')?.x, 36.7);
  assert.equal(boardNodes.find(node => node.id === 'P28')?.x, 63.3);
  assert.equal(boardNodes.find(node => node.id === 'P27')?.visualOnly, undefined);
  assert.ok(boardLines.length > 0);
  assert.deepEqual(initialPieces.filter(piece => piece.side === 'black').map(piece => piece.nodeId),
    ['P01', 'P06', 'P11', 'P16', 'P21']);
});

test('local initialization and board pieces derive from the real GameState', () => {
  const session = createLocalGameSession();
  const board = getLocalBoardView(session);
  assert.deepEqual(session.gameState, createInitialGameState());
  assert.equal(session.gameState.current_player, 'A');
  assert.equal(session.gameState.players.A.reserve_count, 4);
  assert.equal(session.gameState.players.B.reserve_count, 4);
  assert.deepEqual(board.pieces.filter(piece => piece.side === 'black').map(piece => piece.nodeId),
    ['P01', 'P06', 'P11', 'P16', 'P21']);
  assert.deepEqual(board.pieces.filter(piece => piece.side === 'red').map(piece => piece.nodeId),
    ['P05', 'P10', 'P15', 'P20', 'P25']);
  assert.equal(board.pieces.length, 10);
  assert.equal(board.pieces.some(piece => ['P26', 'P27', 'P28', 'P29'].includes(piece.nodeId)), false);
  assert.equal(createLocalGameSession('B').gameState.current_player, 'B');
});

test('only the current player can select and legal targets come from RuleEngine', () => {
  const initial = createLocalGameSession();
  assert.equal(tapLocalGameNode(initial, 'P05').session, initial);
  assert.equal(tapLocalGameNode(initial, 'P02').session, initial);
  const selected = tapLocalGameNode(initial, 'P01').session;
  assert.equal(selected.selectedNode, 'P01');
  const expected = RuleEngine.getAllLegalMoves(initial.gameState)
    .filter(move => move.from === 'P01').map(move => move.to);
  assert.deepEqual(selected.legalDestinations, expected);
  const highlighted = getLocalBoardView(selected).nodes
    .filter(node => node.legalTarget).map(node => node.id);
  assert.deepEqual(highlighted, expected);
  assert.equal(getLocalBoardView(selected).selectedId, 'P01');
});

test('selecting another friendly piece switches selection and illegal empty nodes do not move', () => {
  const initial = createLocalGameSession();
  const first = tapLocalGameNode(initial, 'P01').session;
  const switched = tapLocalGameNode(first, 'P06').session;
  assert.equal(switched.selectedNode, 'P06');
  assert.deepEqual(switched.legalDestinations, RuleEngine.getAllLegalMoves(switched.gameState)
    .filter(move => move.from === 'P06').map(move => move.to));
  const illegal = tapLocalGameNode(first, 'P08');
  assert.equal(illegal.turn, null);
  assert.equal(illegal.session, first);
  assert.equal(illegal.session.gameState.board.occupancy.P01, 'A');
  assert.equal(illegal.session.gameState.board.occupancy.P08, null);
});

test('a legal target executes one real turn and B can take the next turn', () => {
  const initial = createLocalGameSession();
  const selected = tapLocalGameNode(initial, 'P01').session;
  const played = tapLocalGameNode(selected, 'P02');
  assert.deepEqual(played.turn?.move, { from: 'P01', to: 'P02' });
  assert.equal(played.session.gameState, played.turn?.state);
  assert.equal(played.session.gameState.board.occupancy.P01, null);
  assert.equal(played.session.gameState.board.occupancy.P02, 'A');
  assert.equal(played.session.gameState.current_player, 'B');
  assert.equal(played.session.selectedNode, null);
  assert.deepEqual(played.session.legalDestinations, []);
  assert.deepEqual(played.session.lastMove, played.turn?.move);
  const bSelected = tapLocalGameNode(played.session, 'P05').session;
  assert.equal(bSelected.selectedNode, 'P05');
  assert.ok(bSelected.legalDestinations.includes('P04'));
  const bPlayed = tapLocalGameNode(bSelected, 'P04');
  assert.equal(bPlayed.session.gameState.board.occupancy.P04, 'B');
  assert.equal(bPlayed.session.gameState.current_player, 'A');
});

test('CLAMP and CARRY update every displayed piece and reserve from TurnResult.state', () => {
  const clamp = sessionWithPieces({ P01: 'A', P02: 'B', P04: 'A', P29: 'B' });
  const clampTurn = tapLocalGameNode(tapLocalGameNode(clamp, 'P04').session, 'P03');
  assert.deepEqual(clampTurn.turn?.captures.captured_nodes, ['P02']);
  assert.equal(clampTurn.session.gameState.players.A.reserve_count, 3);
  assert.equal(getLocalBoardView(clampTurn.session).pieces.find(piece => piece.nodeId === 'P02')?.side, 'black');

  const carry = sessionWithPieces({ P01: 'B', P03: 'B', P29: 'B', P07: 'A' });
  const carryTurn = tapLocalGameNode(tapLocalGameNode(carry, 'P07').session, 'P02');
  assert.deepEqual(carryTurn.turn?.captures.captured_nodes, ['P01', 'P03']);
  assert.equal(carryTurn.session.gameState.players.A.reserve_count, 2);
  for (const id of ['P01', 'P03']) {
    assert.equal(getLocalBoardView(carryTurn.session).pieces.find(piece => piece.nodeId === id)?.side, 'black');
  }
});

test('multi-capture and insufficient reserve render the engine result atomically', () => {
  const multi = sessionWithPieces({ P11: 'A', P12: 'B', P08: 'B', P18: 'B', P19: 'A', P05: 'B' });
  const multiTurn = tapLocalGameNode(tapLocalGameNode(multi, 'P19').session, 'P13');
  assert.deepEqual(multiTurn.turn?.captures.captured_nodes, ['P12', 'P08', 'P18']);
  assert.equal(multiTurn.session.gameState.players.A.reserve_count, 1);
  for (const id of ['P12', 'P08', 'P18']) {
    assert.equal(getLocalBoardView(multiTurn.session).pieces.find(piece => piece.nodeId === id)?.side, 'black');
  }

  const short = sessionWithPieces({ P01: 'B', P03: 'B', P29: 'B', P07: 'A' }, { reserveA: 1 });
  const shortTurn = tapLocalGameNode(tapLocalGameNode(short, 'P07').session, 'P02');
  assert.equal(shortTurn.turn?.captures.failure_reason, 'INSUFFICIENT_RESERVE');
  assert.equal(shortTurn.session.gameState.board.occupancy.P02, 'A');
  assert.equal(shortTurn.session.gameState.board.occupancy.P07, null);
  assert.equal(shortTurn.session.gameState.board.occupancy.P01, 'B');
  assert.equal(shortTurn.session.gameState.board.occupancy.P03, 'B');
  assert.equal(shortTurn.session.gameState.players.A.reserve_count, 1);
  assert.equal(shortTurn.session.gameState.current_player, 'B');
});

test('CAPTURE_ALL and TEMPLE_TRAP stop further taps with winners from GameState', () => {
  const all = sessionWithPieces({ P11: 'A', P12: 'B', P08: 'B', P18: 'B', P19: 'A' });
  const allTurn = tapLocalGameNode(tapLocalGameNode(all, 'P19').session, 'P13');
  assert.equal(allTurn.session.gameState.game_status, 'FINISHED');
  assert.equal(allTurn.session.gameState.winner, 'A');
  assert.equal(allTurn.session.gameState.winner_reason, 'CAPTURE_ALL');
  assert.equal(tapLocalGameNode(allTurn.session, 'P11').session, allTurn.session);

  const trap = sessionWithPieces({ P27: 'B', P26: 'A', P28: 'A', P29: 'A', P03: 'A', P21: 'A' });
  const trapTurn = tapLocalGameNode(tapLocalGameNode(trap, 'P21').session, 'P22');
  assert.equal(trapTurn.session.gameState.game_status, 'FINISHED');
  assert.equal(trapTurn.session.gameState.winner, 'A');
  assert.equal(trapTurn.session.gameState.winner_reason, 'TEMPLE_TRAP');
  assert.equal(tapLocalGameNode(trapTurn.session, 'P27').session, trapTurn.session);
});

test('local play stops on a P03 lone-piece loss and the page names its winner reason', () => {
  const session = sessionWithPieces({
    P03: 'B', P02: 'A', P04: 'A', P27: 'A', P08: 'A',
    P09: 'A', P07: 'A', P26: 'A', P28: 'A', P21: 'A',
  });
  const turn = tapLocalGameNode(tapLocalGameNode(session, 'P21').session, 'P22');
  assert.equal(turn.session.gameState.game_status, 'FINISHED');
  assert.equal(turn.session.gameState.winner_reason, 'LONE_PIECE_IMMOBILIZED');
  assert.equal(tapLocalGameNode(turn.session, 'P03').session, turn.session);
  const wxml = readFileSync(new URL('../miniprogram/pages/game/game.wxml', import.meta.url), 'utf8');
  assert.match(wxml, /winner_reason == 'LONE_PIECE_IMMOBILIZED'[^\n]*>对方孤棋无路可走<\/view>/);
});

test('stale legal highlighting cannot bypass executeTurn validation', () => {
  const selected = tapLocalGameNode(createLocalGameSession(), 'P01').session;
  const stale = { ...selected, gameState: { ...selected.gameState, current_player: 'B' as const } };
  const snapshot = structuredClone(stale.gameState);
  const attempt = tapLocalGameNode(stale, 'P02');
  assert.equal(attempt.turn, null);
  assert.ok(attempt.error);
  assert.equal(attempt.session, stale);
  assert.deepEqual(stale.gameState, snapshot);
});

test('resignLocalGame finishes the game for the opponent', () => {
  const session = createLocalGameSession();
  const resigned = resignLocalGame(session, 'A');
  assert.ok(resigned);
  assert.equal(resigned.gameState.game_status, 'FINISHED');
  assert.equal(resigned.gameState.winner, 'B');
  assert.equal(resigned.gameState.winner_reason, 'RESIGN');
  assert.equal(resignLocalGame(resigned, 'B'), null);
});

test('undoLocalGame restores the previous position and turn count', () => {
  const played = tapLocalGameNode(tapLocalGameNode(createLocalGameSession(), 'P01').session, 'P02').session;
  const undone = undoLocalGame(played);
  assert.ok(undone);
  assert.deepEqual(undone.gameState, createInitialGameState());
  assert.equal(undone.turnHistory.length, 0);
  assert.equal(undone.lastMove, null);
  assert.equal(undoLocalGame(createLocalGameSession()), null);
});

test('restart recreates the standard game and clears selection and last move', () => {
  const played = tapLocalGameNode(tapLocalGameNode(createLocalGameSession(), 'P01').session, 'P02').session;
  const restarted = createLocalGameSession();
  assert.notEqual(restarted.gameState, played.gameState);
  assert.deepEqual(restarted.gameState, createInitialGameState());
  assert.equal(restarted.selectedNode, null);
  assert.deepEqual(restarted.legalDestinations, []);
  assert.equal(restarted.lastMove, null);
});
