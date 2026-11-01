
export type Source = {
  filename: string
  chunk_index: number
  content: string
}


export type UploadedDocument = {
  document_id: string
  filename: string
  status: string
  uploaded_at: string
  error_message: string | null
}

export type ChatSession = {
  session_id: string
  title: string
  created_at: string
  updated_at: string
}

export type SessionMessage = {
  message_id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export type SessionDetail = {
  session_id: string
  title: string
  created_at: string
  updated_at: string
  messages: SessionMessage[]
}

type StreamQueryOptions = {
  question: string
  sessionId: string | null
  provider?: 'openai' | 'ollama'
  mode?: 'normal' | 'rag'
  signal: AbortSignal
  onToken: (text: string) => void
  onSources: (sources: Source[]) => void
  onDone: (sessionId: string) => void
}

const API_BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const DEFAULT_PROVIDER = import.meta.env.VITE_LLM_PROVIDER ?? 'ollama'
const TOKEN_KEY = 'rag_access_token'

export function getAccessToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function setAccessToken(token: string | null): void {
  if (token) sessionStorage.setItem(TOKEN_KEY, token)
  else sessionStorage.removeItem(TOKEN_KEY)
}

function authHeaders(extra: HeadersInit = {}): HeadersInit {
  const token = getAccessToken()
  return {
    ...extra,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

export type AuthUser = {
  id: string
  email: string
  is_active: boolean
}

export async function registerUser(email: string, password: string): Promise<AuthUser> {
  return checkResponse<AuthUser>(await fetch(`${API_BASE_URL}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  }))
}

export async function loginUser(email: string, password: string): Promise<AuthUser> {
  const tokenResponse = await checkResponse<{ access_token: string; token_type: string }>(
    await fetch(`${API_BASE_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    }),
  )
  setAccessToken(tokenResponse.access_token)
  try {
    return await getCurrentUser()
  } catch (error) {
    setAccessToken(null)
    throw error
  }
}

export async function getCurrentUser(): Promise<AuthUser> {
  return checkResponse<AuthUser>(await fetch(`${API_BASE_URL}/auth/me`, {
    headers: authHeaders(),
  }))
}

export function logoutUser(): void {
  setAccessToken(null)
}

// -----------------------------------------------------------------------------
// Shared response handling
// -----------------------------------------------------------------------------

async function checkResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `Request failed (${response.status})`

    try {
      const body = await response.json()
      detail = body.detail ?? detail
    } catch {
      // Keep the default error message if the response isn't JSON.
    }

    throw new Error(detail)
  }

  return response.json() as Promise<T>
}

// -----------------------------------------------------------------------------
// Conversation history
// -----------------------------------------------------------------------------

export async function fetchSessions(): Promise<ChatSession[]> {
  const response = await fetch(`${API_BASE_URL}/sessions`, { headers: authHeaders() })

  return checkResponse<ChatSession[]>(response)
}

export async function fetchSession(
  sessionId: string,
): Promise<SessionDetail> {
  const response = await fetch(
    `${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}`,
    { headers: authHeaders() },
  )

  return checkResponse<SessionDetail>(response)
}

export async function deleteSession(sessionId: string): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}`,
    {
      method: 'DELETE',
      headers: authHeaders(),
    },
  )

  if (!response.ok) {
    let detail = `Failed to delete conversation (${response.status})`

    try {
      const body = await response.json()
      detail = body.detail ?? detail
    } catch {
      // Keep the default error message if the response isn't JSON.
    }

    throw new Error(detail)
  }
}

export async function renameSession(
  sessionId: string,
  title: string,
): Promise<ChatSession> {
  const response = await fetch(
    `${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}`,
    {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        title: title.trim(),
      }),
    },
  )

  return checkResponse<ChatSession>(response)
}

// -----------------------------------------------------------------------------
// Streaming query
// -----------------------------------------------------------------------------

export async function streamQuery({
  question,
  sessionId,
  provider = DEFAULT_PROVIDER,
  mode = 'rag',
  signal,
  onToken,
  onSources,
  onDone,
}: StreamQueryOptions): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/query/stream`, {
    method: 'POST',
    headers: authHeaders({
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    }),
    body: JSON.stringify({
      question,
      session_id: sessionId,
      provider,
      mode,
    }),
    signal,
  })

  if (!response.ok) {
    let detail = `Request failed (${response.status})`

    try {
      const body = await response.json()
      detail = body.detail ?? detail
    } catch {
      // Response body wasn't JSON; keep the status-based message.
    }

    throw new Error(detail)
  }

  if (!response.body) {
    throw new Error('The server returned an empty response stream.')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  function dispatchEvent(rawEvent: string) {
    let eventName = 'message'
    const dataLines: string[] = []

    for (const line of rawEvent.split('\n')) {
      if (line.startsWith('event:')) {
        eventName = line.slice('event:'.length).trim()
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice('data:'.length).trimStart())
      }
    }

    if (dataLines.length === 0) return

    const data = JSON.parse(dataLines.join('\n')) as {
      text?: string
      sources?: Source[]
      session_id?: string
      message?: string
    }

    if (eventName === 'token' && data.text) {
      onToken(data.text)
    } else if (eventName === 'sources') {
      onSources(data.sources ?? [])
    } else if (eventName === 'done' && data.session_id) {
      onDone(data.session_id)
    } else if (eventName === 'error') {
      throw new Error(
        data.message ?? 'The server could not generate an answer.',
      )
    }
  }

  try {
    while (true) {
      const { value, done } = await reader.read()

      if (done) break

      buffer += decoder.decode(value, { stream: true })

      const events = buffer.split('\n\n')
      buffer = events.pop() ?? ''

      for (const event of events) {
        dispatchEvent(event)
      }
    }

    buffer += decoder.decode()

    if (buffer.trim()) {
      dispatchEvent(buffer)
    }
  } finally {
    reader.releaseLock()
  }
}


// -----------------------------------------------------------------------------
// Document library
// -----------------------------------------------------------------------------

export async function fetchDocuments(): Promise<UploadedDocument[]> {
  const response = await fetch(`${API_BASE_URL}/documents`, { headers: authHeaders() })
  return checkResponse<UploadedDocument[]>(response)
}

export async function uploadDocument(file: File): Promise<UploadedDocument> {
  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(`${API_BASE_URL}/upload`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  })

  return checkResponse<UploadedDocument>(response)
}

export async function deleteDocument(documentId: string): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/documents/${encodeURIComponent(documentId)}`,
    { method: 'DELETE', headers: authHeaders() },
  )

  if (!response.ok) {
    let detail = `Failed to delete document (${response.status})`
    try {
      const body = await response.json()
      detail = body.detail ?? detail
    } catch {
      // Keep the default message when the response isn't JSON.
    }
    throw new Error(detail)
  }
}
