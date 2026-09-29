"""Game use cases; the TypeScript worker remains the only rule authority."""

from datetime import datetime, timezone
from uuid import uuid4

from backend.app.core.config import Settings
from backend.app.core.errors import ApiError
from backend.app.engine_adapter.node_worker import NodeEngineAdapter
from backend.app.schemas.game import (
    AiMoveRequest, AiMoveResponse, AnalyzeResponse, CreateGameRequest, GameResponse,
    LegalMovesResponse, Move, MoveRequest, MoveResponse, GameState, GameReview,
    MoveReview, ResignRequest, ReviewConfig,
)
from backend.app.services.game_store import GameStore


_AI_LEVEL_BUDGETS = {"BEGINNER": (2, 500), "STANDARD": (4, 1000), "ADVANCED": (6, 3000)}


class GameService:
    def __init__(self, adapter: NodeEngineAdapter, store: GameStore, settings: Settings):
        self.adapter = adapter
        self.store = store
        self.settings = settings

    def _ai_search_budget(self, ai_level: str | None) -> tuple[int, int]:
        level = ai_level or "STANDARD"
        depth, budget = _AI_LEVEL_BUDGETS.get(level, _AI_LEVEL_BUDGETS["STANDARD"])
        if level == "STANDARD":
            return self.settings.ai_default_max_depth, self.settings.ai_default_time_limit_ms
        return depth, budget

    @staticmethod
    def _finish_by_resign(state: GameState, resigning_player: str) -> GameState:
        winner = "B" if resigning_player == "A" else "A"
        return state.model_copy(update={
            "game_status": "FINISHED", "winner": winner, "winner_reason": "RESIGN",
        })

    async def create(self, request: CreateGameRequest, user_id: str | None = None) -> GameResponse:
        if request.mode == "LOCAL" and (request.ai_player is not None or request.ai_level is not None):
            raise ApiError("INVALID_REQUEST", "AI options require AI mode")
        ai_player = (request.ai_player or "B") if request.mode == "AI" else None
        ai_level = (request.ai_level or "STANDARD") if request.mode == "AI" else None
        state = await self.adapter.initialize(request.first_player)
        game_id = await self.store.create(state, request.mode, ai_player, ai_level, user_id)
        return GameResponse(game_id=game_id, version=0, state=state, mode=request.mode,
                            human_player=self._human(ai_player), ai_player=ai_player,
                            ai_level=ai_level)

    @staticmethod
    def _human(ai_player: str | None) -> str | None:
        return None if ai_player is None else ("B" if ai_player == "A" else "A")

    async def get(self, game_id: str) -> GameResponse:
        snapshot = await self.store.get_snapshot(game_id)
        if snapshot.mode == "REMOTE":
            raise ApiError("REMOTE_ACTION_REQUIRED", "Use the remote room endpoint")
        return GameResponse(game_id=game_id, version=snapshot.version,
                            state=snapshot.state, mode=snapshot.mode,
                            human_player=self._human(snapshot.ai_player),
                            ai_player=snapshot.ai_player, ai_level=snapshot.ai_level)

    async def legal_moves(self, game_id: str, from_node: str | None) -> LegalMovesResponse:
        lock = await self.store.lock_for(game_id)
        async with lock:
            snapshot = await self.store.get_snapshot(game_id)
            if snapshot.mode == "REMOTE":
                raise ApiError("REMOTE_ACTION_REQUIRED", "Use the remote room endpoint")
            state = snapshot.state
            moves = await self.adapter.legal_moves(state)
            if from_node is not None:
                moves = [move for move in moves if move.from_node == from_node]
            return LegalMovesResponse(moves=moves)

    async def move(self, game_id: str, request: MoveRequest) -> MoveResponse:
        lock = await self.store.lock_for(game_id)
        async with lock:
            snapshot = await self.store.get_snapshot(game_id)
            if snapshot.mode == "REMOTE":
                raise ApiError("REMOTE_ACTION_REQUIRED", "Use the remote room move endpoint")
            if snapshot.state.game_status == "FINISHED":
                raise ApiError("GAME_ALREADY_FINISHED", "Game already finished")
            if snapshot.mode == "AI" and snapshot.state.current_player != self._human(snapshot.ai_player):
                raise ApiError("NOT_HUMAN_TURN", "It is the AI turn")
            turn = await self.adapter.execute_turn(snapshot.state, Move(from_node=request.from_node,
                                                                         to_node=request.to_node))
            await self.store.commit_turn(game_id, snapshot.version, turn, "HUMAN")
            return MoveResponse(turn=turn)

    async def ai_move(self, game_id: str, request: AiMoveRequest) -> AiMoveResponse:
        lock = await self.store.lock_for(game_id)
        async with lock:
            snapshot = await self.store.get_snapshot(game_id)
            if snapshot.state.game_status == "FINISHED":
                raise ApiError("GAME_ALREADY_FINISHED", "Game already finished")
            if snapshot.mode != "AI" or snapshot.ai_player is None:
                raise ApiError("AI_MODE_REQUIRED", "This game has no AI player")
            if snapshot.state.current_player != snapshot.ai_player:
                raise ApiError("NOT_AI_TURN", "It is the human turn")
            depth, budget = self._ai_search_budget(snapshot.ai_level)
            search, turn = await self.adapter.ai_move(snapshot.state, depth, budget)
            await self.store.commit_turn(game_id, snapshot.version, turn, "AI", search)
            return AiMoveResponse(search=search, turn=turn)

    async def undo(self, game_id: str) -> GameResponse:
        lock = await self.store.lock_for(game_id)
        async with lock:
            snapshot = await self.store.get_snapshot(game_id)
            if snapshot.mode == "REMOTE":
                raise ApiError("REMOTE_ACTION_REQUIRED", "Use the remote room endpoint")
            if snapshot.state.game_status == "FINISHED":
                raise ApiError("GAME_ALREADY_FINISHED", "Game already finished")
            if snapshot.version == 0:
                raise ApiError("UNDO_NOT_AVAILABLE", "No moves to undo")
            moves = await self.store.list_moves(game_id)
            steps = self._undo_steps(snapshot, moves)
            await self.store.revert_moves(game_id, snapshot.version, steps)
            updated = await self.store.get_snapshot(game_id)
            return GameResponse(game_id=game_id, version=updated.version, state=updated.state,
                                mode=updated.mode, human_player=self._human(updated.ai_player),
                                ai_player=updated.ai_player, ai_level=updated.ai_level)

    async def resign(self, game_id: str, request: ResignRequest) -> GameResponse:
        lock = await self.store.lock_for(game_id)
        async with lock:
            snapshot = await self.store.get_snapshot(game_id)
            if snapshot.mode == "REMOTE":
                raise ApiError("REMOTE_ACTION_REQUIRED", "Use the remote room endpoint")
            if snapshot.state.game_status == "FINISHED":
                raise ApiError("GAME_ALREADY_FINISHED", "Game already finished")
            if snapshot.mode == "AI":
                if snapshot.ai_player is None:
                    raise ApiError("AI_MODE_REQUIRED", "This game has no AI player")
                resigning = self._human(snapshot.ai_player)
            else:
                if request.resigning_player is None:
                    raise ApiError("INVALID_REQUEST", "resigning_player is required")
                resigning = request.resigning_player
            new_state = self._finish_by_resign(snapshot.state, resigning)
            await self.store.commit_resign(game_id, snapshot.version, new_state)
            updated = await self.store.get_snapshot(game_id)
            return GameResponse(game_id=game_id, version=updated.version, state=updated.state,
                                mode=updated.mode, human_player=self._human(updated.ai_player),
                                ai_player=updated.ai_player, ai_level=updated.ai_level)

    def _undo_steps(self, snapshot, moves: list) -> int:
        if snapshot.mode == "AI":
            if snapshot.state.current_player == snapshot.ai_player:
                return 1
            if (len(moves) >= 2 and moves[-1].actor_type == "AI" and
                    moves[-2].actor_type == "HUMAN"):
                return 2
            return 1
        return 1

    async def replay_game(self, game_id: str) -> list[GameState]:
        """Read historical snapshots without reinterpreting moves under future rules."""
        snapshot, moves = await self.store.read_replay(game_id)
        frames = [snapshot.initial_state]
        for number, item in enumerate(moves, 1):
            if item.turn_number != number or item.turn.before_state != frames[-1]:
                raise ApiError("REPLAY_INTEGRITY_ERROR", "Move history is not contiguous")
            frames.append(item.turn.state)
        if len(moves) != snapshot.version or frames[-1] != snapshot.state:
            raise ApiError("REPLAY_INTEGRITY_ERROR", "Final state differs from move history")
        return frames

    async def analyze(self, game_id: str, expected_version: int | None = None) -> AnalyzeResponse:
        # Reading and saving are short independent transactions; the worker runs between them.
        snapshot = await self.store.get_snapshot(game_id)
        if snapshot.mode == "REMOTE":
            raise ApiError("REMOTE_ACTION_REQUIRED", "Use the remote room endpoint")
        if expected_version is not None and snapshot.version != expected_version:
            raise ApiError("GAME_STATE_CONFLICT", "Game state changed; retry analysis")
        analysis = await self.adapter.analyze_position(
            snapshot.state, self.settings.analysis_max_depth,
            self.settings.analysis_time_limit_ms, self.settings.analysis_candidate_limit,
        )
        await self.store.commit_analysis(game_id, snapshot.version, analysis)
        return AnalyzeResponse(game_id=game_id, game_version=snapshot.version,
                               **analysis.model_dump())

    @staticmethod
    def _reviewed_player(snapshot, requested: str | None) -> str:
        if snapshot.mode == "REMOTE":
            raise ApiError("REMOTE_ACTION_REQUIRED", "Remote room review requires a seat token")
        human = GameService._human(snapshot.ai_player)
        if snapshot.mode == "AI":
            if requested is not None and requested != human:
                raise ApiError("INVALID_REQUEST", "Only the human player can be reviewed")
            return human
        return requested or "A"

    async def get_review(self, game_id: str, reviewed_player: str | None = None) -> GameReview:
        snapshot = await self.store.get_snapshot(game_id)
        player = self._reviewed_player(snapshot, reviewed_player)
        review = await self.store.get_review(game_id, player, ReviewConfig().version)
        if review is None:
            raise ApiError("REVIEW_NOT_FOUND", "Review has not been generated")
        return review

    async def create_review(self, game_id: str,
                            reviewed_player: str | None = None) -> GameReview:
        config = ReviewConfig()
        snapshot, moves = await self.store.read_replay(game_id)
        if snapshot.mode == "REMOTE":
            raise ApiError("REMOTE_ACTION_REQUIRED", "Remote room review requires a seat token")
        if snapshot.state.game_status != "FINISHED":
            raise ApiError("GAME_NOT_FINISHED", "Game has not finished")
        player = self._reviewed_player(snapshot, reviewed_player)
        existing = await self.store.get_review(game_id, player, config.version)
        if existing is not None:
            return existing
        frame = snapshot.initial_state
        for number, item in enumerate(moves, 1):
            if item.turn_number != number or item.turn.before_state != frame:
                raise ApiError("REPLAY_INTEGRITY_ERROR", "Move history is not contiguous")
            frame = item.turn.state
        if len(moves) != snapshot.version or frame != snapshot.state:
            raise ApiError("REPLAY_INTEGRITY_ERROR", "Final state differs from move history")
        reviewed = []
        for item in moves:
            if item.actor_type != "HUMAN" or item.turn.before_state.current_player != player:
                continue
            analysis = await self.adapter.review_move(
                item.turn.before_state, item.turn.state, item.turn.move, config)
            if analysis.scorePerspective != player or analysis.scoreLoss < 0:
                raise ApiError("REVIEW_INCOMPLETE", "Review score perspective is inconsistent")
            reviewed.append(MoveReview(gameMoveId=item.game_move_id, turn=item.turn_number,
                                       player=player, **analysis.model_dump()))
        counts = {category: sum(move.category == category for move in reviewed)
                  for category in ("GOOD", "NORMAL", "MISTAKE", "BLUNDER")}
        turning = sorted((move for move in reviewed if move.category in ("MISTAKE", "BLUNDER")),
                         key=lambda move: (-move.scoreLoss, move.turn))[:config.turning_point_limit]
        best_count = sum(move.bestMoveEquivalent for move in reviewed)
        review = GameReview(
            id=uuid4().hex, gameId=game_id, reviewedPlayer=player, overallScore=None,
            goodMoves=counts["GOOD"], normalMoves=counts["NORMAL"],
            mistakes=counts["MISTAKE"], blunders=counts["BLUNDER"],
            bestMoveRate=best_count / len(reviewed) if reviewed else 0,
            turningPoints=[move.turn for move in turning],
            winner=snapshot.state.winner, winnerReason=snapshot.state.winner_reason,
            reviewConfig=config, reviewConfigVersion=config.version,
            moveReviews=reviewed, createdAt=datetime.now(timezone.utc),
        )
        return await self.store.commit_review(review, snapshot.version)
