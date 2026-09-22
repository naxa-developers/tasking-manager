import api from './apiClient';
import { API_URL } from '../config';

// Keep in sync with backend chat/constants.py (MAX_QUESTION_CHARS).
export const RAG_MAX_QUESTION_CHARS = 4000;

export const createRagSession = (token, locale, payload = {}) => {
  return api(token, locale)
    .post('rag/sessions', payload)
    .then((res) => res.data);
};

export const listRagSessions = (token, locale, params = {}) => {
  return api(token, locale)
    .get('rag/sessions', { params })
    .then((res) => res.data);
};

export const getRagSession = (token, locale, sessionId) => {
  return api(token, locale)
    .get(`rag/sessions/${sessionId}`)
    .then((res) => res.data);
};

export const deleteRagSession = (token, locale, sessionId) => {
  return api(token, locale)
    .delete(`rag/sessions/${sessionId}`)
    .then((res) => res.data);
};

export const updateRagSession = (token, locale, sessionId, payload) => {
  return api(token, locale)
    .patch(`rag/sessions/${sessionId}`, payload)
    .then((res) => res.data);
};

export const streamRagSessionChat = (token, locale, sessionId, payload, onDelta, onMeta, onError) => {
  // Server-Sent Events streaming via fetch (XHR/fetch-based, not EventSource,
  // so we can POST a JSON body).
  const baseURL = typeof API_URL === 'string' ? API_URL : API_URL.toString();
  const url = `${baseURL}rag/sessions/${sessionId}/chat`;
  const headers = {
    'Content-Type': 'application/json',
    ...(token && { Authorization: `Token ${token}` }),
    ...(locale && { 'Accept-Language': locale.replace('-', '_') || 'en' }),
  };

  return fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify({ stream: true, ...payload }),
  })
    .then(async (res) => {
      if (!res.ok || !res.body) {
        const errText = await res.text().catch(() => '');
        throw new Error(errText || `Request failed (${res.status})`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        let event = 'message';
        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed.startsWith('event:')) {
            event = trimmed.slice(6).trim();
          } else if (trimmed.startsWith('data:')) {
            const payloadStr = trimmed.slice(5).trim();
            let data = {};
            try {
              data = JSON.parse(payloadStr);
            } catch (e) {
              data = { raw: payloadStr };
            }
            if (event === 'meta') {
              onMeta && onMeta(data);
            } else if (event === 'error') {
              onError && onError(data.error || data);
            } else if (event === 'done') {
              // no-op
            } else {
              onDelta && onDelta(data.delta || '');
            }
          }
        }
      }
    })
    .catch((err) => {
      onError && onError(err.message || 'Stream failed');
    });
};
