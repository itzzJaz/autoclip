import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import {
  ApiError,
  api,
  formatBytes,
  formatDuration,
  type ExportDetail,
  type PublishRecord,
  type PublishingStatus,
  type Settings,
} from '../api'
import { ErrorNote } from '../components/ErrorNote'
import { PublishComposer } from '../components/PublishComposer'
import { QueueList } from '../components/QueueList'

const IN_FLIGHT: PublishRecord['status'][] = ['pending', 'uploading', 'processing']

export function Publishing() {
  const [params, setParams] = useSearchParams()
  const selectedId = params.get('export')

  const [exports, setExports] = useState<ExportDetail[] | null>(null)
  const [queue, setQueue] = useState<PublishRecord[]>([])
  const [status, setStatus] = useState<PublishingStatus | null>(null)
  const [settings, setSettings] = useState<Settings | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [connecting, setConnecting] = useState(false)
  const [disconnecting, setDisconnecting] = useState(false)
  const [notice, setNotice] = useState('')
  const [filter, setFilter] = useState<'all' | 'unpublished' | 'published'>('all')

  const callbackHandled = useRef(false)

  const loadExports = useCallback(async () => {
    try {
      setExports(await api.listExports(100))
    } catch (err) {
      setError(err as Error)
      setExports([])
    }
  }, [])

  const loadQueue = useCallback(async () => {
    try {
      setQueue(await api.publishingQueue(100))
    } catch {
      /* The queue is not allowed to take the page down. */
    }
  }, [])

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await api.publishingStatus())
    } catch (err) {
      setError(err as Error)
    }
  }, [])

  useEffect(() => {
    void loadExports()
    void loadQueue()
    void loadStatus()
    api
      .getSettings()
      .then(setSettings)
      .catch(() => undefined)
  }, [loadExports, loadQueue, loadStatus])

  // OAuth returns to /publishing?connected=1 or ?error=…; show it once, then
  // strip the params so a refresh does not replay a stale banner.
  useEffect(() => {
    if (callbackHandled.current) return
    const connected = params.get('connected')
    const oauthError = params.get('error')
    if (!connected && !oauthError) return
    callbackHandled.current = true
    if (connected) {
      setNotice('YouTube connected. Private is still the default for every upload.')
      void loadStatus()
    } else if (oauthError) {
      setError(new ApiError(oauthError, 400))
    }
    const next = new URLSearchParams(params)
    next.delete('connected')
    next.delete('error')
    setParams(next, { replace: true })
  }, [params, setParams, loadStatus])

  const hasInFlight = queue.some((job) => IN_FLIGHT.includes(job.status))

  useEffect(() => {
    if (!hasInFlight) return
    const timer = window.setInterval(() => {
      void loadQueue()
      void loadExports()
    }, 3500)
    return () => window.clearInterval(timer)
  }, [hasInFlight, loadQueue, loadExports])

  const publishByExport = useMemo(() => {
    const map = new Map<string, PublishRecord>()
    for (const record of exports ?? []) {
      if (record.publish) map.set(record.id, record.publish)
    }
    // The queue is fresher than the export snapshot during an upload.
    for (const job of queue) map.set(job.export_id, job)
    return map
  }, [exports, queue])

  const open = (exportId: string) => {
    const next = new URLSearchParams(params)
    next.set('export', exportId)
    setParams(next)
  }

  const close = () => {
    const next = new URLSearchParams(params)
    next.delete('export')
    setParams(next)
    void loadExports()
  }

  const connect = async () => {
    setConnecting(true)
    setError(null)
    try {
      const { auth_url } = await api.startYouTubeAuth()
      // Full navigation rather than a popup: the registered redirect is a plain
      // loopback URL, and a popup would be blocked by a browser that cannot see
      // the click was synchronous.
      window.location.assign(auth_url)
    } catch (err) {
      setError(err as Error)
      setConnecting(false)
    }
  }

  const disconnect = async () => {
    if (!window.confirm('Disconnect YouTube? AutoClip will forget the stored token.')) return
    setDisconnecting(true)
    try {
      await api.disconnectYouTube()
      setNotice('YouTube disconnected. Uploads already on YouTube are untouched.')
      void loadStatus()
    } catch (err) {
      setError(err as Error)
    } finally {
      setDisconnecting(false)
    }
  }

  const onQueued = (job: PublishRecord) => {
    setQueue((current) => [job, ...current.filter((item) => item.id !== job.id)])
    setExports((current) =>
      (current ?? []).map((record) =>
        record.id === job.export_id ? { ...record, publish: job } : record,
      ),
    )
  }

  const filtered = (exports ?? []).filter((record) => {
    if (filter === 'all') return true
    const published = publishByExport.get(record.id)?.status === 'published'
    return filter === 'published' ? published : !published
  })

  return (
    <div className="space-y-7">
      <section className="grid gap-5 lg:grid-cols-[1.5fr_1fr]">
        <div className="rise min-w-0">
          <p className="eyebrow">Publishing studio</p>
          <h1 className="display mt-3 text-[clamp(2.4rem,5.6vw,4.8rem)] text-ink-100">
            Every clip,
            <br />
            <span className="serif-accent text-sodium-500">ready to post.</span>
          </h1>
          <p className="mt-4 max-w-xl text-sm leading-relaxed text-ink-300">
            Choose a finished export, read the metadata AutoClip drafted from the clip itself,
            edit anything that is off, then upload to YouTube. Nothing is public unless you say so.
          </p>
        </div>

        <YouTubeCard
          status={status}
          connecting={connecting}
          disconnecting={disconnecting}
          onConnect={() => void connect()}
          onDisconnect={() => void disconnect()}
        />
      </section>

      {notice && (
        <p className="glass flex items-start gap-3 px-4 py-3 text-xs leading-relaxed text-ink-300">
          <span className="status-dot mt-1.5 text-signal-good" />
          <span className="flex-1">{notice}</span>
          <button onClick={() => setNotice('')} className="text-ink-500 hover:text-ink-100">
            ✕
          </button>
        </p>
      )}

      {error && (
        <div className="glass p-5">
          <ErrorNote error={error} onDismiss={() => setError(null)} />
        </div>
      )}

      {selectedId ? (
        <PublishComposer
          key={selectedId}
          exportId={selectedId}
          defaultPrivacy={settings?.publish.default_privacy ?? 'private'}
          defaultStyle={settings?.publish.description_style ?? 'concise'}
          onQueued={onQueued}
          onClose={close}
        />
      ) : (
        <section className="rise">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="eyebrow">Export library</p>
              <p className="mt-1 text-[11px] text-ink-500">
                {exports === null
                  ? 'Reading the export folder…'
                  : `${exports.length} finished ${exports.length === 1 ? 'file' : 'files'} · newest first`}
              </p>
            </div>
            <div className="flex gap-1.5">
              {(['all', 'unpublished', 'published'] as const).map((option) => (
                <button
                  key={option}
                  onClick={() => setFilter(option)}
                  className={[
                    'rounded-full px-3 py-1.5 text-[11px] font-semibold capitalize transition-colors',
                    filter === option
                      ? 'bg-white/[0.1] text-ink-100'
                      : 'text-ink-500 hover:text-ink-200',
                  ].join(' ')}
                >
                  {option}
                </button>
              ))}
            </div>
          </div>

          {exports !== null && exports.length === 0 ? (
            <div className="glass mt-4 flex flex-col items-center gap-3 px-6 py-16 text-center">
              <span className="grid size-12 place-items-center rounded-full border border-white/12 bg-white/[0.04] text-lg text-sodium-400">
                ↑
              </span>
              <p className="text-[15px] font-semibold text-ink-100">No exports yet</p>
              <p className="max-w-sm text-xs leading-relaxed text-ink-500">
                Export a clip from the studio first. Finished files appear here with their real
                duration, size, and Shorts readiness.
              </p>
              <Link to="/" className="btn btn-ghost mt-1">
                Go to the studio
              </Link>
            </div>
          ) : filtered.length === 0 ? (
            <p className="glass mt-4 px-6 py-10 text-center text-xs text-ink-500">
              No exports match that filter.
            </p>
          ) : (
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {filtered.map((record) => (
                <ExportCard
                  key={record.id}
                  record={record}
                  publish={publishByExport.get(record.id) ?? null}
                  onOpen={() => open(record.id)}
                />
              ))}
            </div>
          )}
        </section>
      )}

      <section className={selectedId ? 'rise' : 'rise mt-2'}>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="eyebrow">Upload queue</p>
            <p className="mt-1 text-[11px] text-ink-500">
              {queue.length === 0
                ? 'Uploads are queued and run one at a time.'
                : `${queue.filter((job) => IN_FLIGHT.includes(job.status)).length} active · ${queue.length} total`}
            </p>
          </div>
          <button onClick={() => void loadQueue()} className="btn btn-quiet text-[11px]">
            Refresh
          </button>
        </div>
        <div className="mt-3 max-w-4xl">
          <QueueList
            jobs={queue}
            onRetried={onQueued}
            onOpenExport={(exportId) => open(exportId)}
          />
        </div>
      </section>
    </div>
  )
}

function YouTubeCard({
  status,
  connecting,
  disconnecting,
  onConnect,
  onDisconnect,
}: {
  status: PublishingStatus | null
  connecting: boolean
  disconnecting: boolean
  onConnect: () => void
  onDisconnect: () => void
}) {
  if (status === null) {
    return (
      <div className="glass flex items-center justify-center p-6">
        <p className="text-xs text-ink-500">Checking the YouTube connection…</p>
      </div>
    )
  }

  const connected = status.connected
  const expiry = status.expires_at
    ? new Date(status.expires_at * 1000).toLocaleString()
    : ''

  return (
    <div className="glass flex flex-col p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="eyebrow">YouTube</p>
          <p className="mt-2 flex items-center gap-2 text-[13px] font-semibold text-ink-100">
            <span
              className={`status-dot ${
                connected ? 'text-signal-good' : status.configured ? 'text-signal-warn' : 'text-signal-bad'
              }`}
            />
            {connected ? 'Connected' : status.configured ? 'Not connected' : 'No client file'}
          </p>
        </div>
        {connected ? (
          <button
            onClick={onDisconnect}
            disabled={disconnecting}
            className="btn btn-quiet text-[11px]"
          >
            {disconnecting ? '…' : 'Disconnect'}
          </button>
        ) : (
          <button
            onClick={onConnect}
            disabled={connecting || !status.configured}
            className="btn btn-primary px-3.5 py-2 text-[12px]"
          >
            {connecting ? 'Opening Google…' : 'Connect'}
          </button>
        )}
      </div>

      <dl className="mt-4 space-y-2 text-[11px] leading-relaxed">
        <div className="flex justify-between gap-3">
          <dt className="text-ink-500">Scope</dt>
          <dd className="text-right text-ink-300">upload only</dd>
        </div>
        {status.client_project && (
          <div className="flex justify-between gap-3">
            <dt className="text-ink-500">Project</dt>
            <dd className="truncate text-right text-ink-300">{status.client_project}</dd>
          </div>
        )}
        <div className="flex justify-between gap-3">
          <dt className="text-ink-500">Redirect</dt>
          <dd className="truncate text-right text-ink-300">{status.redirect_uri}</dd>
        </div>
        {connected && expiry && (
          <div className="flex justify-between gap-3">
            <dt className="text-ink-500">Access token</dt>
            <dd className="text-right text-ink-300">
              {status.has_refresh_token ? 'auto-renews' : `expires ${expiry}`}
            </dd>
          </div>
        )}
      </dl>

      {!status.configured && (
        <p className="mt-4 border-t border-white/10 pt-3 text-[11px] leading-relaxed text-ink-400">
          {status.detail || 'The OAuth client file is missing.'}{' '}
          {status.hint && <span className="text-ink-500">{status.hint}</span>}
        </p>
      )}

      {status.configured && !connected && status.configured_redirect_uris.length > 0 && (
        <p className="mt-4 border-t border-white/10 pt-3 text-[10px] leading-relaxed text-ink-500">
          Registered redirect{status.configured_redirect_uris.length > 1 ? 's' : ''}:{' '}
          {status.configured_redirect_uris.join(', ')}. If Google refuses the redirect, add{' '}
          <span className="text-ink-300">{status.redirect_uri}</span> in Google Cloud Console.
        </p>
      )}

      {status.warnings.map((warning) => (
        <p
          key={warning}
          className="mt-3 rounded-[10px] border border-signal-warn/25 bg-signal-warn/[0.06] px-3 py-2 text-[10px] leading-relaxed text-ink-300"
        >
          {warning}
        </p>
      ))}

      <p className="mt-auto pt-4 text-[10px] leading-relaxed text-ink-500">
        The client secret is read from disk and never shown. Tokens stay in{' '}
        <code className="text-ink-400">~/.autoclip</code> with owner-only permissions.
      </p>
    </div>
  )
}

function ExportCard({
  record,
  publish,
  onOpen,
}: {
  record: ExportDetail
  publish: PublishRecord | null
  onOpen: () => void
}) {
  const published = publish?.status === 'published'
  const badge = publish ? PUBLISH_BADGE[publish.status] : null

  return (
    <button
      onClick={onOpen}
      className="glass group overflow-hidden p-2 text-left transition-transform duration-300 hover:-translate-y-0.5 [&:hover]:shadow-[0_36px_80px_-40px_rgba(0,0,0,0.9)]"
    >
      <div className="relative aspect-[4/5] overflow-hidden rounded-[16px] bg-ink-800">
        <img
          src={record.thumbnail_url}
          alt=""
          loading="lazy"
          className="size-full object-cover transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:scale-[1.03]"
        />
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 via-black/35 to-transparent p-3 pt-10">
          <p className="line-clamp-2 text-[12px] font-semibold leading-snug text-white">
            {record.title || record.filename}
          </p>
          <p className="numeric mt-1 text-[10px] text-white/60">
            {formatDuration(record.duration_s)} · {record.ratio} · {formatBytes(record.size_bytes)}
          </p>
        </div>
        {badge && (
          <span
            className={`absolute left-2.5 top-2.5 flex items-center gap-1.5 rounded-full bg-black/70 px-2.5 py-1 text-[9px] font-bold uppercase tracking-[0.14em] backdrop-blur-sm ${badge.tone}`}
          >
            <span className="status-dot" />
            {badge.label}
          </span>
        )}
      </div>

      <div className="flex items-center justify-between gap-2 px-2 py-2.5">
        <span className="truncate text-[10px] text-ink-500">
          {new Date(record.created_at).toLocaleDateString()}
          {record.validation && !record.validation.ok ? ' · needs attention' : ''}
        </span>
        <span className="text-[10px] font-semibold text-sodium-400 opacity-0 transition-opacity group-hover:opacity-100">
          {published ? 'View' : publish ? 'Queue' : 'Publish'} →
        </span>
      </div>
    </button>
  )
}

const PUBLISH_BADGE: Record<PublishRecord['status'], { label: string; tone: string }> = {
  pending: { label: 'Queued', tone: 'text-ink-300' },
  uploading: { label: 'Uploading', tone: 'text-sodium-400' },
  processing: { label: 'Processing', tone: 'text-signal-warn' },
  published: { label: 'Published', tone: 'text-signal-good' },
  failed: { label: 'Failed', tone: 'text-signal-bad' },
}
