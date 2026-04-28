export type NoveltyLabel = 'new' | 'update' | 'watch';
export type SourceType = 'academic' | 'industry' | 'community';
export type PoolType = 'precision' | 'exploration';

export interface FeedItem {
  id: string;
  title: string;
  oneLiner: string;
  novelty: NoveltyLabel;
  pool: PoolType;
  source: SourceType;
  finalScore?: number;
  sourceUrl?: string;
}

export interface FeedData {
  precisionPool: FeedItem[];
  explorationPool: FeedItem[];
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  sources?: SourceType[];
}

export interface Preferences {
  interests: string[];
  preferredPlatforms: string[];
  explorationRatio: number;
  feedSize: number;
  explorationQueries: string[];
}

export interface SkillHealth {
  skillId: string;
  skillType: string;
  successRate: number;
  usageCount: number;
  version: number;
  healRequired: boolean;
}

export interface ExecutionSummary {
  totalLogs: number;
  failingTools: string[];
}

export interface DashboardData {
  feedItems: number;
  avgFinalScore: number;
  precisionItems: number;
  explorationItems: number;
  opens: number;
  skips: number;
  saves: number;
  execution: ExecutionSummary;
  skillHealth: SkillHealth[];
}
