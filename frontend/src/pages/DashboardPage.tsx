import type { ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { fetchDashboard } from '../api/client';
import type { DashboardData } from '../types';

// ─── Small reusable atoms ─────────────────────────────────────────────────────

function Stat({
  label,
  value,
  mono = false,
  accent,
}: {
  label: string;
  value: string | number;
  mono?: boolean;
  accent?: string;
}) {
  return (
    <div
      style={{
        background: 'var(--card)',
        border: '1px solid var(--border)',
        borderRadius: 12,
        padding: '16px 18px',
      }}
    >
      <div style={{ color: 'var(--ink3)', fontSize: 11, marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        {label}
      </div>
      <div
        style={{
          fontFamily: mono ? 'var(--mono)' : 'var(--head)',
          fontSize: 28,
          fontWeight: 800,
          lineHeight: 1,
          color: accent ?? 'var(--ink)',
        }}
      >
        {value}
      </div>
    </div>
  );
}

function SectionHead({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        fontSize: 12,
        fontWeight: 700,
        color: 'var(--ink3)',
        textTransform: 'uppercase',
        letterSpacing: '0.08em',
        marginBottom: 14,
      }}
    >
      {children}
    </div>
  );
}

// ─── Pool distribution bar ────────────────────────────────────────────────────

function PoolBar({ precision, exploration }: { precision: number; exploration: number }) {
  const total = precision + exploration || 1;
  const pPct = Math.round((precision / total) * 100);
  const ePct = 100 - pPct;

  return (
    <div
      style={{
        background: 'var(--card)',
        border: '1px solid var(--border)',
        borderRadius: 12,
        padding: '16px 18px',
      }}
    >
      <div style={{ color: 'var(--ink3)', fontSize: 11, marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        推荐池分布
      </div>
      <div style={{ display: 'flex', borderRadius: 999, overflow: 'hidden', height: 8, marginBottom: 10 }}>
        <div style={{ width: `${pPct}%`, background: 'var(--c-upd)' }} />
        <div style={{ width: `${ePct}%`, background: 'var(--c-acad)' }} />
      </div>
      <div style={{ display: 'flex', gap: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 8, height: 8, borderRadius: 2, background: 'var(--c-upd)', flexShrink: 0 }} />
          <span style={{ fontSize: 12, color: 'var(--ink2)' }}>精准池 {precision} 条</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 8, height: 8, borderRadius: 2, background: 'var(--c-acad)', flexShrink: 0 }} />
          <span style={{ fontSize: 12, color: 'var(--ink2)' }}>探索池 {exploration} 条</span>
        </div>
      </div>
    </div>
  );
}

// ─── Engagement row ───────────────────────────────────────────────────────────

function EngagementBar({
  opens,
  skips,
  saves,
}: {
  opens: number;
  skips: number;
  saves: number;
}) {
  const total = opens + skips + saves || 1;
  const rows = [
    { label: '打开对话', value: opens, color: 'var(--c-upd)', bg: 'var(--c-upd-bg)', textColor: 'var(--c-upd)' },
    { label: '暂不看', value: skips, color: 'var(--ink4)', bg: 'var(--panel)', textColor: 'var(--ink3)' },
    { label: '已保存', value: saves, color: 'var(--c-new)', bg: 'var(--c-new-bg)', textColor: 'var(--c-new)' },
  ];

  return (
    <div
      style={{
        background: 'var(--card)',
        border: '1px solid var(--border)',
        borderRadius: 12,
        padding: '16px 18px',
      }}
    >
      <div
        style={{
          color: 'var(--ink3)',
          fontSize: 11,
          marginBottom: 14,
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
        }}
      >
        用户互动
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {rows.map((row) => (
          <div key={row.label}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: 5,
              }}
            >
              <span style={{ fontSize: 12, color: 'var(--ink2)' }}>{row.label}</span>
              <span
                style={{
                  fontSize: 12,
                  fontFamily: 'var(--mono)',
                  fontWeight: 700,
                  color: row.textColor,
                }}
              >
                {row.value}
              </span>
            </div>
            <div style={{ height: 5, borderRadius: 999, background: 'var(--panel)', overflow: 'hidden' }}>
              <div
                style={{
                  width: `${Math.max(2, (row.value / total) * 100)}%`,
                  height: '100%',
                  background: row.color,
                  borderRadius: 999,
                  transition: 'width 0.4s ease',
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Skill health card ────────────────────────────────────────────────────────

function SkillHealthCard({ data }: { data: DashboardData }) {
  if (!data.skillHealth.length) {
    return (
      <div style={{ color: 'var(--ink3)', fontSize: 13, padding: '20px 0' }}>
        暂无 Skill 记录。
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {data.skillHealth.map((skill) => {
        const pct = Math.round(skill.successRate * 100);
        const status = skill.healRequired ? 'bad' : pct >= 90 ? 'good' : 'warn';
        const color =
          status === 'good' ? 'var(--c-new)' :
          status === 'warn' ? 'var(--c-cls)' :
          '#e0431a';

        return (
          <div
            key={skill.skillId}
            style={{
              background: 'var(--card)',
              border: '1px solid var(--border)',
              borderRadius: 12,
              padding: '14px 16px',
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
                marginBottom: 10,
              }}
            >
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 2 }}>
                  {skill.skillId}
                </div>
                <div style={{ fontSize: 11, color: 'var(--ink3)' }}>
                  {skill.skillType} · v{skill.version} · {skill.usageCount} 次调用
                </div>
              </div>
              <div
                style={{
                  fontFamily: 'var(--mono)',
                  fontSize: 14,
                  fontWeight: 700,
                  color,
                  background: skill.healRequired ? '#fdf0ed' : status === 'warn' ? 'var(--c-cls-bg)' : 'var(--c-new-bg)',
                  borderRadius: 6,
                  padding: '2px 8px',
                }}
              >
                {pct}%
              </div>
            </div>
            <div
              style={{
                height: 6,
                borderRadius: 999,
                background: 'var(--panel)',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  width: `${Math.max(4, pct)}%`,
                  height: '100%',
                  background: color,
                  borderRadius: 999,
                  transition: 'width 0.4s ease',
                }}
              />
            </div>
            {skill.healRequired && (
              <div
                style={{
                  marginTop: 8,
                  fontSize: 11,
                  color: '#e0431a',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                }}
              >
                ⚠ 需要 Heal — 成功率过低
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Execution panel ──────────────────────────────────────────────────────────

function ExecutionPanel({ data }: { data: DashboardData }) {
  const { totalLogs, failingTools } = data.execution;

  return (
    <div
      style={{
        background: 'var(--card)',
        border: '1px solid var(--border)',
        borderRadius: 12,
        padding: '20px',
      }}
    >
      <SectionHead>执行日志</SectionHead>
      <div style={{ display: 'flex', gap: 14, marginBottom: 16 }}>
        <div>
          <div style={{ color: 'var(--ink3)', fontSize: 11, marginBottom: 4 }}>近期日志条数</div>
          <div style={{ fontFamily: 'var(--head)', fontSize: 28, fontWeight: 800 }}>{totalLogs}</div>
        </div>
        <div style={{ width: 1, background: 'var(--border)', margin: '0 4px' }} />
        <div>
          <div style={{ color: 'var(--ink3)', fontSize: 11, marginBottom: 4 }}>异常工具</div>
          <div
            style={{
              fontFamily: 'var(--head)',
              fontSize: 28,
              fontWeight: 800,
              color: failingTools.length ? '#e0431a' : 'var(--c-new)',
            }}
          >
            {failingTools.length}
          </div>
        </div>
      </div>
      {failingTools.length > 0 ? (
        <div>
          <div style={{ fontSize: 12, color: 'var(--ink3)', marginBottom: 8 }}>需要关注：</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {failingTools.map((tool) => (
              <span
                key={tool}
                style={{
                  background: '#fdf0ed',
                  color: '#e0431a',
                  border: '1px solid #f5c4ba',
                  borderRadius: 6,
                  padding: '3px 10px',
                  fontSize: 12,
                  fontFamily: 'var(--mono)',
                }}
              >
                {tool}
              </span>
            ))}
          </div>
        </div>
      ) : (
        <div
          style={{
            fontSize: 13,
            color: 'var(--c-new)',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <span style={{ fontSize: 16 }}>✓</span> 所有工具运行正常
        </div>
      )}
    </div>
  );
}

// ─── Tabs ─────────────────────────────────────────────────────────────────────

type Tab = 'intel' | 'system';

function TabBar({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
  const tabs: { id: Tab; label: string }[] = [
    { id: 'intel', label: '情报质量' },
    { id: 'system', label: '系统状态' },
  ];

  return (
    <div
      style={{
        display: 'flex',
        gap: 4,
        background: 'var(--panel)',
        borderRadius: 10,
        padding: 4,
        width: 'fit-content',
        marginBottom: 28,
      }}
    >
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          style={{
            padding: '7px 18px',
            borderRadius: 8,
            fontSize: 13,
            fontWeight: 600,
            background: active === tab.id ? 'var(--card)' : 'transparent',
            color: active === tab.id ? 'var(--ink)' : 'var(--ink3)',
            boxShadow: active === tab.id ? '0 1px 4px rgba(0,0,0,0.08)' : 'none',
            transition: 'all 0.15s',
          }}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

interface DashboardPageProps {
  savedIds: string[];
}

export function DashboardPage({ savedIds }: DashboardPageProps) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [tab, setTab] = useState<Tab>('intel');

  useEffect(() => {
    void fetchDashboard().then(setData);
  }, []);

  if (!data) {
    return (
      <main
        style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'var(--bg)',
          color: 'var(--ink3)',
          fontSize: 14,
        }}
      >
        正在加载 Dashboard...
      </main>
    );
  }

  const openRate = data.opens + data.skips > 0
    ? Math.round((data.opens / (data.opens + data.skips)) * 100)
    : 0;

  return (
    <main style={{ flex: 1, overflowY: 'auto', background: 'var(--bg)' }}>
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '40px 32px 56px' }}>
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
            Dashboard
          </div>
          <p style={{ color: 'var(--ink2)', fontSize: 14 }}>
            今日情报质量与系统运行状态
          </p>
        </header>

        <TabBar active={tab} onChange={setTab} />

        {tab === 'intel' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            {/* Top stats row */}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                gap: 14,
              }}
            >
              <Stat label="今日卡片总数" value={data.feedItems} />
              <Stat
                label="平均质量分"
                value={data.avgFinalScore.toFixed(2)}
                mono
                accent={data.avgFinalScore >= 0.6 ? 'var(--c-new)' : data.avgFinalScore >= 0.4 ? 'var(--c-cls)' : 'var(--ink)'}
              />
              <Stat
                label="打开率"
                value={`${openRate}%`}
                mono
                accent={openRate >= 50 ? 'var(--c-new)' : 'var(--ink)'}
              />
              <Stat
                label="已保存"
                value={savedIds.length}
                accent={savedIds.length > 0 ? 'var(--c-upd)' : undefined}
              />
            </div>

            {/* Pool + engagement */}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: 14,
              }}
            >
              <PoolBar precision={data.precisionItems} exploration={data.explorationItems} />
              <EngagementBar opens={data.opens} skips={data.skips} saves={data.saves} />
            </div>

            {/* Quality note */}
            <div
              style={{
                background: 'var(--card)',
                border: '1px solid var(--border)',
                borderRadius: 12,
                padding: '16px 18px',
                display: 'flex',
                alignItems: 'flex-start',
                gap: 12,
              }}
            >
              <div style={{ fontSize: 20, lineHeight: 1, paddingTop: 2 }}>
                {data.avgFinalScore >= 0.6 ? '🟢' : data.avgFinalScore >= 0.4 ? '🟡' : '🔴'}
              </div>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>今日情报诊断</div>
                <div style={{ fontSize: 13, color: 'var(--ink2)', lineHeight: 1.6 }}>
                  {data.avgFinalScore >= 0.6
                    ? `今日 ${data.feedItems} 条卡片质量良好，平均分 ${data.avgFinalScore.toFixed(2)}。精准池 ${data.precisionItems} 条，探索池 ${data.explorationItems} 条，偏好匹配度高。`
                    : data.avgFinalScore >= 0.4
                    ? `今日卡片质量一般，平均分 ${data.avgFinalScore.toFixed(2)}。可以尝试在偏好设置中细化兴趣标签，提升匹配度。`
                    : `今日卡片质量较低，平均分 ${data.avgFinalScore.toFixed(2)}。建议检查数据源连通性或调整探索/精准比例。`}
                </div>
              </div>
            </div>
          </div>
        )}

        {tab === 'system' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            <ExecutionPanel data={data} />

            <div>
              <SectionHead>Skill 健康度</SectionHead>
              <SkillHealthCard data={data} />
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
