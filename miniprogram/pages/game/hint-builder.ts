import type { Move, NodeId } from '../../domain/index';
import type { EvaluationBreakdown } from '../../ai/evaluation';
import type { PositionAnalysis } from '../../ai/position-analysis';

const THREAT_TOPICS: Readonly<Record<PositionAnalysis['threats'][number]['type'], string>> = {
  IMMEDIATE_WIN_AVAILABLE: '直接终局机会',
  CAPTURE_AVAILABLE: '捕获机会',
  CAPTURE_THREAT: '捕获威胁',
  VULNERABILITY: '受攻击风险',
  LONE_PIECE_MOBILITY_RISK: '孤棋机动性',
};

const EVALUATION_TOPICS: Readonly<Record<Exclude<keyof EvaluationBreakdown, 'terminal'>, string>> = {
  material: '子力', reserve: '备用棋', mobility: '机动性', templeControl: '庙宇控制',
  captureOpportunity: '捕获机会', vulnerability: '受攻击风险', trapRisk: '孤棋风险',
};

export interface GameHintView {
  readonly level: 1 | 2 | 3;
  readonly hintText: string;
  readonly focusTopics: readonly string[];
  readonly candidateFromNodes: readonly NodeId[];
  readonly bestMove: Move | null;
}

function buildEvidence(analysis: PositionAnalysis, level: 1 | 2 | 3) {
  const threatTypes = [...new Set(analysis.threats.map(threat => threat.type))];
  const topics = [...new Set(threatTypes.map(kind => THREAT_TOPICS[kind]))];
  if (topics.length === 0) {
    const ranked = (Object.keys(EVALUATION_TOPICS) as Array<Exclude<keyof EvaluationBreakdown, 'terminal'>>)
      .sort((a, b) => Math.abs(analysis.evaluationBreakdown[b].weightedScore) -
        Math.abs(analysis.evaluationBreakdown[a].weightedScore));
    topics.push(EVALUATION_TOPICS[ranked[0]]);
  }
  const focusTopics = topics.slice(0, 3);
  const origins = [...new Set(analysis.candidateMoves.map(item => item.move.from))];
  const candidateFromNodes = (analysis.bestMove
    ? origins.filter(node => node !== analysis.bestMove!.to) : origins).slice(0, 3);
  if (level === 1) return { focusTopics, candidateFromNodes: [] as NodeId[], bestMove: null };
  if (level === 2) return { focusTopics, candidateFromNodes, bestMove: null };
  return { focusTopics, candidateFromNodes, bestMove: analysis.bestMove };
}

function fallbackHint(level: 1 | 2 | 3, focusTopics: readonly string[],
                      candidateFromNodes: readonly NodeId[], bestMove: Move | null): string {
  const topic = focusTopics[0] ?? '当前局面';
  if (level === 1) return `先关注${topic}，再检查自己有哪些合法选择。`;
  if (level === 2) {
    return candidateFromNodes.length > 0
      ? `可以优先考虑 ${candidateFromNodes.join('、')} 的棋子，比较它们的合法路线。`
      : `继续关注${topic}，比较当前可选棋子的合法路线。`;
  }
  return bestMove
    ? `当前推荐走 ${bestMove.from}→${bestMove.to}，这是本次引擎搜索得到的最佳行动。`
    : '本次分析没有找到可推荐的行动。';
}

export function buildHintFromAnalysis(analysis: PositionAnalysis, level: 1 | 2 | 3): GameHintView {
  const evidence = buildEvidence(analysis, level);
  return {
    level,
    hintText: fallbackHint(level, evidence.focusTopics, evidence.candidateFromNodes, evidence.bestMove),
    focusTopics: evidence.focusTopics,
    candidateFromNodes: evidence.candidateFromNodes,
    bestMove: evidence.bestMove,
  };
}
