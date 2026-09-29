import test from 'node:test';
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import { existsSync } from 'node:fs';

registerHooks({ resolve(specifier, context, nextResolve) {
  try { return nextResolve(specifier, context); }
  catch (error) {
    if (specifier.startsWith('.') && context.parentURL &&
        (error as NodeJS.ErrnoException).code === 'ERR_MODULE_NOT_FOUND') {
      const url = new URL(`${specifier}.ts`, context.parentURL);
      if (existsSync(url)) return nextResolve(url.href, context);
    }
    throw error;
  }
} });

const { createApiClient, ApiError, messageForApiError } =
  await import('../miniprogram/services/api-client.ts');
const { createGameApi } = await import('../miniprogram/services/game-api.ts');

test('client unwraps success envelope and game API sends exact create/move paths and bodies', async () => {
  const sent: Array<{url: string; method: string; data?: unknown}> = [];
  const client = createApiClient({ baseUrl: 'http://127.0.0.1:8000', request: options => {
    sent.push(options);
    options.success({ statusCode: 200, data: { code: 0, message: 'success', data: { game_id: 'g1' } } });
  } });
  const api = createGameApi(client);
  assert.deepEqual(await api.createGame(), { game_id: 'g1' });
  await api.getGame('g1');
  await api.getLegalMoves('g1', 'P01');
  await api.move('g1', { from_node: 'P01', to_node: 'P02' });
  await api.aiMove('g1', {});
  await api.undo('g1');
  await api.resign('g1');
  await api.resign('g1', { resigning_player: 'A' });
  await api.analyzeGame('g1');
  await api.analyzeGame('g1', 0);
  await api.createGame({ first_player: 'B', mode: 'AI', ai_player: 'B', ai_level: 'STANDARD' });
  assert.deepEqual(sent.map(item => [item.method, item.url]), [
    ['POST', 'http://127.0.0.1:8000/api/v1/game'],
    ['GET', 'http://127.0.0.1:8000/api/v1/game/g1'],
    ['GET', 'http://127.0.0.1:8000/api/v1/game/g1/legal-moves?from_node=P01'],
    ['POST', 'http://127.0.0.1:8000/api/v1/game/g1/move'],
    ['POST', 'http://127.0.0.1:8000/api/v1/game/g1/ai-move'],
    ['POST', 'http://127.0.0.1:8000/api/v1/game/g1/undo'],
    ['POST', 'http://127.0.0.1:8000/api/v1/game/g1/resign'],
    ['POST', 'http://127.0.0.1:8000/api/v1/game/g1/resign'],
    ['POST', 'http://127.0.0.1:8000/api/v1/ai/analyze'],
    ['POST', 'http://127.0.0.1:8000/api/v1/ai/analyze'],
    ['POST', 'http://127.0.0.1:8000/api/v1/game'],
  ]);
  assert.deepEqual(sent[0].data, { first_player: 'A', mode: 'LOCAL' });
  assert.deepEqual(sent[3].data, { from_node: 'P01', to_node: 'P02' });
  assert.deepEqual(sent[4].data, {});
  assert.deepEqual(sent[5].data, {});
  assert.deepEqual(sent[6].data, {});
  assert.deepEqual(sent[7].data, { resigning_player: 'A' });
  assert.deepEqual(sent[8].data, { game_id: 'g1' });
  assert.deepEqual(sent[9].data, { game_id: 'g1', expected_version: 0 });
  assert.deepEqual(sent[10].data, { first_player: 'B', mode: 'AI',
    ai_player: 'B', ai_level: 'STANDARD' });
});

test('review API reads and generates one completed game review', async () => {
  const sent: Array<{url: string; method: string; data?: unknown}> = [];
  const client = createApiClient({ baseUrl: 'http://127.0.0.1:8000', request: options => {
    sent.push(options);
    options.success({ statusCode: 200, data: { code: 0, message: 'success', data: { id: 'r1' } } });
  } });
  const api = createGameApi(client);
  await api.getReview('g1', 'B');
  await api.createReview('g1', 'B');
  assert.deepEqual(sent.map(item => [item.method, item.url, item.data]), [
    ['GET', 'http://127.0.0.1:8000/api/v1/game/g1/review?reviewed_player=B', undefined],
    ['POST', 'http://127.0.0.1:8000/api/v1/game/g1/review', { reviewed_player: 'B' }],
  ]);
});

test('API errors keep public codes and show safe messages', async () => {
  for (const code of ['GAME_NOT_FOUND', 'GAME_STATE_CONFLICT', 'ENGINE_UNAVAILABLE']) {
    const client = createApiClient({ baseUrl: 'http://server', request: options => {
      options.success({ statusCode: code === 'GAME_NOT_FOUND' ? 404 : 409,
        data: { code, message: 'internal detail', data: null } });
    } });
    await assert.rejects(client.request('GET', '/anything'), (error: unknown) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.code, code);
      assert.notEqual(messageForApiError(error), 'internal detail');
      return true;
    });
  }
});

test('transport failure and unknown server errors never expose internals', async () => {
  const network = createApiClient({ baseUrl: 'http://server', request: options => {
    options.fail({ errMsg: 'socket secret detail' });
  } });
  await assert.rejects(network.request('GET', '/anything'), (error: unknown) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.code, 'NETWORK_ERROR');
    assert.doesNotMatch(messageForApiError(error), /secret/);
    return true;
  });
  const server = createApiClient({ baseUrl: 'http://server', request: options => {
    options.success({ statusCode: 500, data: '<stack trace>' });
  } });
  await assert.rejects(server.request('GET', '/anything'), (error: unknown) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.code, 'SERVER_UNAVAILABLE');
    assert.doesNotMatch(messageForApiError(error), /stack/);
    return true;
  });
});
