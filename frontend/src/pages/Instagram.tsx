import { useEffect, useState } from 'react'

import {
  api,
  formatDuration,
  type ExportDetail,
  type InstagramPublishRecord,
  type InstagramStatus,
} from '../api'
import { ErrorNote } from '../components/ErrorNote'

export function Instagram() {
  const [status, setStatus] = useState<InstagramStatus | null>(null)
  const [exports, setExports] = useState<ExportDetail[]>([])
  const [jobs, setJobs] = useState<InstagramPublishRecord[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [caption, setCaption] = useState('')
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const load = async () => {
    try {
      const [nextStatus, nextExports, nextJobs] = await Promise.all([
        api.instagramStatus(),
        api.listExports(100),
        api.instagramJobs(),
      ])
      setStatus(nextStatus)
      setExports(nextExports)
      setJobs(nextJobs)
    } catch (err) {
      setError(err as Error)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const publish = async () => {
    if (!selectedId || !confirm) return
    setBusy(true)
    setError(null)
    try {
      await api.publishInstagram(selectedId, caption, true)
      setConfirm(false)
      await load()
    } catch (err) {
      setError(err as Error)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <section className="grid gap-5 lg:grid-cols-[1.45fr_0.55fr]">
        <div className="rise">
          <p className="eyebrow">Instagram publishing</p>
          <h1 className="display mt-3 text-[clamp(2.4rem,5vw,4.6rem)] text-ink-100">
            Reels,
            <br />
            <span className="serif-accent text-sodium-500">ready for reach.</span>
          </h1>
          <p className="mt-4 max-w-xl text-sm leading-relaxed text-ink-300">
            Choose a finished export, write its caption, and publish to an Instagram Business or
            Creator account connected through Meta.
          </p>
        </div>
        <InstagramStatusCard status={status} onRefresh={() => void load()} />
      </section>

      {error && (
        <div className="glass p-5">
          <ErrorNote error={error} onDismiss={() => setError(null)} />
        </div>
      )}

      <section className="grid gap-5 xl:grid-cols-[1fr_22rem]">
        <div className="glass p-4 sm:p-5">
          <div className="mb-4 flex items-end justify-between">
            <div>
              <p className="eyebrow">Export library</p>
              <p className="mt-1 text-[11px] text-ink-500">Choose a 9:16 Reel export</p>
            </div>
            <span className="numeric text-[11px] text-ink-500">{exports.length}</span>
          </div>

          {exports.length === 0 ? (
            <p className="rounded-[14px] border border-dashed border-white/10 px-5 py-10 text-center text-xs text-ink-500">
              Export a clip in the Studio first.
            </p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {exports.map((item) => (
                <button
                  key={item.id}
                  onClick={() => setSelectedId(item.id)}
                  className={[
                    'overflow-hidden rounded-[14px] border p-2 text-left transition-colors',
                    selectedId === item.id
                      ? 'border-sodium-500/60 bg-sodium-500/[0.08]'
                      : 'border-white/10 bg-white/[0.025] hover:border-white/20',
                  ].join(' ')}
                >
                  <img
                    src={item.thumbnail_url}
                    alt=""
                    className="aspect-[9/16] w-full rounded-[10px] object-cover"
                  />
                  <p className="mt-2 line-clamp-2 px-1 text-[12px] font-semibold text-ink-100">
                    {item.title || item.filename}
                  </p>
                  <p className="numeric mt-1 px-1 pb-1 text-[10px] text-ink-500">
                    {item.ratio} · {formatDuration(item.duration_s)}
                  </p>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="glass h-fit p-5">
          <p className="eyebrow">Reel details</p>
          <label className="mt-4 block">
            <span className="text-[11px] font-semibold text-ink-300">Caption</span>
            <textarea
              value={caption}
              onChange={(event) => setCaption(event.target.value)}
              className="field mt-2 min-h-36 resize-y text-[13px]"
              maxLength={2200}
              placeholder="Write a caption, add context, and finish with a call to action…"
            />
          </label>
          <div className="mt-3 flex justify-between text-[10px] text-ink-500">
            <span>{caption.length}/2200</span>
            {selectedId && <span className="text-signal-good">Export selected</span>}
          </div>
          <label className="mt-5 flex items-start gap-3 text-[12px] leading-relaxed text-ink-300">
            <input
              type="checkbox"
              checked={confirm}
              onChange={(event) => setConfirm(event.target.checked)}
              className="mt-0.5 size-4 accent-sodium-500"
            />
            I reviewed the Reel and approved publishing to Instagram.
          </label>
          <button
            onClick={() => void publish()}
            disabled={!status?.configured || !selectedId || !confirm || busy}
            className="btn btn-primary mt-5 w-full"
          >
            {busy ? 'Publishing to Instagram…' : 'Publish Reel'}
          </button>
        </div>
      </section>

      {jobs.length > 0 && (
        <section className="glass p-5">
          <p className="eyebrow">Recent Instagram posts</p>
          <div className="mt-3 divide-y divide-white/[0.07]">
            {jobs.map((job) => (
              <a
                key={job.id}
                href={job.url || undefined}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-3 py-3 text-[12px] text-ink-300 hover:text-ink-100"
              >
                <span
                  className={[
                    'status-dot',
                    job.status === 'published'
                      ? 'text-signal-good'
                      : job.status === 'failed'
                        ? 'text-signal-bad'
                        : 'text-signal-warn',
                  ].join(' ')}
                />
                <span className="min-w-0 flex-1 truncate">
                  {job.caption || 'Instagram Reel'}
                </span>
                <span className="numeric text-[10px] uppercase text-ink-500">{job.status}</span>
              </a>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

function InstagramStatusCard({
  status,
  onRefresh,
}: {
  status: InstagramStatus | null
  onRefresh: () => void
}) {
  return (
    <div className="glass p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="eyebrow">Meta connection</p>
          <p className="mt-2 flex items-center gap-2 text-[13px] font-semibold text-ink-100">
            <span
              className={`status-dot ${
                status?.configured
                  ? 'text-signal-good'
                  : status
                    ? 'text-signal-warn'
                    : 'text-ink-500'
              }`}
            />
            {status?.configured ? 'Connected' : status ? 'Setup required' : 'Checking…'}
          </p>
        </div>
        <button onClick={onRefresh} className="btn btn-quiet text-[11px]">
          Refresh
        </button>
      </div>

      {status?.account.username && (
        <div className="mt-4 grid grid-cols-2 gap-3">
          <div className="glass-quiet p-3">
            <p className="eyebrow">Followers</p>
            <p className="numeric mt-2 text-2xl font-bold text-ink-100">
              {(status.account.followers ?? 0).toLocaleString()}
            </p>
          </div>
          <div className="glass-quiet p-3">
            <p className="eyebrow">Posts</p>
            <p className="numeric mt-2 text-2xl font-bold text-ink-100">
              {(status.account.media ?? 0).toLocaleString()}
            </p>
          </div>
        </div>
      )}

      {status && !status.configured && (
        <div className="mt-4 space-y-3 text-[11px] leading-relaxed text-ink-400">
          <p><strong className="text-ink-200">Meta setup</strong></p>
          <ol className="list-decimal space-y-2 pl-4">
            <li>Create a Meta app in <code>developers.facebook.com</code> and add Instagram Graph API.</li>
            <li>Connect a Professional or Creator Instagram account to a Facebook Page.</li>
            <li>Create a System User or grant <code>instagram_content_publish</code>, <code>instagram_basic</code>, and <code>pages_read_engagement</code>.</li>
            <li>Set environment variables and restart M-CLIP:
              <span className="mt-2 block rounded-[8px] bg-black/20 px-2 py-2 font-mono text-[9px] text-ink-300">
                AUTOCLIP_META_APP_ID=…<br />
                AUTOCLIP_META_APP_SECRET=…<br />
                AUTOCLIP_META_ACCESS_TOKEN=…<br />
                AUTOCLIP_INSTAGRAM_ACCOUNT_ID=…<br />
                AUTOCLIP_PUBLIC_BASE_URL=https://your-tunnel.example
              </span>
            </li>
            <li>Expose this M-CLIP server publicly with HTTPS; Instagram cannot download <code>localhost</code> exports.</li>
          </ol>
        </div>
      )}
    </div>
  )
}
