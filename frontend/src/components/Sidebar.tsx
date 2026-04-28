interface SidebarProps {
  page: string;
  setPage: (page: string) => void;
  savedCount: number;
  feedCount: number | null;
}

export function Sidebar({ page, setPage, savedCount, feedCount }: SidebarProps) {
  const items = [
    { id: 'feed', label: 'Daily Feed', badge: feedCount == null ? null : `${feedCount}` },
    { id: 'chat', label: 'Chat', badge: null },
    { id: 'dashboard', label: 'Dashboard', badge: savedCount > 0 ? `${savedCount}` : null },
  ];

  return (
    <aside
      style={{
        width: 200,
        background: 'var(--side)',
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        flexShrink: 0,
      }}
    >
      <div style={{ padding: '24px 18px 18px' }}>
        <div
          style={{
            fontFamily: 'var(--head)',
            fontWeight: 800,
            fontSize: 16,
            color: 'var(--stext)',
            marginBottom: 4,
          }}
        >
          AI Radar
        </div>
        <div
          style={{
            fontSize: 10,
            color: 'var(--sdim)',
            fontFamily: 'var(--mono)',
            letterSpacing: '0.08em',
          }}
        >
          PRODUCT INTELLIGENCE
        </div>
      </div>

      <nav style={{ flex: 1, padding: '10px 10px 0' }}>
        {items.map((item) => (
          <button
            key={item.id}
            onClick={() => setPage(item.id)}
            style={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              textAlign: 'left',
              padding: '10px 12px',
              borderRadius: 8,
              marginBottom: 4,
              background: page === item.id ? 'rgba(0,0,0,0.08)' : 'transparent',
              color: page === item.id ? 'var(--stext)' : 'var(--sdim)',
              fontSize: 13,
              fontWeight: page === item.id ? 600 : 500,
            }}
          >
            <span>{item.label}</span>
            {item.badge != null ? (
              <span style={{ fontSize: 10, fontFamily: 'var(--mono)', opacity: 0.75 }}>
                {item.badge}
              </span>
            ) : null}
          </button>
        ))}
      </nav>

      <div style={{ padding: '16px 18px', borderTop: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: 'var(--c-new)',
              animation: 'pulse 2.5s infinite',
            }}
          />
          <span style={{ fontSize: 10, color: 'var(--sdim)', fontFamily: 'var(--mono)' }}>
            Agents running
          </span>
        </div>
      </div>
    </aside>
  );
}
