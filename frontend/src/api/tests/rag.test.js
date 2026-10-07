import { streamRagSessionChat } from '../rag';

describe('streamRagSessionChat error rendering', () => {
  const noop = () => {};
  const originalFetch = global.fetch;

  afterEach(() => {
    if (originalFetch === undefined) {
      delete global.fetch;
    } else {
      global.fetch = originalFetch;
    }
  });

  const respond = (status, body) =>
    Promise.resolve({
      ok: false,
      status,
      text: () => Promise.resolve(body),
    });

  it('surfaces the API Error field on 422 RAGQuestionTooLong', async () => {
    global.fetch = jest.fn(() =>
      respond(
        422,
        JSON.stringify({
          Error: 'This message is too long for search — please shorten it.',
          SubCode: 'RAGQuestionTooLong',
        }),
      ),
    );
    const onError = jest.fn();

    await streamRagSessionChat('token', 'en', 1, { question: 'q' }, noop, noop, onError);

    expect(onError).toHaveBeenCalledWith(
      'This message is too long for search — please shorten it.',
    );
  });

  it('surfaces the API Error field on 503 RAGRetrievalFailed', async () => {
    global.fetch = jest.fn(() =>
      respond(
        503,
        JSON.stringify({
          Error: 'Knowledge base search is temporarily unavailable. Please try again.',
          SubCode: 'RAGRetrievalFailed',
        }),
      ),
    );
    const onError = jest.fn();

    await streamRagSessionChat('token', 'en', 1, { question: 'q' }, noop, noop, onError);

    expect(onError).toHaveBeenCalledWith(
      'Knowledge base search is temporarily unavailable. Please try again.',
    );
  });

  it('falls back to the raw body for non-JSON error responses', async () => {
    global.fetch = jest.fn(() => respond(500, 'gateway blew up'));
    const onError = jest.fn();

    await streamRagSessionChat('token', 'en', 1, { question: 'q' }, noop, noop, onError);

    expect(onError).toHaveBeenCalledWith('gateway blew up');
  });
});
