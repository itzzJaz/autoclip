import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import {
  ApiError,
  api,
  formatDuration,
  type Job,
  type JobSettingsOverrides,
  type PublishingAnalytics,
  type InstagramStatus,
  type ProviderStatus,
} from '../api'
import { ErrorNote } from '../components/ErrorNote'
import { useEngine } from '../engine'

export function Ingest() {
  const navigate = useNavigate()
  const { status: engine } = useEngine()
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState<'url' | 'file' | null>(null)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [providers, setProviders] = useState<ProviderStatus[]>([])
  const [overrides, setOverrides] = useState<JobSettingsOverrides>({})
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [analytics, setAnalytics] = useState<PublishingAnalytics | null>(null)
  const [instagram, setInstagram] = useState<InstagramStatus | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.listJobs(8).then(setJobs).catch(() => undefined)
    api.providerStatus().then(setProviders).catch(() => undefined)
    api.publishingAnalytics().then(setAnalytics).catch(() => undefined)
    api.instagramStatus().then(setInstagram).catch(() => undefined)
  }, [])

  const start = useCallback(
    async (kind: 'url' | 'file', run: () => Promise<{ id: string }>) => {
      setBusy(kind)
      setError(null)
      try {
        const source = await run()
        const job = await api.createJob(source.id, overrides)
        navigate(`/jobs/${job.id}`)
      } catch (err) {
        setError(err as Error)
      } finally {
        setBusy(null)
      }
    },
    [navigate, overrides],
  )

  const submitUrl = (event: React.FormEvent) => {
    event.preventDefault()
    if (!url.trim()) return
    void start('url', () => api.ingestYouTube(url.trim()))
  }

  const submitFile = (file: File) => void start('file', () => api.uploadSource(file))

  const usableProvider = providers.find((p) => p.available)

  return (
    <div className="space-y-6">
      <section className="grid gap-5 lg:grid-cols-[1.45fr_0.55fr]">
        <div className="glass relative overflow-hidden p-6 sm:p-9 lg:p-11">
          <div
            aria-hidden
            className="pointer-events-none absolute -right-24 -top-28 size-80 rounded-full bg-sodium-500/20 blur-3xl"
          />
          <p className="eyebrow relative">Local-first · no uploads · no watermark</p>
          <h1 className="display relative mt-5 text-[clamp(2.9rem,7.2vw,6.4rem)] text-ink-100">
            Long video in.
            <br />
            <span className="serif-accent text-sodium-500">Shorts</span> out.
          </h1>
          <p className="relative mt-5 max-w-xl text-sm leading-relaxed text-ink-300">
            Drop in a podcast, talk, or stream. M-CLIP finds the moments that stand on
            their own, reframes them for a phone, and burns the captions.
          </p>

          {engine && engine.state !== 'running' && (
            <div className="relative mt-6 flex flex-wrap items-center gap-3 rounded-[14px] border border-sodium-500/25 bg-sodium-500/[0.07] px-4 py-3">
              <span className="status-dot text-signal-warn" />
              <p className="text-xs leading-relaxed text-ink-200">
                The engine is {engine.state}. New jobs will wait in the queue until it is
                started.
              </p>
              <Link to="/settings" className="ml-auto text-xs font-semibold text-sodium-400">
                Engine settings →
              </Link>
            </div>
          )}

          <form onSubmit={submitUrl} className="relative mt-8">
            <label htmlFor="url" className="eyebrow">
              Paste a link
            </label>
            <div className="mt-2.5 flex flex-col gap-2 sm:flex-row">
              <input
                id="url"
                className="field text-[15px]"
                placeholder="https://youtube.com/watch?v=…"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                autoComplete="off"
                spellCheck={false}
                disabled={busy !== null}
              />
              <button
                type="submit"
                className="btn btn-primary shrink-0 sm:px-6"
                disabled={busy !== null || !url.trim()}
              >
                {busy === 'url' ? 'Fetching…' : 'Ingest link'}
              </button>
            </div>
            <p className="mt-2.5 text-[11px] text-ink-500">
              Only download video you own or have the rights to process.
            </p>
          </form>
        </div>

        <div className="glass flex flex-col p-4 sm:p-5">
          <p className="eyebrow">Or drop a file</p>
          <div
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              const file = e.dataTransfer.files[0]
              if (file) submitFile(file)
            }}
            className={[
              'mt-3 flex flex-1 cursor-pointer flex-col items-center justify-center gap-3 rounded-[16px] border border-dashed px-5 py-12 text-center transition-colors duration-200',
              dragging
                ? 'border-sodium-500 bg-sodium-500/10'
                : 'border-white/15 bg-white/[0.02] hover:border-white/30 hover:bg-white/[0.04]',
            ].join(' ')}
            onClick={() => fileInput.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') fileInput.current?.click()
            }}
          >
            <span className="grid size-12 place-items-center rounded-full border border-white/15 bg-white/[0.05] text-lg text-sodium-400">
              ↑
            </span>
            <span className="text-[15px] font-semibold text-ink-100">
              {busy === 'file' ? 'Uploading…' : dragging ? 'Release to upload' : 'Drop video or audio'}
            </span>
            <span className="text-[11px] text-ink-500">mp4 · mov · mkv · webm · mp3 · wav · m4a</span>
          </div>
          <input
            ref={fileInput}
            type="file"
            className="hidden"
            accept="video/*,audio/*"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) submitFile(file)
              e.target.value = ''
            }}
          />

          <div className="mt-4 grid grid-cols-3 gap-2 text-center">
            <Stat label="Transcribe" value="Whisper" />
            <Stat label="Reframe" value="MediaPipe" />
            <Stat label="Render" value="ffmpeg" />
          </div>
        </div>
      </section>

      {error && (
        <div className="glass p-5">
          <ErrorNote error={error} onDismiss={() => setError(null)} />
        </div>
      )}

      {providers.length > 0 && !usableProvider && (
        <p className="glass flex flex-wrap items-center gap-2 px-5 py-4 text-xs text-ink-300">
          <span className="status-dot text-signal-warn" />
          No AI provider is reachable yet, so clip selection will fail.
          <Link to="/settings" className="font-semibold text-sodium-400">
            Add a key or start Ollama →
          </Link>
        </p>
      )}

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StudioMetric
          label="Published videos"
          value={(analytics?.totals.published ?? 0).toLocaleString()}
          detail="YouTube"
        />
        <StudioMetric
          label="Total views"
          value={(analytics?.totals.views ?? 0).toLocaleString()}
          detail="YouTube"
        />
        <StudioMetric
          label="Instagram followers"
          value={(instagram?.account.followers ?? 0).toLocaleString()}
          detail={instagram?.account.username ? `@${instagram.account.username}` : 'Not connected'}
        />
        <StudioMetric
          label="Instagram posts"
          value={(instagram?.account.media ?? 0).toLocaleString()}
          detail="Reels and posts"
        />
      </section>

      <section className="grid gap-5 lg:grid-cols-[1.45fr_1fr]">
        <AdvancedOptions
          open={advancedOpen}
          onToggle={() => setAdvancedOpen((v) => !v)}
          overrides={overrides}
          onChange={setOverrides}
          providers={providers}
        />
        <RecentJobs jobs={jobs} />
      </section>
    </div>
  )
}

function StudioMetric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="glass p-4 sm:p-5">
      <p className="eyebrow">{label}</p>
      <p className="numeric mt-3 text-[clamp(1.7rem,4vw,2.5rem)] font-bold leading-none tracking-tight text-ink-100">
        {value}
      </p>
      <p className="mt-2 truncate text-[10px] text-ink-500">{detail}</p>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[10px] border border-white/[0.07] bg-white/[0.02] px-2 py-2">
      <span className="block text-[9px] uppercase tracking-[0.18em] text-ink-500">{label}</span>
      <span className="mt-1 block text-[11px] font-semibold text-ink-200">{value}</span>
    </div>
  )
}

function AdvancedOptions({
  open,
  onToggle,
  overrides,
  onChange,
  providers,
}: {
  open: boolean
  onToggle: () => void
  overrides: JobSettingsOverrides
  onChange: (next: JobSettingsOverrides) => void
  providers: ProviderStatus[]
}) {
  const set = <K extends keyof JobSettingsOverrides>(key: K, value: JobSettingsOverrides[K]) =>
    onChange({ ...overrides, [key]: value })

  return (
    <div className="glass p-5 sm:p-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="eyebrow">Run options</p>
          <p className="mt-1 text-[11px] text-ink-500">
            Overrides for this job only. Saved defaults live in Settings.
          </p>
        </div>
        <button type="button" onClick={onToggle} className="btn btn-ghost px-3 py-2 text-[12px]">
          {open ? 'Hide' : 'Configure'}
        </button>
      </div>

      <div
        className="grid transition-[grid-template-rows] duration-400 ease-[cubic-bezier(0.16,1,0.3,1)]"
        style={{ gridTemplateRows: open ? '1fr' : '0fr' }}
      >
        <div className="overflow-hidden">
          <div className="grid gap-4 pt-5 sm:grid-cols-2">
            <Selector
              label="Provider"
              value={overrides.provider ?? ''}
              onChange={(v) => set('provider', v || undefined)}
              options={[
                { value: '', label: 'Use default' },
                ...providers.map((p) => ({
                  value: p.name,
                  label: p.available ? p.name : `${p.name} — unavailable`,
                  disabled: !p.available,
                })),
              ]}
            />
            <Selector
              label="Whisper model"
              value={overrides.whisper_model ?? ''}
              onChange={(v) => set('whisper_model', v || undefined)}
              options={[
                { value: '', label: 'Use default' },
                { value: 'tiny', label: 'tiny — fastest' },
                { value: 'base', label: 'base' },
                { value: 'small', label: 'small — balanced' },
                { value: 'medium', label: 'medium' },
                { value: 'large-v3', label: 'large-v3 — best' },
              ]}
            />
            <NumberField
              label="Max clips"
              value={overrides.max_clips}
              placeholder="10"
              min={1}
              max={50}
              onChange={(v) => set('max_clips', v)}
            />
            <div className="grid grid-cols-2 gap-3">
              <NumberField
                label="Min length (s)"
                value={overrides.min_duration_s}
                placeholder="20"
                min={5}
                max={300}
                onChange={(v) => set('min_duration_s', v)}
              />
              <NumberField
                label="Max length (s)"
                value={overrides.max_duration_s}
                placeholder="90"
                min={5}
                max={300}
                onChange={(v) => set('max_duration_s', v)}
              />
            </div>
            <label className="flex items-center gap-3 text-[12px] text-ink-200 sm:col-span-2">
              <input
                type="checkbox"
                checked={overrides.diarization ?? false}
                onChange={(e) => set('diarization', e.target.checked || undefined)}
                className="size-4 accent-sodium-500"
              />
              Label speakers and cut to whoever is talking
            </label>
          </div>
        </div>
      </div>
    </div>
  )
}

function Selector({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string; disabled?: boolean }[]
}) {
  return (
    <label className="block">
      <span className="eyebrow">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="field mt-1.5 cursor-pointer text-[12px]"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}

function NumberField({
  label,
  value,
  placeholder,
  min,
  max,
  onChange,
}: {
  label: string
  value: number | undefined
  placeholder: string
  min: number
  max: number
  onChange: (value: number | undefined) => void
}) {
  return (
    <label className="block">
      <span className="eyebrow">{label}</span>
      <input
        type="number"
        className="field numeric mt-1.5 text-[12px]"
        placeholder={placeholder}
        value={value ?? ''}
        min={min}
        max={max}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : undefined)}
      />
    </label>
  )
}

function RecentJobs({ jobs }: { jobs: Job[] }) {
  return (
    <div className="glass flex min-h-48 flex-col p-5 sm:p-6">
      <div className="flex items-baseline justify-between">
        <p className="eyebrow">Recent runs</p>
        <span className="numeric text-[10px] text-ink-500">{jobs.length}</span>
      </div>

      {jobs.length === 0 ? (
        <div className="flex flex-1 items-center justify-center py-10 text-center">
          <p className="max-w-56 text-xs leading-relaxed text-ink-500">
            Nothing processed yet. Your first run will appear here.
          </p>
        </div>
      ) : (
        <ul className="mt-3 flex-1">
          {jobs.map((job) => (
            <li key={job.id}>
              <Link
                to={job.status === 'done' ? `/jobs/${job.id}/clips` : `/jobs/${job.id}`}
                className="glass-link group -mx-2 flex items-center gap-3 px-2 py-3"
              >
                <span className={`status-dot ${jobTone(job.status)}`} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium text-ink-200 group-hover:text-ink-100">
                    {job.source?.title || 'Untitled'}
                  </span>
                  <span className="numeric mt-0.5 block text-[10px] text-ink-500">
                    {job.source ? formatDuration(job.source.duration_s) : '—'} · {job.provider}
                  </span>
                </span>
                <StatusTag job={job} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function jobTone(status: Job['status']): string {
  return {
    done: 'text-signal-good',
    failed: 'text-signal-bad',
    running: 'text-sodium-500',
    queued: 'text-ink-500',
    cancelled: 'text-ink-500',
  }[status]
}

function StatusTag({ job }: { job: Job }) {
  const tone: Record<string, string> = {
    done: 'text-signal-good',
    failed: 'text-signal-bad',
    running: 'text-sodium-500',
    queued: 'text-ink-400',
    cancelled: 'text-ink-500',
  }
  const label = job.status === 'running' ? `${Math.round(job.progress * 100)}%` : job.status

  return (
    <span className={`numeric shrink-0 text-[10px] font-semibold uppercase tracking-wider ${tone[job.status] ?? 'text-ink-400'}`}>
      {label}
    </span>
  )
}
