import { NavLink, Outlet } from 'react-router-dom'

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
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 px-3 pt-3 lg:px-6">
        <div className="glass mx-auto flex max-w-[1700px] items-center gap-2 rounded-[22px] px-3 py-2 sm:gap-4 sm:px-4">
          <NavLink to="/" className="group flex shrink-0 items-center gap-2.5 pr-1">
            <span
              aria-hidden
              className="grid size-9 place-items-center rounded-[13px] bg-gradient-to-br from-sodium-500 to-sodium-600 text-[15px] font-black text-ink-900 shadow-[0_10px_26px_-12px_rgba(255,101,168,0.9)]"
            >
              A
            </span>
            <span className="hidden leading-none sm:block">
              <span className="display block text-[17px] tracking-[-0.04em] text-ink-100">
                AUTOCLIP
              </span>
              <span className="mt-1 block text-[9px] font-semibold uppercase tracking-[0.24em] text-ink-400">
                local studio
              </span>
            </span>
          </NavLink>

          <nav className="ml-1 flex items-center gap-0.5 sm:ml-3">
            <TopLink to="/" end>
              Studio
            </TopLink>
            <TopLink to="/publishing">Publishing</TopLink>
            <TopLink to="/settings">Settings</TopLink>
          </nav>

          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            <SystemBadge />
            <EngineControl />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1700px] px-4 pb-28 pt-6 sm:pt-8 lg:px-8">
        <Outlet />
      </main>
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
          'rounded-full px-2.5 py-2 text-[12px] font-semibold transition-colors duration-200 sm:px-3.5 sm:text-[13px]',
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
