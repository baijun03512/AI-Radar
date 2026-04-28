import { useEffect, useRef, useState } from 'react';
import { recordAction, streamChat } from '../api/client';
import { NoveltyTag, SourceTag } from '../components/Tags';
import type { ChatMessage, FeedItem, SourceType } from '../types';

interface ChatPageProps {
  product: FeedItem | null;
  onSave: (id: string) => void;
  saved: boolean;
  onBack: () => void;
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user';
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        marginBottom: 16,
      }}
    >
      <div style={{ maxWidth: '76%' }}>
        <div
          style={{
            background: isUser ? '#dfe6f6' : '#ffffff',
            color: '#111111',
            border: '1px solid var(--border)',
            borderRadius: isUser ? '16px 16px 6px 16px' : '16px 16px 16px 6px',
            padding: '12px 16px',
            fontSize: 14,
            lineHeight: 1.7,
            whiteSpace: 'pre-wrap',
          }}
        >
          {message.content}
        </div>
        {!isUser && message.sources?.length ? (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
            {message.sources.map((source, index) => (
              <SourceTag key={`${source}-${index}`} type={source} />
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function shortProductName(title: string, max = 64): string {
  return title.length > max ? `${title.slice(0, max - 1)}…` : title;
}

function starterQuestion(): string {
  return '可以直接问我这张卡片背后的技术原理、落地方式、优缺点，或者它为什么值得关注。';
}

function uniqueSources(sources: SourceType[]): SourceType[] {
  return [...new Set(sources)];
}

export function ChatPage({ product, onSave, saved, onBack }: ChatPageProps) {
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    product ? [{ role: 'assistant', content: starterQuestion() }] : [],
  );
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  useEffect(() => () => cancelRef.current?.(), []);

  if (!product) {
    return (
      <main
        style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'var(--bg)',
          color: 'var(--ink3)',
        }}
      >
        先从左侧卡片里选一个话题开始。
      </main>
    );
  }

  const send = () => {
    const query = input.trim();
    if (!query || loading) {
      return;
    }

    setMessages((current) => [...current, { role: 'user', content: query }, { role: 'assistant', content: '' }]);
    setInput('');
    setLoading(true);

    cancelRef.current = streamChat(
      product,
      query,
      (chunk) => {
        setMessages((current) => {
          const copy = [...current];
          const last = copy[copy.length - 1];
          copy[copy.length - 1] = { ...last, content: `${last.content}${chunk}` };
          return copy;
        });
      },
      (sources: SourceType[]) => {
        setMessages((current) => {
          const copy = [...current];
          const last = copy[copy.length - 1];
          copy[copy.length - 1] = { ...last, sources: uniqueSources(sources) };
          return copy;
        });
      },
      () => setLoading(false),
      () => {
        setLoading(false);
        setMessages((current) => {
          const copy = [...current];
          const last = copy[copy.length - 1];
          if (!last.content) {
            copy[copy.length - 1] = {
              ...last,
              content: '这次流式回答在返回正文前中断了，可以再试一次。',
            };
          }
          return copy;
        });
      },
    );
  };

  return (
    <main
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--bg)',
        overflow: 'hidden',
      }}
    >
      <header
        style={{
          background: 'var(--card)',
          borderBottom: '1px solid var(--border)',
          padding: '16px 28px',
          display: 'flex',
          alignItems: 'center',
          gap: 14,
        }}
      >
        <button
          onClick={onBack}
          style={{
            border: '1px solid var(--border2)',
            borderRadius: 999,
            padding: '7px 14px',
            fontSize: 12,
            color: 'var(--ink2)',
          }}
        >
          返回
        </button>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontFamily: 'var(--head)', fontSize: 18, fontWeight: 700 }}>
              {product.title}
            </span>
            <NoveltyTag type={product.novelty} />
            <SourceTag type={product.source} />
          </div>
          <div
            style={{
              marginTop: 4,
              color: 'var(--ink3)',
              fontSize: 12,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {product.oneLiner}
          </div>
        </div>

        <button
          onClick={() => {
            onSave(product.id);
            if (!saved) {
              void recordAction(product.id, 'save', product);
            }
          }}
          style={{
            background: saved ? 'var(--c-new-bg)' : 'transparent',
            color: saved ? 'var(--c-new)' : 'var(--ink2)',
            border: `1px solid ${saved ? 'transparent' : 'var(--border2)'}`,
            borderRadius: 999,
            padding: '8px 14px',
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          {saved ? '已保存' : '保存'}
        </button>
      </header>

      <section ref={scrollRef} style={{ flex: 1, overflowY: 'auto', padding: '28px 32px' }}>
        {messages.map((message, index) => (
          <MessageBubble key={`${message.role}-${index}`} message={message} />
        ))}
        {loading ? <div style={{ color: 'var(--ink3)', fontSize: 12, paddingLeft: 8 }}>正在生成回答...</div> : null}
      </section>

      <footer
        style={{
          borderTop: '1px solid var(--border)',
          background: 'var(--card)',
          padding: '16px 28px',
        }}
      >
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end' }}>
          <textarea
            rows={2}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                send();
              }
            }}
            placeholder={`继续追问 ${shortProductName(product.title)}`}
            style={{
              flex: 1,
              resize: 'none',
              border: '1px solid var(--border2)',
              borderRadius: 12,
              background: 'var(--bg)',
              padding: '12px 14px',
              color: 'var(--ink)',
              fontSize: 14,
            }}
          />
          <button
            onClick={send}
            disabled={loading || !input.trim()}
            style={{
              background: 'var(--ink)',
              color: '#fff',
              borderRadius: 999,
              padding: '11px 22px',
              fontSize: 13,
              fontWeight: 600,
              opacity: loading || !input.trim() ? 0.4 : 1,
            }}
          >
            发送
          </button>
        </div>
      </footer>
    </main>
  );
}
