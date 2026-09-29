import { gameService } from '../../services/index';
import type { BoardState } from '../../types/domain';
import { boardLines, boardNodes } from '../../mock/game';
import { openPage, backHome } from '../../utils/navigation';
import { analyzePosition } from '../../ai/position-analysis';
import type { AiLevelDto } from '../../services/api-contract';
import { createLocalGameSession, getLocalBoardView, resignLocalGame, tapLocalGameNode, undoLocalGame } from './local-game';
import type { LocalGameSession } from './local-game';
import { mapGameStateToView } from './game-state-mapper';
import type { GameViewModel } from './game-state-mapper';
import { createApiClient } from '../../services/api-client';
import { createGameApi } from '../../services/game-api';
import { RemoteGameController } from './remote-game';
import type { RemoteGameSnapshot } from './remote-game';
import { AiGameController } from './ai-game';
import type { AiGameSnapshot } from './ai-game';
import type { Player } from '../../domain/index';
import { createWxDeviceHistoryStore } from '../../services/device-history';
import type { GameIdStorage } from './remote-game';
import { mapPositionAnalysis } from '../analysis/analysis-view-model';
import type { AnalysisViewModel } from '../analysis/analysis-view-model';
import { buildHintFromAnalysis, type GameHintView } from './hint-builder';

const activeGameIdKey = 'activeRemoteGameId';
const activeAiGameIdKey = 'activeAiGameId';
const activeLocalGameIdKey = 'activeLocalGameId';
const emptyBoard: BoardState = { nodes: boardNodes, lines: boardLines, pieces: [] };

const AI_LEVEL_LABELS: Readonly<Record<AiLevelDto, string>> = {
  BEGINNER: '入门 AI', STANDARD: '标准 AI', ADVANCED: '进阶 AI',
};

function aiSideLabel(level: AiLevelDto | null | undefined, side: Player): string {
  return `${AI_LEVEL_LABELS[level ?? 'STANDARD']} · ${side}`;
}

const gameIdStorage = {
  read: (): string | null => {
    const id = wx.getStorageSync(activeGameIdKey);
    return typeof id === 'string' && id ? id : null;
  },
  write: (id: string): void => { wx.setStorageSync(activeGameIdKey, id); },
  clear: (): void => { wx.removeStorageSync(activeGameIdKey); },
};
const aiGameIdStorage = {
  read: (): string | null => {
    const id = wx.getStorageSync(activeAiGameIdKey);
    return typeof id === 'string' && id ? id : null;
  },
  write: (id: string): void => { wx.setStorageSync(activeAiGameIdKey, id); },
  clear: (): void => { wx.removeStorageSync(activeAiGameIdKey); },
};

function storageForRoute(base: GameIdStorage, requestedId?: string): GameIdStorage {
  let requested = requestedId || null;
  return {
    read: () => requested ?? base.read(),
    write: id => { base.write(id); requested = null; },
    clear: () => {
      const missing = requested ?? base.read();
      if (missing) {
        try { createWxDeviceHistoryStore().remove(missing); } catch { /* keep game recovery available */ }
      }
      if (!requested || base.read() === requested) base.clear();
    },
  };
}

Page({
  data: { board: gameService.getBoard(), localSession: null as LocalGameSession | null,
    localGameId: '', localTurns: 0, localErrorMessage: '',
    remoteState: null as RemoteGameSnapshot | null, remoteView: null as GameViewModel | null,
    remoteReady: false, aiState: null as AiGameSnapshot | null,
    aiView: null as GameViewModel | null, aiReady: false,
    aiAName: '玩家 A', aiBName: '标准 AI · B',
    aiCaptureText: '',
    aiAnalysisView: null as AnalysisViewModel | null,
    aiDifficulty: 'STANDARD' as AiLevelDto,
    localHintView: null as GameHintView | null,
    localHintLevel: 0,
    localHintLoading: false,
    localHintError: '',
    mode: 'ai', thinking: false,
    showResign: false, showSettings: false },
  remoteController: null as RemoteGameController | null,
  aiController: null as AiGameController | null,
  aiFirstPlayer: 'A' as Player,
  onLoad(options: { mode?: string; first?: string; gameId?: string }) {
    if (options.mode === 'local') this.enterLocalGame(options.gameId);
    else if (options.mode === 'remote') {
      this.setData({ mode: 'remote', board: emptyBoard, remoteReady: false,
        thinking: false, showResign: false, showSettings: false,
        localHintView: null, localHintLevel: 0, localHintLoading: false, localHintError: '' });
      this.remoteController = new RemoteGameController(
        createGameApi(createApiClient()), storageForRoute(gameIdStorage, options.gameId),
        snapshot => this.renderRemote(snapshot),
        { createOnMissing: !options.gameId },
      );
      this.renderRemote(this.remoteController.snapshot);
      void this.remoteController.enter();
    } else {
      this.aiFirstPlayer = options.first === 'ai' ? 'B' : 'A';
      this.setData({ mode: 'ai', board: emptyBoard, aiReady: false,
        thinking: false, showResign: false, showSettings: false,
        localHintView: null, localHintLevel: 0, localHintLoading: false, localHintError: '' });
      this.aiController = new AiGameController(
        createGameApi(createApiClient()), storageForRoute(aiGameIdStorage, options.gameId),
        snapshot => this.renderAi(snapshot),
        { createOnMissing: !options.gameId, aiLevel: this.data.aiDifficulty },
      );
      this.renderAi(this.aiController.snapshot);
      void this.aiController.enter(this.aiFirstPlayer);
    }
  },
  onUnload() {
    this.remoteController?.dispose(); this.remoteController = null;
    this.aiController?.dispose(); this.aiController = null;
  },
  renderRemote(snapshot: RemoteGameSnapshot) {
    if (snapshot.gameId && snapshot.gameState) {
      this.saveHistory(snapshot.gameId, 'remote', snapshot.gameState,
        snapshot.gameVersion ?? this.historyTurns(snapshot.gameId));
    }
    const view = snapshot.gameState ? mapGameStateToView(snapshot.gameState, {
      selectedNode: snapshot.selectedNode,
      legalTargets: snapshot.legalTargets,
      lastMove: snapshot.lastMove,
    }) : null;
    this.setData({ remoteState: snapshot, remoteView: view,
      remoteReady: view !== null, board: view?.board ?? emptyBoard });
  },
  renderAi(snapshot: AiGameSnapshot) {
    if (snapshot.gameId && snapshot.gameState) {
      this.saveHistory(snapshot.gameId, 'ai', snapshot.gameState,
        snapshot.gameVersion ?? this.historyTurns(snapshot.gameId));
    }
    const view = snapshot.gameState ? mapGameStateToView(snapshot.gameState, {
      selectedNode: snapshot.selectedNode,
      legalTargets: snapshot.legalTargets,
      lastMove: snapshot.lastMove,
      lastCapture: snapshot.lastCapture,
    }) : null;
    const analysisView = snapshot.analysis && snapshot.gameState
      ? mapPositionAnalysis(snapshot.gameState, snapshot.analysis) : null;
    this.setData({ aiState: snapshot, aiView: view,
      aiAnalysisView: analysisView,
      aiCaptureText: snapshot.lastCapture?.was_applied
        ? `本步吃子 ${snapshot.lastCapture.captured_nodes.length} 枚，备用棋消耗 ${snapshot.lastCapture.reserve_used} 枚`
        : '',
      aiAName: snapshot.aiPlayer === 'A' ? aiSideLabel(snapshot.aiLevel, 'A') : '玩家 A',
      aiBName: snapshot.aiPlayer === 'B' ? aiSideLabel(snapshot.aiLevel, 'B') : '玩家 B',
      aiDifficulty: snapshot.aiLevel ?? this.data.aiDifficulty,
      aiReady: view !== null, board: view?.board ?? emptyBoard });
  },
  back() { backHome(); },
  onNode(event: WechatMiniprogram.CustomEvent<{ id: string }>) {
    if (this.data.mode === 'ai') {
      void this.aiController?.tapNode(event.detail.id);
      return;
    }
    if (this.data.mode === 'remote') {
      void this.remoteController?.tapNode(event.detail.id);
      return;
    }
    if (this.data.mode === 'local') {
      const session = this.data.localSession as LocalGameSession | null;
      if (session === null) return;
      const result = tapLocalGameNode(session, event.detail.id);
      if (result.error) {
        wx.showToast({ title: result.error, icon: 'none' });
        return;
      }
      if (result.session === session) return;
      if (result.turn && this.data.localGameId) {
        const turns = this.data.localTurns + 1;
        if (!this.saveHistory(this.data.localGameId, 'local', result.session.gameState,
          turns, result.session.lastMove)) return;
        this.setData({ localTurns: turns });
      }
      this.setData({ localSession: result.session, board: getLocalBoardView(result.session) });
      if (result.turn?.captures.failure_reason === 'INSUFFICIENT_RESERVE') {
        wx.showToast({ title: '备用棋不足，本次吃子未生效', icon: 'none' });
      }
    }
  },
  onAction(event: WechatMiniprogram.TouchEvent) {
    const action = event.currentTarget.dataset.action as string;
    if (action === 'undo') this.undo();
    else if (action === 'hint') this.hint();
    else if (action === 'analysis') this.openAnalysis();
    else if (action === 'review') this.openReview();
    else if (action === 'resign') this.resign();
    else if (action === 'restart') {
      if (this.data.mode === 'remote') this.restartRemoteGame();
      else if (this.data.mode === 'ai') this.restartAiGame();
      else this.restartLocalGame();
    }
    else if (action === 'settings') this.settings();
  },
  historyTurns(id: string): number {
    try { return createWxDeviceHistoryStore().get(id)?.turns ?? 0; }
    catch { return 0; }
  },
  saveHistory(id: string, mode: 'local' | 'remote' | 'ai',
              state: LocalGameSession['gameState'], turns: number,
              lastMove: LocalGameSession['lastMove'] = null): boolean {
    try {
      createWxDeviceHistoryStore().record({ id, mode, state, turns, lastMove });
      return true;
    } catch {
      wx.showToast({ title: '历史记录保存失败', icon: 'none' });
      return false;
    }
  },
  enterLocalGame(requestedId?: string) {
    const savedId = requestedId || wx.getStorageSync(activeLocalGameIdKey);
    if (typeof savedId === 'string' && savedId) {
      try {
        const entry = createWxDeviceHistoryStore().get(savedId);
        if (entry?.mode === 'local' && entry.localState &&
            (requestedId || entry.status === 'PLAYING')) {
          const session: LocalGameSession = {
            initialState: entry.localState,
            gameState: entry.localState,
            turnHistory: [],
            selectedNode: null,
            legalDestinations: [],
            lastMove: entry.lastMove ?? null,
          };
          wx.setStorageSync(activeLocalGameIdKey, savedId);
          this.setData({ mode: 'local', localGameId: savedId, localTurns: entry.turns,
            localSession: session, board: getLocalBoardView(session),
            localErrorMessage: '',
            showResign: false, showSettings: false,
            localHintView: null, localHintLevel: 0, localHintLoading: false, localHintError: '' });
          return;
        }
      } catch {
        if (requestedId) {
          this.setData({ mode: 'local', localSession: null, localGameId: savedId,
            localErrorMessage: '本地历史棋局读取失败', board: emptyBoard });
          return;
        }
        wx.showToast({ title: '本地记录读取失败', icon: 'none' });
      }
    }
    if (requestedId) {
      this.setData({ mode: 'local', localSession: null, localGameId: requestedId,
        localErrorMessage: '本地历史棋局不存在', board: emptyBoard });
      return;
    }
    this.restartLocalGame('A');
  },
  restartLocalGame(firstPlayer: Player = 'A') {
    const session = createLocalGameSession(firstPlayer);
    const id = `local-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    if (!this.saveHistory(id, 'local', session.gameState, 0)) {
      this.setData({ mode: 'local', localErrorMessage: '本地棋局保存失败，请重试新局' });
      return;
    }
    try { wx.setStorageSync(activeLocalGameIdKey, id); }
    catch { wx.showToast({ title: '自动续局设置失败，请从历史对局打开', icon: 'none' }); }
    this.setData({
      mode: 'local', localGameId: id, localTurns: 0,
      localSession: session, board: getLocalBoardView(session),
      localErrorMessage: '',
      showResign: false, showSettings: false,
      localHintView: null, localHintLevel: 0, localHintLoading: false, localHintError: '',
    });
  },
  restartLocalFirstB() {
    this.setData({ showSettings: false });
    this.restartLocalGame('B');
  },
  restartRemoteGame() { void this.remoteController?.restart(); },
  refreshRemoteGame() { void this.remoteController?.enter(); },
  retryRemoteGame() { void this.remoteController?.enter(); },
  restartAiGame() {
    this.aiFirstPlayer = 'A';
    this.setData({ showSettings: false });
    void this.aiController?.restart('A');
  },
  restartAiFirstGame() {
    this.aiFirstPlayer = 'B';
    this.setData({ showSettings: false });
    void this.aiController?.restart('B');
  },
  retryAiGame() { void this.aiController?.enter(this.aiFirstPlayer); },
  undo() {
    if (this.data.mode === 'local') {
      const session = this.data.localSession as LocalGameSession | null;
      if (!session) {
        wx.showToast({ title: '当前无法悔棋', icon: 'none' });
        return;
      }
      const undone = undoLocalGame(session);
      if (!undone) {
        wx.showToast({ title: '还没有可撤销的步数', icon: 'none' });
        return;
      }
      const turns = Math.max(0, this.data.localTurns - 1);
      if (this.data.localGameId &&
          !this.saveHistory(this.data.localGameId, 'local', undone.gameState, turns, undone.lastMove)) {
        return;
      }
      this.setData({ localSession: undone, board: getLocalBoardView(undone), localTurns: turns });
      return;
    }
    if (this.data.mode === 'ai') {
      void this.aiController?.undo();
      return;
    }
    if (this.data.mode === 'remote') {
      wx.showToast({ title: '远程对局需双方同意才能悔棋', icon: 'none' });
      return;
    }
    wx.showToast({ title: '当前无法悔棋', icon: 'none' });
  },
  hint() {
    if (this.data.mode === 'ai') {
      void this.aiController?.requestCoachHint();
      return;
    }
    if (this.data.mode === 'local') {
      void this.requestLocalHint();
      return;
    }
    if (this.data.mode === 'remote') {
      void this.remoteController?.requestHint();
    }
  },
  async requestLocalHint() {
    const session = this.data.localSession as LocalGameSession | null;
    if (!session || session.gameState.game_status !== 'PLAYING' || this.data.localHintLoading) return;
    const level = Math.min(3, this.data.localHintLevel + 1) as 1 | 2 | 3;
    this.setData({ localHintLoading: true, localHintError: '' });
    try {
      const analysis = analyzePosition(session.gameState,
        { maxDepth: 2, timeLimitMs: 1000, now: () => Date.now() });
      this.setData({
        localHintView: buildHintFromAnalysis(analysis, level),
        localHintLevel: level,
        localHintLoading: false,
      });
    } catch {
      this.setData({ localHintLoading: false, localHintError: '提示暂时不可用' });
    }
  },
  openAnalysis() {
    if (this.data.mode === 'ai') {
      void this.aiController?.analyze();
      return;
    }
    const gameId = this.data.mode === 'local'
      ? this.data.localGameId : this.data.remoteState?.gameId;
    if (!gameId) {
      wx.showToast({ title: '当前没有可分析的棋局', icon: 'none' });
      return;
    }
    openPage(`/pages/analysis/analysis?mode=${this.data.mode}&gameId=${encodeURIComponent(gameId)}`);
  },
  openReview() {
    const gameId = this.data.mode === 'ai'
      ? this.data.aiState?.gameId : this.data.remoteState?.gameId;
    if (gameId) openPage(`/pages/review/review?gameId=${encodeURIComponent(gameId)}`);
  },
  isGameFinished(): boolean {
    if (this.data.mode === 'local') return this.data.localSession?.gameState.game_status === 'FINISHED';
    if (this.data.mode === 'remote') return this.data.remoteView?.gameOver ?? false;
    return this.data.aiView?.gameOver ?? false;
  },
  resign() {
    if (this.isGameFinished()) {
      wx.showToast({ title: '本局已结束', icon: 'none' });
      return;
    }
    this.setData({ showResign: true });
  },
  cancelResign() { this.setData({ showResign: false }); },
  confirmResign() {
    this.setData({ showResign: false });
    if (this.data.mode === 'local') {
      const session = this.data.localSession as LocalGameSession | null;
      if (!session || session.gameState.game_status === 'FINISHED') return;
      const resigned = resignLocalGame(session, session.gameState.current_player);
      if (!resigned) return;
      this.setData({
        localSession: resigned,
        board: getLocalBoardView(resigned),
        localHintView: null,
        localHintLevel: 0,
      });
      if (this.data.localGameId) {
        this.saveHistory(this.data.localGameId, 'local', resigned.gameState,
          this.data.localTurns, resigned.lastMove);
      }
      wx.showToast({ title: '已认输', icon: 'none' });
      return;
    }
    if (this.data.mode === 'ai') {
      void this.aiController?.resign();
      return;
    }
    if (this.data.mode === 'remote') {
      void this.remoteController?.resign();
    }
  },
  selectAiDifficulty(event: WechatMiniprogram.TouchEvent) {
    const level = event.currentTarget.dataset.level as AiLevelDto;
    if (!level || level === this.data.aiDifficulty) return;
    this.aiController?.setAiLevel(level);
    this.setData({ aiDifficulty: level });
  },
  startAiGameWithDifficulty() {
    this.setData({ showSettings: false });
    void this.aiController?.restart(this.aiFirstPlayer);
  },
  settings() { this.setData({ showSettings: !this.data.showSettings }); },
  toggleThinking() {}
});
