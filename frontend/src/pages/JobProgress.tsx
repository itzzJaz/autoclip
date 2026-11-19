import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { api, formatDuration } from '../api'
import { ErrorNote } from '../components/ErrorNote'
import { useEngine } from '../engine'
import { useJobStream } from '../useJobStream'

/** Stage order and labels, mirroring autoclip.pipeline.Stage. */
const STAGES = [
  { key: 'prepare', label: 'Prepare', note: 'Extracting audio and thumbnails' },
  { key: 'transcribe', label: 'Transcribe', note: 'Word-level timing' },
  { key: 'highlights', label: 'Highlights', note: 'Choosing the moments worth cutting' },
  { key: 'reframe', label: 'Reframe', note: 'Tracking the speaker into vertical' },
  { key: 'captions', label: 'Captions', note: 'Building subtitle timing' },
  { key: 'export', label: 'Export', note: 'Rendering clips' },
] as const

export function JobProgress() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const { job, progress } = useJobStream(jobId)
  const { status: engine } = useEngine()
  const [cancelling, setCancelling] = useState(false)
  const [actionError, setActionError] = useState<Error | null>(null)

  useEffect(() => {
    if (job?.status === 'done') {
      // A short hold so the completed state is legible rather than a flash.
      const timer = setTimeout(() => navigate(`/jobs/${job.id}/clips`), 900)
      return () => clearTimeout(timer)
    }
  }, [job?.status, job?.id, navigate])

  if (!job) {
    return (
      <div className="glass mx-auto mt-24 max-w-md p-8 text-center">
        <p className="text-sm text-ink-400">Connecting to the job stream…</p>
      </div>
    )
  }

  const activeIndex = STAGES.findIndex((s) => s.key === job.current_stage)
  const percent = Math.round((progress?.overall ?? job.progress) * 100)
  const waitingForEngine =
    (job.status === 'queued' || job.status === 'running') &&
    engine !== null &&
    engine.state !== 'running'

  const cancel = async () => {
    setCancelling(true)
    setActionError(null)
    try {
      await api.cancelJob(job.id)
    } catch (err) {
      setActionError(err as Error)
    } finally {
      setCancelling(false)
    }
  }

  const retry = async () => {
    setActionError(null)
    try {
      await api.retryJob(job.id)
      window.location.reload()
    } catch (err) {
      setActionError(err as Error)
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <section className="glass rise relative overflow-hidden p-6 sm:p-8">
        <div
          aria-hidden
          className="pointer-events-none absolute -right-20 -top-24 size-72 rounded-full bg-sodium-500/15 blur-3xl"
        />
        <div className="relative flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0">
            <p className="eyebrow">{job.status === 'running' ? 'Processing' : job.status}</p>
            <h1 className="display mt-3 max-w-2xl truncate text-[clamp(1.8rem,4vw,3.2rem)] text-ink-100">
              {job.source?.title || 'Untitled'}
            </h1>
            {job.source && (
              <p className="numeric mt-2 text-[11px] text-ink-500">
                {formatDuration(job.source.duration_s)}
                {job.source.width ? ` · ${job.source.width}×${job.source.height}` : ''} ·{' '}
                {job.provider}
              </p>
            )}
          </div>

          <div className="flex items-center gap-5">
            <span className="numeric text-[clamp(3rem,8vw,5rem)] font-bold leading-none tracking-[-0.05em] text-ink-100">
              {percent}
              <span className="ml-1 align-top text-xl text-ink-500">%</span>
            </span>
            {(job.status === 'running' || job.status === 'queued') && (
              <button onClick={cancel} disabled={cancelling} className="btn btn-ghost">
                {cancelling ? 'Cancelling…' : 'Cancel'}
              </button>
            )}
            {(job.status === 'failed' || job.status === 'cancelled') && (
              <button onClick={retry} className="btn btn-primary">
                Retry
              </button>
            )}
            {job.status === 'done' && (
              <button onClick={() => navigate(`/jobs/${job.id}/clips`)} className="btn btn-primary">
                Review clips
              </button>
            )}
          </div>
        </div>

        <div className="relative mt-6 h-1 overflow-hidden rounded-full bg-white/10">
          <div
            className="h-full rounded-full bg-sodium-500 transition-[width] duration-700 ease-[cubic-bezier(0.16,1,0.3,1)]"
            style={{ width: `${Math.max(1.5, percent)}%` }}
          />
        </div>

        {waitingForEngine && (
          <p className="relative mt-4 flex items-start gap-2.5 rounded-[12px] border border-signal-warn/25 bg-signal-warn/[0.07] px-3.5 py-2.5 text-[11px] leading-relaxed text-ink-300">
            <span className="status-dot mt-1 text-signal-warn" />
            <span>
              The engine is {engine?.state}. This job is held at the front of the queue and starts
              as soon as the engine is running — press Start engine in the header.
            </span>
          </p>
        )}
      </section>

      {job.error && (
        <div className="glass p-5">
          <ErrorNote error={new Error(job.error)} />
          <p className="mt-3 text-[11px] text-ink-500">
            Retrying resumes from the stage that failed — finished stages are not redone.
          </p>
        </div>
      )}

      {actionError && (
        <div className="glass p-5">
          <ErrorNote error={actionError} onDismiss={() => setActionError(null)} />
        </div>
      )}

      <section className="glass rise p-4 sm:p-6">
        <p className="eyebrow px-2 pb-2">Pipeline</p>
        <ol>
          {STAGES.map((stage, index) => {
            // A failed job stopped *at* current_stage, so that stage must read as
            // failed rather than as still running — otherwise the checklist claims
            // work is in progress while the banner says it died.
            const failedHere =
              (job.status === 'failed' || job.status === 'cancelled') && index === activeIndex

            const state =
              job.status === 'done' || (activeIndex >= 0 && index < activeIndex)
                ? 'done'
                : failedHere
                  ? 'stopped'
                  : index === activeIndex && job.status === 'running'
                    ? 'active'
                    : 'pending'

            const fraction =
              state === 'done' ? 1 : state === 'active' ? (progress?.stageProgress ?? 0) : 0

            return (
              <li
                key={stage.key}
                className="grid grid-cols-[2.2rem_1fr] items-start gap-x-4 rounded-[12px] px-2 py-4"
                style={{ animationDelay: `${index * 55}ms` }}
              >
                <span
                  className={[
                    'numeric grid size-7 place-items-center rounded-full border text-[10px] font-bold',
                    state === 'done'
                      ? 'border-signal-good/30 bg-signal-good/10 text-signal-good'
                      : state === 'stopped'
                        ? 'border-signal-bad/30 bg-signal-bad/10 text-signal-bad'
                        : state === 'active'
                          ? 'border-sodium-500/40 bg-sodium-500/10 text-sodium-400'
                          : 'border-white/10 text-ink-600',
                  ].join(' ')}
                >
                  {state === 'done' ? '✓' : state === 'stopped' ? '✕' : String(index + 1).padStart(2, '0')}
                </span>

                <div>
                  <div className="flex flex-wrap items-baseline justify-between gap-x-4">
                    <span
                      className={[
                        'text-[13.5px] font-medium',
                        state === 'pending' ? 'text-ink-600' : 'text-ink-100',
                      ].join(' ')}
                    >
                      {stage.label}
                    </span>
                    <span
                      className={`text-[11px] ${state === 'stopped' ? 'text-signal-bad' : 'text-ink-500'}`}
                    >
                      {state === 'stopped'
                        ? job.status === 'cancelled'
                          ? 'cancelled here'
                          : 'failed here'
                        : state === 'active'
                          ? (progress?.message ?? stage.note)
                          : stage.note}
                    </span>
                  </div>

                  <div className="mt-2.5 h-px w-full overflow-hidden bg-white/10">
                    <div
                      className="h-px origin-left bg-sodium-500 transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)]"
                      style={{ transform: `scaleX(${fraction})` }}
                    />
                  </div>
                </div>
              </li>
            )
          })}
        </ol>
      </section>
    </div>
  )
}
