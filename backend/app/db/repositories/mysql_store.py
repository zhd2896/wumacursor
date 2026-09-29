"""MySQL unit of work: one versioned game update and move insert per transaction."""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, select, text, func, or_, and_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from backend.app.core.errors import ApiError
from backend.app.db.models import (AiAnalysisModel, CoachHintModel, GameModel, GameReviewModel,
                                    MoveReviewModel, ReviewExplanationModel, UserModel,
                                    TrainingRecordModel)
from backend.app.db.repositories.game import GameRepository
from backend.app.db.repositories.remote import RemoteRepository
from backend.app.db.repositories.move import MoveRepository
from backend.app.schemas.game import GameReview, GameState, PositionAnalysis, SearchResult, TurnResult
from backend.app.schemas.explanation import ExplanationBundle
from backend.app.schemas.coach import CoachHint
from backend.app.schemas.training import (TrainingAnswerResult, TrainingItemInternal,
                                          TrainingSource)
from backend.app.db.repositories.training import TrainingRepository
from backend.app.services.game_store import StoredGame, StoredMove, StoredRemoteRoom


class MySQLGameStore:
    def __init__(self, database_url: str):
        self.engine = create_engine(database_url, pool_pre_ping=True, isolation_level="REPEATABLE READ")
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    async def ping(self) -> None:
        await asyncio.to_thread(self._ping)

    async def register_device(self, token_hash: str) -> str:
        return await asyncio.to_thread(self._register_device, token_hash)

    def _register_device(self, token_hash: str) -> str:
        try:
            with self.sessions.begin() as session:
                user_id = uuid4().hex
                session.add(UserModel(id=user_id, external_user_id="device:" + token_hash,
                                      nickname="本机棋手"))
                session.flush()
                return user_id
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def resolve_device(self, token_hash: str) -> str | None:
        return await asyncio.to_thread(self._resolve_device, token_hash)

    def _resolve_device(self, token_hash: str) -> str | None:
        try:
            with self.sessions() as session:
                return session.scalar(select(UserModel.id).where(
                    UserModel.external_user_id == "device:" + token_hash))
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def personal_games(self, user_id: str, limit: int,
                             cursor: tuple[datetime, str] | None,
                             status: str | None = None) -> tuple[list[dict], bool]:
        return await asyncio.to_thread(self._personal_games, user_id, limit, cursor, status)

    def _personal_games(self, user_id: str, limit: int,
                        cursor: tuple[datetime, str] | None,
                        status: str | None) -> tuple[list[dict], bool]:
        try:
            with self.sessions() as session:
                query = select(GameModel).where(GameModel.user_id == user_id,
                                                GameModel.mode != "REMOTE")
                if status is not None:
                    query = query.where(GameModel.status == status)
                if cursor:
                    when, game_id = cursor
                    naive = when.astimezone(timezone.utc).replace(tzinfo=None)
                    query = query.where(or_(GameModel.created_at < naive,
                                            and_(GameModel.created_at == naive,
                                                 GameModel.id < game_id)))
                rows = session.scalars(query.order_by(GameModel.created_at.desc(),
                                                       GameModel.id.desc()).limit(limit + 1)).all()
                selected = rows[:limit]
                reviewed_games = set(session.scalars(select(GameReviewModel.game_id).where(
                    GameReviewModel.game_id.in_([row.id for row in selected]))).all()) if selected else set()
                result = []
                for row in selected:
                    result.append({"gameId": row.id, "mode": row.mode,
                                   "status": row.status, "winner": row.winner,
                                   "startedAt": row.started_at.replace(tzinfo=timezone.utc).isoformat(),
                                   "finishedAt": row.finished_at.replace(tzinfo=timezone.utc).isoformat()
                                   if row.finished_at else None,
                                   "turns": row.version,
                                   "reviewAvailable": row.id in reviewed_games,
                                   "cursorDate": row.created_at.replace(tzinfo=timezone.utc).isoformat()})
                return result, len(rows) > limit
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def personal_profile(self, user_id: str) -> dict:
        return await asyncio.to_thread(self._personal_profile, user_id)

    def _personal_profile(self, user_id: str) -> dict:
        try:
            with self.sessions() as session:
                nickname = session.scalar(select(UserModel.nickname).where(UserModel.id == user_id))
                if nickname is None:
                    raise ApiError("AUTH_INVALID", "Account is unavailable")
                games = session.scalar(select(func.count()).select_from(GameModel).where(
                    GameModel.user_id == user_id, GameModel.mode != "REMOTE")) or 0
                finished = session.scalar(select(func.count()).select_from(GameModel).where(
                    GameModel.user_id == user_id, GameModel.mode != "REMOTE",
                    GameModel.status == "FINISHED")) or 0
                training = session.scalar(select(func.count()).select_from(TrainingRecordModel).where(
                    TrainingRecordModel.user_id == user_id)) or 0
                correct = session.scalar(select(func.count()).select_from(TrainingRecordModel).where(
                    TrainingRecordModel.user_id == user_id,
                    TrainingRecordModel.result == "CORRECT")) or 0
                ai_results = session.execute(select(GameModel.winner, GameModel.ai_player).where(
                    GameModel.user_id == user_id, GameModel.mode == "AI",
                    GameModel.status == "FINISHED")).all()
                wins = sum(winner == ("B" if ai_player == "A" else "A")
                           for winner, ai_player in ai_results)
                losses = sum(winner == ai_player for winner, ai_player in ai_results)
                reviewed = session.scalar(select(func.count(func.distinct(GameReviewModel.game_id)))
                    .join(GameModel, GameModel.id == GameReviewModel.game_id)
                    .where(GameModel.user_id == user_id)) or 0
                return {"id": user_id, "nickname": nickname, "games": games,
                        "finishedGames": finished, "wins": wins, "losses": losses,
                        "reviewedGames": reviewed, "training": training, "correct": correct}
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    def _ping(self) -> None:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def lock_for(self, game_id: str) -> asyncio.Lock:
        # The database CAS is the concurrency guard; no unbounded game-id cache.
        return asyncio.Lock()

    async def create(self, state: GameState, mode: str = "LOCAL",
                     ai_player: str | None = None, ai_level: str | None = None,
                     user_id: str | None = None) -> str:
        return await asyncio.to_thread(self._create, state, mode, ai_player, ai_level, user_id)

    def _create(self, state: GameState, mode: str,
                ai_player: str | None, ai_level: str | None, user_id: str | None) -> str:
        try:
            with self.sessions.begin() as session:
                return GameRepository(session).create_game(state, mode, ai_player, ai_level, user_id)
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def get_snapshot(self, game_id: str) -> StoredGame:
        return await asyncio.to_thread(self._get_snapshot, game_id)

    def _get_snapshot(self, game_id: str) -> StoredGame:
        try:
            with self.sessions() as session:
                return GameRepository(session).get_snapshot(game_id)
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def commit_turn(self, game_id: str, expected_version: int, turn: TurnResult,
                          actor_type: str, search: SearchResult | None = None) -> None:
        await asyncio.to_thread(self._commit_turn, game_id, expected_version, turn, actor_type, search)

    def _commit_turn(self, game_id: str, expected_version: int, turn: TurnResult,
                     actor_type: str, search: SearchResult | None) -> None:
        try:
            with self.sessions.begin() as session:
                games = GameRepository(session)
                row = games.get_game(game_id)
                if row.version != expected_version or GameState.model_validate(row.current_state) != turn.before_state:
                    raise ApiError("GAME_STATE_CONFLICT", "Game state changed; retry the move")
                games.update_game_state(row, expected_version, turn.state)
                MoveRepository(session).create_move(game_id, expected_version + 1, turn, actor_type, search)
                session.flush()
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def revert_moves(self, game_id: str, expected_version: int, steps: int) -> None:
        await asyncio.to_thread(self._revert_moves, game_id, expected_version, steps)

    async def commit_resign(self, game_id: str, expected_version: int, state: GameState) -> None:
        await asyncio.to_thread(self._commit_resign, game_id, expected_version, state)

    def _commit_resign(self, game_id: str, expected_version: int, state: GameState) -> None:
        try:
            with self.sessions.begin() as session:
                games = GameRepository(session)
                row = games.get_game(game_id)
                if row.version != expected_version or GameState.model_validate(row.current_state).game_status == "FINISHED":
                    raise ApiError("GAME_STATE_CONFLICT", "Game state changed; retry resign")
                games.update_game_state(row, expected_version, state)
                session.flush()
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    def _revert_moves(self, game_id: str, expected_version: int, steps: int) -> None:
        try:
            with self.sessions.begin() as session:
                games = GameRepository(session)
                row = games.get_game(game_id)
                moves = MoveRepository(session).list_moves(game_id)
                if row.version != expected_version or steps < 1 or steps > len(moves):
                    raise ApiError("GAME_STATE_CONFLICT", "Game state changed; retry undo")
                new_version = expected_version - steps
                snapshot = games.get_snapshot(game_id)
                new_state = snapshot.initial_state if new_version == 0 else moves[new_version - 1].turn.state
                games.revert_game_state(row, expected_version, new_version, new_state)
                MoveRepository(session).delete_moves_after(game_id, new_version)
                session.flush()
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def list_moves(self, game_id: str) -> list[StoredMove]:
        return await asyncio.to_thread(self._list_moves, game_id)

    def _list_moves(self, game_id: str) -> list[StoredMove]:
        try:
            with self.sessions() as session:
                GameRepository(session).get_game(game_id)
                return MoveRepository(session).list_moves(game_id)
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def read_replay(self, game_id: str) -> tuple[StoredGame, list[StoredMove]]:
        return await asyncio.to_thread(self._read_replay, game_id)

    def _read_replay(self, game_id: str) -> tuple[StoredGame, list[StoredMove]]:
        try:
            # One InnoDB repeatable-read transaction keeps the header and turns consistent.
            with self.sessions.begin() as session:
                snapshot = GameRepository(session).get_snapshot(game_id)
                moves = MoveRepository(session).list_moves(game_id)
                return snapshot, moves
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    def close(self) -> None:
        self.engine.dispose()

    async def create_remote_room(self, state: GameState, token_hash: str, code: str,
                                 device_id: str, public: bool,
                                 expires_at) -> StoredRemoteRoom:
        return await asyncio.to_thread(self._create_remote_room, state, token_hash, code,
                                       device_id, public, expires_at)

    def _create_remote_room(self, state, token_hash, code, device_id, public, expires_at):
        try:
            with self.sessions.begin() as session:
                return RemoteRepository(session).create(state, token_hash, code,
                                                        device_id, public, expires_at)
        except IntegrityError as exc:
            raise ApiError("REMOTE_CODE_CONFLICT", "Invite code already exists") from exc
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def join_remote_room(self, code: str, token_hash: str,
                               device_id: str, now) -> StoredRemoteRoom:
        return await asyncio.to_thread(self._join_remote_room, code, token_hash, device_id, now)

    def _join_remote_room(self, code, token_hash, device_id, now):
        try:
            with self.sessions.begin() as session:
                return RemoteRepository(session).join(code, token_hash, device_id, now)
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def match_remote_room(self, state: GameState, token_hash: str, code: str,
                                device_id: str, expires_at, now) -> StoredRemoteRoom:
        return await asyncio.to_thread(self._match_remote_room, state, token_hash, code,
                                       device_id, expires_at, now)

    def _match_remote_room(self, state, token_hash, code, device_id, expires_at, now):
        try:
            # Serialize the empty-queue case across server processes: row locks alone
            # cannot prevent two first-time callers from creating separate rooms.
            with self.engine.connect() as connection:
                acquired = connection.scalar(text("SELECT GET_LOCK('wuma_remote_match', 10)"))
                connection.commit()
                if acquired != 1:
                    raise ApiError("DATABASE_UNAVAILABLE", "Matchmaking is busy")
                try:
                    with connection.begin():
                        with self.sessions(bind=connection) as session:
                            room = RemoteRepository(session).match(
                                state, token_hash, code, device_id, expires_at, now)
                            session.commit()
                            return room
                finally:
                    connection.execute(text("SELECT RELEASE_LOCK('wuma_remote_match')"))
                    connection.commit()
        except IntegrityError as exc:
            raise ApiError("REMOTE_CODE_CONFLICT", "Invite code already exists") from exc
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def get_remote_room(self, game_id: str) -> StoredRemoteRoom:
        return await asyncio.to_thread(self._get_remote_room, game_id)

    def _get_remote_room(self, game_id):
        try:
            with self.sessions() as session:
                return RemoteRepository.stored(RemoteRepository(session).get(game_id))
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def cancel_remote_room(self, game_id: str,
                                 token_hash: str) -> StoredRemoteRoom:
        return await asyncio.to_thread(self._cancel_remote_room, game_id, token_hash)

    def _cancel_remote_room(self, game_id, token_hash):
        try:
            with self.sessions.begin() as session:
                return RemoteRepository(session).cancel(game_id, token_hash)
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def get_remote_move(self, game_id: str,
                              request_id: str) -> StoredMove | None:
        return await asyncio.to_thread(self._get_remote_move, game_id, request_id)

    def _get_remote_move(self, game_id, request_id):
        try:
            with self.sessions() as session:
                return RemoteRepository(session).get_move(game_id, request_id)
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def commit_remote_turn(self, game_id: str, token_hash: str,
                                 expected_version: int, request_id: str,
                                 turn: TurnResult) -> StoredMove:
        return await asyncio.to_thread(self._commit_remote_turn, game_id, token_hash,
                                       expected_version, request_id, turn)

    def _commit_remote_turn(self, game_id, token_hash, expected_version, request_id, turn):
        try:
            with self.sessions.begin() as session:
                return RemoteRepository(session).commit_turn(game_id, token_hash,
                                                              expected_version, request_id, turn)
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def commit_analysis(self, game_id: str, expected_version: int,
                              analysis: PositionAnalysis) -> None:
        await asyncio.to_thread(self._commit_analysis, game_id, expected_version, analysis)

    def _commit_analysis(self, game_id: str, expected_version: int,
                         analysis: PositionAnalysis) -> None:
        try:
            with self.sessions.begin() as session:
                row = session.scalar(select(GameModel).where(GameModel.id == game_id).with_for_update())
                if row is None:
                    raise ApiError("GAME_NOT_FOUND", "Game not found")
                if row.version != expected_version:
                    raise ApiError("GAME_STATE_CONFLICT", "Game state changed; retry analysis")
                session.add(AiAnalysisModel(
                    game_id=game_id, game_version=expected_version,
                    analyzed_player=analysis.analyzedPlayer,
                    best_move=analysis.bestMove.model_dump(by_alias=True) if analysis.bestMove else None,
                    best_score=analysis.bestScore, score_perspective=analysis.scorePerspective,
                    evaluation_before=analysis.evaluationBefore.model_dump(mode="json"),
                    evaluation_breakdown=analysis.evaluationBreakdown.model_dump(mode="json"),
                    candidate_moves=[item.model_dump(mode="json", by_alias=True)
                                     for item in analysis.candidateMoves],
                    threats=[item.model_dump(mode="json", by_alias=True) for item in analysis.threats],
                    search_depth=analysis.searchDepth, nodes_searched=analysis.nodesSearched,
                    thinking_time_ms=analysis.thinkingTimeMs, algorithm=analysis.algorithm,
                    tt_hits=analysis.ttHits, timed_out=analysis.timedOut,
                    terminal=analysis.terminal, winner=analysis.winner,
                    winner_reason=analysis.winnerReason,
                ))
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def get_review(self, game_id: str, player: str, version: int) -> GameReview | None:
        return await asyncio.to_thread(self._get_review, game_id, player, version)

    @staticmethod
    def _read_review(session, game_id: str, player: str, version: int) -> GameReview | None:
        row = session.scalar(select(GameReviewModel).where(
            GameReviewModel.game_id == game_id,
            GameReviewModel.reviewed_player == player,
            GameReviewModel.review_config_version == version))
        if row is None:
            return None
        moves = session.scalars(select(MoveReviewModel).where(
            MoveReviewModel.game_review_id == row.id).order_by(MoveReviewModel.turn_number)).all()
        return GameReview.model_validate({
            "id": row.id, "gameId": row.game_id, "reviewedPlayer": row.reviewed_player,
            "overallScore": row.overall_score, "goodMoves": row.good_moves,
            "normalMoves": row.normal_moves, "mistakes": row.mistakes,
            "blunders": row.blunders, "bestMoveRate": row.best_move_rate,
            "turningPoints": row.turning_points, "winner": row.winner,
            "winnerReason": row.winner_reason, "reviewConfig": row.review_config,
            "reviewConfigVersion": row.review_config_version,
            "moveReviews": [move.analysis for move in moves],
            "createdAt": row.created_at.replace(tzinfo=timezone.utc),
        })

    def _get_review(self, game_id: str, player: str, version: int) -> GameReview | None:
        try:
            with self.sessions() as session:
                GameRepository(session).get_game(game_id)
                return self._read_review(session, game_id, player, version)
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def commit_review(self, review: GameReview, expected_version: int) -> GameReview:
        return await asyncio.to_thread(self._commit_review, review, expected_version)

    def _commit_review(self, review: GameReview, expected_version: int) -> GameReview:
        try:
            with self.sessions.begin() as session:
                row = session.scalar(select(GameModel).where(
                    GameModel.id == review.gameId).with_for_update())
                if row is None:
                    raise ApiError("GAME_NOT_FOUND", "Game not found")
                if row.version != expected_version or row.status != "FINISHED":
                    raise ApiError("GAME_STATE_CONFLICT", "Game state changed during review")
                existing = self._read_review(session, review.gameId,
                                             review.reviewedPlayer, review.reviewConfigVersion)
                if existing is not None:
                    return existing
                session.add(GameReviewModel(
                    id=review.id, game_id=review.gameId,
                    reviewed_player=review.reviewedPlayer, overall_score=review.overallScore,
                    good_moves=review.goodMoves, normal_moves=review.normalMoves,
                    mistakes=review.mistakes, blunders=review.blunders,
                    best_move_rate=review.bestMoveRate, turning_points=review.turningPoints,
                    winner=review.winner, winner_reason=review.winnerReason,
                    review_config=review.reviewConfig.model_dump(mode="json"),
                    review_config_version=review.reviewConfigVersion,
                    created_at=review.createdAt.replace(tzinfo=None),
                ))
                for move in review.moveReviews:
                    session.add(MoveReviewModel(
                        game_review_id=review.id, game_move_id=move.gameMoveId,
                        turn_number=move.turn, player=move.player,
                        actual_move=move.actualMove.model_dump(mode="json", by_alias=True),
                        best_move=move.bestMove.model_dump(mode="json", by_alias=True),
                        score_before=move.scoreBefore, score_after=move.scoreAfter,
                        best_score=move.bestScore, actual_move_score=move.actualMoveScore,
                        score_loss=move.scoreLoss, category=move.category,
                        evaluation_before=move.evaluationBefore.model_dump(mode="json"),
                        evaluation_after=move.evaluationAfter.model_dump(mode="json"),
                        candidate_moves=[item.model_dump(mode="json", by_alias=True)
                                         for item in move.bestCandidateMoves],
                        threats=[item.model_dump(mode="json", by_alias=True)
                                 for item in move.threatsBefore],
                        engine_explanation=move.engineExplanation,
                        search_depth=move.searchDepth, timed_out=move.timedOut,
                        analysis=move.model_dump(mode="json", by_alias=True),
                        created_at=review.createdAt.replace(tzinfo=None),
                    ))
                session.flush()
                return review
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def get_explanation(self, review_id: str, prompt_version: str) -> ExplanationBundle | None:
        return await asyncio.to_thread(self._get_explanation, review_id, prompt_version)

    @staticmethod
    def _read_explanation(session, review_id: str, prompt_version: str) -> ExplanationBundle | None:
        row = session.scalar(select(ReviewExplanationModel).where(
            ReviewExplanationModel.game_review_id == review_id,
            ReviewExplanationModel.prompt_version == prompt_version))
        return ExplanationBundle.model_validate(row.payload) if row is not None else None

    def _get_explanation(self, review_id: str, prompt_version: str) -> ExplanationBundle | None:
        try:
            with self.sessions() as session:
                return self._read_explanation(session, review_id, prompt_version)
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def commit_explanation(self, bundle: ExplanationBundle) -> ExplanationBundle:
        return await asyncio.to_thread(self._commit_explanation, bundle)

    def _commit_explanation(self, bundle: ExplanationBundle) -> ExplanationBundle:
        try:
            with self.sessions.begin() as session:
                parent = session.scalar(select(GameReviewModel).where(
                    GameReviewModel.id == bundle.gameReviewId).with_for_update())
                if parent is None:
                    raise ApiError("REVIEW_NOT_FOUND", "Review has not been generated")
                existing = self._read_explanation(session, bundle.gameReviewId,
                                                   bundle.promptVersion)
                if existing is not None:
                    return existing
                session.add(ReviewExplanationModel(
                    game_review_id=bundle.gameReviewId,
                    prompt_version=bundle.promptVersion,
                    provider=bundle.gameExplanation.provider,
                    model=bundle.gameExplanation.model,
                    fallback_used=(bundle.gameExplanation.fallbackUsed or
                                   any(item.fallbackUsed for item in bundle.moveExplanations)),
                    payload=bundle.model_dump(mode="json"),
                    created_at=bundle.createdAt.replace(tzinfo=None),
                ))
                session.flush()
                return bundle
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def get_coach_hint(self, game_id: str, game_version: int, player: str,
                             level: int, prompt_version: str) -> CoachHint | None:
        return await asyncio.to_thread(self._get_coach_hint, game_id, game_version,
                                       player, level, prompt_version)

    @staticmethod
    def _read_coach_hint(session, game_id: str, game_version: int, player: str,
                         level: int, prompt_version: str) -> CoachHint | None:
        row = session.scalar(select(CoachHintModel).where(
            CoachHintModel.game_id == game_id,
            CoachHintModel.game_version == game_version,
            CoachHintModel.analyzed_player == player,
            CoachHintModel.hint_level == level,
            CoachHintModel.prompt_version == prompt_version))
        if row is None:
            return None
        return CoachHint(gameId=row.game_id, gameVersion=row.game_version,
                         analyzedPlayer=row.analyzed_player, level=row.hint_level,
                         hintText=row.hint_text, focusTopics=row.focus_topics,
                         candidateFromNodes=row.candidate_nodes, bestMove=row.best_move,
                         provider=row.provider, model=row.model,
                         promptVersion=row.prompt_version, fallbackUsed=row.fallback_used,
                         generatedAt=row.created_at.replace(tzinfo=timezone.utc))

    def _get_coach_hint(self, game_id: str, game_version: int, player: str,
                        level: int, prompt_version: str) -> CoachHint | None:
        try:
            with self.sessions() as session:
                return self._read_coach_hint(session, game_id, game_version,
                                             player, level, prompt_version)
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def commit_coach_hint(self, hint: CoachHint) -> CoachHint:
        return await asyncio.to_thread(self._commit_coach_hint, hint)

    def _commit_coach_hint(self, hint: CoachHint) -> CoachHint:
        try:
            with self.sessions.begin() as session:
                row = session.scalar(select(GameModel).where(
                    GameModel.id == hint.gameId).with_for_update())
                if row is None:
                    raise ApiError("GAME_NOT_FOUND", "Game not found")
                if (row.version != hint.gameVersion or row.status != "PLAYING" or
                    row.current_player != hint.analyzedPlayer):
                    raise ApiError("GAME_STATE_CONFLICT", "Game state changed during coaching")
                existing = self._read_coach_hint(session, hint.gameId, hint.gameVersion,
                                                 hint.analyzedPlayer, hint.level,
                                                 hint.promptVersion)
                if existing is not None:
                    return existing
                session.add(CoachHintModel(
                    game_id=hint.gameId, game_version=hint.gameVersion,
                    analyzed_player=hint.analyzedPlayer, hint_level=hint.level,
                    hint_text=hint.hintText, focus_topics=hint.focusTopics,
                    candidate_nodes=hint.candidateFromNodes,
                    best_move=hint.bestMove.model_dump(by_alias=True) if hint.bestMove else None,
                    provider=hint.provider, model=hint.model,
                    prompt_version=hint.promptVersion, fallback_used=hint.fallbackUsed,
                    created_at=hint.generatedAt.replace(tzinfo=None),
                ))
                session.flush()
                return hint
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def list_training_sources(self, review_id: str) -> list[TrainingSource]:
        return await asyncio.to_thread(self._list_training_sources, review_id)

    def _list_training_sources(self, review_id: str) -> list[TrainingSource]:
        try:
            with self.sessions() as session:
                return TrainingRepository(session).sources(review_id)
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def commit_training_items(self, review_id: str,
                                    items: list[TrainingItemInternal]) -> list[TrainingItemInternal]:
        return await asyncio.to_thread(self._commit_training_items, review_id, items)

    def _commit_training_items(self, review_id: str,
                               items: list[TrainingItemInternal]) -> list[TrainingItemInternal]:
        try:
            with self.sessions.begin() as session:
                return TrainingRepository(session).commit_items(review_id, items)
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def list_training_items(self, limit: int, offset: int, category: str | None,
                                  training_type: str | None,
                                  user_id: str | None = None) -> tuple[list[TrainingItemInternal], int]:
        return await asyncio.to_thread(self._list_training_items, limit, offset,
                                       category, training_type, user_id)

    def _list_training_items(self, limit: int, offset: int, category: str | None,
                             training_type: str | None,
                             user_id: str | None) -> tuple[list[TrainingItemInternal], int]:
        try:
            with self.sessions() as session:
                return TrainingRepository(session).list_items(limit, offset, category, training_type, user_id)
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def get_training_item(self, training_id: str) -> TrainingItemInternal:
        return await asyncio.to_thread(self._get_training_item, training_id)

    def _get_training_item(self, training_id: str) -> TrainingItemInternal:
        try:
            with self.sessions() as session:
                return TrainingRepository(session).get_item(training_id)
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def get_training_attempt(self, client_attempt_id: str,
                                   user_id: str | None = None) -> TrainingAnswerResult | None:
        return await asyncio.to_thread(self._get_training_attempt, client_attempt_id, user_id)

    def _get_training_attempt(self, client_attempt_id: str,
                             user_id: str | None) -> TrainingAnswerResult | None:
        try:
            with self.sessions() as session:
                return TrainingRepository(session).get_attempt(client_attempt_id, user_id)
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc

    async def commit_training_record(self, record: TrainingAnswerResult,
                                     user_id: str | None = None) -> TrainingAnswerResult:
        return await asyncio.to_thread(self._commit_training_record, record, user_id)

    def _commit_training_record(self, record: TrainingAnswerResult,
                                user_id: str | None) -> TrainingAnswerResult:
        try:
            with self.sessions.begin() as session:
                return TrainingRepository(session).commit_record(record, user_id)
        except IntegrityError as exc:
            raise ApiError("TRAINING_ATTEMPT_CONFLICT", "Attempt ID already used") from exc
        except SQLAlchemyError as exc:
            raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed") from exc
