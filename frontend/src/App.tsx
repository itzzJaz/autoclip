import { useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { EngineProvider, useEngine } from './engine'

/**
 * Application shell.
 *
 * A floating glass masthead rather than a sidebar: the work is a small set of
 * screens, and a persistent rail would spend a fifth of the width restating
 * that. The engine switch lives here because it is the one control that applies
 * to every screen.
 */
export function App() {
  return (
    <EngineProvider>
      <Shell />
    </EngineProvider>
  )
}

function Shell() {
  const location = useLocation()
  const navigate = useNavigate()
  const { status, start, stop, busy } = useEngine()
  const [paletteOpen, setPaletteOpen] = useState(false)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((open) => !open)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const commands = useMemo<PaletteCommand[]>(
    () => [
      { label: 'Open Studio', hint: 'Go to clip creation', icon: 'studio', action: () => navigate('/') },
      { label: 'Open YouTube Publishing', hint: 'Exports and uploads', icon: 'youtube', action: () => navigate('/publishing') },
      { label: 'Open Instagram Publishing', hint: 'Reels and setup', icon: 'instagram', action: () => navigate('/instagram') },
      { label: 'Open Settings', hint: 'Models, export, and system', icon: 'settings', action: () => navigate('/settings') },
      {
        label: status?.state === 'running' ? 'Stop processing engine' : 'Start processing engine',
        hint: status?.state === 'running' ? 'Release GPU and unload models' : 'Prepare transcription and clip analysis',
        icon: 'engine',
        action: () =>
          status?.state === 'running'
          ? void stop(Boolean(status.active_job_id))
            : void start(),
      },
    ],
    [navigate, start, status?.state, stop],
  )

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 px-3 pt-3 lg:px-6">
        <div className="glass mx-auto flex max-w-[1700px] items-center gap-2 rounded-[22px] px-3 py-2 sm:gap-4 sm:px-4">
          <NavLink to="/" className="group flex shrink-0 items-center gap-2.5 pr-1">
            <span
              aria-hidden
              className="grid size-9 place-items-center rounded-[13px] bg-sodium-500 text-[15px] font-black text-ink-900 shadow-[0_10px_26px_-12px_rgba(105,199,160,0.9)]"
            >
              M
            </span>
            <span className="hidden leading-none sm:block">
              <span className="display block text-[17px] tracking-[-0.04em] text-ink-100">
                M-CLIP
              </span>
              <span className="mt-1 block text-[9px] font-semibold uppercase tracking-[0.24em] text-ink-400">
                local studio
              </span>
            </span>
          </NavLink>

          <nav className="ml-1 flex items-center gap-0.5 sm:ml-3">
            <TopLink to="/" end>
              <StudioIcon /> Studio
            </TopLink>
            <TopLink to="/publishing"><YouTubeIcon /> YouTube</TopLink>
            <TopLink to="/instagram"><InstagramIcon /> Instagram</TopLink>
            <TopLink to="/settings"><SettingsIcon /> Settings</TopLink>
          </nav>

          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            <button
              onClick={() => setPaletteOpen(true)}
              className="btn btn-ghost hidden h-9 items-center gap-2 px-3 text-[11px] md:inline-flex"
              aria-label="Open command palette"
            >
              <SearchIcon />
              <span className="text-ink-500">Search</span>
              <kbd className="rounded-[6px] border border-white/10 bg-black/10 px-1.5 py-0.5 text-[9px] text-ink-400">
                ⌘K
              </kbd>
            </button>
            <SystemBadge />
            <EngineControl />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1700px] px-4 pb-28 pt-6 sm:pt-8 lg:px-8">
        <div key={location.pathname} className="page-transition">
          <Outlet />
        </div>
      </main>
      {paletteOpen && (
        <CommandPalette
          commands={commands}
          busy={busy}
          onClose={() => setPaletteOpen(false)}
        />
      )}
    </div>
  )
}

function TopLink({
  to,
  end,
  children,
}: {
  to: string
  end?: boolean
  children: React.ReactNode
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        [
          'inline-flex items-center gap-1.5 rounded-full px-2.5 py-2 text-[12px] font-semibold transition-colors duration-200 sm:px-3.5 sm:text-[13px]',
          isActive
            ? 'bg-white/[0.09] text-ink-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]'
            : 'text-ink-400 hover:text-ink-100',
        ].join(' ')
      }
    >
      {children}
    </NavLink>
  )
}

function StudioIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="3" y="3" width="7" height="7" rx="2" fill="currentColor" />
      <rect x="14" y="3" width="7" height="7" rx="2" fill="currentColor" opacity=".65" />
      <rect x="3" y="14" width="7" height="7" rx="2" fill="currentColor" opacity=".65" />
      <rect x="14" y="14" width="7" height="7" rx="2" fill="currentColor" />
    </svg>
  )
}

function YouTubeIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="2" y="5" width="20" height="14" rx="5" stroke="currentColor" strokeWidth="1.8" />
      <path d="m10 9 5 3-5 3V9Z" fill="currentColor" />
    </svg>
  )
}

function InstagramIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="3" y="3" width="18" height="18" rx="5" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="17.4" cy="6.6" r="1" fill="currentColor" />
    </svg>
  )
}

function SettingsIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.8" />
      <path d="M12 2v3M12 19v3M4.93 4.93l2.12 2.12M16.95 16.95l2.12 2.12M2 12h3M19 12h3M4.93 19.07l2.12-2.12M16.95 7.05l2.12-2.12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

function SearchIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="11" cy="11" r="6.5" stroke="currentColor" strokeWidth="1.8" />
      <path d="m16 16 4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

interface PaletteCommand {
  label: string
  hint: string
  icon: 'studio' | 'youtube' | 'instagram' | 'settings' | 'engine'
  action: () => void
}

function CommandPalette({
  commands,
  busy,
  onClose,
}: {
  commands: PaletteCommand[]
  busy: boolean
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    input.current?.focus()
  }, [])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return commands
    return commands.filter(
      (command) =>
        command.label.toLowerCase().includes(needle) ||
        command.hint.toLowerCase().includes(needle),
    )
  }, [commands, query])

  useEffect(() => setActive(0), [query])

  const run = (command: PaletteCommand) => {
    onClose()
    command.action()
  }

  return (
    <div
      className="fixed inset-0 z-[90] flex justify-center bg-ink-900/75 px-3 pt-[12vh] backdrop-blur-md"
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="glass h-fit w-full max-w-xl overflow-hidden">
        <div className="flex items-center gap-3 border-b border-white/[0.08] px-4 py-3">
          <SearchIcon />
          <input
            ref={input}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Escape') onClose()
              if (event.key === 'ArrowDown') {
                event.preventDefault()
                setActive((current) => Math.min(current + 1, filtered.length - 1))
              }
              if (event.key === 'ArrowUp') {
                event.preventDefault()
                setActive((current) => Math.max(current - 1, 0))
              }
              if (event.key === 'Enter' && filtered[active]) {
                event.preventDefault()
                run(filtered[active])
              }
            }}
            className="min-w-0 flex-1 bg-transparent text-[15px] text-ink-100 outline-none placeholder:text-ink-500"
            placeholder="Search M-CLIP…"
          />
          <kbd className="rounded-[6px] border border-white/10 px-1.5 py-1 text-[9px] text-ink-500">
            ESC
          </kbd>
        </div>
        <div className="max-h-[420px] overflow-y-auto p-2">
          {filtered.length === 0 ? (
            <p className="px-3 py-8 text-center text-xs text-ink-500">No matching commands</p>
          ) : (
            filtered.map((command, index) => (
              <button
                key={command.label}
                onMouseEnter={() => setActive(index)}
                onClick={() => run(command)}
                disabled={busy && command.icon === 'engine'}
                className={[
                  'flex w-full items-center gap-3 rounded-[12px] px-3 py-3 text-left transition-colors',
                  index === active ? 'bg-white/[0.09] text-ink-100' : 'text-ink-300 hover:bg-white/[0.05]',
                ].join(' ')}
              >
                <span className="grid size-8 place-items-center rounded-[9px] border border-white/[0.08] bg-white/[0.035] text-sodium-400">
                  {command.icon === 'engine' ? '▶' : command.label.slice(0, 1)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[12.5px] font-semibold">{command.label}</span>
                  <span className="mt-0.5 block text-[10px] text-ink-500">{command.hint}</span>
                </span>
                {index === active && (
                  <kbd className="rounded-[6px] border border-white/10 px-1.5 py-0.5 text-[9px] text-ink-500">
                    ↵
                  </kbd>
                )}
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

const STATE_LABEL: Record<string, string> = {
  stopped: 'Engine stopped',
  starting: 'Starting engine',
  running: 'Engine running',
  stopping: 'Stopping engine',
  error: 'Engine error',
}

const STATE_TONE: Record<string, string> = {
  stopped: 'text-ink-500',
  starting: 'text-signal-warn',
  running: 'text-signal-good',
  stopping: 'text-signal-warn',
  error: 'text-signal-bad',
}

function EngineControl() {
  const { status, busy, error, start, stop } = useEngine()
  const state = status?.state ?? 'stopped'
  const transitional = state === 'starting' || state === 'stopping'
  const showError = Boolean(error || status?.error)

  const onStop = () => {
    if (status?.active_job_id) {
      const ok = window.confirm(
        'A video is being processed right now. Stopping the engine will cancel it.\n\n' +
          'Stop anyway?',
      )
      if (!ok) return
      void stop(true)
      return
    }
    void stop(false)
  }

  return (
    <div className="relative flex items-center gap-2">
      <div className="hidden min-w-0 text-right sm:block">
        <span className={`flex items-center justify-end gap-2 text-[12px] font-semibold ${STATE_TONE[state]}`}>
          <span className={`status-dot ${transitional ? 'pulse-dot' : ''}`} />
          {STATE_LABEL[state] ?? state}
        </span>
        <span className="mt-0.5 block max-w-40 truncate text-[10px] text-ink-500">
          {state === 'running'
            ? status?.model_loaded
              ? `${status.model_loaded} loaded`
              : 'model loads on first job'
            : state === 'stopped'
              ? 'start to process video'
              : state === 'error'
                ? 'open for details'
                : 'one moment…'}
        </span>
      </div>

      {state === 'running' ? (
        <button onClick={onStop} disabled={busy} className="btn btn-ghost px-3 py-2 text-[12px]">
          Stop
        </button>
      ) : (
        <button
          onClick={() => void start()}
          disabled={busy || transitional}
          className="btn btn-primary px-3 py-2 text-[12px]"
        >
          {transitional ? (
            <span className="flex items-center gap-2">
              <Spinner /> {state === 'starting' ? 'Starting' : 'Stopping'}
            </span>
          ) : state === 'error' ? (
            'Retry'
          ) : (
            'Start engine'
          )}
        </button>
      )}

      {showError && (
        <div className="glass absolute right-0 top-[calc(100%+10px)] z-50 w-80 p-4 text-left">
          <p className="eyebrow text-signal-bad">Engine error</p>
          <p className="mt-2 whitespace-pre-line text-xs leading-relaxed text-ink-300">
            {error || status?.error}
          </p>
        </div>
      )}
    </div>
  )
}

function Spinner() {
  return (
    <svg className="size-3.5 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

function SystemBadge() {
  const { status } = useEngine()
  if (!status) return null

  return (
    <div className="hidden items-center gap-3 text-[10px] text-ink-500 lg:flex">
      <span className="numeric">
        {status.ffmpeg_version ? `ffmpeg ${status.ffmpeg_version.split(' ')[0]}` : 'ffmpeg missing'}
      </span>
      <span className="h-3 w-px bg-white/10" />
      <span className={status.ready ? 'text-ink-400' : 'text-signal-bad'}>
        {status.ready ? 'render ready' : 'render unavailable'}
      </span>
    </div>
  )
}
