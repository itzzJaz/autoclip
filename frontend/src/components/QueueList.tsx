import { useState } from 'react'

import { api, type PublishRecord } from '../api'
import { ErrorNote } from './ErrorNote'

const LABEL: Record<PublishRecord['status'], string> = {
  pending: 'Pending',
  uploading: 'Uploading',
  processing: 'Processing',
  published: 'Published',
  failed: 'Failed',
}

const TONE: Record<PublishRecord['status'], string> = {
  pending: 'text-ink-400',
  uploading: 'text-sodium-500',
  processing: 'text-signal-warn',
  published: 'text-signal-good',
  failed: 'text-signal-bad',
}

/**
 * The upload queue.
 *
 * Progress is the server's measured byte offset, so the bar only moves when
 * YouTube has actually accepted more of the file. Processing is a separate,
 * slower state: the upload is finished but YouTube is still transcoding, and
 * showing a full bar with "Processing" is the honest reading.
 */
export function QueueList({
  jobs,
  onRetried,
  onOpenExport,
}: {
  jobs: PublishRecord[]
  onRetried: (job: PublishRecord) => void
  onOpenExport?: (exportId: string) => void
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const [errors, setErrors] = useState<Record<string, Error>>({})

  if (jobs.length === 0) {
    return (
      <div className="glass-quiet flex min-h-32 items-center justify-center px-6 py-10 text-center">
        <p className="max-w-xs text-xs leading-relaxed text-ink-500">
          No uploads yet. Publishing a clip adds it here and shows real transfer progress.
        </p>
      </div>
    )
  }

  const retry = async (job: PublishRecord) => {
    setBusy(job.id)
    try {
      onRetried(await api.retryPublish(job.id))
    } catch (err) {
      setErrors((current) => ({ ...current, [job.id]: err as Error }))
    } finally {
      setBusy(null)
    }
  }

  return (
    <ul className="space-y-2.5">
      {jobs.map((job) => (
        <li key={job.id} className="glass-quiet p-3">
          <div className="flex items-start gap-3">
            <div className="relative h-[4.5rem] w-12 shrink-0 overflow-hidden rounded-[10px] bg-ink-800">
              {job.thumbnail_url ? (
                <img
                  src={job.thumbnail_url}
                  alt=""
                  className="size-full object-cover"
                  loading="lazy"
                />
              ) : (
                <span className="grid size-full place-items-center text-[9px] uppercase tracking-wider text-ink-600">
                  no img
                </span>
              )}
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex items-start justify-between gap-3">
                <button
                  onClick={() => onOpenExport?.(job.export_id)}
                  className="min-w-0 truncate text-left text-[13px] font-semibold text-ink-100 hover:text-sodium-400"
                  title={job.title}
                >
                  {job.title || 'Untitled upload'}
                </button>
                <span
                  className={`flex shrink-0 items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider ${TONE[job.status]}`}
                >
                  <span className={`status-dot ${job.status === 'uploading' ? 'pulse-dot' : ''}`} />
                  {LABEL[job.status]}
                </span>
              </div>

              <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[10px] text-ink-500">
                <span className="capitalize">{job.privacy}</span>
                {job.hashtags.length > 0 && <span className="truncate">{job.hashtags.join(' ')}</span>}
                {job.attempts > 1 && <span>attempt {job.attempts}</span>}
                {job.published_at && (
                  <span className="numeric">{new Date(job.published_at).toLocaleString()}</span>
                )}
              </div>

              {job.status === 'uploading' && (
                <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/10">
                  <div
                    className="h-full rounded-full bg-sodium-500 transition-[width] duration-500 ease-[cubic-bezier(0.16,1,0.3,1)]"
                    style={{ width: `${Math.max(2, Math.round(job.progress * 100))}%` }}
                  />
                </div>
              )}
              {job.status === 'uploading' && (
                <p className="numeric mt-1 text-[10px] text-ink-400">
                  {Math.round(job.progress * 100)}% transferred
                </p>
              )}

              {job.status === 'processing' && (
                <p className="mt-2 text-[11px] leading-relaxed text-ink-400">
                  Transfer complete. YouTube is still transcoding it — this can take a few
                  minutes. Nothing needs to stay open.
                </p>
              )}

              {job.status === 'published' && job.url && (
                <a
                  href={job.url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-1.5 inline-flex items-center gap-1 text-[11px] font-semibold text-sodium-400 hover:text-sodium-500"
                >
                  Open on YouTube ↗
                </a>
              )}

              {job.error && (
                <div className="mt-2">
                  <ErrorNote error={new Error(job.error)} />
                </div>
              )}
              {errors[job.id] && (
                <div className="mt-2">
                  <ErrorNote
                    error={errors[job.id]}
                    onDismiss={() =>
                      setErrors((current) => {
                        const next = { ...current }
                        delete next[job.id]
                        return next
                      })
                    }
                  />
                </div>
              )}

              <div className="mt-2 flex items-center gap-3">
                {job.status === 'failed' && (
                  <button
                    onClick={() => void retry(job)}
                    disabled={busy === job.id}
                    className="btn btn-ghost px-3 py-1.5 text-[11px]"
                  >
                    {busy === job.id ? 'Retrying…' : job.video_id ? 'Check again' : 'Resume upload'}
                  </button>
                )}
                {onOpenExport && job.status !== 'published' && (
                  <button
                    onClick={() => onOpenExport(job.export_id)}
                    className="btn btn-quiet px-1 py-1 text-[11px]"
                  >
                    Edit metadata
                  </button>
                )}
                {job.download_url && (
                  <a href={job.download_url} download className="btn btn-quiet px-1 py-1 text-[11px]">
                    Download
                  </a>
                )}
              </div>
            </div>
          </div>
        </li>
      ))}
    </ul>
  )
}
