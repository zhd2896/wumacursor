import type { GameState, Move, Player } from '../domain/index';

export const HISTORY_STORAGE_KEY = 'wuma:history:v1';

export type HistoryMode = 'local' | 'remote' | 'ai' | 'online';

export interface DeviceHistoryEntry {
  readonly id: string;
  readonly mode: HistoryMode;
  readonly startedAt: number;
  readonly updatedAt: number;
  readonly turns: number;
  readonly status: GameState['game_status'];
  readonly winner: Player | null;
  readonly winnerReason: GameState['winner_reason'];
  readonly localState?: GameState;
  readonly lastMove?: Move | null;
}

export interface DeviceHistoryStorage {
  get(key: string): unknown;
  set(key: string, value: unknown): void;
  remove(key: string): void;
}

export interface RecordDeviceGame {
  readonly id: string;
  readonly mode: HistoryMode;
  readonly state: GameState;
  readonly turns: number;
  readonly lastMove?: Move | null;
}

export interface DeviceHistoryStore {
  list(): DeviceHistoryEntry[];
  get(id: string): DeviceHistoryEntry | null;
  record(game: RecordDeviceGame): DeviceHistoryEntry;
  remove(id: string): void;
}

function validEntry(value: unknown): value is DeviceHistoryEntry {
  if (!value || typeof value !== 'object') return false;
  const row = value as Partial<DeviceHistoryEntry>;
  const validMode = row.mode === 'local' || row.mode === 'remote' ||
    row.mode === 'ai' || row.mode === 'online';
  const validWinner = row.winner === null || row.winner === 'A' || row.winner === 'B';
  const validReason = row.winnerReason === null || row.winnerReason === 'CAPTURE_ALL' ||
    row.winnerReason === 'TEMPLE_TRAP' || row.winnerReason === 'LONE_PIECE_IMMOBILIZED' ||
    row.winnerReason === 'RESIGN';
  const validState = row.mode !== 'local' || (!!row.localState &&
    typeof row.localState.board?.occupancy === 'object' &&
    row.localState.game_status === row.status);
  return typeof row.id === 'string' && row.id.length > 0 && validMode &&
    typeof row.startedAt === 'number' && Number.isFinite(row.startedAt) &&
    typeof row.updatedAt === 'number' && Number.isFinite(row.updatedAt) &&
    typeof row.turns === 'number' && Number.isInteger(row.turns) && row.turns >= 0 &&
    (row.status === 'PLAYING' || row.status === 'FINISHED') &&
    validWinner && validReason && validState;
}

export function createDeviceHistoryStore(storage: DeviceHistoryStorage,
                                         now: () => number = Date.now): DeviceHistoryStore {
  function read(): DeviceHistoryEntry[] {
    const data = storage.get(HISTORY_STORAGE_KEY);
    if (data === undefined || data === null || data === '') return [];
    if (!data || typeof data !== 'object') throw new Error('Device history is damaged');
    const parsed = data as { version?: unknown; records?: unknown };
    if (parsed.version !== 1 || !Array.isArray(parsed.records) ||
        !parsed.records.every(validEntry)) throw new Error('Device history is damaged');
    const ids = new Set(parsed.records.map((row: DeviceHistoryEntry) => row.id));
    if (ids.size !== parsed.records.length) throw new Error('Device history has duplicate IDs');
    return parsed.records;
  }
  function write(records: DeviceHistoryEntry[]): void {
    if (records.length) storage.set(HISTORY_STORAGE_KEY, { version: 1, records });
    else storage.remove(HISTORY_STORAGE_KEY);
  }
  return {
    list: () => read().slice().sort((a, b) =>
      b.updatedAt - a.updatedAt || b.startedAt - a.startedAt || a.id.localeCompare(b.id)),
    get: id => read().find(row => row.id === id) ?? null,
    record: game => {
      if (!game.id || !Number.isInteger(game.turns) || game.turns < 0) {
        throw new Error('Invalid device game record');
      }
      const records = read();
      const index = records.findIndex(row => row.id === game.id);
      const previous = index < 0 ? null : records[index];
      if (previous && previous.mode !== game.mode) throw new Error('Device game mode changed');
      if (previous && previous.turns === game.turns &&
          previous.status === game.state.game_status &&
          previous.winner === game.state.winner &&
          previous.winnerReason === game.state.winner_reason) return previous;
      const timestamp = now();
      const row: DeviceHistoryEntry = {
        id: game.id, mode: game.mode, startedAt: previous?.startedAt ?? timestamp,
        updatedAt: timestamp, turns: game.turns,
        status: game.state.game_status, winner: game.state.winner,
        winnerReason: game.state.winner_reason,
        ...(game.mode === 'local' ? {
          localState: game.state, lastMove: game.lastMove ?? null,
        } : {}),
      };
      if (index < 0) records.push(row);
      else records[index] = row;
      write(records);
      return row;
    },
    remove: id => write(read().filter(row => row.id !== id)),
  };
}

export function createWxDeviceHistoryStore(): DeviceHistoryStore {
  return createDeviceHistoryStore({
    get: key => wx.getStorageSync(key),
    set: (key, value) => { wx.setStorageSync(key, value); },
    remove: key => { wx.removeStorageSync(key); },
  });
}
