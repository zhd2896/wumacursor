from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.core.errors import ApiError
from backend.app.main import create_app
from backend.app.services.game_store import InMemoryGameStore
from backend.app.schemas.game import BoardState, GameState


@pytest.fixture
def client():
    with TestClient(create_app(store=InMemoryGameStore(), require_auth=False)) as test_client:
        yield test_client


def create_game(client: TestClient, first_player: str = "A", mode: str = "LOCAL",
                ai_player: str | None = None) -> tuple[str, dict]:
    body = {"first_player": first_player, "mode": mode}
    if ai_player is not None:
        body.update({"ai_player": ai_player, "ai_level": "STANDARD"})
    response = client.post("/api/v1/game", json=body)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["code"] == 0
    return payload["data"]["game_id"], payload["data"]["state"]


def test_undo_local_game_reverts_last_move(client: TestClient):
    game_id, state = create_game(client)
    move = client.post(f"/api/v1/game/{game_id}/move",
                       json={"from_node": "P01", "to_node": "P02"})
    assert move.status_code == 200, move.text
    undone = client.post(f"/api/v1/game/{game_id}/undo")
    assert undone.status_code == 200, undone.text
    payload = undone.json()["data"]
    assert payload["version"] == 0
    assert payload["state"] == state
    assert client.portal.call(client.app.state.store.list_moves, game_id) == []


def test_undo_ai_game_reverts_human_and_ai_pair(client: TestClient):
    game_id, _ = create_game(client, mode="AI", ai_player="B")
    human = client.post(f"/api/v1/game/{game_id}/move",
                        json={"from_node": "P01", "to_node": "P02"})
    assert human.status_code == 200, human.text
    ai = client.post(f"/api/v1/game/{game_id}/ai-move", json={})
    assert ai.status_code == 200, ai.text
    undone = client.post(f"/api/v1/game/{game_id}/undo")
    assert undone.status_code == 200, undone.text
    assert undone.json()["data"]["version"] == 0
    assert undone.json()["data"]["state"]["current_player"] == "A"
    moves = client.portal.call(client.app.state.store.list_moves, game_id)
    assert moves == []


def test_undo_ai_game_reverts_pending_human_move_before_ai_responds(client: TestClient):
    game_id, _ = create_game(client, mode="AI", ai_player="B")
    human = client.post(f"/api/v1/game/{game_id}/move",
                        json={"from_node": "P01", "to_node": "P02"})
    assert human.status_code == 200, human.text
    undone = client.post(f"/api/v1/game/{game_id}/undo")
    assert undone.status_code == 200, undone.text
    assert undone.json()["data"]["version"] == 0
    assert client.portal.call(client.app.state.store.list_moves, game_id) == []


def test_resign_local_game_finishes_with_resign_reason(client: TestClient):
    game_id, _ = create_game(client)
    move = client.post(f"/api/v1/game/{game_id}/move",
                       json={"from_node": "P01", "to_node": "P02"})
    assert move.status_code == 200, move.text
    resigned = client.post(f"/api/v1/game/{game_id}/resign",
                           json={"resigning_player": "B"})
    assert resigned.status_code == 200, resigned.text
    payload = resigned.json()["data"]
    assert payload["state"]["game_status"] == "FINISHED"
    assert payload["state"]["winner"] == "A"
    assert payload["state"]["winner_reason"] == "RESIGN"
    assert len(client.portal.call(client.app.state.store.list_moves, game_id)) == 1


def test_resign_ai_game_records_human_loss(client: TestClient):
    game_id, _ = create_game(client, mode="AI", ai_player="B")
    resigned = client.post(f"/api/v1/game/{game_id}/resign", json={})
    assert resigned.status_code == 200, resigned.text
    payload = resigned.json()["data"]
    assert payload["state"]["winner"] == "B"
    assert payload["state"]["winner_reason"] == "RESIGN"


def test_create_ai_game_accepts_beginner_level(client: TestClient):
    created = client.post("/api/v1/game", json={"mode": "AI", "first_player": "A",
                                                "ai_player": "B", "ai_level": "BEGINNER"})
    assert created.status_code == 200, created.text
    assert created.json()["data"]["ai_level"] == "BEGINNER"


def test_undo_rejects_empty_board(client: TestClient):
    game_id, _ = create_game(client)
    denied = client.post(f"/api/v1/game/{game_id}/undo")
    assert denied.status_code == 409 and denied.json()["code"] == "UNDO_NOT_AVAILABLE"


def test_ai_game_persists_identity_and_rejects_wrong_actor_turn(client: TestClient):
    created = client.post("/api/v1/game", json={"mode": "AI", "first_player": "A",
                                                "ai_player": "B", "ai_level": "STANDARD"})
    assert created.status_code == 200, created.text
    game = created.json()["data"]
    assert (game["mode"], game["human_player"], game["ai_player"], game["ai_level"]) == (
        "AI", "A", "B", "STANDARD")
    game_id = game["game_id"]
    assert client.get(f"/api/v1/game/{game_id}").json()["data"] == game
    denied = client.post(f"/api/v1/game/{game_id}/ai-move", json={})
    assert denied.status_code == 409 and denied.json()["code"] == "NOT_AI_TURN"
    human = client.post(f"/api/v1/game/{game_id}/move",
                        json={"from_node": "P01", "to_node": "P02"})
    assert human.status_code == 200, human.text
    denied = client.post(f"/api/v1/game/{game_id}/move",
                         json={"from_node": "P05", "to_node": "P04"})
    assert denied.status_code == 409 and denied.json()["code"] == "NOT_HUMAN_TURN"
    ai = client.post(f"/api/v1/game/{game_id}/ai-move", json={})
    assert ai.status_code == 200, ai.text
    assert ai.json()["data"]["search"]["scorePerspective"] == "B"
    assert ai.json()["data"]["search"]["bestMove"] == ai.json()["data"]["turn"]["move"]
    denied = client.post(f"/api/v1/game/{game_id}/ai-move", json={})
    assert denied.status_code == 409 and denied.json()["code"] == "NOT_AI_TURN"


def test_ai_search_budget_is_server_controlled_and_local_games_reject_ai(client: TestClient):
    local_id, _ = create_game(client)
    denied = client.post(f"/api/v1/game/{local_id}/ai-move", json={})
    assert denied.status_code == 409 and denied.json()["code"] == "AI_MODE_REQUIRED"
    ai_id, _ = create_game(client, mode="AI", ai_player="A")
    for body in ({"max_depth": 999}, {"time_limit_ms": 99999999},
                 {"max_depth": 1, "time_limit_ms": 10}):
        rejected = client.post(f"/api/v1/game/{ai_id}/ai-move", json=body)
        assert rejected.status_code == 422 and rejected.json()["code"] == "INVALID_REQUEST"
    game = client.get(f"/api/v1/game/{ai_id}").json()["data"]
    assert game["state"]["current_player"] == "A"


def test_two_concurrent_ai_requests_execute_one_turn(client: TestClient):
    game_id, _ = create_game(client, mode="AI", ai_player="A")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(client.post, f"/api/v1/game/{game_id}/ai-move", json={})
                   for _ in range(2)]
        responses = [future.result(timeout=15) for future in futures]
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert next(response for response in responses if response.status_code == 409).json()["code"] == "NOT_AI_TURN"
    moves = client.portal.call(client.app.state.store.list_moves, game_id)
    assert len(moves) == 1 and moves[0].actor_type == "AI"


def seed_position(client: TestClient, pieces: dict[str, str], first_player: str = "A",
                  mode: str = "LOCAL", ai_player: str | None = None) -> str:
    game_id, raw_state = create_game(client, first_player, mode, ai_player)
    state = GameState.model_validate(raw_state)
    occupancy = {node: None for node in state.board.occupancy}
    occupancy.update(pieces)
    custom = state.model_copy(update={"board": BoardState(occupancy=occupancy)})
    client.portal.call(client.app.state.store.update, game_id, custom)
    return game_id


def test_health_and_openapi_reach_live_engine(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"code": 0, "message": "success", "data": {"status": "ok", "engine": "ok"}}
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    assert "/api/v1/game/{game_id}/ai-move" in schema.json()["paths"]


def test_ready_requires_both_canonical_worker_and_database(client: TestClient, monkeypatch):
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json() == {"code": 0, "message": "success",
                            "data": {"status": "ok", "engine": "ok"}}

    async def database_unavailable():
        raise ApiError("DATABASE_UNAVAILABLE", "Database operation failed")

    monkeypatch.setattr(client.app.state.store, "ping", database_unavailable)
    failure = client.get("/ready")
    assert failure.status_code == 503
    assert failure.json()["code"] == "DATABASE_UNAVAILABLE"
    assert client.get("/health").status_code == 200


def test_create_get_and_legal_moves_use_canonical_state(client: TestClient):
    game_id, state = create_game(client, "B")
    assert state["current_player"] == "B"
    assert state["first_player"] == "B"
    assert len(state["board"]["occupancy"]) == 29
    assert state["players"] == {"A": {"reserve_count": 4}, "B": {"reserve_count": 4}}
    assert client.get(f"/api/v1/game/{game_id}").json()["data"]["state"] == state
    moves = client.get(f"/api/v1/game/{game_id}/legal-moves").json()["data"]["moves"]
    assert moves and all(state["board"]["occupancy"][m["from"]] == "B" for m in moves)
    by_node = client.get(f"/api/v1/game/{game_id}/legal-moves", params={"from_node": moves[0]["from"]})
    assert by_node.status_code == 200
    assert by_node.json()["data"]["moves"] == [m for m in moves if m["from"] == moves[0]["from"]]


def test_analyze_uses_authoritative_game_and_does_not_execute_move(client: TestClient):
    game_id, before = create_game(client, mode="AI", ai_player="B")
    response = client.post("/api/v1/ai/analyze", json={"game_id": game_id})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["game_id"] == game_id and data["game_version"] == 0
    assert data["analyzedPlayer"] == data["scorePerspective"] == "A"
    assert data["evaluationBefore"]["scorePerspective"] == "A"
    assert data["evaluationBreakdown"] == data["evaluationBefore"]["breakdown"]
    assert data["candidateMoves"] and data["candidateMoves"][0]["rank"] == 1
    assert data["candidateMoves"][0]["score"] == data["bestScore"]
    assert data["bestMove"] in [item["move"] for item in data["candidateMoves"]]
    assert data["algorithm"] == "ITERATIVE_DEEPENING_ALPHA_BETA"
    assert client.get(f"/api/v1/game/{game_id}").json()["data"]["state"] == before
    assert client.portal.call(client.app.state.store.list_moves, game_id) == []


def test_analyze_rejects_unknown_game_and_untrusted_board(client: TestClient):
    missing = client.post("/api/v1/ai/analyze", json={"game_id": "missing"})
    assert missing.status_code == 404 and missing.json()["code"] == "GAME_NOT_FOUND"
    game_id, state = create_game(client)
    rejected = client.post("/api/v1/ai/analyze", json={"game_id": game_id,
                                                        "board": state["board"]})
    assert rejected.status_code == 422 and rejected.json()["code"] == "INVALID_REQUEST"


def test_analyze_rejects_stale_client_version_before_search(client: TestClient):
    game_id, _ = create_game(client)
    assert client.get(f"/api/v1/game/{game_id}").json()["data"]["version"] == 0
    move = client.post(f"/api/v1/game/{game_id}/move",
                       json={"from_node": "P01", "to_node": "P02"})
    assert move.status_code == 200
    stale = client.post("/api/v1/ai/analyze",
                        json={"game_id": game_id, "expected_version": 0})
    assert stale.status_code == 409 and stale.json()["code"] == "GAME_STATE_CONFLICT"
    fresh = client.post("/api/v1/ai/analyze",
                        json={"game_id": game_id, "expected_version": 1})
    assert fresh.status_code == 200 and fresh.json()["data"]["game_version"] == 1


def test_analyze_finished_game_skips_search(client: TestClient):
    game_id = seed_position(client, {"P11": "A", "P12": "B", "P08": "B",
                                     "P18": "B", "P19": "A"})
    turn = client.post(f"/api/v1/game/{game_id}/move",
                       json={"from_node": "P19", "to_node": "P13"})
    assert turn.status_code == 200 and turn.json()["data"]["turn"]["game_over"] is True
    response = client.post("/api/v1/ai/analyze", json={"game_id": game_id})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["terminal"] is True and data["winnerReason"] == "CAPTURE_ALL"
    assert data["bestMove"] is None and data["candidateMoves"] == []
    assert data["bestScore"] == data["evaluationBefore"]["score"]
    assert data["game_version"] == 1


def test_analyze_timeout_is_normal_result_and_engine_failure_is_explicit(client: TestClient):
    game_id, before = create_game(client)
    service = client.app.state.service
    service.settings = Settings(analysis_time_limit_ms=0)
    timed = client.post("/api/v1/ai/analyze", json={"game_id": game_id})
    assert timed.status_code == 200, timed.text
    result = timed.json()["data"]
    assert result["timedOut"] is True and result["searchDepth"] == 0
    assert result["candidateMoves"] == []
    assert result["bestScore"] == result["evaluationBefore"]["score"]
    with patch.object(client.app.state.adapter, "analyze_position",
                      side_effect=ApiError("ENGINE_UNAVAILABLE", "offline")):
        failed = client.post("/api/v1/ai/analyze", json={"game_id": game_id})
    assert failed.status_code == 503 and failed.json()["code"] == "ENGINE_UNAVAILABLE"
    assert client.get(f"/api/v1/game/{game_id}").json()["data"]["state"] == before


def test_unknown_game_and_invalid_request_have_one_error_shape(client: TestClient):
    missing = client.get("/api/v1/game/missing")
    assert missing.status_code == 404
    assert missing.json() == {"code": "GAME_NOT_FOUND", "message": "Game not found", "data": None}
    invalid = client.post("/api/v1/game", json={"first_player": "C", "mode": "LOCAL"})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "INVALID_REQUEST"
    assert invalid.json()["data"] is None


def test_move_executes_real_turn_and_rejects_wrong_turn(client: TestClient):
    game_id, before = create_game(client)
    response = client.post(f"/api/v1/game/{game_id}/move", json={"from_node": "P01", "to_node": "P02"})
    assert response.status_code == 200, response.text
    turn = response.json()["data"]["turn"]
    after = turn["state"]
    assert turn["move"] == {"from": "P01", "to": "P02"}
    assert turn["before_state"] == before
    assert turn["board_after"] == after["board"]
    assert after["board"]["occupancy"]["P01"] is None
    assert after["board"]["occupancy"]["P02"] == "A"
    assert after["current_player"] == "B"
    assert client.get(f"/api/v1/game/{game_id}").json()["data"]["state"] == after
    repeat = client.post(f"/api/v1/game/{game_id}/move", json={"from_node": "P01", "to_node": "P02"})
    assert repeat.status_code == 400
    assert repeat.json()["code"] == "INVALID_MOVE"


def test_move_error_mapping_preserves_state(client: TestClient):
    game_id, before = create_game(client)
    occupied = client.post(f"/api/v1/game/{game_id}/move", json={"from_node": "P01", "to_node": "P06"})
    assert occupied.status_code == 400
    assert occupied.json()["code"] == "TARGET_OCCUPIED"
    wrong_player = client.post(f"/api/v1/game/{game_id}/move", json={"from_node": "P05", "to_node": "P04"})
    assert wrong_player.status_code == 409
    assert wrong_player.json()["code"] == "NOT_PLAYER_TURN"
    bad_node = client.post(f"/api/v1/game/{game_id}/move", json={"from_node": "P30", "to_node": "P02"})
    assert bad_node.status_code == 422
    assert bad_node.json()["code"] == "NODE_NOT_FOUND"
    assert client.get(f"/api/v1/game/{game_id}").json()["data"]["state"] == before


def test_blocked_path_is_classified_by_canonical_engine(client: TestClient):
    game_id = seed_position(client, {"P01": "A", "P02": "A", "P05": "B"})
    response = client.post(f"/api/v1/game/{game_id}/move", json={"from_node": "P01", "to_node": "P03"})
    assert response.status_code == 400
    assert response.json()["code"] == "PATH_BLOCKED"


def test_capture_turn_result_and_capture_all_winner_are_serialized(client: TestClient):
    game_id = seed_position(client, {"P11": "A", "P12": "B", "P08": "B", "P18": "B", "P19": "A"})
    response = client.post(f"/api/v1/game/{game_id}/move", json={"from_node": "P19", "to_node": "P13"})
    assert response.status_code == 200, response.text
    turn = response.json()["data"]["turn"]
    assert turn["captures"]["was_applied"] is True
    assert turn["captures"]["captured_nodes"]
    assert turn["captures"]["replacement_nodes"]
    assert turn["captures"]["reserve_used"] > 0
    assert turn["game_over"] is True
    assert turn["winner"] == "A"
    assert turn["winner_reason"] == "CAPTURE_ALL"
    assert turn["state"]["winner_reason"] == "CAPTURE_ALL"
    assert turn["reserve_after"]["A"] < turn["reserve_before"]["A"]


@pytest.mark.parametrize("pieces,reason", [
    ({"P27": "B", "P26": "A", "P28": "A", "P29": "A", "P03": "A", "P21": "A"}, "TEMPLE_TRAP"),
    ({"P03": "B", "P02": "A", "P04": "A", "P27": "A", "P08": "A", "P09": "A",
      "P07": "A", "P26": "A", "P28": "A", "P21": "A"}, "LONE_PIECE_IMMOBILIZED"),
])
def test_lone_piece_winner_reasons_round_trip(client: TestClient, pieces: dict, reason: str):
    game_id = seed_position(client, pieces)
    response = client.post(f"/api/v1/game/{game_id}/move", json={"from_node": "P21", "to_node": "P22"})
    assert response.status_code == 200, response.text
    turn = response.json()["data"]["turn"]
    assert turn["winner_reason"] == reason
    assert turn["state"]["winner_reason"] == reason
    assert client.get(f"/api/v1/game/{game_id}").json()["data"]["state"]["winner_reason"] == reason
    for endpoint, body in [("move", {"from_node": "P22", "to_node": "P21"}),
                           ("ai-move", {})]:
        rejected = client.post(f"/api/v1/game/{game_id}/{endpoint}", json=body)
        assert rejected.status_code == 409
        assert rejected.json()["code"] == "GAME_ALREADY_FINISHED"


def test_ai_move_returns_real_search_and_executes_turn(client: TestClient):
    game_id, before = create_game(client, mode="AI", ai_player="A")
    legal = client.get(f"/api/v1/game/{game_id}/legal-moves").json()["data"]["moves"]
    response = client.post(f"/api/v1/game/{game_id}/ai-move", json={})
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    search, turn = result["search"], result["turn"]
    assert search["algorithm"] == "ITERATIVE_DEEPENING_ALPHA_BETA"
    assert search["bestMove"] in legal
    assert search["scorePerspective"] == "A"
    assert 0 <= search["searchDepth"] <= client.app.state.service.settings.ai_default_max_depth
    assert isinstance(search["nodesSearched"], int)
    assert isinstance(search["ttHits"], int)
    assert isinstance(search["thinkingTimeMs"], (int, float))
    assert isinstance(search["timedOut"], bool)
    assert "winProbability" not in search
    assert turn["move"] == search["bestMove"]
    assert turn["state"] != before
    assert client.get(f"/api/v1/game/{game_id}").json()["data"]["state"] == turn["state"]


def test_ai_move_preserves_rule_ambiguity(client: TestClient):
    game_id = seed_position(client, {
        "P03": "B", "P13": "B", "P02": "A", "P04": "A", "P27": "A", "P08": "A",
        "P09": "A", "P07": "A", "P26": "A", "P28": "A", "P12": "A", "P14": "A",
        "P18": "A", "P19": "A", "P17": "A",
    }, first_player="B", mode="AI", ai_player="B")
    response = client.post(f"/api/v1/game/{game_id}/ai-move", json={})
    assert response.status_code == 409
    assert response.json()["code"] == "RULE_AMBIGUITY"


def test_capture_with_no_reserve_reports_engine_failure_reason_as_turn_result(client: TestClient):
    game_id = seed_position(client, {"P11": "A", "P12": "B", "P08": "B", "P18": "B", "P19": "A"})
    state = GameState.model_validate(client.get(f"/api/v1/game/{game_id}").json()["data"]["state"])
    players = state.players.copy()
    players["A"] = players["A"].model_copy(update={"reserve_count": 0})
    client.portal.call(client.app.state.store.update, game_id, state.model_copy(update={"players": players}))
    response = client.post(f"/api/v1/game/{game_id}/move", json={"from_node": "P19", "to_node": "P13"})
    assert response.status_code == 200
    turn = response.json()["data"]["turn"]
    assert turn["captures"]["failure_reason"] == "INSUFFICIENT_RESERVE"
    assert turn["captures"]["was_applied"] is False
    assert turn["reserve_after"]["A"] == 0


def test_engine_process_failure_maps_to_503():
    settings = Settings(engine_command=("definitely-not-a-real-engine-command",))
    with TestClient(create_app(settings, store=InMemoryGameStore(), require_auth=False)) as client:
        for response in [client.get("/health"),
                         client.post("/api/v1/game", json={"first_player": "A"})]:
            assert response.status_code == 503
            assert response.json()["code"] == "ENGINE_UNAVAILABLE"
            assert response.json()["data"] is None


def test_running_engine_recovers_without_losing_stored_games(client: TestClient):
    game_id, state = create_game(client)
    client.app.state.adapter.process.kill()
    assert client.get("/health").status_code == 503
    recovered = client.get("/health")
    assert recovered.status_code == 200
    assert recovered.json()["data"]["engine"] == "ok"
    assert client.get(f"/api/v1/game/{game_id}").json()["data"]["state"] == state
    assert client.get(f"/api/v1/game/{game_id}/legal-moves").status_code == 200


def test_same_game_concurrent_moves_are_serialized(client: TestClient):
    game_id, _ = create_game(client)
    path = f"/api/v1/game/{game_id}/move"
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(client.post, path, json={"from_node": "P01", "to_node": "P02"})
                   for _ in range(2)]
        responses = [future.result(timeout=10) for future in futures]
    assert sorted(response.status_code for response in responses) == [200, 400]
    state = client.get(f"/api/v1/game/{game_id}").json()["data"]["state"]
    assert state["board"]["occupancy"]["P01"] is None
    assert state["board"]["occupancy"]["P02"] == "A"
    assert state["current_player"] == "B"


def test_ai_and_human_moves_cannot_overwrite_the_same_old_state(client: TestClient):
    game_id, _ = create_game(client, mode="AI", ai_player="A")
    with ThreadPoolExecutor(max_workers=2) as pool:
        ai = pool.submit(client.post, f"/api/v1/game/{game_id}/ai-move", json={})
        human = pool.submit(client.post, f"/api/v1/game/{game_id}/move",
                            json={"from_node": "P01", "to_node": "P02"})
        ai_response, human_response = ai.result(timeout=15), human.result(timeout=15)
    assert ai_response.status_code == 200, ai_response.text
    assert human_response.status_code == 409
    assert human_response.json()["code"] in {"NOT_HUMAN_TURN", "NOT_PLAYER_TURN"}
    ai_turn = ai_response.json()["data"]["turn"]
    stored = client.get(f"/api/v1/game/{game_id}").json()["data"]["state"]
    assert stored == ai_turn["state"]
