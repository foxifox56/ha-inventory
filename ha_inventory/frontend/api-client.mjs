// Same-origin API wrapper with one narrow retry for an expired write session.
export function createApiClient(fetchImpl, apiBaseUrl) {
  let writeToken = '';

  async function readResponse(response) {
    return response.json().catch(() => ({}));
  }

  async function acquireWriteSession() {
    const response = await fetchImpl(new URL('write-session', apiBaseUrl), {
      cache: 'no-store',
    });
    const body = await readResponse(response);
    if (!response.ok || !body.write_token) {
      const error = new Error(body.error || 'Schreibsitzung konnte nicht geöffnet werden.');
      error.status = response.status;
      error.code = body.code;
      throw error;
    }
    writeToken = body.write_token;
  }

  async function request(path, options = {}, refreshedWriteSession = false) {
    const method = (options.method || 'GET').toUpperCase();
    const isMutation = !['GET', 'HEAD', 'OPTIONS'].includes(method);
    if (isMutation && !writeToken) await acquireWriteSession();

    const response = await fetchImpl(new URL(path, apiBaseUrl), {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(isMutation && writeToken
          ? { 'X-HA-Inventory-Write-Token': writeToken }
          : {}),
        ...(options.headers || {}),
      },
    });
    const body = await readResponse(response);
    if (
      response.status === 403
      && body.code === 'write_session_invalid'
      && isMutation
      && !refreshedWriteSession
    ) {
      writeToken = '';
      await acquireWriteSession();
      return request(path, options, true);
    }
    if (!response.ok) {
      const error = new Error(body.error || 'Die Anfrage ist fehlgeschlagen.');
      error.status = response.status;
      error.code = body.code;
      error.field = body.field;
      error.retryAfterSeconds = Number(body.retry_after_seconds);
      throw error;
    }
    return body;
  }

  return { request, acquireWriteSession };
}
