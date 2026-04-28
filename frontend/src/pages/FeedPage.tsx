import { useEffect, useMemo, useState } from 'react';
import { fetchFeed, isMockFeedEnabled, recordAction } from '../api/client';
import { NoveltyTag, PoolTag, SourceTag } from '../components/Tags';
import type { FeedData, FeedItem } from '../types';

interface FeedPageProps {
  onOpenChat: (item: FeedItem) => void;
  savedIds: string[];
  onSave: (id: string) => void;
  onFeedCountChange?: (count: number | null) => void;
}

interface FeedCardProps {
  item: FeedItem;
  index: number;
  saved: boolean;
  onOpen: (item: FeedItem) => void;
  onSave: (id: string) => void;
  onDismiss: (id: string) => void;
}

const PRECISION_VISIBLE_COUNT = 5;
const EXPLORATION_VISIBLE_COUNT = 3;

function sourceTitle(type: FeedItem['source']): string {
  if (type === 'academic') {
    return '学术';
  }
  if (type === 'industry') {
    return '产品';
  }
  return '社区';
}

function FeedCard({ item, index, saved, onOpen, onSave, onDismiss }: FeedCardProps) {
  return (
    <article
      onClick={() => {
        onOpen(item);
        void recordAction(item.id, 'open', item);
      }}
      style={{
        background: 'var(--card)',
        border: '1px solid var(--border)',
        borderRadius: 12,
        padding: '18px 18px 16px',
        boxShadow: '0 8px 24px rgba(0,0,0,0.05)',
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
        cursor: 'pointer',
        breakInside: 'avoid',
        marginBottom: 14,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <SourceTag type={item.source} />
          <NoveltyTag type={item.novelty} />
          <PoolTag type={item.pool} />
        </div>
        <div style={{ color: 'var(--ink4)', fontFamily: 'var(--mono)', fontSize: 12 }}>
          {String(index + 1).padStart(2, '0')}
        </div>
      </div>

      <div
        style={{
          fontSize: 17,
          fontWeight: 500,
          lineHeight: 1.68,
          whiteSpace: 'pre-wrap',
          color: 'var(--ink)',
        }}
      >
        {item.oneLiner}
      </div>

      <div
        style={{
          color: 'var(--ink3)',
          fontSize: 12,
          lineHeight: 1.6,
          borderTop: '1px solid var(--border)',
          paddingTop: 10,
        }}
      >
        {sourceTitle(item.source)}来源: {item.title}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 'auto' }}>
        <button
          onClick={(event) => {
            event.stopPropagation();
            onOpen(item);
            void recordAction(item.id, 'open', item);
          }}
          style={{
            background: 'var(--ink)',
            color: '#fff',
            borderRadius: 999,
            padding: '8px 14px',
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          进入对话
        </button>
        <button
          onClick={(event) => {
            event.stopPropagation();
            onSave(item.id);
            if (!saved) {
              void recordAction(item.id, 'save', item);
            }
          }}
          style={{
            background: saved ? 'var(--c-new-bg)' : 'transparent',
            color: saved ? 'var(--c-new)' : 'var(--ink2)',
            border: `1px solid ${saved ? 'transparent' : 'var(--border2)'}`,
            borderRadius: 999,
            padding: '8px 12px',
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          {saved ? '已保存' : '保存'}
        </button>
        <button
          onClick={(event) => {
            event.stopPropagation();
            onDismiss(item.id);
            void recordAction(item.id, 'skip', item);
          }}
          style={{ marginLeft: 'auto', color: 'var(--ink3)', fontSize: 12, padding: '8px 0' }}
        >
          暂不看
        </button>
      </div>
    </article>
  );
}

function FeedSection({
  title,
  subtitle,
  items,
  savedIds,
  onOpenChat,
  onSave,
  onDismiss,
  startIndex,
}: {
  title: string;
  subtitle: string;
  items: FeedItem[];
  savedIds: string[];
  onOpenChat: (item: FeedItem) => void;
  onSave: (id: string) => void;
  onDismiss: (id: string) => void;
  startIndex: number;
}) {
  return (
    <section style={{ marginTop: 28 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 14 }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>{title}</h2>
          <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--ink3)' }}>{subtitle}</p>
        </div>
        <div style={{ fontSize: 12, color: 'var(--ink3)', fontFamily: 'var(--mono)' }}>{items.length} 张</div>
      </div>

      <div
        style={{
          columnWidth: 360,
          columnGap: 14,
        }}
      >
        {items.map((item, index) => (
          <FeedCard
            key={item.id}
            item={item}
            index={startIndex + index}
            saved={savedIds.includes(item.id)}
            onOpen={onOpenChat}
            onSave={onSave}
            onDismiss={onDismiss}
          />
        ))}
      </div>
    </section>
  );
}

export function FeedPage({ onOpenChat, savedIds, onSave, onFeedCountChange }: FeedPageProps) {
  const [feed, setFeed] = useState<FeedData>({ precisionPool: [], explorationPool: [] });
  const [dismissedIds, setDismissedIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadFeed = async () => {
    setLoading(true);
    setError(null);
    onFeedCountChange?.(null);
    try {
      const data = await fetchFeed();
      setFeed(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Feed request failed.';
      setFeed({ precisionPool: [], explorationPool: [] });
      setError(message);
      onFeedCountChange?.(0);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadFeed();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const precisionItems = useMemo(
    () => feed.precisionPool.filter((item) => !dismissedIds.includes(item.id)).slice(0, PRECISION_VISIBLE_COUNT),
    [dismissedIds, feed.precisionPool],
  );

  const explorationItems = useMemo(
    () => feed.explorationPool.filter((item) => !dismissedIds.includes(item.id)).slice(0, EXPLORATION_VISIBLE_COUNT),
    [dismissedIds, feed.explorationPool],
  );

  const totalVisible = precisionItems.length + explorationItems.length;

  useEffect(() => {
    onFeedCountChange?.(loading ? null : totalVisible);
  }, [loading, onFeedCountChange, totalVisible]);

  const dismissItem = (id: string) => {
    setDismissedIds((current) => [...current, id]);
  };

  return (
    <main style={{ flex: 1, overflowY: 'auto', background: 'var(--bg)' }}>
      <div style={{ maxWidth: 1180, margin: '0 auto', padding: '40px 32px 56px' }}>
        <header style={{ marginBottom: 28 }}>
          <div
            style={{
              fontFamily: 'var(--head)',
              fontSize: 32,
              fontWeight: 800,
              lineHeight: 1,
              marginBottom: 8,
            }}
          >
            {new Date().toISOString().slice(0, 10)}
          </div>
          <p style={{ color: 'var(--ink2)', fontSize: 14 }}>
            {loading
              ? '正在生成今天的雷达卡片...'
              : `今天展示 ${totalVisible} 张卡片：精准池 ${precisionItems.length} 张，探索池 ${explorationItems.length} 张。`}
          </p>
        </header>

        <section
          style={{
            background: 'var(--card)',
            border: '1px solid var(--border)',
            borderRadius: 16,
            padding: '14px 16px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 14,
            marginBottom: 24,
            flexWrap: 'wrap',
          }}
        >
          <div>
            <div style={{ fontSize: 13, fontWeight: 600 }}>今日固定日报</div>
            <div style={{ fontSize: 12, color: 'var(--ink3)', marginTop: 4 }}>
              后端每天生成 12 张候选卡，首页固定展示 8 张：精准池 5 张，探索池 3 张。
            </div>
          </div>
          <div style={{ fontSize: 12, color: 'var(--ink3)', fontFamily: 'var(--mono)' }}>12 generated / 8 visible</div>
        </section>

        {loading ? (
          <div
            style={{
              marginTop: 48,
              color: 'var(--ink3)',
              fontSize: 14,
            }}
          >
            正在抓取并整理卡片...
          </div>
        ) : error ? (
          <div
            style={{
              marginTop: 32,
              background: 'var(--card)',
              border: '1px solid var(--border)',
              borderRadius: 12,
              padding: '18px 20px',
              maxWidth: 560,
            }}
          >
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8 }}>Feed 暂不可用</div>
            <div style={{ fontSize: 13, color: 'var(--ink2)', lineHeight: 1.6, marginBottom: 14 }}>{error}</div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <button
                onClick={() => void loadFeed()}
                style={{
                  background: 'var(--ink)',
                  color: '#fff',
                  borderRadius: 999,
                  padding: '8px 14px',
                  fontSize: 12,
                  fontWeight: 600,
                }}
              >
                重试
              </button>
              <span style={{ fontSize: 12, color: 'var(--ink3)' }}>
                {isMockFeedEnabled() ? '当前开启了演示兜底数据。' : '当前没有注入 mock 卡片。'}
              </span>
            </div>
          </div>
        ) : (
          <>
            <FeedSection
              title="精准池"
              subtitle="围绕你的主关注方向，优先给出今天最值得先看的技术与产品。"
              items={precisionItems}
              savedIds={savedIds}
              onOpenChat={onOpenChat}
              onSave={onSave}
              onDismiss={dismissItem}
              startIndex={0}
            />
            <FeedSection
              title="探索池"
              subtitle="保留少量广谱新热点，避免视野完全被已有偏好锁死。"
              items={explorationItems}
              savedIds={savedIds}
              onOpenChat={onOpenChat}
              onSave={onSave}
              onDismiss={dismissItem}
              startIndex={precisionItems.length}
            />
          </>
        )}

        {!loading && !error && totalVisible === 0 ? (
          <div
            style={{
              marginTop: 48,
              textAlign: 'center',
              color: 'var(--ink3)',
              fontSize: 14,
            }}
          >
            今天这批卡片已经看完了。
          </div>
        ) : null}
      </div>
    </main>
  );
}
