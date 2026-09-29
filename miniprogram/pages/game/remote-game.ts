import { NODE_IDS } from '../../domain/index';
import type { CaptureResult, GameState, Move, NodeId } from '../../domain/index';
import { ApiError, messageForApiError } from '../../services/api-client';
import { analyzePosition } from '../../ai/position-analysis';
import type { GameApi } from '../../services/game-api';
import { buildHintFromAnalysis, type GameHintView } from './hint-builder';

export interface GameIdStorage {
  read(): string | null;
  write(gameId: string): void;
  clear(): void;
}

export interface RemoteGameSnapshot {
  readonly gameId: string | null;
  readonly gameVersion: number | null;
  readonly gameState: GameState | null;
  readonly selectedNode: NodeId | null;
  readonly legalTargets: readonly NodeId[];
  readonly lastMove: Move | null;
  readonly lastCapture: CaptureResult | null;
  readonly isLoadingGame: boolean;
  readonly isLoadingLegalMoves: boolean;
  readonly isSubmittingMove: boolean;
  readonly needsResync: boolean;
  readonly errorMessage: string | null;
  readonly notice: string | null;
  readonly hintView: GameHintView | null;
  readonly hintLevel: number;
  readonly isHintLoading: boolean;
  readonly hintErrorMessage: string | null;
}

const emptySnapshot: RemoteGameSnapshot = {
  gameId: null, gameVersion: null, gameState: null, selectedNode: null, legalTargets: [],
  lastMove: null, lastCapture: null,
  isLoadingGame: false, isLoadingLegalMoves: false, isSubmittingMove: false,
  needsResync: false,
  errorMessage: null, notice: null,
  hintView: null, hintLevel: 0, isHintLoading: false, hintErrorMessage: null,
};

export class RemoteGameController {
  private readonly api: GameApi;
  private readonly storage: GameIdStorage;
  private readonly onChange: (snapshot: RemoteGameSnapshot) => void;
  private state: RemoteGameSnapshot = emptySnapshot;
  private disposed = false;
  private requestGeneration = 0;
  private legalGeneration = 0;
  private readonly createOnMissing: boolean;

  constructor(
    api: GameApi,
    storage: GameIdStorage,
    onChange: (snapshot: RemoteGameSnapshot) => void,
    options: { createOnMissing?: boolean } = {},
  ) {
    this.api = api;
    this.storage = storage;
    this.onChange = onChange;
    this.createOnMissing = options.createOnMissing ?? true;
  }

  get snapshot(): RemoteGameSnapshot { return this.state; }

  private publish(patch: Partial<RemoteGameSnapshot>): void {
    if (this.disposed) return;
    this.state = { ...this.state, ...patch };
    this.onChange(this.state);
  }

  private current(generation: number): boolean {
    return !this.disposed && generation === this.requestGeneration;
  }

  async enter(): Promise<void> {
    if (this.disposed || this.state.isLoadingGame || this.state.isSubmittingMove) return;
    const generation = ++this.requestGeneration;
    this.legalGeneration++;
    this.publish({ isLoadingGame: true, errorMessage: null, notice: null,
      selectedNode: null, legalTargets: [], isLoadingLegalMoves: false });
    try {
      const saved = this.storage.read();
      let game;
      if (saved) {
        try {
          game = await this.api.getGame(saved);
        } catch (error) {
          const canReplaceSavedGame = error instanceof ApiError &&
            (error.code === 'GAME_NOT_FOUND' ||
              (this.createOnMissing && error.code === 'AUTH_FORBIDDEN'));
          if (!canReplaceSavedGame) throw error;
          if (!this.current(generation)) return;
          this.storage.clear();
          if (!this.createOnMissing) throw error;
          game = await this.api.createGame();
        }
      } else {
        if (!this.createOnMissing) throw new ApiError('GAME_NOT_FOUND', 404);
        game = await this.api.createGame();
      }
      if (!this.current(generation)) return;
      this.storage.write(game.game_id);
      this.publish({ gameId: game.game_id, gameVersion: game.version ?? null,
        gameState: game.state,
        lastMove: null, lastCapture: null, isLoadingGame: false, needsResync: false,
        hintView: null, hintLevel: 0, hintErrorMessage: null });
    } catch (error) {
      if (this.current(generation)) this.publish({ isLoadingGame: false,
        errorMessage: messageForApiError(error) });
    }
  }

  async restart(): Promise<void> {
    if (this.disposed || this.state.isLoadingGame || this.state.isSubmittingMove) return;
    const generation = ++this.requestGeneration;
    this.legalGeneration++;
    this.publish({ isLoadingGame: true, errorMessage: null,
      selectedNode: null, legalTargets: [], isLoadingLegalMoves: false });
    try {
      const game = await this.api.createGame();
      if (!this.current(generation)) return;
      this.storage.write(game.game_id);
      this.publish({ gameId: game.game_id, gameVersion: game.version ?? null,
        gameState: game.state,
        lastMove: null, lastCapture: null, notice: null, isLoadingGame: false,
        needsResync: false, hintView: null, hintLevel: 0, hintErrorMessage: null });
    } catch (error) {
      if (this.current(generation)) this.publish({ isLoadingGame: false,
        errorMessage: messageForApiError(error) });
    }
  }

  async tapNode(id: string): Promise<void> {
    if (this.disposed || this.state.isLoadingGame || this.state.isSubmittingMove ||
        this.state.needsResync ||
        this.state.gameState?.game_status !== 'PLAYING' || !this.state.gameId ||
        !NODE_IDS.includes(id as NodeId)) return;
    const node = id as NodeId;
    if (this.state.gameState.board.occupancy[node] === this.state.gameState.current_player) {
      await this.selectNode(node);
    } else if (this.state.selectedNode && this.state.legalTargets.includes(node)) {
      await this.submitMove(this.state.selectedNode, node);
    }
  }

  private async selectNode(node: NodeId): Promise<void> {
    const generation = ++this.legalGeneration;
    const gameId = this.state.gameId!;
    this.publish({ selectedNode: node, legalTargets: [],
      isLoadingLegalMoves: true, errorMessage: null, notice: null });
    try {
      const result = await this.api.getLegalMoves(gameId, node);
      if (this.disposed || generation !== this.legalGeneration || this.state.gameId !== gameId) return;
      this.publish({ legalTargets: result.moves.filter(move => move.from === node).map(move => move.to),
        isLoadingLegalMoves: false });
    } catch (error) {
      if (this.disposed || generation !== this.legalGeneration) return;
      this.publish({ selectedNode: null, legalTargets: [], isLoadingLegalMoves: false,
        errorMessage: messageForApiError(error) });
    }
  }

  private async submitMove(from: NodeId, to: NodeId): Promise<void> {
    const gameId = this.state.gameId!;
    const generation = this.requestGeneration;
    this.legalGeneration++;
    this.publish({ isSubmittingMove: true, isLoadingLegalMoves: false,
      errorMessage: null, notice: null });
    try {
      const { turn } = await this.api.move(gameId, { from_node: from, to_node: to });
      if (!this.current(generation) || this.state.gameId !== gameId) return;
      this.publish({ gameState: turn.state,
        gameVersion: this.state.gameVersion === null ? null : this.state.gameVersion + 1,
        lastMove: turn.move, lastCapture: turn.capture,
        selectedNode: null, legalTargets: [],
        notice: turn.capture.failure_reason === 'INSUFFICIENT_RESERVE'
          ? '备用棋不足，本次吃子未生效' : null });
    } catch (error) {
      if (!this.current(generation)) return;
      if (error instanceof ApiError && error.code === 'GAME_STATE_CONFLICT') {
        this.publish({ needsResync: true, selectedNode: null, legalTargets: [] });
        await this.reloadAfterRejection(gameId, generation, null, '棋局状态已更新');
      } else if (error instanceof ApiError &&
          ['INVALID_MOVE', 'PATH_BLOCKED', 'TARGET_OCCUPIED',
            'NOT_PLAYER_TURN', 'GAME_ALREADY_FINISHED'].includes(error.code)) {
        this.publish({ needsResync: true, selectedNode: null, legalTargets: [] });
        await this.reloadAfterRejection(gameId, generation, messageForApiError(error), null);
      } else {
        this.publish({ selectedNode: null, legalTargets: [], errorMessage: messageForApiError(error) });
      }
    } finally {
      if (this.current(generation)) this.publish({ isSubmittingMove: false });
    }
  }

  private async reloadAfterRejection(
    gameId: string, generation: number, errorMessage: string | null, notice: string | null,
  ): Promise<void> {
    try {
      const game = await this.api.getGame(gameId);
      if (!this.current(generation)) return;
      this.publish({ gameState: game.state, gameVersion: game.version ?? null,
        selectedNode: null, legalTargets: [],
        lastMove: null, lastCapture: null, errorMessage, notice, needsResync: false });
    } catch (error) {
      if (!this.current(generation)) return;
      if (error instanceof ApiError && error.code === 'GAME_NOT_FOUND') {
        this.storage.clear();
        this.publish({ gameId: null, gameVersion: null, gameState: null,
          selectedNode: null, legalTargets: [],
          errorMessage: messageForApiError(error), needsResync: false });
      } else {
        this.publish({ selectedNode: null, legalTargets: [],
          errorMessage: messageForApiError(error) });
      }
    }
  }

  async requestHint(): Promise<void> {
    if (this.disposed || this.state.isLoadingGame || this.state.isSubmittingMove ||
        this.state.needsResync || !this.state.gameState ||
        this.state.gameState.game_status !== 'PLAYING' || this.state.isHintLoading) return;
    const level = Math.min(3, this.state.hintLevel + 1) as 1 | 2 | 3;
    const state = this.state.gameState;
    const generation = this.requestGeneration;
    this.publish({ isHintLoading: true, hintErrorMessage: null, selectedNode: null,
      legalTargets: [], isLoadingLegalMoves: false });
    try {
      const analysis = analyzePosition(state, { maxDepth: 2, timeLimitMs: 1000, now: () => Date.now() });
      if (!this.current(generation) || this.state.gameState !== state) return;
      this.publish({ hintView: buildHintFromAnalysis(analysis, level), hintLevel: level });
    } catch {
      if (!this.current(generation)) return;
      this.publish({ hintErrorMessage: '提示暂时不可用' });
    } finally {
      if (this.current(generation)) this.publish({ isHintLoading: false });
    }
  }

  async resign(): Promise<void> {
    if (this.disposed || this.state.isLoadingGame || this.state.isSubmittingMove ||
        !this.state.gameId || this.state.gameState?.game_status === 'FINISHED') return;
    const gameId = this.state.gameId;
    const resigning = this.state.gameState!.current_player;
    const generation = this.requestGeneration;
    this.legalGeneration++;
    this.publish({ isSubmittingMove: true, errorMessage: null, notice: null,
      selectedNode: null, legalTargets: [], isLoadingLegalMoves: false });
    try {
      const game = await this.api.resign(gameId, { resigning_player: resigning });
      if (!this.current(generation) || this.state.gameId !== gameId) return;
      this.publish({ gameState: game.state, gameVersion: game.version ?? null,
        selectedNode: null, legalTargets: [], hintView: null, hintLevel: 0,
        notice: `玩家 ${resigning} 认输，本局结束` });
    } catch (error) {
      if (!this.current(generation)) return;
      this.publish({ errorMessage: messageForApiError(error) });
    } finally {
      if (this.current(generation)) this.publish({ isSubmittingMove: false });
    }
  }

  dispose(): void {
    this.disposed = true;
    this.requestGeneration++;
    this.legalGeneration++;
  }
}
