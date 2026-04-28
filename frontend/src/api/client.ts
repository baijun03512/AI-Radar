import type {
  DashboardData,
  FeedData,
  FeedItem,
  NoveltyLabel,
  Preferences,
  SourceType,
} from '../types';

interface RawFeedItem {
  item_id: string;
  title: string;
  one_liner: string;
  novelty_label: string;
  novelty_type?: NoveltyLabel;
  source_layer_icon: string;
  source_type?: SourceType;
  final_score: number;
  pool_type: 'precision' | 'exploration';
}

interface RawFeedResponse {
  precision_pool: RawFeedItem[];
  exploration_pool: RawFeedItem[];
}

interface RawPreferences {
  interests: string[];
  preferred_platforms: string[];
  exploration_ratio: number;
  feed_size: number;
  exploration_queries: string[];
}

interface RawDashboard {
  skill_health: Array<{
    skill_id: string;
    skill_type: string;
    success_rate: number;
    usage_count: number;
    version: number;
    heal_required: boolean;
  }>;
  feed_metrics: {
    feed_items: number;
    avg_final_score: number;
    precision_items: number;
    exploration_items: number;
    opens: number;
    skips: number;
    saves: number;
  };
  execution: {
    total_logs: number;
    failing_tools: string[];
  };
}

interface RawChatMetaSource {
  layer: string;
  source_type?: SourceType;
}

const MOCK_FEED: FeedItem[] = [
  {
    id: 'mock-gemini',
    title: 'Gemini 2.5 Pro',
    oneLiner: 'Google shipped a stronger reasoning model with better coding and long-context depth.',
    novelty: 'new',
    pool: 'precision',
    source: 'industry',
    finalScore: 0.91,
  },
  {
    id: 'mock-cursor',
    title: 'Cursor Background Agent',
    oneLiner: 'A background execution flow that keeps working after you leave the editor.',
    novelty: 'update',
    pool: 'precision',
    source: 'community',
    finalScore: 0.82,
  },
  {
    id: 'mock-paper',
    title: 'Agentic Coding Token Study',
    oneLiner: 'A recent paper studying how coding agents spend tokens in real tasks.',
    novelty: 'watch',
    pool: 'exploration',
    source: 'academic',
    finalScore: 0.74,
  },
];

const MOCK_FEED_DATA: FeedData = {
  precisionPool: MOCK_FEED.filter((item) => item.pool === 'precision'),
  explorationPool: MOCK_FEED.filter((item) => item.pool === 'exploration'),
};

const MOCK_PREFERENCES: Preferences = {
  interests: ['AI agents', 'developer tools', 'LLM applications'],
  preferredPlatforms: ['product_hunt', 'reddit', 'arxiv'],
  explorationRatio: 0.3,
  feedSize: 10,
  explorationQueries: ['open source AI', 'multimodal AI', 'AI workflow automation'],
};

const MOCK_DASHBOARD: DashboardData = {
  feedItems: 40,
  avgFinalScore: 0.48,
  precisionItems: 24,
  explorationItems: 16,
  opens: 0,
  skips: 0,
  saves: 0,
  execution: { totalLogs: 0, failingTools: [] },
  skillHealth: [
    {
      skillId: 'crawler_arxiv_v1',
      skillType: 'crawler',
      successRate: 1,
      usageCount: 16,
      version: 1,
      healRequired: false,
    },
  ],
};

const ENABLE_MOCK_FEED = import.meta.env.VITE_ENABLE_MOCK_FEED === 'true';

async function get<T>(path: string, timeoutMs = 5000): Promise<T> {
  const response = await fetch(path, { signal: AbortSignal.timeout(timeoutMs) });
  if (!response.ok) {
    throw new Error(`GET ${path} failed: ${response.status}`);
  }
  return response.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) {
    throw new Error(`POST ${path} failed: ${response.status}`);
  }
  return response.json();
}

function isNoveltyLabel(value: string | undefined): value is NoveltyLabel {
  return value === 'new' || value === 'update' || value === 'watch';
}

function isSourceType(value: string | undefined): value is SourceType {
  return value === 'academic' || value === 'industry' || value === 'community';
}

function mapNovelty(label: string): NoveltyLabel {
  if (label.includes('🆕') || label.includes('ð') || label.includes('馃啎') || label.includes('棣冨晭')) {
    return 'new';
  }
  if (label.includes('🔭') || label.includes('ð­') || label.includes('馃搶') || label.includes('棣冩惗')) {
    return 'watch';
  }
  return 'update';
}

function mapSource(icon: string): SourceType {
  if (icon.includes('📚') || icon.includes('ð') || icon.includes('馃摎') || icon.includes('棣冩憥')) {
    return 'academic';
  }
  if (
    icon.includes('🏭') ||
    icon.includes('ð­') ||
    icon.includes('馃彮') ||
    icon.includes('馃彚') ||
    icon.includes('棣冨疆')
  ) {
    return 'industry';
  }
  return 'community';
}

function mapSourceFromLayer(layer: string): SourceType {
  const normalized = layer.trim().toLowerCase();
  if (normalized.includes('academic') || normalized.includes('学术')) {
    return 'academic';
  }
  if (normalized.includes('industry') || normalized.includes('工业')) {
    return 'industry';
  }
  return 'community';
}

function mapFeedItem(item: RawFeedItem): FeedItem {
  return {
    id: item.item_id,
    title: item.title,
    oneLiner: item.one_liner,
    novelty: isNoveltyLabel(item.novelty_type) ? item.novelty_type : mapNovelty(item.novelty_label),
    pool: item.pool_type,
    source: isSourceType(item.source_type) ? item.source_type : mapSource(item.source_layer_icon),
    finalScore: item.final_score,
  };
}

export async function fetchFeed(): Promise<FeedData> {
  try {
    const payload = await get<RawFeedResponse>('/api/feed', 65000);
    return {
      precisionPool: payload.precision_pool.map(mapFeedItem),
      explorationPool: payload.exploration_pool.map(mapFeedItem),
    };
  } catch (error) {
    if (ENABLE_MOCK_FEED) {
      return MOCK_FEED_DATA;
    }
    throw error;
  }
}

export function isMockFeedEnabled(): boolean {
  return ENABLE_MOCK_FEED;
}

export async function recordAction(
  itemId: string,
  action: 'open' | 'skip' | 'save',
  item?: FeedItem,
): Promise<void> {
  try {
    await post(`/api/feed/${itemId}/action`, {
      action,
      item_title: item?.title ?? '',
      one_liner: item?.oneLiner ?? '',
      pool_type: item?.pool ?? null,
      source_type: item?.source ?? null,
    });
  } catch {
    return;
  }
}

export async function fetchPreferences(): Promise<Preferences> {
  try {
    const payload = await get<RawPreferences>('/api/preferences');
    return {
      interests: payload.interests,
      preferredPlatforms: payload.preferred_platforms,
      explorationRatio: payload.exploration_ratio,
      feedSize: payload.feed_size,
      explorationQueries: payload.exploration_queries,
    };
  } catch {
    return MOCK_PREFERENCES;
  }
}

export async function updatePreferences(preferences: Partial<Preferences>): Promise<void> {
  try {
    await post('/api/preferences', {
      interests: preferences.interests,
      preferred_platforms: preferences.preferredPlatforms,
      exploration_ratio: preferences.explorationRatio,
      feed_size: preferences.feedSize,
      exploration_queries: preferences.explorationQueries,
    });
  } catch {
    return;
  }
}

export async function fetchDashboard(): Promise<DashboardData> {
  try {
    const payload = await get<RawDashboard>('/api/dashboard');
    return {
      feedItems: payload.feed_metrics.feed_items,
      avgFinalScore: payload.feed_metrics.avg_final_score,
      precisionItems: payload.feed_metrics.precision_items,
      explorationItems: payload.feed_metrics.exploration_items,
      opens: payload.feed_metrics.opens,
      skips: payload.feed_metrics.skips,
      saves: payload.feed_metrics.saves,
      execution: {
        totalLogs: payload.execution.total_logs,
        failingTools: payload.execution.failing_tools,
      },
      skillHealth: payload.skill_health.map((skill) => ({
        skillId: skill.skill_id,
        skillType: skill.skill_type,
        successRate: skill.success_rate,
        usageCount: skill.usage_count,
        version: skill.version,
        healRequired: skill.heal_required,
      })),
    };
  } catch {
    return MOCK_DASHBOARD;
  }
}

export function streamChat(
  product: FeedItem,
  query: string,
  onChunk: (text: string) => void,
  onMeta: (sources: SourceType[]) => void,
  onDone: () => void,
  onError: () => void,
): () => void {
  const controller = new AbortController();

  (async () => {
    let sawMessage = false;
    let sawDone = false;

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          product_id: product.id,
          product_name: product.title,
        }),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        onError();
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      const processEventBlock = (eventBlock: string) => {
        const lines = eventBlock.split('\n');
        const eventName = lines.find((line) => line.startsWith('event: '))?.slice(7).trim();
        const dataLine = lines.find((line) => line.startsWith('data: '))?.slice(6).trim();
        if (!eventName || !dataLine) {
          return;
        }

        try {
          const payload = JSON.parse(dataLine) as {
            delta?: string;
            sources_used?: RawChatMetaSource[];
          };

          if (eventName === 'meta') {
            const sources = (payload.sources_used ?? []).map((source) =>
              isSourceType(source.source_type) ? source.source_type : mapSourceFromLayer(source.layer),
            );
            onMeta(sources);
          }

          if (eventName === 'message') {
            sawMessage = true;
            onChunk(payload.delta ?? '');
          }

          if (eventName === 'done') {
            sawDone = true;
            onDone();
          }
        } catch {
          return;
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop() ?? '';

        for (const eventBlock of events) {
          processEventBlock(eventBlock);
        }
      }

      if (buffer.trim()) {
        processEventBlock(buffer);
      }

      if (!sawDone) {
        if (sawMessage) {
          onDone();
        } else {
          onError();
        }
      }
    } catch (error) {
      if ((error as Error).name !== 'AbortError') {
        if (sawMessage) {
          onDone();
        } else {
          onError();
        }
      }
    }
  })();

  return () => controller.abort();
}
