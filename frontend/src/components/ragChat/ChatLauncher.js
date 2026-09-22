import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useSelector } from 'react-redux';
import {
  createRagSession,
  getRagSession,
  streamRagSessionChat,
  RAG_MAX_QUESTION_CHARS,
} from '../../api/rag';
import { ChatMessageList } from './ChatMessage';
import { ChatInput } from './ChatInput';
import './chatLauncher.scss';

const STORAGE_SESSION_KEY = 'tm_rag_floating_session_id';

function getStoredSessionId() {
  try {
    return localStorage.getItem(STORAGE_SESSION_KEY);
  } catch (e) {
    return null;
  }
}

function setStoredSessionId(id) {
  try {
    if (id) localStorage.setItem(STORAGE_SESSION_KEY, id);
    else localStorage.removeItem(STORAGE_SESSION_KEY);
  } catch (e) {}
}

export const ChatLauncher = () => {
  const token = useSelector((state) => state.auth.token);
  const locale = useSelector((state) => state.preferences.locale);

  const [isOpen, setIsOpen] = useState(false);
  const [question, setQuestion] = useState('');
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [booting, setBooting] = useState(false);
  const [error, setError] = useState(null);
  const bottomRef = useRef(null);
  const panelRef = useRef(null);

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading, scrollToBottom]);

  const loadSession = useCallback(
    async (id) => {
      try {
        const data = await getRagSession(token, locale, id);
        const serverMessages = data.messages || [];
        setMessages(
          serverMessages.map((m) => ({
            role: m.role,
            content: m.content,
          })),
        );
        setActiveId(id);
        setStoredSessionId(id);
        setError(null);
      } catch (err) {
        // Session may have been deleted or not found; clear storage
        setStoredSessionId(null);
        setActiveId(null);
        setMessages([]);
        // Don't show error for missing session on boot; will create new on send
        if (err?.response?.status !== 404) {
          setError(err?.response?.data?.Error || err?.message || 'Failed to load session');
        }
      }
    },
    [token, locale],
  );

  const ensureSession = useCallback(async () => {
    if (activeId) return activeId;
    // Try stored id first — validate it exists
    const stored = getStoredSessionId();
    if (stored) {
      try {
        const data = await getRagSession(token, locale, stored);
        if (data?.session?.id) {
          // Ensure local state is synced
          await loadSession(stored);
          return stored;
        }
      } catch (e) {
        // stored session invalid; clear and fall through to create
        setStoredSessionId(null);
      }
    }
    // Create fresh session (floating widget keeps its own current conversation)
    try {
      const session = await createRagSession(token, locale, {});
      setActiveId(session.id);
      setStoredSessionId(session.id);
      setMessages([]);
      setError(null);
      return session.id;
    } catch (err) {
      setError(err?.response?.data?.Error || err?.message || 'Failed to create session');
      return null;
    }
  }, [activeId, loadSession, token, locale]);

  // Eagerly bootstrap when panel opens first time
  useEffect(() => {
    if (!isOpen) return;
    if (activeId || booting) return;
    const stored = getStoredSessionId();
    if (stored) {
      setBooting(true);
      loadSession(stored).finally(() => setBooting(false));
    } else {
      // No stored session yet; don't auto-create until first message to avoid empty sessions.
      // But we could also auto-create so input is enabled immediately.
      // Spec says widget should be able to start/use a conversation — create on open for better UX.
      setBooting(true);
      ensureSession().finally(() => setBooting(false));
    }
  }, [isOpen, activeId, booting, loadSession, ensureSession]);

  const newChat = async () => {
    setError(null);
    try {
      const session = await createRagSession(token, locale, {});
      setActiveId(session.id);
      setStoredSessionId(session.id);
      setMessages([]);
      setQuestion('');
    } catch (err) {
      setError(err?.response?.data?.Error || err?.message || 'Failed to create session');
    }
  };

  const send = async (e) => {
    e?.preventDefault();
    const q = question.trim();
    if (!q || loading) return;
    if (q.length > RAG_MAX_QUESTION_CHARS) {
      setError(`Question is too long (max ${RAG_MAX_QUESTION_CHARS} characters).`);
      return;
    }
    setError(null);
    setQuestion('');
    // Ensure we have a session id
    let sessionId = activeId;
    if (!sessionId) {
      setLoading(true);
      sessionId = await ensureSession();
      setLoading(false);
      if (!sessionId) return;
    }
    setMessages((m) => [...m, { role: 'user', content: q }]);
    setLoading(true);
    let acc = '';
    streamRagSessionChat(
      token,
      locale,
      sessionId,
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
    });
  };

  // Chat requires login (backend rejects anonymous sessions with 401/404).
  if (!token) return null;

  return (
    <>
      {/* Launcher button */}
      <button
        onClick={() => setIsOpen((v) => !v)}
        className="chat-launcher-button bg-red white bn br-100 shadow-5 pointer flex items-center justify-center"
        aria-label={isOpen ? 'Close chat' : 'Open chat'}
        data-testid="chat-launcher-button"
        style={{
          position: 'fixed',
          bottom: '24px',
          right: '24px',
          width: '56px',
          height: '56px',
          fontSize: '1.6rem',
          zIndex: 999,
        }}
      >
        {isOpen ? '×' : '💬'}
      </button>

      {isOpen && (
        <div
          ref={panelRef}
          className="chat-panel bg-white shadow-5 br2 flex flex-column overflow-hidden"
          data-testid="chat-panel"
          style={{
            position: 'fixed',
            bottom: '90px',
            right: '24px',
            width: '380px',
            height: '520px',
            maxHeight: '70vh',
            zIndex: 998,
            border: '1px solid #e0e0e0',
          }}
        >
          {/* Header */}
          <div className="bg-blue-dark white pa3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <h3 className="f5 ma0">TM Assistant</h3>
              <button
                onClick={newChat}
                className="ml2 ph2 pv1 br1 ba b--white bg-transparent white pointer f7"
                aria-label="New chat"
                data-testid="floating-new-chat"
                title="Start new chat"
                disabled={booting}
              >
                + New chat
              </button>
            </div>
            <button
              onClick={() => setIsOpen(false)}
              className="bn bg-transparent white pointer f4 ml2"
              aria-label="Close chat panel"
              data-testid="chat-panel-close"
            >
              ×
            </button>
          </div>

          {/* Messages */}
          <div
            className="flex-auto overflow-y-auto pa3"
            style={{ background: '#fafafa' }}
            data-testid="floating-chat-messages"
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
          </div>

          {/* Input */}
          <ChatInput
            value={question}
            onChange={setQuestion}
            onSubmit={send}
            loading={loading}
            disabled={booting || (!activeId && loading)}
            maxChars={RAG_MAX_QUESTION_CHARS}
            testIdInput="floating-chat-input"
            testIdSend="floating-chat-send"
            placeholderId="rag.chat.placeholder"
            defaultPlaceholder="Ask something…"
          />
        </div>
      )}
    </>
  );
};
