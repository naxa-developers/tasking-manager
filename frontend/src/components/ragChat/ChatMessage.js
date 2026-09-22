import React from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import './ChatMessage.css';

export const GREETING =
  'Hi! I am TMBot, your Tasking Manager assistant. Ask me about mapping, validation, project creation, permissions, or task states.';

function normalizeSteps(raw) {
  let display = raw || '';
  // The LLM often emits steps as 4-space-indented lines. With a blank line
  // before them, markdown reads that as a <pre> code block and preserves
  // every blank line literally (the gappy look). These answers are prose, so
  // dedent non-fenced lines; real ``` fences are left untouched.
  const lines = display.split('\n');
  let inFence = false;
  display = lines
    .map((l) => {
      if (/^\s*```/.test(l)) {
        inFence = !inFence;
        return l;
      }
      if (!inFence) {
        return l.replace(/^(?: {4}|\t)/, '').replace(/\s+$/, '');
      }
      return l;
    })
    .join('\n');
  const hasLegacy = display.includes('Step 1:') && display.includes('Step 2:');
  const hasMarkdown = /\n?1\.\s/.test(display) && /\n?2\.\s/.test(display);
  const hasInlineSteps =
    (hasLegacy || hasMarkdown) && !display.includes('\n1.') && !display.includes('\nStep');
  if (hasLegacy || hasMarkdown || hasInlineSteps) {
    if (display.includes('Step 1:')) {
      display = display.replace(/\s*(Step \d+:)/g, '\n$1').trim();
    }
    if (/1\.\s/.test(display)) {
      display = display.replace(/\s+(\d+\.\s)/g, '\n$1');
    }
    display = display.replace(/\n\n+/g, '\n').trim();
    display = display.replace(/([^\n])\n(1\. |Step 1:)/, '$1\n\n$2');
    display = display.replace(/\n{3,}/g, '\n\n');
  }
  if (display.toLowerCase().includes('filter') && display.includes('Country')) {
    display = display.replace(/\bCountry\b/g, 'location').replace(/\bcountry\b/g, 'location');
  }
  // A closing sentence on a bare single newline right after the final list
  // item ("...select a location.\nThis will help you...") would otherwise
  // render glued inside that bullet (breaks:true). Split trailing non-list
  // lines after the last numbered item into their own paragraph.
  const ls = display.split('\n');
  let lastItem = -1;
  ls.forEach((l, i) => {
    if (/^\d+\.\s/.test(l.trim())) {
      lastItem = i;
    }
  });
  if (lastItem >= 0) {
    let k = lastItem + 1;
    while (
      k < ls.length &&
      ls[k].trim() !== '' &&
      !/^\d+\.\s/.test(ls[k].trim()) &&
      !/^([-*•]|Step \d+:)/.test(ls[k].trim())
    ) {
      k += 1;
    }
    if (k > lastItem + 1 && ls[lastItem + 1].trim() !== '') {
      ls.splice(lastItem + 1, 0, '');
      display = ls.join('\n');
    }
  }
  return display;
}

/**
 * Render assistant/user text as sanitized markdown (Option A).
 *
 * The LLM emits `**bold**`, numbered lists and links; the old plain-text path
 * rendered those markers literally. marked.parse handles them; DOMPurify with
 * the default config strips scripts/raw-HTML event handlers (no iframes, no
 * extra tags — unlike the project-description renderer in htmlFromMarkdown.js).
 * The Step/list line-splitting above is kept so single-line "1. ... 2. ..."
 * answers still become real lists.
 */
function renderContent(raw) {
  const normalized = normalizeSteps(raw);
  // breaks:true keeps single newlines as <br> so step-per-line answers don't
  // merge into one paragraph. (Per-call option — does not touch the global
  // marked config used by htmlFromMarkdown.js.)
  const html = DOMPurify.sanitize(marked.parse(normalized || '', { breaks: true }), {
    // No embedded media (markdown images are a trackable-pixel exfil channel)
    // and link schemes limited to http(s)/mailto/tel/#/relative.
    FORBID_TAGS: [
      'img',
      'picture',
      'source',
      'iframe',
      'object',
      'embed',
      'form',
      'input',
      'style',
    ],
    FORBID_ATTR: ['srcset', 'style'],
    ALLOWED_URI_REGEXP: /^(?:https?:|mailto:|tel:|#|\/)/i,
  });
  return (
    <div
      className="rag-markdown"
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

export const ChatMessage = ({ message }) => {
  const m = message;
  return (
    <div
      className={`mb3 pa3 br2 ${
        m.role === 'user' ? 'bg-light-blue ml4' : 'bg-white mr4 shadow-1'
      } ${m.isError ? 'bg-washed-red' : ''}`}
      data-testid={m.role === 'user' ? 'chat-message-user' : 'chat-message-assistant'}
    >
      <div className="f7 b ttu tracked mb1 o-60">{m.role === 'user' ? `You` : `TMBot`}</div>
      <div className="f6 lh-copy" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
        {renderContent(m.content)}
        {m.streaming && <span className="o-60"> ▌</span>}
      </div>
    </div>
  );
};

export const ChatMessageList = ({ messages, loading, error, bottomRef }) => {
  const list = messages.length === 0 ? [{ role: 'assistant', content: GREETING }] : messages;
  return (
    <>
      {list.map((m, i) => (
        <ChatMessage key={i} message={m} />
      ))}
      {loading && <div className="f6 i o-60 pa2">Thinking…</div>}
      {error && <div className="f7 red pa2 bg-washed-red br1">{error}</div>}
      <div ref={bottomRef} />
    </>
  );
};
