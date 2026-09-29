"""Persistence contract and an explicit in-memory implementation for isolated API tests."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from backend.app.core.errors import ApiError
from backend.app.schemas.game import GameReview, GameState, PositionAnalysis, SearchResult, TurnResult
from backend.app.schemas.explanation import ExplanationBundle
from backend.app.schemas.coach import CoachHint
from backend.app.schemas.training import (TrainingAnswerResult, TrainingItemInternal,
                                          TrainingSource)


@dataclass(frozen=True)
class StoredGame:
    game_id: str
    initial_state: GameState
    state: GameState
    version: int
    mode: str = "LOCAL"
    ai_player: str | None = None
    ai_level: str | None = None
    user_id: str | None = None


@dataclass(frozen=True)
class StoredMove:
    turn_number: int
    actor_type: str
    turn: TurnResult
    search: SearchResult | None
    game_move_id: int = 0


@dataclass(frozen=True)
class StoredRemoteRoom:
    game_id: str
    invite_code: str
    host_token_hash: str
    guest_token_hash: str | None
    host_device_id: str
    guest_device_id: str | None
    public: bool
    status: str
    expires_at: datetime


class GameStore(Protocol):
    async def ping(self) -> None: ...
    async def register_device(self, token_hash: str) -> str: ...
    async def resolve_device(self, token_hash: str) -> str | None: ...
    async def personal_games(self, user_id: str, limit: int,
                             cursor: tuple[datetime, str] | None,
                             status: str | None = None) -> tuple[list[dict], bool]: ...
    async def personal_profile(self, user_id: str) -> dict: ...

    async def create(self, state: GameState, mode: str = "LOCAL",
                     ai_player: str | None = None, ai_level: str | None = None,
                     user_id: str | None = None) -> str: ...
    async def get_snapshot(self, game_id: str) -> StoredGame: ...
    async def commit_turn(self, game_id: str, expected_version: int, turn: TurnResult,
                          actor_type: str, search: SearchResult | None = None) -> None: ...
    async def revert_moves(self, game_id: str, expected_version: int, steps: int) -> None: ...
    async def commit_resign(self, game_id: str, expected_version: int, state: GameState) -> None: ...
    async def list_moves(self, game_id: str) -> list[StoredMove]: ...
    async def read_replay(self, game_id: str) -> tuple[StoredGame, list[StoredMove]]: ...
    async def lock_for(self, game_id: str) -> asyncio.Lock: ...
    async def commit_analysis(self, game_id: str, expected_version: int,
                              analysis: PositionAnalysis) -> None: ...
    async def get_review(self, game_id: str, player: str, version: int) -> GameReview | None: ...
    async def commit_review(self, review: GameReview, expected_version: int) -> GameReview: ...
    async def get_explanation(self, review_id: str, prompt_version: str) -> ExplanationBundle | None: ...
    async def commit_explanation(self, bundle: ExplanationBundle) -> ExplanationBundle: ...
    async def get_coach_hint(self, game_id: str, game_version: int, player: str,
                             level: int, prompt_version: str) -> CoachHint | None: ...
    async def commit_coach_hint(self, hint: CoachHint) -> CoachHint: ...
    async def list_training_sources(self, review_id: str) -> list[TrainingSource]: ...
    async def commit_training_items(self, review_id: str,
                                    items: list[TrainingItemInternal]) -> list[TrainingItemInternal]: ...
    async def list_training_items(self, limit: int, offset: int, category: str | None,
                                  training_type: str | None,
                                  user_id: str | None = None) -> tuple[list[TrainingItemInternal], int]: ...
    async def get_training_item(self, training_id: str) -> TrainingItemInternal: ...
    async def get_training_attempt(self, client_attempt_id: str,
                                   user_id: str | None = None) -> TrainingAnswerResult | None: ...
    async def commit_training_record(self, record: TrainingAnswerResult,
                                     user_id: str | None = None) -> TrainingAnswerResult: ...
    async def create_remote_room(self, state: GameState, token_hash: str, code: str,
                                 device_id: str, public: bool,
                                 expires_at: datetime) -> StoredRemoteRoom: ...
    async def join_remote_room(self, code: str, token_hash: str,
                               device_id: str, now: datetime) -> StoredRemoteRoom: ...
    async def match_remote_room(self, state: GameState, token_hash: str, code: str,
                                device_id: str, expires_at: datetime,
                                now: datetime) -> StoredRemoteRoom: ...
    async def get_remote_room(self, game_id: str) -> StoredRemoteRoom: ...
    async def cancel_remote_room(self, game_id: str,
                                 token_hash: str) -> StoredRemoteRoom: ...
    async def get_remote_move(self, game_id: str,
                              request_id: str) -> StoredMove | None: ...
    async def commit_remote_turn(self, game_id: str, token_hash: str,
                                 expected_version: int, request_id: str,
                                 turn: TurnResult) -> StoredMove: ...


class InMemoryGameStore:
    """Test-only store; production creates MySQLGameStore by default."""

    def __init__(self):
        self._games: dict[str, StoredGame] = {}
        self._moves: dict[str, list[StoredMove]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._analyses: dict[str, list[tuple[int, PositionAnalysis]]] = {}
        self._reviews: dict[tuple[str, str, int], GameReview] = {}
        self._explanations: dict[tuple[str, str], ExplanationBundle] = {}
        self._coach_hints: dict[tuple[str, int, str, int, str], CoachHint] = {}
        self._training_items: dict[str, TrainingItemInternal] = {}
        self._training_keys: dict[tuple[str, int, str, int], str] = {}
        self._training_records: dict[str, TrainingAnswerResult] = {}
        self._catalog_lock = asyncio.Lock()
        self._remote_rooms: dict[str, StoredRemoteRoom] = {}
        self._remote_requests: dict[tuple[str, str], StoredMove] = {}
        self._device_users: dict[str, str] = {}
        self._game_created: dict[str, datetime] = {}
        self._training_owners: dict[str, str | None] = {}

    async def ping(self) -> None:
        return None

    async def register_device(self, token_hash: str) -> str:
        async with self._catalog_lock:
            user_id = uuid4().hex
            self._device_users[token_hash] = user_id
            return user_id

    async def resolve_device(self, token_hash: str) -> str | None:
        return self._device_users.get(token_hash)

    async def personal_games(self, user_id: str, limit: int,
                             cursor: tuple[datetime, str] | None,
                             status: str | None = None) -> tuple[list[dict], bool]:
        rows = [(self._game_created[id], game) for id, game in self._games.items()
                if game.user_id == user_id and game.mode != "REMOTE" and
                (status is None or game.state.game_status == status)]
        rows.sort(key=lambda row: (row[0], row[1].game_id), reverse=True)
        if cursor:
            rows = [row for row in rows if (row[0], row[1].game_id) < cursor]
        selected = rows[:limit + 1]
        return [self._personal_row(date, game) for date, game in selected[:limit]], len(selected) > limit

    def _personal_row(self, date: datetime, game: StoredGame) -> dict:
        return {"gameId": game.game_id, "mode": game.mode, "status": game.state.game_status,
                "winner": game.state.winner, "startedAt": date.isoformat(),
                "finishedAt": None, "turns": game.version,
                "reviewAvailable": any(key[0] == game.game_id for key in self._reviews),
                "cursorDate": date.isoformat()}

    async def personal_profile(self, user_id: str) -> dict:
        games = [game for game in self._games.values()
                 if game.user_id == user_id and game.mode != "REMOTE"]
        records = [record for key, record in self._training_records.items()
                   if self._training_owners.get(key) == user_id]
        ai_finished = [game for game in games if game.mode == "AI" and
                       game.state.game_status == "FINISHED"]
        wins = sum(game.state.winner == ("B" if game.ai_player == "A" else "A")
                   for game in ai_finished)
        losses = sum(game.state.winner == game.ai_player for game in ai_finished)
        return {"id": user_id, "nickname": "本机棋手", "games": len(games),
                "finishedGames": sum(game.state.game_status == "FINISHED" for game in games),
                "wins": wins, "losses": losses,
                "reviewedGames": len({key[0] for key in self._reviews
                                      if self._games[key[0]].user_id == user_id}),
                "training": len(records),
                "correct": sum(record.result == "CORRECT" for record in records)}

    async def create(self, state: GameState, mode: str = "LOCAL",
                     ai_player: str | None = None, ai_level: str | None = None,
                     user_id: str | None = None) -> str:
        async with self._catalog_lock:
            game_id = uuid4().hex
            self._games[game_id] = StoredGame(game_id, state, state, 0, mode, ai_player, ai_level, user_id)
            self._game_created[game_id] = datetime.now(timezone.utc)
            self._moves[game_id] = []
            self._locks[game_id] = asyncio.Lock()
            self._analyses[game_id] = []
            return game_id

    async def lock_for(self, game_id: str) -> asyncio.Lock:
        async with self._catalog_lock:
            lock = self._locks.get(game_id)
        if lock is None:
            raise ApiError("GAME_NOT_FOUND", "Game not found")
        return lock

    async def get_snapshot(self, game_id: str) -> StoredGame:
        game = self._games.get(game_id)
        if game is None:
            raise ApiError("GAME_NOT_FOUND", "Game not found")
        return game

    async def commit_turn(self, game_id: str, expected_version: int, turn: TurnResult,
                          actor_type: str, search: SearchResult | None = None) -> None:
        game = await self.get_snapshot(game_id)
        if game.version != expected_version or game.state != turn.before_state:
            raise ApiError("GAME_STATE_CONFLICT", "Game state changed; retry the move")
        self._moves[game_id].append(StoredMove(game.version + 1, actor_type, turn, search,
                                               game.version + 1))
        self._games[game_id] = StoredGame(game_id, game.initial_state, turn.state,
                                          game.version + 1, game.mode, game.ai_player, game.ai_level,
                                          game.user_id)

    async def revert_moves(self, game_id: str, expected_version: int, steps: int) -> None:
        game = await self.get_snapshot(game_id)
        moves = self._moves[game_id]
        if game.version != expected_version or steps < 1 or steps > len(moves):
            raise ApiError("GAME_STATE_CONFLICT", "Game state changed; retry undo")
        new_version = expected_version - steps
        new_state = game.initial_state if new_version == 0 else moves[new_version - 1].turn.state
        self._moves[game_id] = moves[:new_version]
        self._games[game_id] = StoredGame(game_id, game.initial_state, new_state, new_version,
                                          game.mode, game.ai_player, game.ai_level, game.user_id)

    async def commit_resign(self, game_id: str, expected_version: int, state: GameState) -> None:
        game = await self.get_snapshot(game_id)
        if game.version != expected_version or game.state.game_status == "FINISHED":
            raise ApiError("GAME_STATE_CONFLICT", "Game state changed; retry resign")
        self._games[game_id] = StoredGame(game_id, game.initial_state, state, game.version + 1,
                                          game.mode, game.ai_player, game.ai_level, game.user_id)

    async def list_moves(self, game_id: str) -> list[StoredMove]:
        await self.get_snapshot(game_id)
        return list(self._moves[game_id])

    async def read_replay(self, game_id: str) -> tuple[StoredGame, list[StoredMove]]:
        lock = await self.lock_for(game_id)
        async with lock:
            return await self.get_snapshot(game_id), await self.list_moves(game_id)

    async def update(self, game_id: str, state: GameState) -> None:
        """Fixture setup for legacy API tests; never used by production."""
        lock = await self.lock_for(game_id)
        async with lock:
            game = await self.get_snapshot(game_id)
            self._games[game_id] = StoredGame(game_id, state, state, game.version,
                                              game.mode, game.ai_player, game.ai_level,
                                              game.user_id)

    def _create_remote_unlocked(self, state: GameState, token_hash: str, code: str,
                                device_id: str, public: bool,
                                expires_at: datetime) -> StoredRemoteRoom:
        if any(room.invite_code == code for room in self._remote_rooms.values()):
            raise ApiError("REMOTE_CODE_CONFLICT", "Invite code already exists")
        game_id = uuid4().hex
        self._games[game_id] = StoredGame(game_id, state, state, 0, "REMOTE")
        self._game_created[game_id] = datetime.now(timezone.utc)
        self._moves[game_id] = []
        self._locks[game_id] = asyncio.Lock()
        room = StoredRemoteRoom(game_id, code, token_hash, None, device_id,
                                None, public, "WAITING", expires_at)
        self._remote_rooms[game_id] = room
        return room

    async def create_remote_room(self, state: GameState, token_hash: str, code: str,
                                 device_id: str, public: bool,
                                 expires_at: datetime) -> StoredRemoteRoom:
        async with self._catalog_lock:
            return self._create_remote_unlocked(state, token_hash, code, device_id,
                                                public, expires_at)

    async def join_remote_room(self, code: str, token_hash: str,
                               device_id: str, now: datetime) -> StoredRemoteRoom:
        async with self._catalog_lock:
            room = next((item for item in self._remote_rooms.values()
                         if item.invite_code == code), None)
            if room is None:
                raise ApiError("REMOTE_ROOM_NOT_FOUND", "Room not found")
            if room.status != "WAITING" or room.expires_at <= now:
                raise ApiError("REMOTE_ROOM_UNAVAILABLE", "Room is no longer available")
            if room.host_device_id == device_id:
                raise ApiError("REMOTE_SELF_JOIN", "Use another device to join")
            joined = StoredRemoteRoom(room.game_id, room.invite_code,
                                      room.host_token_hash, token_hash,
                                      room.host_device_id, device_id, room.public,
                                      "PLAYING", room.expires_at)
            self._remote_rooms[room.game_id] = joined
            return joined

    async def match_remote_room(self, state: GameState, token_hash: str, code: str,
                                device_id: str, expires_at: datetime,
                                now: datetime) -> StoredRemoteRoom:
        async with self._catalog_lock:
            candidate = next((item for item in self._remote_rooms.values()
                              if item.public and item.status == "WAITING"
                              and item.expires_at > now
                              and item.host_device_id != device_id), None)
            if candidate is None:
                return self._create_remote_unlocked(state, token_hash, code,
                                                    device_id, True, expires_at)
            joined = StoredRemoteRoom(candidate.game_id, candidate.invite_code,
                                      candidate.host_token_hash, token_hash,
                                      candidate.host_device_id, device_id, True,
                                      "PLAYING", candidate.expires_at)
            self._remote_rooms[candidate.game_id] = joined
            return joined

    async def get_remote_room(self, game_id: str) -> StoredRemoteRoom:
        room = self._remote_rooms.get(game_id)
        if room is None:
            raise ApiError("REMOTE_ROOM_NOT_FOUND", "Room not found")
        return room

    async def cancel_remote_room(self, game_id: str,
                                 token_hash: str) -> StoredRemoteRoom:
        async with self._catalog_lock:
            room = await self.get_remote_room(game_id)
            if room.host_token_hash != token_hash:
                raise ApiError("REMOTE_ACCESS_DENIED", "This seat is unavailable")
            if room.status != "WAITING":
                raise ApiError("REMOTE_ROOM_UNAVAILABLE", "Room is no longer waiting")
            cancelled = StoredRemoteRoom(room.game_id, room.invite_code,
                                         room.host_token_hash, room.guest_token_hash,
                                         room.host_device_id, room.guest_device_id,
                                         room.public, "CANCELLED", room.expires_at)
            self._remote_rooms[game_id] = cancelled
            return cancelled

    async def get_remote_move(self, game_id: str,
                              request_id: str) -> StoredMove | None:
        return self._remote_requests.get((game_id, request_id))

    async def commit_remote_turn(self, game_id: str, token_hash: str,
                                 expected_version: int, request_id: str,
                                 turn: TurnResult) -> StoredMove:
        room = await self.get_remote_room(game_id)
        seat = "A" if room.host_token_hash == token_hash else (
            "B" if room.guest_token_hash == token_hash else None)
        if seat is None:
            raise ApiError("REMOTE_ACCESS_DENIED", "This seat is unavailable")
        existing = await self.get_remote_move(game_id, request_id)
        if existing is not None:
            if (existing.turn.before_state.current_player != seat or
                existing.turn.move != turn.move or
                existing.turn_number - 1 != expected_version):
                raise ApiError("REMOTE_REQUEST_CONFLICT", "Request ID already used")
            return existing
        game = await self.get_snapshot(game_id)
        if room.status != "PLAYING":
            raise ApiError("REMOTE_ROOM_UNAVAILABLE", "Opponent has not joined")
        if game.state.current_player != seat:
            raise ApiError("NOT_YOUR_TURN", "Wait for your turn")
        if game.version != expected_version or game.state != turn.before_state:
            raise ApiError("GAME_STATE_CONFLICT", "Game state changed")
        move = StoredMove(expected_version + 1, "HUMAN", turn, None,
                          expected_version + 1)
        self._moves[game_id].append(move)
        self._remote_requests[(game_id, request_id)] = move
        self._games[game_id] = StoredGame(game_id, game.initial_state, turn.state,
                                          expected_version + 1, "REMOTE")
        return move

    async def commit_analysis(self, game_id: str, expected_version: int,
                              analysis: PositionAnalysis) -> None:
        lock = await self.lock_for(game_id)
        async with lock:
            game = await self.get_snapshot(game_id)
            if game.version != expected_version:
                raise ApiError("GAME_STATE_CONFLICT", "Game state changed; retry analysis")
            self._analyses[game_id].append((expected_version, analysis))

    async def get_review(self, game_id: str, player: str, version: int) -> GameReview | None:
        await self.get_snapshot(game_id)
        return self._reviews.get((game_id, player, version))

    async def commit_review(self, review: GameReview, expected_version: int) -> GameReview:
        lock = await self.lock_for(review.gameId)
        async with lock:
            game = await self.get_snapshot(review.gameId)
            if game.version != expected_version or game.state.game_status != "FINISHED":
                raise ApiError("GAME_STATE_CONFLICT", "Game state changed during review")
            key = (review.gameId, review.reviewedPlayer, review.reviewConfigVersion)
            if key not in self._reviews:
                self._reviews[key] = review
            return self._reviews[key]

    async def get_explanation(self, review_id: str, prompt_version: str) -> ExplanationBundle | None:
        return self._explanations.get((review_id, prompt_version))

    async def commit_explanation(self, bundle: ExplanationBundle) -> ExplanationBundle:
        async with self._catalog_lock:
            key = (bundle.gameReviewId, bundle.promptVersion)
            if key not in self._explanations:
                self._explanations[key] = bundle
            return self._explanations[key]

    async def get_coach_hint(self, game_id: str, game_version: int, player: str,
                             level: int, prompt_version: str) -> CoachHint | None:
        return self._coach_hints.get((game_id, game_version, player, level, prompt_version))

    async def commit_coach_hint(self, hint: CoachHint) -> CoachHint:
        lock = await self.lock_for(hint.gameId)
        async with lock:
            game = await self.get_snapshot(hint.gameId)
            if (game.version != hint.gameVersion or game.state.game_status != "PLAYING" or
                game.state.current_player != hint.analyzedPlayer):
                raise ApiError("GAME_STATE_CONFLICT", "Game state changed during coaching")
            key = (hint.gameId, hint.gameVersion, hint.analyzedPlayer,
                   hint.level, hint.promptVersion)
            if key not in self._coach_hints:
                self._coach_hints[key] = hint
            return self._coach_hints[key]

    async def list_training_sources(self, review_id: str) -> list[TrainingSource]:
        review = next((item for item in self._reviews.values() if item.id == review_id), None)
        if review is None:
            raise ApiError("REVIEW_REQUIRED", "Generate a game review first")
        moves = {move.game_move_id: move for move in self._moves[review.gameId]}
        return [TrainingSource(sourceMoveId=review_move.gameMoveId,
                               sourceMoveReviewId=review_move.gameMoveId,
                               stateSnapshot=moves[review_move.gameMoveId].turn.before_state,
                               stateSchemaVersion=1,
                               originalMove=moves[review_move.gameMoveId].turn.move)
                for review_move in review.moveReviews]

    async def commit_training_items(self, review_id: str,
                                    items: list[TrainingItemInternal]) -> list[TrainingItemInternal]:
        async with self._catalog_lock:
            review = next((item for item in self._reviews.values() if item.id == review_id), None)
            if review is None or self._games[review.gameId].state.game_status != "FINISHED":
                raise ApiError("REVIEW_REQUIRED", "Generate a finished game review first")
            saved = []
            for item in items:
                key = (review_id, item.sourceMoveReviewId,
                       item.trainingType, item.generationVersion)
                if key not in self._training_keys:
                    self._training_keys[key] = item.id
                    self._training_items[item.id] = item
                saved.append(self._training_items[self._training_keys[key]])
            return saved

    async def list_training_items(self, limit: int, offset: int, category: str | None,
                                  training_type: str | None,
                                  user_id: str | None = None) -> tuple[list[TrainingItemInternal], int]:
        items = [item for item in self._training_items.values()
                 if (category is None or item.sourceCategory == category) and
                 (training_type is None or item.trainingType == training_type) and
                 (user_id is None or self._games[item.sourceGameId].user_id == user_id)]
        items.sort(key=lambda item: (item.sourceCategory == "BLUNDER", item.createdAt, item.id),
                   reverse=True)
        return items[offset:offset + limit], len(items)

    async def get_training_item(self, training_id: str) -> TrainingItemInternal:
        item = self._training_items.get(training_id)
        if item is None:
            raise ApiError("TRAINING_NOT_FOUND", "Training question not found")
        return item

    async def get_training_attempt(self, client_attempt_id: str,
                                   user_id: str | None = None) -> TrainingAnswerResult | None:
        if client_attempt_id in self._training_records and self._training_owners.get(client_attempt_id) != user_id:
            raise ApiError("TRAINING_ATTEMPT_CONFLICT", "Attempt ID already used")
        return self._training_records.get(client_attempt_id)

    async def commit_training_record(self, record: TrainingAnswerResult,
                                     user_id: str | None = None) -> TrainingAnswerResult:
        async with self._catalog_lock:
            if record.trainingId not in self._training_items:
                raise ApiError("TRAINING_NOT_FOUND", "Training question not found")
            existing = self._training_records.get(record.clientAttemptId)
            if existing is not None:
                if existing.trainingId != record.trainingId or existing.submittedMove != record.submittedMove:
                    raise ApiError("TRAINING_ATTEMPT_CONFLICT", "Attempt ID already used")
                return existing
            self._training_records[record.clientAttemptId] = record
            self._training_owners[record.clientAttemptId] = user_id
            return record
