
import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  ArrowUp,
  BookOpen,
  ChevronDown,
  FileText,
  Menu,
  MessageSquare,
  MoreHorizontal,
  LogOut,
  PanelLeft,
  Plus,
  Search,
  Sparkles,
  Square,
  Pencil,
  Trash2,
  X
} from 'lucide-react'

import {
  streamQuery,
  fetchSessions,
  fetchSession,
  deleteSession,
  renameSession,
  type Source,
  type ChatSession,
  fetchDocuments,
  uploadDocument,
  deleteDocument,
  type UploadedDocument,
  loginUser,
  registerUser,
  getCurrentUser,
  getAccessToken,
  logoutUser,
  type AuthUser,
} from './lib/api'

type Message = {
  id: number
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
}

const suggestions = [
  {
    icon: BookOpen,
    title: 'Explain a concept',
    prompt: 'Explain how retrieval augmented generation works.',
  },
  {
    icon: Search,
    title: 'Search my documents',
    prompt: 'What information is available in my uploaded documents?',
  },
  {
    icon: FileText,
    title: 'Summarize a document',
    prompt: 'Give me a concise summary of my documents.',
  },
  {
    icon: Sparkles,
    title: 'Help me understand',
    prompt: 'Help me understand the key ideas in my knowledge base.',
  },
]

function App() {
  const [authUser, setAuthUser] = useState<AuthUser | null>(null)
  const [authReady, setAuthReady] = useState(false)
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login')
  const [authEmail, setAuthEmail] = useState('')
  const [authPassword, setAuthPassword] = useState('')
  const [authBusy, setAuthBusy] = useState(false)
  const [authError, setAuthError] = useState<string | null>(null)
  const [profileOpen, setProfileOpen] = useState(false)
  const [openMenuSessionId, setOpenMenuSessionId] = useState<string | null>(
    null,
  )

  const [renamingSessionId, setRenamingSessionId] = useState<string | null>(
    null,
  )

  const [renameValue, setRenameValue] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)

  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [chats, setChats] = useState<ChatSession[]>([])

  // activeChat is the backend session UUID, not the display title.
  const [activeChat, setActiveChat] = useState<string | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)

  const [nextMessageId, setNextMessageId] = useState(1)
  const [isStreaming, setIsStreaming] = useState(false)
  const [isLoadingChats, setIsLoadingChats] = useState(true)
  const [isLoadingSession, setIsLoadingSession] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const abortControllerRef = useRef<AbortController | null>(null)

  const hasMessages = messages.length > 0
  const [mode, setMode] = useState<'normal' | 'rag'>('rag')
  const [provider, setProvider] = useState<'openai' | 'ollama'>('ollama')

  const [documents, setDocuments] = useState<UploadedDocument[]>([])
  const [isDocumentsOpen, setIsDocumentsOpen] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [documentError, setDocumentError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  // Restore the signed-in user from the session token.
  useEffect(() => {
    async function restoreAuth() {
      if (!getAccessToken()) {
        setAuthReady(true)
        setIsLoadingChats(false)
        return
      }
      try {
        setAuthUser(await getCurrentUser())
      } catch {
        logoutUser()
      } finally {
        setAuthReady(true)
      }
    }
    void restoreAuth()
  }, [])

  // Load only the signed-in user's conversation history.
  useEffect(() => {
    if (!authUser) return
    let cancelled = false
    async function loadChats() {
      setIsLoadingChats(true)
      try {
        const sessions = await fetchSessions()
        if (!cancelled) setChats(sessions)
      } catch (caught) {
        const message = caught instanceof Error ? caught.message : 'Could not load conversations.'
        if (!cancelled) setError(message)
      } finally {
        if (!cancelled) setIsLoadingChats(false)
      }
    }
    void loadChats()
    if (!authReady) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#212121] text-[#e5e5e5]">
        <p className="text-sm text-[#b4b4b4]">Checking your session…</p>
      </div>
    )
  }

  if (!authUser) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#212121] px-4 text-[#e5e5e5]">
        <div className="w-full max-w-md rounded-2xl border border-white/10 bg-[#2a2a2a] p-8 shadow-2xl">
          <div className="mb-7 text-center">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-white text-black">
              <Sparkles size={24} />
            </div>
            <h1 className="text-2xl font-semibold">RAG Workspace</h1>
            <p className="mt-2 text-sm text-[#a3a3a3]">
              {authMode === 'login' ? 'Sign in to continue to your knowledge assistant.' : 'Create an account to get started.'}
            </p>
          </div>
          <form onSubmit={handleAuthSubmit} className="space-y-4">
            <label className="block">
              <span className="mb-1.5 block text-sm text-[#d4d4d4]">Email</span>
              <input type="email" required autoComplete="email" value={authEmail} onChange={(event) => setAuthEmail(event.target.value)} placeholder="you@example.com" className="w-full rounded-lg border border-white/10 bg-[#1f1f1f] px-3 py-3 text-sm outline-none focus:border-white/30" />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-sm text-[#d4d4d4]">Password</span>
              <input type="password" required minLength={authMode === 'register' ? 8 : undefined} autoComplete={authMode === 'login' ? 'current-password' : 'new-password'} value={authPassword} onChange={(event) => setAuthPassword(event.target.value)} placeholder={authMode === 'register' ? 'At least 8 characters' : 'Your password'} className="w-full rounded-lg border border-white/10 bg-[#1f1f1f] px-3 py-3 text-sm outline-none focus:border-white/30" />
            </label>
            {authError && <p role="alert" className="rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-300">{authError}</p>}
            <button type="submit" disabled={authBusy} className="w-full rounded-lg bg-white px-4 py-3 text-sm font-semibold text-black transition hover:bg-[#e5e5e5] disabled:opacity-50">
              {authBusy ? 'Please wait…' : authMode === 'login' ? 'Sign in' : 'Create account'}
            </button>
          </form>
          <p className="mt-5 text-center text-sm text-[#a3a3a3]">
            {authMode === 'login' ? "Don't have an account?" : 'Already have an account?'}{' '}
            <button type="button" onClick={() => { setAuthMode(authMode === 'login' ? 'register' : 'login'); setAuthError(null) }} className="font-medium text-white underline underline-offset-4">
              {authMode === 'login' ? 'Create one' : 'Sign in'}
            </button>
          </p>
        </div>
      </div>
    )
  }

  return () => { cancelled = true }
  }, [authUser])

  async function handleAuthSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setAuthBusy(true)
    setAuthError(null)
    try {
      if (authMode === 'register') {
        await registerUser(authEmail.trim(), authPassword)
      }
      const user = await loginUser(authEmail.trim(), authPassword)
      setAuthUser(user)
      setAuthPassword('')
      setChats([])
      setMessages([])
      setActiveChat(null)
      setSessionId(null)
    } catch (caught) {
      setAuthError(caught instanceof Error ? caught.message : 'Authentication failed.')
    } finally {
      setAuthBusy(false)
    }
  }

  function handleLogout() {
    logoutUser()
    setAuthUser(null)
    setChats([])
    setMessages([])
    setActiveChat(null)
    setSessionId(null)
    setDocuments([])
    setIsDocumentsOpen(false)
    setProfileOpen(false)
    setError(null)
  }

  async function refreshDocuments() {
    const result = await fetchDocuments()
    setDocuments(result)
  }

  async function openDocumentLibrary() {
    setIsDocumentsOpen(true)
    setDocumentError(null)
    try {
      await refreshDocuments()
    } catch (caught) {
      setDocumentError(caught instanceof Error ? caught.message : 'Could not load documents.')
    }
  }

  async function handleFileSelected(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    // Reset the input so selecting the same file again triggers onChange.
    event.target.value = ''
    if (!file) return

    setIsUploading(true)
    setDocumentError(null)
    try {
      await uploadDocument(file)
      await refreshDocuments()
      setIsDocumentsOpen(true)
    } catch (caught) {
      setDocumentError(caught instanceof Error ? caught.message : 'Upload failed.')
      setIsDocumentsOpen(true)
    } finally {
      setIsUploading(false)
    }
  }

  async function handleDeleteDocument(document: UploadedDocument) {
    if (!window.confirm(`Delete "${document.filename}" from your knowledge base?`)) return
    setDocumentError(null)
    try {
      await deleteDocument(document.document_id)
      await refreshDocuments()
    } catch (caught) {
      setDocumentError(caught instanceof Error ? caught.message : 'Could not delete document.')
    }
  }

  function startNewChat() {
    abortControllerRef.current?.abort()
    abortControllerRef.current = null

    setMessages([])
    setInput('')
    setActiveChat(null)
    setSessionId(null)
    setMobileSidebarOpen(false)
    setNextMessageId(1)
    setIsStreaming(false)
    setIsLoadingSession(false)
    setError(null)
  }

  async function openChat(chatSessionId: string) {
    if (isStreaming || isLoadingSession) return

    setIsLoadingSession(true)
    setError(null)

    try {
      const session = await fetchSession(chatSessionId)

      const loadedMessages: Message[] = session.messages.map(
        (message, index) => ({
          id: index + 1,
          role: message.role,
          content: message.content,
        }),
      )

      setMessages(loadedMessages)
      setNextMessageId(loadedMessages.length + 1)
      setActiveChat(session.session_id)
      setSessionId(session.session_id)
      setMobileSidebarOpen(false)
    } catch (caught) {
      const message =
        caught instanceof Error
          ? caught.message
          : 'Could not load this conversation.'

      setError(message)
    } finally {
      setIsLoadingSession(false)
    }
  }

  async function handleRenameSession(chat: ChatSession) {
  const title = renameValue.trim()

  if (!title || title === chat.title) {
    setRenamingSessionId(null)
    setRenameValue('')
    return
  }

  try {
    const updatedSession = await renameSession(chat.session_id, title)

    setChats((previous) =>
      previous.map((item) =>
        item.session_id === chat.session_id
          ? {
              ...item,
              title: updatedSession.title,
              updated_at: updatedSession.updated_at,
            }
          : item,
      ),
    )

    setRenamingSessionId(null)
    setRenameValue('')
    setOpenMenuSessionId(null)
  } catch (caught) {
    const message =
      caught instanceof Error
        ? caught.message
        : 'Could not rename conversation.'

    setError(message)
  }
}

  async function refreshChats() {
    try {
      const sessions = await fetchSessions()
      setChats(sessions)
    } catch (caught) {
      const message =
        caught instanceof Error
          ? caught.message
          : 'Could not refresh conversations.'

      setError(message)
    }
  }

  async function removeChat(chatSessionId: string) {
    if (isStreaming) return

    try {
      await deleteSession(chatSessionId)

      setChats((previous) =>
        previous.filter((chat) => chat.session_id !== chatSessionId),
      )

      if (activeChat === chatSessionId) {
        startNewChat()
      }
    } catch (caught) {
      const message =
        caught instanceof Error
          ? caught.message
          : 'Could not delete conversation.'

      setError(message)
    }
  }

  async function sendMessage(text = input) {
    const content = text.trim()

    if (!content || isStreaming || isLoadingSession) return

    const userMessageId = nextMessageId
    const assistantMessageId = nextMessageId + 1

    const userMessage: Message = {
      id: userMessageId,
      role: 'user',
      content,
    }

    const assistantMessage: Message = {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
    }

    setNextMessageId((previous) => previous + 2)
    setMessages((previous) => [
      ...previous,
      userMessage,
      assistantMessage,
    ])

    setInput('')
    setError(null)
    setIsStreaming(true)

    // Show a temporary sidebar item for a new conversation.
    const temporarySessionId = `pending-${userMessageId}`

    if (!sessionId) {
      const title =
        content.length > 35 ? `${content.slice(0, 35)}…` : content

      setChats((previous) => [
        {
          session_id: temporarySessionId,
          title,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        ...previous,
      ])
    }

    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      await streamQuery({
        question: content,
        sessionId,
        mode,
        provider,
        signal: controller.signal,

        onToken: (token) => {
          setMessages((previous) =>
            previous.map((message) =>
              message.id === assistantMessageId
                ? {
                    ...message,
                    content: message.content + token,
                  }
                : message,
            ),
          )
        },

        onSources: (sources) => {
          setMessages((previous) =>
            previous.map((message) =>
              message.id === assistantMessageId
                ? {
                    ...message,
                    sources,
                  }
                : message,
            ),
          )
        },

        onDone: (newSessionId) => {
          setSessionId(newSessionId)
          setActiveChat(newSessionId)

          // Replace the temporary sidebar ID with the actual DB ID.
          setChats((previous) =>
            previous.map((chat) =>
              chat.session_id === temporarySessionId
                ? {
                    ...chat,
                    session_id: newSessionId,
                  }
                : chat,
            ),
          )
        },
      })

      // The backend has finished saving the response.
      await refreshChats()
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === 'AbortError') {
        return
      }

      const message =
        caught instanceof Error
          ? caught.message
          : 'Something went wrong.'

      setError(message)

      setMessages((previous) =>
        previous.map((item) =>
          item.id === assistantMessageId && !item.content
            ? {
                ...item,
                content: `Sorry, I couldn't complete that request. ${message}`,
              }
            : item,
        ),
      )
    } finally {
      setIsStreaming(false)
      abortControllerRef.current = null
    }
  }

  function stopGeneration() {
    abortControllerRef.current?.abort()
    abortControllerRef.current = null
    setIsStreaming(false)
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    sendMessage()
  }

  return (
    <div className="flex h-screen overflow-hidden bg-[#212121] text-[#ececec]">
      {/* Mobile sidebar backdrop */}
      {mobileSidebarOpen && (
        <button
          aria-label="Close sidebar backdrop"
          className="fixed inset-0 z-30 bg-black/50 md:hidden"
          onClick={() => setMobileSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-[260px] flex-col bg-[#171717] transition-transform duration-200 md:relative md:translate-x-0 ${
          mobileSidebarOpen ? 'translate-x-0' : '-translate-x-full'
        } ${sidebarOpen ? 'md:flex' : 'md:hidden'}`}
      >
        <div className="flex items-center justify-between px-3 py-3">
          <button
            aria-label="Close sidebar"
            className="rounded-lg p-2 text-[#b4b4b4] transition hover:bg-[#2a2a2a] hover:text-white"
            onClick={() => {
              setSidebarOpen(false)
              setMobileSidebarOpen(false)
            }}
          >
            <PanelLeft size={20} />
          </button>

          <button
            aria-label="Search conversations"
            className="rounded-lg p-2 text-[#b4b4b4] transition hover:bg-[#2a2a2a] hover:text-white"
          >
            <Search size={20} />
          </button>
        </div>

        <div className="px-3">
          <button
            onClick={startNewChat}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-white transition hover:bg-[#2a2a2a]"
          >
            <span className="text-lg">＋</span>
            <span>New chat</span>
          </button>

          <button onClick={openDocumentLibrary} className="mt-1 flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-[#b4b4b4] transition hover:bg-[#2a2a2a] hover:text-white">
            <BookOpen size={18} />
            <span>Knowledge base</span>
          </button>
        </div>

        <div className="mt-7 px-5">
          <p className="text-xs font-semibold text-[#8e8e8e]">
            Your chats
          </p>
        </div>

        <div className="mt-2 flex-1 overflow-y-auto px-2">
          {isLoadingChats ? (
            <p className="px-3 py-2 text-xs text-[#8e8e8e]">
              Loading conversations...
            </p>
          ) : chats.length === 0 ? (
            <p className="px-3 py-2 text-xs text-[#8e8e8e]">
              No conversations yet
            </p>
          ) : (
            chats.map((chat) => (
  <div
    key={chat.session_id}
    className={`group relative flex items-center gap-2 rounded-lg transition ${
      activeChat === chat.session_id
        ? 'bg-[#2a2a2a] text-white'
        : 'text-[#b4b4b4] hover:bg-[#222222] hover:text-white'
    }`}
  >
    {renamingSessionId === chat.session_id ? (
      <form
        className="flex min-w-0 flex-1 items-center gap-1 px-2 py-1.5"
        onSubmit={(event) => {
          event.preventDefault()
          handleRenameSession(chat)
        }}
      >
        <input
          autoFocus
          value={renameValue}
          onChange={(event) => setRenameValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              setRenamingSessionId(null)
              setRenameValue('')
            }
          }}
          maxLength={255}
          className="min-w-0 flex-1 rounded border border-white/20 bg-[#171717] px-2 py-1 text-sm text-white outline-none focus:border-white/40"
        />

        <button
          type="submit"
          aria-label="Save conversation name"
          className="rounded px-2 py-1 text-xs text-white hover:bg-[#414141]"
        >
          Save
        </button>
      </form>
    ) : (
      <>
        <button
          onClick={() => openChat(chat.session_id)}
          disabled={
            isLoadingSession ||
            isStreaming ||
            chat.session_id.startsWith('pending-')
          }
          className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-left text-sm disabled:opacity-50"
        >
          <MessageSquare size={16} className="shrink-0" />
          <span className="flex-1 truncate">{chat.title}</span>
        </button>

        <button
          aria-label={`Conversation options for ${chat.title}`}
          title="Conversation options"
          disabled={
            isStreaming ||
            chat.session_id.startsWith('pending-')
          }
          onClick={() =>
            setOpenMenuSessionId((current) =>
              current === chat.session_id ? null : chat.session_id,
            )
          }
          className="mr-1 rounded p-1 text-[#8e8e8e] opacity-0 transition hover:bg-[#414141] hover:text-white group-hover:opacity-100 disabled:opacity-30"
        >
          <MoreHorizontal size={16} />
        </button>

        {openMenuSessionId === chat.session_id && (
          <div className="absolute right-2 top-9 z-50 w-40 rounded-xl border border-white/10 bg-[#2f2f2f] p-1 shadow-xl">
            <button
              onClick={() => {
                setRenamingSessionId(chat.session_id)
                setRenameValue(chat.title)
                setOpenMenuSessionId(null)
              }}
              className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-[#e5e5e5] hover:bg-[#414141]"
            >
              <Pencil size={15} />
              Rename
            </button>

            <button
              onClick={() => {
                setOpenMenuSessionId(null)
                removeChat(chat.session_id)
              }}
              disabled={isStreaming}
              className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-red-300 hover:bg-[#414141] disabled:opacity-40"
            >
              <Trash2 size={15} />
              Delete
            </button>
          </div>
        )}
      </>
    )}
  </div>
))
          )}
        </div>

        <div className="relative border-t border-white/10 p-3">
          {profileOpen && (
            <div className="absolute bottom-[calc(100%-4px)] left-3 right-3 rounded-xl border border-white/10 bg-[#252525] p-3 shadow-xl">
              <p className="mb-3 break-all text-xs text-[#b4b4b4]">{authUser?.email}</p>
              <button onClick={handleLogout} className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm hover:bg-[#353535]">
                <LogOut size={16} /> Log out
              </button>
            </div>
          )}
          <button onClick={() => setProfileOpen((open) => !open)} className="flex w-full items-center gap-3 rounded-lg p-2 text-left transition hover:bg-[#2a2a2a]">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#4b5563] text-xs font-semibold">
              {(authUser?.email?.[0] ?? 'U').toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{authUser?.email ?? 'Account'}</p>
              <p className="truncate text-xs text-[#8e8e8e]">Signed in</p>
            </div>
            <MoreHorizontal size={18} className="text-[#8e8e8e]" />
          </button>
        </div>
      </aside>

      {/* Main chat area */}
      <main className="relative flex min-w-0 flex-1 flex-col">
        {/* Top navigation */}
        <header className="flex h-14 shrink-0 items-center justify-between px-3 md:px-5">
          <div className="flex items-center gap-2">
            {!sidebarOpen && (
              <button
                aria-label="Open sidebar"
                className="rounded-lg p-2 text-[#b4b4b4] transition hover:bg-[#2a2a2a] hover:text-white"
                onClick={() => setSidebarOpen(true)}
              >
                <PanelLeft size={20} />
              </button>
            )}

            <button
              className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-lg font-semibold transition hover:bg-[#2a2a2a]"
              onClick={startNewChat}
            >
              RAG Chat
              <ChevronDown size={16} className="text-[#8e8e8e]" />
            </button>
          </div>

          <div className="flex items-center gap-2">
            <button
              aria-label="Open mobile sidebar"
              className="rounded-lg p-2 text-[#b4b4b4] transition hover:bg-[#2a2a2a] hover:text-white md:hidden"
              onClick={() => setMobileSidebarOpen(true)}
            >
              <Menu size={20} />
            </button>

            <button className="hidden items-center gap-2 rounded-full border border-white/10 px-3 py-1.5 text-sm text-[#d4d4d4] transition hover:bg-[#2a2a2a] sm:flex">
              <Sparkles size={15} />
              Share
            </button>
          </div>
        </header>

        {/* Messages */}
        <section className="flex min-h-0 flex-1 flex-col">
          {hasMessages ? (
            <div className="flex-1 overflow-y-auto">
              <div className="mx-auto max-w-3xl px-4 pb-8 pt-6">
                <div className="space-y-8">
                  {messages.map((message) => (
                    <div
                      key={message.id}
                      className={`flex gap-4 ${
                        message.role === 'user'
                          ? 'justify-end'
                          : 'justify-start'
                      }`}
                    >
                      {message.role === 'assistant' && (
                        <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white text-black">
                          <Sparkles size={17} />
                        </div>
                      )}

                      <div
                        className={`max-w-[85%] whitespace-pre-wrap text-[15px] leading-7 ${
                          message.role === 'user'
                            ? 'rounded-3xl bg-[#303030] px-5 py-3'
                            : 'flex-1 pt-1'
                        }`}
                      >
                        {message.content ||
                          (isStreaming && message.role === 'assistant'
                            ? ' '
                            : '')}

                        {message.role === 'assistant' &&
                          message.sources &&
                          message.sources.length > 0 && (
                            <details className="mt-4 rounded-xl border border-white/10 bg-[#262626] p-3 text-sm">
                              <summary className="cursor-pointer text-[#b4b4b4]">
                                Sources ({message.sources.length})
                              </summary>

                              <div className="mt-3 space-y-3">
                                {message.sources.map((source, index) => (
                                  <div
                                    key={`${source.filename}-${source.chunk_index}-${index}`}
                                  >
                                    <p className="mb-1 text-xs font-medium text-[#d4d4d4]">
                                      {source.filename} · chunk{' '}
                                      {source.chunk_index}
                                    </p>

                                    <p className="whitespace-pre-wrap text-xs leading-5 text-[#999]">
                                      {source.content}
                                    </p>
                                  </div>
                                ))}
                              </div>
                            </details>
                          )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center px-4 pb-6">
              <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-full border border-white/10 bg-[#2a2a2a]">
                <Sparkles size={23} />
              </div>

              <h1 className="mb-8 text-center text-2xl font-semibold tracking-tight sm:text-3xl">
                What can I help you find?
              </h1>

              <div className="grid w-full max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2">
                {suggestions.map((suggestion) => {
                  const Icon = suggestion.icon

                  return (
                    <button
                      key={suggestion.title}
                      onClick={() => sendMessage(suggestion.prompt)}
                      className="group flex min-h-[90px] items-start gap-3 rounded-2xl border border-white/10 p-4 text-left transition hover:bg-[#2a2a2a]"
                    >
                      <Icon
                        size={19}
                        className="mt-0.5 shrink-0 text-[#a3a3a3] transition group-hover:text-white"
                      />

                      <div>
                        <p className="text-sm font-medium text-[#ececec]">
                          {suggestion.title}
                        </p>

                        <p className="mt-1 text-xs leading-5 text-[#8e8e8e]">
                          {suggestion.prompt}
                        </p>
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {error && (
            <p
              role="alert"
              className="mx-auto mb-2 max-w-3xl px-4 text-sm text-red-300"
            >
              {error}
            </p>
          )}

          {isLoadingSession && (
            <p className="mb-2 text-center text-xs text-[#8e8e8e]">
              Loading conversation...
            </p>
          )}

          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.txt"
            className="hidden"
            onChange={handleFileSelected}
          />

          {/* Composer */}
          <div className="shrink-0 px-3 pb-3 pt-2 sm:px-5 sm:pb-5">
            <div className="mx-auto max-w-3xl">
              <form
                onSubmit={handleSubmit}
                className="rounded-3xl border border-white/10 bg-[#2f2f2f] px-3 pb-3 pt-2 shadow-lg transition focus-within:border-white/20"
              >
                <textarea
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault()
                      sendMessage()
                    }
                  }}
                  placeholder={
  mode === 'normal'
    ? 'Ask anything'
    : 'Ask anything about your documents'
}
                  rows={1}
                  className="max-h-48 min-h-10 w-full resize-none bg-transparent px-2 py-2 text-[15px] leading-6 text-white outline-none placeholder:text-[#8e8e8e]"
                />

                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      aria-label="Attach a file"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={isUploading}
                      title={isUploading ? "Uploading…" : "Upload a document"}
                      className="rounded-full p-2 text-[#b4b4b4] transition hover:bg-[#414141] hover:text-white"
                    >
                      <Plus size={20} />
                    </button>

                    <button
                      type="button"
                      onClick={openDocumentLibrary}
                      className="flex items-center gap-1 rounded-full px-2 py-1.5 text-xs text-[#b4b4b4] transition hover:bg-[#414141] hover:text-white"
                    >
                      <BookOpen size={15} />
                      Sources
                    </button>
                  </div>

                  <div className="flex items-center gap-2">
                    <select
                      aria-label="Chat mode"
                      value={mode}
                      onChange={(event) =>
                        setMode(event.target.value as 'normal' | 'rag')
                      }
                      disabled={isStreaming}
                      className="max-w-[100px] cursor-pointer rounded-full border border-white/10 bg-[#3a3a3a] px-3 py-2 text-xs text-white outline-none hover:bg-[#454545] disabled:opacity-50"
                    >
                      <option value="normal">Normal</option>
                      <option value="rag">RAG</option>
                    </select>

                    <select
                      aria-label="Model provider"
                      value={provider}
                      onChange={(event) =>
                        setProvider(event.target.value as 'openai' | 'ollama')
                      }
                      disabled={isStreaming}
                      className="max-w-[115px] cursor-pointer rounded-full border border-white/10 bg-[#3a3a3a] px-3 py-2 text-xs text-white outline-none hover:bg-[#454545] disabled:opacity-50"
                    >
                      <option value="ollama">Ollama</option>
                      <option value="openai">OpenAI</option>
                    </select>

                    {isStreaming ? (
                      <button
                        type="button"
                        onClick={stopGeneration}
                        aria-label="Stop generation"
                        className="flex h-9 w-9 items-center justify-center rounded-full bg-white text-black transition hover:bg-[#e5e5e5]"
                      >
                        <Square size={14} fill="currentColor" />
                      </button>
                    ) : (
                      <button
                        type="submit"
                        disabled={!input.trim() || isLoadingSession}
                        aria-label="Send message"
                        className="flex h-9 w-9 items-center justify-center rounded-full bg-white text-black transition hover:bg-[#e5e5e5] disabled:cursor-not-allowed disabled:bg-[#676767] disabled:text-[#252525]"
                      >
                        <ArrowUp size={19} strokeWidth={2.5} />
                      </button>
                    )}
                  </div>
                </div>
              </form>

              <p className="mt-3 text-center text-[11px] text-[#777]">
  {mode === 'normal'
    ? 'Responses are generated by the selected language model.'
    : 'Answers are generated from your knowledge base. Verify important information.'}
</p>
            </div>
          </div>
        </section>
      </main>

      {isDocumentsOpen && (
        <div
          className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/65 p-4 backdrop-blur-sm"
          onClick={() => setIsDocumentsOpen(false)}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="document-library-title"
            onClick={(event) => event.stopPropagation()}
            className="flex max-h-[80vh] w-full max-w-[560px] flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#202020] p-5 text-white shadow-2xl"
          >
            <div className="mb-4 flex shrink-0 items-center justify-between">
              <div>
                <h2
                  id="document-library-title"
                  className="text-lg font-semibold"
                >
                  Knowledge base
                </h2>
                <p className="mt-1 text-sm text-[#999]">
                  PDF, DOCX, and TXT files · up to 25 MB each
                </p>
              </div>
              <button
                type="button"
                aria-label="Close document library"
                onClick={() => setIsDocumentsOpen(false)}
                className="rounded-lg p-2 text-[#aaa] hover:bg-[#333] hover:text-white"
              >
                <X size={18} />
              </button>
            </div>

            <div className="mb-4 flex shrink-0 items-center justify-between rounded-xl border border-white/10 bg-[#2a2a2a] p-3">
              <div className="min-w-0">
                <p className="text-sm font-medium">Add a document</p>
                <p className="mt-1 text-xs text-[#999]">
                  {isUploading
                    ? 'Uploading and indexing…'
                    : 'Upload a file to make it searchable in RAG mode.'}
                </p>
              </div>
              <button
                type="button"
                disabled={isUploading}
                onClick={() => fileInputRef.current?.click()}
                className="ml-3 shrink-0 rounded-full bg-white px-4 py-2 text-sm font-medium text-black disabled:opacity-50"
              >
                {isUploading ? 'Uploading…' : 'Upload'}
              </button>
            </div>

            {documentError && (
              <p
                role="alert"
                className="mb-3 shrink-0 rounded-lg bg-red-950/40 p-3 text-sm text-red-300"
              >
                {documentError}
              </p>
            )}

            <div className="min-h-0 space-y-2 overflow-y-auto">
              {documents.length === 0 ? (
                <p className="py-6 text-center text-sm text-[#888]">
                  No documents uploaded yet.
                </p>
              ) : (
                documents.map((document) => (
                  <div
                    key={document.document_id}
                    className="flex items-center gap-3 rounded-xl border border-white/10 px-3 py-3"
                  >
                    <FileText size={18} className="shrink-0 text-[#aaa]" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm">{document.filename}</p>
                      <p className="mt-1 text-xs text-[#888]">
                        {document.status}
                        {document.error_message
                          ? ` · ${document.error_message}`
                          : ''}
                      </p>
                    </div>
                    <button
                      type="button"
                      aria-label={`Delete ${document.filename}`}
                      title="Delete document"
                      onClick={() => handleDeleteDocument(document)}
                      className="rounded-lg p-2 text-[#999] hover:bg-red-950/50 hover:text-red-300"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                ))
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

export default App