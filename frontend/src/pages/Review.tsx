import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import {
  api,
  formatBytes,
  formatDuration,
  type CaptionStyle,
  type Clip,
  type CropPath,
  type Job,
  type Word,
} from '../api'
import { CaptionEditor } from '../components/CaptionEditor'
import { ClipPlayer } from '../components/ClipPlayer'
import { ErrorNote } from '../components/ErrorNote'
import { TrimBar } from '../components/TrimBar'

const RATIOS = ['9:16', '1:1', '16:9'] as const

export function Review() {
  const { jobId } = useParams()
  const [job, setJob] = useState<Job | null>(null)
  const [clips, setClips] = useState<Clip[]>([])
  const [styles, setStyles] = useState<CaptionStyle[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [words, setWords] = useState<Word[]>([])
  const [cropPath, setCropPath] = useState<CropPath | null>(null)
  const [wordsDirty, setWordsDirty] = useState(false)
  const [savingWords, setSavingWords] = useState(false)
  const [exporting, setExporting] = useState<Set<string>>(new Set())
  const [manualOpen, setManualOpen] = useState(false)
  const [creatingManual, setCreatingManual] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  useEffect(() => {
    if (!jobId) return
    void Promise.all([api.getJob(jobId), api.listClips(jobId), api.captionStyles()])
      .then(([loadedJob, loadedClips, loadedStyles]) => {
        setJob(loadedJob)
        setClips(loadedClips)
        setStyles(loadedStyles)
        setSelectedId((current) => current ?? loadedClips[0]?.id ?? null)
      })
      .catch((err) => setError(err as Error))
  }, [jobId])

  const selected = useMemo(
    () => clips.find((clip) => clip.id === selectedId) ?? null,
    [clips, selectedId],
  )

  useEffect(() => {
    if (!selected) return
    setWordsDirty(false)
    api
      .getClipWords(selected.id)
      .then(setWords)
      .catch(() => setWords([]))
    // 404 is expected for audio-only sources and jobs that never reframed; the
    // player falls back to a centre crop, matching what the renderer does.
    api
      .getCropPath(selected.id)
      .then(setCropPath)
      .catch(() => setCropPath(null))
  }, [selected?.id])

  const patchClip = useCallback((updated: Clip) => {
    setClips((current) => current.map((clip) => (clip.id === updated.id ? updated : clip)))
  }, [])

  const setStatus = async (clip: Clip, status: Clip['status']) => {
    try {
      patchClip(await api.patchClip(clip.id, { status }))
    } catch (err) {
      setError(err as Error)
    }
  }

  const commitTrim = async (start: number, end: number) => {
    if (!selected) return
    try {
      patchClip(await api.patchClip(selected.id, { start_s: start, end_s: end }))
      setWords(await api.getClipWords(selected.id))
    } catch (err) {
      setError(err as Error)
    }
  }

  const saveWords = async () => {
    if (!selected) return
    setSavingWords(true)
    try {
      patchClip(await api.patchCaptions(selected.id, { words }))
      setWordsDirty(false)
    } catch (err) {
      setError(err as Error)
    } finally {
      setSavingWords(false)
    }
  }

  const setStyle = async (clip: Clip, styleKey: string) => {
    try {
      patchClip(await api.patchCaptions(clip.id, { caption_style: styleKey }))
    } catch (err) {
      setError(err as Error)
    }
  }

  const setRatio = async (clip: Clip, ratio: string) => {
    try {
      patchClip(await api.patchCaptions(clip.id, { ratio }))
    } catch (err) {
      setError(err as Error)
    }
  }

  const exportClip = async (clip: Clip) => {
    setExporting((current) => new Set(current).add(clip.id))
    setError(null)
    try {
      await api.exportClip(clip.id, clip.ratio, clip.caption_style)
      patchClip(await api.getClip(clip.id))
    } catch (err) {
      setError(err as Error)
    } finally {
      setExporting((current) => {
        const next = new Set(current)
        next.delete(clip.id)
        return next
      })
    }
  }

  const exportKept = async () => {
    const targets = clips.filter((clip) => clip.status === 'kept')
    for (const clip of targets) await exportClip(clip)
  }

  const createManualClip = async (startS: number, endS: number, title: string) => {
    if (!jobId) return
    setCreatingManual(true)
    setError(null)
    try {
      const created = await api.createManualClip(jobId, startS, endS, title)
      setClips((current) => [...current, created].sort((a, b) => a.rank - b.rank))
      setSelectedId(created.id)
      setManualOpen(false)
    } catch (err) {
      setError(err as Error)
    } finally {
      setCreatingManual(false)
    }
  }

  const keptCount = clips.filter((clip) => clip.status === 'kept').length
  const exportedCount = clips.reduce((total, clip) => total + clip.exports.length, 0)
  const activeStyle = styles.find((style) => style.key === selected?.caption_style)

  if (error && clips.length === 0) {
    return (
      <div className="mx-auto max-w-2xl pt-24">
        <div className="glass p-6">
          <ErrorNote error={error} />
        </div>
      </div>
    )
  }

  if (!job) {
    return (
      <div className="glass mx-auto mt-24 max-w-md p-8 text-center">
        <p className="text-sm text-ink-400">Loading clips and transcript…</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="rise flex flex-wrap items-end justify-between gap-5">
        <div className="min-w-0">
          <Link to="/" className="eyebrow transition-colors hover:text-sodium-400">
            ← All jobs
          </Link>
          <h1 className="display mt-3 max-w-3xl truncate text-[clamp(1.9rem,4.2vw,3.6rem)] text-ink-100">
            {job.source?.title || 'Untitled'}
          </h1>
          <p className="numeric mt-2 text-[11px] text-ink-500">
            {clips.length} clips · {keptCount} kept · {exportedCount} exported
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button onClick={() => setManualOpen(true)} className="btn btn-ghost">
            + Add clip
          </button>
          <Link to="/publishing" className="btn btn-ghost">
            Publishing
          </Link>
          <button onClick={exportKept} disabled={keptCount === 0} className="btn btn-primary">
            Export kept
          </button>
        </div>
      </div>

      {error && (
        <div className="glass max-w-3xl p-5">
          <ErrorNote error={error} onDismiss={() => setError(null)} />
        </div>
      )}

      {clips.length === 0 ? (
        <EmptyState onCreate={() => setManualOpen(true)} />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,19rem)_minmax(22rem,27rem)_minmax(0,1fr)]">
          {/* Ranked list */}
          <section className="glass flex min-h-0 flex-col p-3 xl:max-h-[82vh]">
            <p className="eyebrow px-2 pb-2 pt-1">Ranked moments</p>
            <ul className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1">
              {clips.map((clip, index) => (
                <li key={clip.id}>
                  <ClipRow
                    clip={clip}
                    index={index}
                    selected={clip.id === selectedId}
                    onSelect={() => setSelectedId(clip.id)}
                    onKeep={() => setStatus(clip, clip.status === 'kept' ? 'candidate' : 'kept')}
                    onDiscard={() =>
                      setStatus(clip, clip.status === 'discarded' ? 'candidate' : 'discarded')
                    }
                  />
                </li>
              ))}
            </ul>
          </section>

          {/* Player + trim */}
          <section className="glass flex flex-col p-3 sm:p-4">
            {selected && jobId && (
              <>
                <ClipPlayer
                  src={api.mediaUrl(jobId)}
                  startS={selected.start_s}
                  endS={selected.end_s}
                  words={words}
                  style={activeStyle}
                  ratio={selected.ratio}
                  cropPath={cropPath}
                />
                <div className="mt-5 border-t border-white/10 pt-4">
                  <TrimBar
                    words={words}
                    startS={selected.start_s}
                    endS={selected.end_s}
                    originalStart={selected.start_s}
                    originalEnd={selected.end_s}
                    onCommit={commitTrim}
                  />
                </div>
              </>
            )}
          </section>

          {/* Editor + style */}
          <section className="space-y-4">
            {selected && (
              <>
                <div className="glass p-5">
                  <p className="eyebrow">Why this clip</p>
                  <p className="mt-2 max-w-prose text-[0.9375rem] leading-relaxed text-ink-300">
                    {selected.reason || 'No rationale returned for this clip.'}
                  </p>
                  {selected.hook && (
                    <p className="serif-accent mt-3 border-l border-sodium-500/40 pl-3 text-lg leading-snug text-ink-200">
                      “{selected.hook}”
                    </p>
                  )}
                  <div className="mt-4 flex flex-wrap items-center gap-2">
                    <span className="chip">
                      score <span className="numeric text-ink-100">{selected.score}</span>
                    </span>
                    <span className="chip">{formatDuration(selected.duration_s)}</span>
                    <span className="chip">{selected.ratio}</span>
                    {selected.user_trimmed && <span className="chip">trimmed</span>}
                  </div>
                </div>

                <div className="glass p-5">
                  <CaptionEditor
                    words={words}
                    onChange={(next) => {
                      setWords(next)
                      setWordsDirty(true)
                    }}
                    onSave={saveWords}
                    saving={savingWords}
                    dirty={wordsDirty}
                  />
                </div>

                <div className="glass p-5">
                  <p className="eyebrow">Caption style</p>
                  <div className="mt-3 grid gap-1.5 sm:grid-cols-2">
                    {styles.map((style) => (
                      <button
                        key={style.key}
                        onClick={() => setStyle(selected, style.key)}
                        className={[
                          'rounded-[12px] border px-3 py-2.5 text-left transition-colors duration-200',
                          style.key === selected.caption_style
                            ? 'border-sodium-500/55 bg-sodium-500/[0.08]'
                            : 'border-white/10 bg-white/[0.02] hover:border-white/25',
                        ].join(' ')}
                      >
                        <span className="block text-[12px] font-semibold text-ink-100">
                          {style.label}
                        </span>
                        <span className="mt-0.5 block text-[10px] leading-snug text-ink-500">
                          {style.description}
                        </span>
                      </button>
                    ))}
                  </div>

                  <div className="mt-5 flex flex-wrap items-center gap-2">
                    <span className="eyebrow mr-1">Ratio</span>
                    {RATIOS.map((ratio) => (
                      <button
                        key={ratio}
                        onClick={() => setRatio(selected, ratio)}
                        className={[
                          'numeric btn px-3.5 py-1.5 text-[11px]',
                          ratio === selected.ratio ? 'btn-primary' : 'btn-ghost',
                        ].join(' ')}
                      >
                        {ratio}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="glass p-5">
                  <button
                    onClick={() => exportClip(selected)}
                    disabled={exporting.has(selected.id)}
                    className="btn btn-primary w-full"
                  >
                    {exporting.has(selected.id) ? 'Rendering…' : 'Export this clip'}
                  </button>
                  {exporting.has(selected.id) && (
                    <p className="mt-2 text-center text-[10px] text-ink-500">
                      Rendering on this machine. The button returns when the MP4 is verified.
                    </p>
                  )}

                  {selected.exports.length > 0 && (
                    <ul className="mt-4 space-y-2 border-t border-white/10 pt-4">
                      {selected.exports.map((record) => (
                        <li
                          key={record.id}
                          className="glass-quiet flex items-center gap-3 px-3 py-2.5"
                        >
                          <span className="min-w-0 flex-1">
                            <span className="numeric block text-[11px] text-ink-200">
                              {record.ratio} · {record.style}
                            </span>
                            <span className="numeric mt-0.5 block text-[10px] text-ink-500">
                              {formatBytes(record.size_bytes)}
                            </span>
                          </span>
                          <a
                            href={record.download_url}
                            download
                            className="btn btn-quiet px-1.5 py-1 text-[11px]"
                          >
                            Download
                          </a>
                          <Link
                            to={`/publishing?export=${record.id}`}
                            className="btn btn-ghost px-3 py-1.5 text-[11px]"
                          >
                            Publish ↗
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </>
            )}
          </section>
        </div>
      )}

      {manualOpen && jobId && (
        <ManualClipModal
          jobId={jobId}
          durationS={job.source?.duration_s ?? 0}
          creating={creatingManual}
          onClose={() => setManualOpen(false)}
          onCreate={createManualClip}
        />
      )}
    </div>
  )
}

function ClipRow({
  clip,
  index,
  selected,
  onSelect,
  onKeep,
  onDiscard,
}: {
  clip: Clip
  index: number
  selected: boolean
  onSelect: () => void
  onKeep: () => void
  onDiscard: () => void
}) {
  return (
    <div
      className={[
        'rise group grid cursor-pointer grid-cols-[2.4rem_1fr] gap-x-3 rounded-[12px] px-2 py-2.5 transition-colors duration-200',
        selected
          ? 'bg-white/[0.075] shadow-[inset_0_1px_0_rgba(255,255,255,0.07)]'
          : 'hover:bg-white/[0.04]',
        clip.status === 'discarded' ? 'opacity-40' : '',
      ].join(' ')}
      style={{ animationDelay: `${Math.min(index, 10) * 35}ms` }}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onSelect()
      }}
    >
      {/* The score is the thing you scan by, so it gets the display weight. */}
      <span
        className={[
          'numeric self-start pt-0.5 text-[19px] font-bold leading-none tracking-tight',
          clip.score >= 85 ? 'text-sodium-500' : selected ? 'text-ink-200' : 'text-ink-500',
        ].join(' ')}
      >
        {clip.score}
      </span>

      <div className="min-w-0">
        <p className="line-clamp-2 text-[12.5px] font-medium leading-snug text-ink-100">
          {clip.title || 'Untitled clip'}
        </p>
        <div className="mt-1 flex items-baseline gap-2.5">
          <span className="numeric text-[10px] text-ink-500">{formatDuration(clip.duration_s)}</span>
          {clip.user_trimmed && <span className="text-[10px] text-ink-600">trimmed</span>}
          {clip.exports.length > 0 && (
            <span className="text-[10px] text-signal-good">
              {clip.exports.length} export{clip.exports.length > 1 ? 's' : ''}
            </span>
          )}

          <span
            className={[
              'ml-auto flex gap-2.5 transition-opacity duration-200',
              selected ? 'opacity-100' : 'opacity-0 group-hover:opacity-100',
            ].join(' ')}
          >
            <button
              onClick={(e) => {
                e.stopPropagation()
                onKeep()
              }}
              className={`text-[10px] font-semibold ${clip.status === 'kept' ? 'text-signal-good' : 'text-ink-400 hover:text-ink-100'}`}
            >
              {clip.status === 'kept' ? 'kept' : 'keep'}
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation()
                onDiscard()
              }}
              className="text-[10px] font-semibold text-ink-400 hover:text-signal-bad"
            >
              {clip.status === 'discarded' ? 'undo' : 'drop'}
            </button>
          </span>
        </div>
      </div>
    </div>
  )
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="glass max-w-xl p-8">
      <h2 className="display text-3xl text-ink-200">No clips came back.</h2>
      <p className="mt-4 text-sm leading-relaxed text-ink-400">
        The model found nothing self-contained enough to stand alone — which is a real answer for
        some source material, not necessarily a failure.
      </p>
      <p className="mt-3 text-sm leading-relaxed text-ink-400">
        Choose the moment yourself. The segment will go through the normal trim, caption, export,
        and publishing workflow.
      </p>
      <div className="mt-5 flex flex-wrap gap-2">
        <button onClick={onCreate} className="btn btn-primary">
          Choose a segment
        </button>
        <Link to="/" className="btn btn-ghost">
          Try another video
        </Link>
      </div>
    </div>
  )
}

function ManualClipModal({
  jobId,
  durationS,
  creating,
  onClose,
  onCreate,
}: {
  jobId: string
  durationS: number
  creating: boolean
  onClose: () => void
  onCreate: (startS: number, endS: number, title: string) => void
}) {
  const initialEnd = durationS > 0 ? Math.min(30, durationS) : 30
  const [startS, setStartS] = useState(0)
  const [endS, setEndS] = useState(initialEnd)
  const [title, setTitle] = useState('')
  const valid =
    endS > startS &&
    startS >= 0 &&
    (durationS <= 0 || endS <= durationS)

  return (
    <div
      className="fixed inset-0 z-[80] grid place-items-center overflow-y-auto bg-ink-900/75 p-4 backdrop-blur-xl"
      role="dialog"
      aria-modal="true"
      aria-label="Create a manual clip"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="glass w-full max-w-4xl p-4 sm:p-6">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <p className="eyebrow">Manual selection</p>
            <h2 className="display mt-2 text-3xl text-ink-100">Choose your moment</h2>
          </div>
          <button onClick={onClose} className="btn btn-ghost px-3 py-2" aria-label="Close">
            ×
          </button>
        </div>

        <div className="grid gap-5 lg:grid-cols-[minmax(18rem,22rem)_1fr]">
          <ClipPlayer
            src={api.mediaUrl(jobId)}
            startS={startS}
            endS={endS}
            words={[]}
            style={undefined}
            ratio="9:16"
            cropPath={null}
          />

          <div className="glass-quiet h-fit p-4 sm:p-5">
            <label className="block">
              <span className="eyebrow">Clip title</span>
              <input
                className="field mt-2"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="Give this moment a name"
              />
            </label>

            <div className="mt-5 grid grid-cols-2 gap-3">
              <label className="block">
                <span className="eyebrow">Start</span>
                <input
                  type="number"
                  className="field numeric mt-2"
                  min={0}
                  max={durationS > 0 ? durationS : undefined}
                  step={0.1}
                  value={startS}
                  onChange={(event) => setStartS(Math.max(0, Number(event.target.value) || 0))}
                />
              </label>
              <label className="block">
                <span className="eyebrow">End</span>
                <input
                  type="number"
                  className="field numeric mt-2"
                  min={0.1}
                  max={durationS > 0 ? durationS : undefined}
                  step={0.1}
                  value={endS}
                  onChange={(event) => setEndS(Math.max(0.1, Number(event.target.value) || 0.1))}
                />
              </label>
            </div>

            <div className="mt-4">
              <div className="flex justify-between text-[10px] text-ink-500">
                <span className="numeric">{formatDuration(startS)}</span>
                <span className="numeric">{(endS - startS).toFixed(1)} seconds</span>
                <span className="numeric">{formatDuration(endS)}</span>
              </div>
              <input
                type="range"
                min={0}
                max={durationS > 0 ? durationS : endS}
                step={0.1}
                value={startS}
                onChange={(event) => setStartS(Number(event.target.value))}
                className="mt-3 h-1 w-full"
                aria-label="Clip start time"
              />
              <input
                type="range"
                min={0}
                max={durationS > 0 ? durationS : endS}
                step={0.1}
                value={endS}
                onChange={(event) => setEndS(Number(event.target.value))}
                className="mt-3 h-1 w-full"
                aria-label="Clip end time"
              />
            </div>

            {!valid && (
              <p className="mt-4 text-xs text-signal-bad">
                Choose an end time after the start and within the source.
              </p>
            )}

            <button
              onClick={() => onCreate(startS, endS, title)}
              disabled={!valid || creating}
              className="btn btn-primary mt-5 w-full"
            >
              {creating ? 'Adding clip…' : 'Create and open clip'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
