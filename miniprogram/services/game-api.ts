import type { NodeId } from '../domain/index';
import type { ApiClient } from './api-client';
import type { AiMoveRequestDto, AiMoveResponseDto, CreateGameRequestDto, GameDto, LegalMovesDto,
  MoveRequestDto, MoveResponseDto, PositionAnalysisDto, GameReviewDto,
  ExplainedReviewDto, CoachHintDto, ResignRequestDto } from './api-contract';

export interface GameApi {
  createGame(request?: CreateGameRequestDto): Promise<GameDto>;
  getGame(gameId: string): Promise<GameDto>;
  getLegalMoves(gameId: string, fromNode?: NodeId): Promise<LegalMovesDto>;
  move(gameId: string, request: MoveRequestDto): Promise<MoveResponseDto>;
  aiMove(gameId: string, request: AiMoveRequestDto): Promise<AiMoveResponseDto>;
  undo(gameId: string): Promise<GameDto>;
  resign(gameId: string, request?: ResignRequestDto): Promise<GameDto>;
  analyzeGame(gameId: string, expectedVersion?: number): Promise<PositionAnalysisDto>;
  getCoachHint(gameId: string, level: 1 | 2 | 3, expectedVersion: number): Promise<CoachHintDto>;
  getReview(gameId: string, reviewedPlayer?: 'A' | 'B'): Promise<GameReviewDto>;
  createReview(gameId: string, reviewedPlayer?: 'A' | 'B'): Promise<GameReviewDto>;
  getReviewExplanation(gameId: string, reviewedPlayer?: 'A' | 'B'): Promise<ExplainedReviewDto>;
  explainReview(gameId: string, reviewedPlayer?: 'A' | 'B'): Promise<ExplainedReviewDto>;
}

export function createGameApi(client: ApiClient): GameApi {
  const base = (gameId: string) => `/api/v1/game/${encodeURIComponent(gameId)}`;
  return {
    createGame: (request = { first_player: 'A', mode: 'LOCAL' }) =>
      client.request('POST', '/api/v1/game', request),
    getGame: gameId => client.request('GET', base(gameId)),
    getLegalMoves: (gameId, fromNode) => client.request('GET',
      `${base(gameId)}/legal-moves${fromNode ? `?from_node=${encodeURIComponent(fromNode)}` : ''}`),
    move: (gameId, request) => client.request('POST', `${base(gameId)}/move`, request),
    aiMove: (gameId, request) => client.request('POST', `${base(gameId)}/ai-move`, request, 50000),
    undo: gameId => client.request('POST', `${base(gameId)}/undo`, {}),
    resign: (gameId, request = {}) => client.request('POST', `${base(gameId)}/resign`, request),
    analyzeGame: (gameId, expectedVersion) => client.request('POST', '/api/v1/ai/analyze',
      { game_id: gameId, ...(expectedVersion === undefined ? {} : { expected_version: expectedVersion }) },
      50000),
    getCoachHint: (gameId, level, expectedVersion) => client.request('POST',
      `${base(gameId)}/coach/hint`, { level, expected_version: expectedVersion }, 50000),
    getReview: (gameId, reviewedPlayer) => client.request('GET',
      `${base(gameId)}/review${reviewedPlayer ? `?reviewed_player=${reviewedPlayer}` : ''}`),
    createReview: (gameId, reviewedPlayer) => client.request('POST', `${base(gameId)}/review`,
      reviewedPlayer ? { reviewed_player: reviewedPlayer } : {}, 180000),
    getReviewExplanation: (gameId, reviewedPlayer) => client.request('GET',
      `${base(gameId)}/review/explain${reviewedPlayer ? `?reviewed_player=${reviewedPlayer}` : ''}`),
    explainReview: (gameId, reviewedPlayer) => client.request('POST',
      `${base(gameId)}/review/explain`, reviewedPlayer ? { reviewed_player: reviewedPlayer } : {}, 120000),
  };
}
