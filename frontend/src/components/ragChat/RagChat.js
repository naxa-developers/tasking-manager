import React, { useState, useRef, useEffect } from 'react';
import { useSelector } from 'react-redux';
import { FormattedMessage } from 'react-intl';
import {
  createRagSession,
  listRagSessions,
  getRagSession,
  deleteRagSession,
  streamRagSessionChat,
  RAG_MAX_QUESTION_CHARS,
} from '../../api/rag';
import { Button } from '../button';
import { ChatMessageList } from './ChatMessage';
import { ChatInput } from './ChatInput';

export const RagChat = () => {
  const token = useSelector((state) => state.auth.token);
  const locale = useSelector((state) => state.preferences.locale);
  const [question, setQuestion] = useState('');
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [booting, setBooting] = useState(true);
  const [error, setError] = useState(null);
  const bottomRef = useRef(null);

  const scrollToBottom = () => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  const selectSession = async (id) => {
    setActiveId(id);
    setError(null);
    try {
      const data = await getRagSession(token, locale, id);
      const serverMessages = data.messages || [];
      setMessages(
        serverMessages.map((m) => ({
          role: m.role,
          content: m.content,
        })),
      );
    } catch (err) {
      setError(err?.response?.data?.Error || err?.message || 'Failed to load session');
    }
  };

  const newSession = async () => {
    setError(null);
    try {
      const session = await createRagSession(token, locale, {});
      setSessions((s) => [session, ...s]);
      setActiveId(session.id);
      setMessages([]);
      setQuestion('');
    } catch (err) {
      setError(err?.response?.data?.Error || err?.message || 'Failed to create session');
    }
  };

  const removeSession = async (id) => {
    setError(null);
    try {
      await deleteRagSession(token, locale, id);
      setSessions((s) => s.filter((x) => x.id !== id));
      if (activeId === id) {
        setActiveId(null);
        setMessages([]);
      }
    } catch (err) {
      setError(err?.response?.data?.Error || err?.message || 'Failed to delete session');
    }
  };

  const bootstrap = async () => {
    try {
      const data = await listRagSessions(token, locale);
      const list = data.sessions || [];
      if (list.length === 0) {
        const session = await createRagSession(token, locale, {});
        setSessions([session]);
        setActiveId(session.id);
        setMessages([]);
      } else {
        setSessions(list);
        await selectSession(list[0].id);
      }
    } catch (err) {
      setError(err?.response?.data?.Error || err?.message || 'Failed to load sessions');
    } finally {
      setBooting(false);
    }
  };

  useEffect(() => {
    bootstrap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const send = async (e) => {
    e?.preventDefault();
    const q = question.trim();
    if (!q || loading || !activeId) return;
    if (q.length > RAG_MAX_QUESTION_CHARS) {
      setError(`Question is too long (max ${RAG_MAX_QUESTION_CHARS} characters).`);
      return;
    }
    setError(null);
    setMessages((m) => [...m, { role: 'user', content: q }]);
    setQuestion('');
    setLoading(true);

    let acc = '';

    streamRagSessionChat(
      token,
      locale,
      activeId,
      { question: q },
      (delta) => {
        acc += delta;
        setMessages((m) => {
          const copy = [...m];
          const last = copy[copy.length - 1];
          if (last && last.role === 'assistant' && last.streaming) {
            copy[copy.length - 1] = { ...last, content: acc };
          } else {
            copy.push({ role: 'assistant', content: acc, streaming: true });
          }
          return copy;
        });
      },
      () => {
        setMessages((m) => {
          const copy = [...m];
          const last = copy[copy.length - 1];
          if (last && last.role === 'assistant') {
            copy[copy.length - 1] = {
              ...last,
              streaming: false,
            };
          }
          return copy;
        });
      },
      (err) => {
        setError(err);
        setMessages((m) => {
          const copy = [...m];
          const last = copy[copy.length - 1];
          if (last && last.role === 'assistant' && last.streaming) {
            copy[copy.length - 1] = { ...last, streaming: false, isError: true };
          }
          return copy;
        });
      },
    ).finally(() => {
      setLoading(false);
      // Refresh the session title (auto-set from first question) in the sidebar.
      listRagSessions(token, locale)
        .then((d) => setSessions(d.sessions || []))
        .catch(() => {});
    });
  };

  return (
    <div className="w-100 mw8 center pa3">
      <div className="bg-white shadow-1 br2 overflow-hidden flex" style={{ height: '72vh' }}>
        {/* Sidebar — only exposed on /chat development UI */}
        <div className="w5 bg-near-white br b--light-gray flex flex-column">
          <div className="pa3 bb b--light-gray">
            <Button
              className="bg-red white w-100"
              onClick={newSession}
              data-testid="rag-new-session"
            >
              + New chat
            </Button>
          </div>
          <div className="flex-auto overflow-y-auto">
            {sessions.map((s) => (
              <div
                key={s.id}
                className={`pa3 bb b--light-gray pointer ${
                  s.id === activeId ? 'bg-washed-blue' : ''
                }`}
                onClick={() => selectSession(s.id)}
                data-testid="rag-session-item"
              >
                <div className="f6 b truncate">{s.title || 'New chat'}</div>
                <div className="f7 o-50 flex justify-between items-center mt1">
                  <span>{s.message_count || 0} msgs</span>
                  <button
                    className="bn bg-transparent red pointer f7"
                    onClick={(e) => {
                      e.stopPropagation();
                      removeSession(s.id);
                    }}
                  >
                    delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Main chat */}
        <div className="flex-auto flex flex-column">
          <div className="bg-blue-dark white pa3 flex flex-wrap items-center justify-between gap-3">
            <h2 className="f4 ma0">
              <FormattedMessage id="rag.chat.title" defaultMessage="TMBot" />
              <span className="fw4 f6 ml2 o-70">Tasking Manager assistant</span>
            </h2>
          </div>

          <div
            className="pa3 overflow-y-auto flex-auto"
            style={{ background: '#fafafa' }}
            data-testid="rag-messages"
          >
            {booting ? (
              <div className="f6 i o-60 pa2">Loading…</div>
            ) : (
              <ChatMessageList
                messages={messages}
                loading={loading}
                error={error}
                bottomRef={bottomRef}
              />
            )}
            {/* Keep bottomRef for scroll even when booting is done above? ChatMessageList also has one, but we need outer */}
            <div ref={booting ? bottomRef : null} />
          </div>

          <ChatInput
            value={question}
            onChange={setQuestion}
            onSubmit={send}
            loading={loading}
            disabled={!activeId}
            maxChars={RAG_MAX_QUESTION_CHARS}
            testIdInput="rag-input"
            testIdSend="rag-send"
          />
        </div>
      </div>
    </div>
  );
};
