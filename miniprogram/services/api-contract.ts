/** Transport types copied from backend/app/schemas/game.py, reusing the canonical DTO shape. */
import type { CaptureResult, GameState, Move, NodeId, Player, TurnResult } from '../domain/index';
import type { IterativeDeepeningSearchResult } from '../ai/iterative-deepening';
import type { PositionAnalysis } from '../ai/position-analysis';
import type { ReviewMoveAnalysis } from '../ai/review-analysis';

export interface ApiResponse<T> {
  readonly code: number | string;
  readonly message: string;
  readonly data: T | null;
}

export type GameStateDto = GameState;
export type CaptureResultDto = CaptureResult;
export type TurnResultDto = TurnResult;
export type SearchResultDto = IterativeDeepeningSearchResult;

export type AiLevelDto = 'BEGINNER' | 'STANDARD' | 'ADVANCED';

export interface GameDto {
  readonly game_id: string;
  readonly version?: number;
  readonly state: GameStateDto;
  readonly mode: 'LOCAL' | 'AI';
  readonly human_player: Player | null;
  readonly ai_player: Player | null;
  readonly ai_level: AiLevelDto | null;
}
export type CreateGameRequestDto =
  | { readonly first_player: Player; readonly mode: 'LOCAL' }
  | { readonly first_player: Player; readonly mode: 'AI';
      readonly ai_player: Player; readonly ai_level: AiLevelDto };
export interface ResignRequestDto { readonly resigning_player?: Player; }
export interface LegalMovesDto { readonly moves: readonly Move[] }
export interface MoveRequestDto { readonly from_node: NodeId; readonly to_node: NodeId }
export interface MoveResponseDto { readonly turn: TurnResultDto }
export type AiMoveRequestDto = Record<string, never>;
export interface AiMoveResponseDto { readonly search: SearchResultDto; readonly turn: TurnResultDto }
export type PositionAnalysisDto = PositionAnalysis & {
  readonly game_id: string;
  readonly game_version: number;
};

export interface CoachHintDto {
  readonly gameId: string;
  readonly gameVersion: number;
  readonly analyzedPlayer: Player;
  readonly level: 1 | 2 | 3;
  readonly hintText: string;
  readonly focusTopics: readonly string[];
  readonly candidateFromNodes: readonly NodeId[];
  readonly bestMove: Move | null;
  readonly fallbackUsed: boolean;
  readonly provider: string;
  readonly model: string | null;
  readonly promptVersion: 'coach_hint_v1';
  readonly generatedAt: string;
}

export interface TrainingQuestionDto {
  readonly id: string;
  readonly player: Player;
  readonly stateSnapshot: GameState;
  readonly sourceTurn: number;
  readonly sourceCategory: 'MISTAKE' | 'BLUNDER';
  readonly trainingType: 'BEST_MOVE';
  readonly trainingTags: readonly string[];
  readonly difficultyTag: 'UNCALIBRATED';
}

export interface TrainingListDto {
  readonly items: readonly TrainingQuestionDto[];
  readonly total: number;
}

export interface TrainingAnswerDto {
  readonly id: string;
  readonly trainingId: string;
  readonly clientAttemptId: string;
  readonly submittedMove: Move;
  readonly legal: true;
  readonly bestMoveEquivalent: boolean;
  readonly bestMove: Move;
  readonly bestScore: number;
  readonly submittedMoveScore: number;
  readonly scoreLoss: number;
  readonly result: 'CORRECT' | 'SUBOPTIMAL';
  readonly feedback: string;
  readonly searchDepth: number;
  readonly timedOut: boolean;
  readonly hintLevelUsed: number | null;
  readonly answeredAt: string;
}

export type MoveReviewDto = ReviewMoveAnalysis & {
  readonly gameMoveId: number;
  readonly turn: number;
  readonly player: Player;
};

export interface ReviewConfigDto {
  readonly version: number;
  readonly max_depth: number;
  readonly time_limit_ms_per_move: number;
  readonly candidate_limit: number;
  readonly good_max_loss: number;
  readonly normal_max_loss: number;
  readonly mistake_max_loss: number;
  readonly turning_point_limit: number;
  readonly thresholds_kind: 'heuristic thresholds';
}

export interface GameReviewDto {
  readonly id: string;
  readonly gameId: string;
  readonly reviewedPlayer: Player;
  readonly overallScore: number | null;
  readonly goodMoves: number;
  readonly normalMoves: number;
  readonly mistakes: number;
  readonly blunders: number;
  readonly bestMoveRate: number;
  readonly turningPoints: readonly number[];
  readonly winner: Player | null;
  readonly winnerReason: GameState['winner_reason'];
  readonly reviewConfigVersion: number;
  readonly reviewConfig: ReviewConfigDto;
  readonly moveReviews: readonly MoveReviewDto[];
  readonly createdAt: string;
}

export interface MoveExplanationDto {
  readonly turn: number;
  readonly headline: string;
  readonly explanation: string;
  readonly suggestion: string;
  readonly provider: string;
  readonly model: string | null;
  readonly promptVersion: 'review_explanation_v1';
  readonly fallbackUsed: boolean;
}

export interface GameExplanationDto {
  readonly overall_summary: string;
  readonly strengths: readonly string[];
  readonly main_problems: readonly string[];
  readonly practice_suggestions: readonly string[];
  readonly provider: string;
  readonly model: string | null;
  readonly promptVersion: 'review_explanation_v1';
  readonly fallbackUsed: boolean;
}

export interface ExplainedReviewDto {
  readonly review: GameReviewDto;
  readonly explanation: {
    readonly gameReviewId: string;
    readonly promptVersion: 'review_explanation_v1';
    readonly gameExplanation: GameExplanationDto;
    readonly moveExplanations: readonly MoveExplanationDto[];
    readonly createdAt: string;
  };
}
