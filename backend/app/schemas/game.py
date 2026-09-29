"""Transport DTOs that mirror the canonical TypeScript Engine JSON."""

from typing import Annotated, Generic, Literal, TypeVar
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


Player = Literal["A", "B"]
NodeId = Annotated[str, StringConstraints(pattern=r"^P(?:0[1-9]|1[0-9]|2[0-9])$")]
WinnerReason = Literal["CAPTURE_ALL", "TEMPLE_TRAP", "LONE_PIECE_IMMOBILIZED", "RESIGN"]
AiLevel = Literal["BEGINNER", "STANDARD", "ADVANCED"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PlayerState(StrictModel):
    reserve_count: int


class BoardState(StrictModel):
    occupancy: dict[NodeId, Player | None]


class GameState(StrictModel):
    board: BoardState
    players: dict[Player, PlayerState]
    first_player: Player
    current_player: Player
    game_status: Literal["PLAYING", "FINISHED"]
    winner: Player | None
    winner_reason: WinnerReason | None


class Move(StrictModel):
    from_node: NodeId = Field(alias="from")
    to_node: NodeId = Field(alias="to")


class CapturePattern(StrictModel):
    capture_type: Literal["CLAMP", "CARRY"]
    line_id: str
    segment_nodes: tuple[NodeId, NodeId, NodeId]
    attacker_nodes: list[NodeId]
    captured_nodes: list[NodeId]
    created_by_move: bool


class CaptureResult(StrictModel):
    patterns: list[CapturePattern]
    captured_nodes: list[NodeId]
    replacement_nodes: list[NodeId]
    required_reserve: int
    reserve_used: int
    was_applied: bool
    failure_reason: Literal[
        "NONE", "INSUFFICIENT_RESERVE", "TWO_PIECES_CANNOT_CARRY",
        "LAST_PIECE_CANNOT_CLAMP", "NOT_NEW_PATTERN", "LINE_HAS_EXTRA_PIECES",
    ]


class TurnResult(StrictModel):
    move: Move
    before_state: GameState
    board_before: BoardState
    board_after: BoardState
    reserve_before: dict[Player, int]
    reserve_after: dict[Player, int]
    capture: CaptureResult
    captures: CaptureResult
    winner: Player | None
    winner_reason: WinnerReason | None
    game_over: bool
    state: GameState


class CandidateMoveScore(StrictModel):
    move: Move
    score: float


class SearchResult(StrictModel):
    bestMove: Move | None
    evaluationScore: float
    scorePerspective: Player
    searchDepth: int
    nodesSearched: int
    algorithm: Literal["ITERATIVE_DEEPENING_ALPHA_BETA"]
    candidateMoves: list[CandidateMoveScore]
    cutoffs: int
    thinkingTimeMs: float
    ttProbes: int
    ttHits: int
    ttCutoffs: int
    ttStores: int
    ttSize: int
    timedOut: bool


class FeatureContribution(StrictModel):
    rawValue: float
    weight: float
    weightedScore: float


class EvaluationBreakdown(StrictModel):
    material: FeatureContribution
    reserve: FeatureContribution
    mobility: FeatureContribution
    templeControl: FeatureContribution
    captureOpportunity: FeatureContribution
    vulnerability: FeatureContribution
    trapRisk: FeatureContribution
    terminal: FeatureContribution


class EvaluationResult(StrictModel):
    score: float
    scorePerspective: Player
    breakdown: EvaluationBreakdown
    terminal: bool


class CandidateAnalysis(StrictModel):
    move: Move
    score: float
    rank: int
    scorePerspective: Player
    isBest: bool


class ThreatInfo(StrictModel):
    type: Literal["IMMEDIATE_WIN_AVAILABLE", "CAPTURE_AVAILABLE", "CAPTURE_THREAT",
                  "VULNERABILITY", "LONE_PIECE_MOBILITY_RISK"]
    player: Player
    relatedMove: Move | None = None
    relatedNodes: list[NodeId] | None = None
    evidence: dict[str, str | float]


class PositionAnalysis(StrictModel):
    analyzedPlayer: Player
    scorePerspective: Player
    bestMove: Move | None
    bestScore: float
    evaluationBefore: EvaluationResult
    evaluationBreakdown: EvaluationBreakdown
    candidateMoves: list[CandidateAnalysis]
    searchDepth: int
    nodesSearched: int
    thinkingTimeMs: float
    algorithm: Literal["ITERATIVE_DEEPENING_ALPHA_BETA"]
    ttHits: int
    timedOut: bool
    threats: list[ThreatInfo]
    terminal: bool
    winner: Player | None
    winnerReason: WinnerReason | None


class AnalyzeRequest(StrictModel):
    game_id: str = Field(min_length=1, max_length=32)
    expected_version: int | None = Field(default=None, ge=0)


class AnalyzeResponse(PositionAnalysis):
    game_id: str
    game_version: int


class ReviewConfig(StrictModel):
    version: int = 1
    max_depth: int = 2
    time_limit_ms_per_move: int = 1000
    candidate_limit: int = 3
    good_max_loss: float = 0
    normal_max_loss: float = 30
    mistake_max_loss: float = 100
    turning_point_limit: int = 3
    thresholds_kind: Literal["heuristic thresholds"] = "heuristic thresholds"


class ReviewMoveAnalysis(StrictModel):
    actualMove: Move
    bestMove: Move
    scorePerspective: Player
    scoreBefore: float
    scoreAfter: float
    bestScore: float
    actualMoveScore: float
    scoreLoss: float
    bestMoveEquivalent: bool
    category: Literal["GOOD", "NORMAL", "MISTAKE", "BLUNDER"]
    evaluationBefore: EvaluationResult
    evaluationAfter: EvaluationResult
    bestCandidateMoves: list[CandidateAnalysis]
    threatsBefore: list[ThreatInfo]
    engineExplanation: str
    searchDepth: int
    timedOut: bool


class MoveReview(ReviewMoveAnalysis):
    gameMoveId: int
    turn: int
    player: Player


class GameReview(StrictModel):
    id: str
    gameId: str
    reviewedPlayer: Player
    overallScore: float | None
    goodMoves: int
    normalMoves: int
    mistakes: int
    blunders: int
    bestMoveRate: float
    turningPoints: list[int]
    winner: Player | None
    winnerReason: WinnerReason | None
    reviewConfig: ReviewConfig
    reviewConfigVersion: int
    moveReviews: list[MoveReview]
    createdAt: datetime


class ReviewRequest(StrictModel):
    reviewed_player: Player | None = None


class ResignRequest(StrictModel):
    resigning_player: Player | None = None


class CreateGameRequest(StrictModel):
    first_player: Player = "A"
    mode: Literal["LOCAL", "AI"] = "LOCAL"
    ai_player: Player | None = None
    ai_level: AiLevel | None = None


class MoveRequest(StrictModel):
    from_node: NodeId
    to_node: NodeId


class AiMoveRequest(StrictModel):
    pass


class HealthResponse(StrictModel):
    status: Literal["ok"]
    engine: Literal["ok"]


class GameResponse(StrictModel):
    game_id: str
    version: int
    state: GameState
    mode: Literal["LOCAL", "AI"]
    human_player: Player | None
    ai_player: Player | None
    ai_level: AiLevel | None


class LegalMovesResponse(StrictModel):
    moves: list[Move]


class MoveResponse(StrictModel):
    turn: TurnResult


class AiMoveResponse(StrictModel):
    search: SearchResult
    turn: TurnResult


T = TypeVar("T")


class ApiResponse(StrictModel, Generic[T]):
    code: int | str = 0
    message: str = "success"
    data: T | None
