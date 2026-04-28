import { useEffect, useState } from 'react';
import './index.css';
import { Sidebar } from './components/Sidebar';
import { ChatPage } from './pages/ChatPage';
import { DashboardPage } from './pages/DashboardPage';
import { FeedPage } from './pages/FeedPage';
import type { FeedItem } from './types';

type Page = 'feed' | 'chat' | 'dashboard';

function App() {
  const [page, setPage] = useState<Page>('feed');
  const [chatProduct, setChatProduct] = useState<FeedItem | null>(null);
  const [savedIds, setSavedIds] = useState<string[]>(() => {
    const saved = window.localStorage.getItem('ai-radar-saved-ids');
    if (saved) {
      try {
        return JSON.parse(saved) as string[];
      } catch {
        window.localStorage.removeItem('ai-radar-saved-ids');
      }
    }
    return [];
  });
  const [feedCount, setFeedCount] = useState<number | null>(null);

  useEffect(() => {
    window.localStorage.setItem('ai-radar-saved-ids', JSON.stringify(savedIds));
  }, [savedIds]);

  const openChat = (item: FeedItem) => {
    setChatProduct(item);
    setPage('chat');
  };

  const markSaved = (id: string) => {
    setSavedIds((current) =>
      current.includes(id) ? current : [...current, id],
    );
  };

  return (
    <div style={{ display: 'flex', height: '100%', width: '100%' }}>
      <Sidebar
        page={page}
        setPage={(nextPage) => setPage(nextPage as Page)}
        savedCount={savedIds.length}
        feedCount={feedCount}
      />

      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', position: 'relative' }}>
        {page === 'feed' ? (
          <FeedPage
            onOpenChat={openChat}
            savedIds={savedIds}
            onSave={markSaved}
            onFeedCountChange={setFeedCount}
          />
        ) : null}

        {page === 'chat' ? (
          <ChatPage
            key={chatProduct?.id ?? 'no-product'}
            product={chatProduct}
            onSave={markSaved}
            saved={chatProduct != null && savedIds.includes(chatProduct.id)}
            onBack={() => setPage('feed')}
          />
        ) : null}

        {page === 'dashboard' ? (
          <DashboardPage savedIds={savedIds} />
        ) : null}
      </div>
    </div>
  );
}

export default App;
