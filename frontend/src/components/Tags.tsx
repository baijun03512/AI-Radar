import type { NoveltyLabel, PoolType, SourceType } from '../types';

interface TagProps {
  label: string;
  color: string;
  background: string;
}

export function Tag({ label, color, background }: TagProps) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '3px 10px',
        borderRadius: 999,
        background,
        color,
        fontSize: 11,
        fontWeight: 600,
        whiteSpace: 'nowrap',
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: color,
          flexShrink: 0,
        }}
      />
      {label}
    </span>
  );
}

const NOVELTY_CFG: Record<NoveltyLabel, TagProps> = {
  new: { label: '新技术', color: 'var(--c-new)', background: 'var(--c-new-bg)' },
  update: { label: '知识延伸', color: 'var(--c-upd)', background: 'var(--c-upd-bg)' },
  watch: { label: '值得跟进', color: 'var(--c-cls)', background: 'var(--c-cls-bg)' },
};

const SOURCE_CFG: Record<SourceType, TagProps> = {
  academic: { label: '学术信号', color: 'var(--c-acad)', background: 'var(--c-acad-bg)' },
  industry: { label: '工业落地', color: 'var(--c-ind)', background: 'var(--c-ind-bg)' },
  community: { label: '社区反馈', color: 'var(--c-com)', background: 'var(--c-com-bg)' },
};

const POOL_CFG: Record<PoolType, TagProps> = {
  precision: { label: '精准池', color: 'var(--c-upd)', background: 'var(--c-upd-bg)' },
  exploration: { label: '探索池', color: 'var(--c-acad)', background: 'var(--c-acad-bg)' },
};

export function NoveltyTag({ type }: { type: NoveltyLabel }) {
  return <Tag {...NOVELTY_CFG[type]} />;
}

export function SourceTag({ type }: { type: SourceType }) {
  return <Tag {...SOURCE_CFG[type]} />;
}

export function PoolTag({ type }: { type: PoolType }) {
  return <Tag {...POOL_CFG[type]} />;
}
