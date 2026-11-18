import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'

import { ApiError, api, type EngineStatus } from './api'

interface EngineValue {
  status: EngineStatus | null
  busy: boolean
  error: string
  start: () => Promise<void>
  stop: (force?: boolean) => Promise<void>
  refresh: () => Promise<void>
}

const EngineContext = createContext<EngineValue | null>(null)

/**
 * Engine state shared by the header and every page.
 *
 * Polling rather than SSE: the state changes on user action and at most a few
 * times a minute, and a 4s poll is cheaper than keeping a second event stream
 * open for a switch. While a transition is running it polls faster so the
 * "Starting…" label doesn't outlive the transition.
 */
export function EngineProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<EngineStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const timer = useRef<number | null>(null)

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.engineStatus())
    } catch {
      /* The header is allowed to stay quiet when the server is down. */
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    const delay = status?.state === 'starting' || status?.state === 'stopping' ? 700 : 5000
    timer.current = window.setTimeout(() => {
      void refresh()
    }, delay)
    return () => {
      if (timer.current) window.clearTimeout(timer.current)
    }
  }, [status?.state, refresh])

  const run = useCallback(
    async (action: () => Promise<EngineStatus>) => {
      setBusy(true)
      setError('')
      // Show the transitional state immediately instead of waiting for the
      // first poll — model loading can take several seconds.
      setStatus((current) =>
        current
          ? {
              ...current,
              state: action === api.startEngine ? 'starting' : 'stopping',
              error: null,
            }
          : current,
      )
      try {
        setStatus(await action())
      } catch (err) {
        const message = err instanceof ApiError ? `${err.message}${err.hint ? `\n${err.hint}` : ''}` : String(err)
        setError(message)
        await refresh()
      } finally {
        setBusy(false)
      }
    },
    [refresh],
  )

  const start = useCallback(() => run(api.startEngine), [run])
  const stop = useCallback((force = false) => run(() => api.stopEngine(force)), [run])

  return (
    <EngineContext.Provider value={{ status, busy, error, start, stop, refresh }}>
      {children}
    </EngineContext.Provider>
  )
}

export function useEngine(): EngineValue {
  const value = useContext(EngineContext)
  if (value === null) throw new Error('useEngine must be used inside EngineProvider')
  return value
}
