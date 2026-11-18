import { useCallback, useEffect, useRef, useState } from 'react'

import {
  api,
  formatBytes,
  formatDuration,
  type ExportDetail,
  type GeneratedMetadata,
  type Privacy,
  type PublishRecord,
} from '../api'
import { ErrorNote } from './ErrorNote'
import { ValidationPanel } from './ValidationPanel'

const PRIVACY_COPY: Record<Privacy, { label: string; note: string }> = {
  private: {
    label: 'Private',
    note: 'Only you can see it. The safe default — you can change it in YouTube Studio.',
  },
  unlisted: {
    label: 'Unlisted',
    note: 'Anyone with the link can watch. It will not appear in search or on your channel.',
  },
  public: {
    label: 'Public',
    note: 'Visible to everyone immediately. This needs a second confirmation below.',
  },
}

type Style = 'concise' | 'story' | 'educational'

const STYLE_LABEL: Record<Style, string> = {
  concise: 'Concise',
  story: 'Story',
  educational: 'Educational',
}

/**
 * The publish flow for one completed export.
 *
 * Order is deliberate: see the file, read what will be said about it, choose who
 * can see it, then confirm. Nothing uploads until the last step, and the button
 * stays disabled while the file itself fails YouTube's requirements.
 */
export function PublishComposer({
  exportId,
  defaultPrivacy,
  defaultStyle,
  onQueued,
  onClose,
}: {
  exportId: string
  defaultPrivacy: Privacy
  defaultStyle: Style
  onQueued: (job: PublishRecord) => void
  onClose: () => void
}) {
  const [record, setRecord] = useState<ExportDetail | null>(null)
  const [loadError, setLoadError] = useState<Error | null>(null)
  const [metadata, setMetadata] = useState<GeneratedMetadata | null>(null)
  const [generating, setGenerating] = useState(false)
  const [metadataError, setMetadataError] = useState<Error | null>(null)
  const [style, setStyle] = useState<Style>(defaultStyle)

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [hashtags, setHashtags] = useState<string[]>([])
  const [hashtagDraft, setHashtagDraft] = useState('')
  const [tags, setTags] = useState('')
  const [privacy, setPrivacy] = useState<Privacy>(defaultPrivacy)
  const [confirmed, setConfirmed] = useState(false)
  const [confirmPublic, setConfirmPublic] = useState(false)

  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<Error | null>(null)
  const [queued, setQueued] = useState<PublishRecord | null>(null)
  const autoRan = useRef(false)

  const load = useCallback(async () => {
    setLoadError(null)
    try {
      const detail = await api.getExport(exportId, true)
      setRecord(detail)
      if (detail.publish) {
        setTitle(detail.publish.title)
        setDescription(detail.publish.description)
        setHashtags(detail.publish.hashtags)
        setTags(detail.publish.tags.join(', '))
        setPrivacy(detail.publish.privacy)
      }
    } catch (err) {
      setLoadError(err as Error)
    }
  }, [exportId])

  useEffect(() => {
    void load()
  }, [load])

  const requestMetadata = useCallback(
    async (nextStyle: Style) => {
      setGenerating(true)
      setMetadataError(null)
      try {
        const draft = await api.generateMetadata(exportId, { style: nextStyle })
        setMetadata(draft)
        setTitle((current) => current || draft.recommended_title)
        setDescription((current) => current || draft.description)
        setHashtags((current) => (current.length > 0 ? current : draft.hashtags))
        setTags((current) => current || draft.tags.join(', '))
      } catch (err) {
        setMetadataError(err as Error)
      } finally {
        setGenerating(false)
      }
    },
    [exportId],
  )

  // One automatic draft when the screen opens, so the common path is "read and
  // adjust" rather than "press generate first". Regenerate stays available.
  useEffect(() => {
    if (autoRan.current || !record || record.publish) return
    autoRan.current = true
    void requestMetadata(style)
  }, [record, requestMetadata, style])

  const regenerate = () => void requestMetadata(style)

  const addHashtag = () => {
    const value = hashtagDraft.trim().replace(/^#/, '').replace(/[^\w]/g, '')
    if (!value) return
    const candidate = `#${value}`
    setHashtags((current) =>
      current.length >= 5 || current.some((tag) => tag.toLowerCase() === candidate.toLowerCase())
        ? current
        : [...current, candidate],
    )
    setHashtagDraft('')
  }

  const publish = async () => {
    if (!record) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const job = await api.publishExport(record.id, {
        title: title.trim(),
        description,
        hashtags,
        tags: tags
          .split(',')
          .map((tag) => tag.trim())
          .filter(Boolean),
        privacy,
        confirm: confirmed,
        confirm_public: confirmPublic,
      })
      setQueued(job)
      onQueued(job)
    } catch (err) {
      setSubmitError(err as Error)
    } finally {
      setSubmitting(false)
    }
  }

  if (loadError) {
    return (
      <div className="glass p-6">
        <ErrorNote error={loadError} />
        <button onClick={onClose} className="btn btn-ghost mt-4">
          Back to library
        </button>
      </div>
    )
  }

  if (!record) {
    return (
      <div className="glass flex min-h-72 items-center justify-center p-8">
        <p className="text-sm text-ink-400">Loading export and checking its file…</p>
      </div>
    )
  }

  const existing = record.publish ?? queued
  const locked =
    existing !== null &&
    (existing.status === 'pending' ||
      existing.status === 'uploading' ||
      existing.status === 'processing' ||
      existing.status === 'published')

  const blocking = record.validation?.errors ?? []
  const canPublish =
    !locked &&
    !submitting &&
    blocking.length === 0 &&
    title.trim().length > 0 &&
    confirmed &&
    (privacy !== 'public' || confirmPublic)

  return (
    <div className="rise">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <button onClick={onClose} className="eyebrow transition-colors hover:text-sodium-400">
            ← Export library
          </button>
          <h2 className="display mt-2 max-w-2xl text-[clamp(1.6rem,3.4vw,2.6rem)] text-ink-100">
            {record.title || record.filename}
          </h2>
          <p className="numeric mt-2 text-[11px] text-ink-500">
            {record.filename} · {formatDuration(record.duration_s)} · {record.ratio} ·{' '}
            {formatBytes(record.size_bytes)} · {new Date(record.created_at).toLocaleString()}
          </p>
        </div>
      </div>

      {existing && (
        <div
          className={[
            'mt-5 rounded-[14px] border px-4 py-3 text-xs leading-relaxed',
            existing.status === 'published'
              ? 'border-signal-good/30 bg-signal-good/[0.07] text-ink-200'
              : existing.status === 'failed'
                ? 'border-signal-bad/30 bg-signal-bad/[0.07] text-ink-200'
                : 'border-sodium-500/25 bg-sodium-500/[0.07] text-ink-200',
          ].join(' ')}
        >
          <span className="font-semibold capitalize">{existing.status}</span>
          {' — '}
          {existing.status === 'published'
            ? 'This export is already on YouTube. It will never be uploaded a second time.'
            : existing.status === 'processing'
              ? 'The file is uploaded and YouTube is transcoding it. The queue will show when it is live.'
              : existing.status === 'uploading'
                ? 'The upload is in progress. Progress is in the queue below.'
                : existing.status === 'pending'
                  ? 'This upload is queued. You can follow it below.'
                  : 'The last attempt failed. Retry from the queue, or fix the details and publish again.'}
          {existing.url && (
            <a
              href={existing.url}
              target="_blank"
              rel="noreferrer"
              className="ml-2 font-semibold text-sodium-400"
            >
              Open ↗
            </a>
          )}
        </div>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,21rem)_minmax(0,1fr)]">
        <div className="space-y-5">
          <div className="glass overflow-hidden p-2.5">
            <div className="overflow-hidden rounded-[14px] bg-black">
              <video
                src={record.preview_url || record.download_url}
                controls
                playsInline
                preload="metadata"
                className="mx-auto max-h-[58vh] w-full object-contain"
              />
            </div>
          </div>

          <div className="glass p-5">
            <p className="eyebrow">Shorts check</p>
            <div className="mt-3">
              <ValidationPanel report={record.validation} />
            </div>
            <p className="mt-4 border-t border-white/10 pt-3 text-[10px] leading-relaxed text-ink-500">
              AutoClip measures the exported file and never alters it to pass a check.
              YouTube decides the final classification; a vertical file under three minutes
              does not guarantee it is surfaced as a Short.
            </p>
          </div>
        </div>

        <div className="space-y-5">
          <section className="glass p-5 sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="eyebrow">Metadata</p>
                <p className="mt-1 text-[11px] text-ink-500">
                  {metadata
                    ? metadata.generated_by === 'local-draft'
                      ? 'Drafted locally — no AI provider answered.'
                      : `Drafted by ${metadata.generated_by} from the clip and its transcript.`
                    : generating
                      ? 'Reading the transcript…'
                      : 'Generate a title, description, and hashtags.'}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <select
                  value={style}
                  onChange={(e) => setStyle(e.target.value as Style)}
                  disabled={locked || generating}
                  className="field w-auto py-1.5 text-[11px]"
                  aria-label="Description style"
                >
                  {(Object.keys(STYLE_LABEL) as Style[]).map((key) => (
                    <option key={key} value={key}>
                      {STYLE_LABEL[key]}
                    </option>
                  ))}
                </select>
                <button
                  onClick={regenerate}
                  disabled={locked || generating}
                  className="btn btn-ghost px-3 py-1.5 text-[11px]"
                >
                  {generating ? 'Generating…' : metadata ? 'Regenerate' : 'Generate'}
                </button>
              </div>
            </div>

            {metadata?.warning && (
              <p className="mt-3 rounded-[10px] border border-signal-warn/25 bg-signal-warn/[0.07] px-3 py-2 text-[11px] leading-relaxed text-ink-300">
                {metadata.warning}
              </p>
            )}
            {metadata && metadata.notes.length > 0 && (
              <ul className="mt-2 space-y-1 text-[10px] leading-relaxed text-ink-500">
                {metadata.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            )}
            {metadataError && (
              <div className="mt-3">
                <ErrorNote error={metadataError} onDismiss={() => setMetadataError(null)} />
              </div>
            )}

            {metadata && metadata.titles.length > 0 && (
              <div className="mt-5">
                <span className="eyebrow">Title options</span>
                <div className="mt-2 grid gap-2 sm:grid-cols-3">
                  {metadata.titles.map((option, index) => {
                    const active = option === title
                    return (
                      <button
                        key={`${option}-${index}`}
                        onClick={() => setTitle(option)}
                        disabled={locked}
                        className={[
                          'rounded-[10px] border p-3 text-left text-[12px] leading-snug transition-colors duration-200',
                          active
                            ? 'border-sodium-500/60 bg-sodium-500/[0.09] text-ink-100'
                            : 'border-white/10 bg-white/[0.025] text-ink-300 hover:border-white/25',
                        ].join(' ')}
                      >
                        {option}
                        {option === metadata.recommended_title && (
                          <span className="mt-1 block text-[9px] font-semibold uppercase tracking-[0.16em] text-sodium-400">
                            recommended
                          </span>
                        )}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            <label className="mt-5 block">
              <span className="eyebrow flex items-center justify-between">
                <span>Title</span>
                <span className={`numeric ${title.length > 100 ? 'text-signal-bad' : 'text-ink-600'}`}>
                  {title.length}/100
                </span>
              </span>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={120}
                disabled={locked}
                className="field mt-1.5 text-sm"
                placeholder="The moment in one line"
              />
            </label>

            <label className="mt-4 block">
              <span className="eyebrow flex items-center justify-between">
                <span>Description</span>
                <span className="numeric text-ink-600">{description.length}/5000</span>
              </span>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                maxLength={5000}
                rows={6}
                disabled={locked}
                className="field mt-1.5 resize-y text-sm leading-relaxed"
                placeholder="What happens in this clip"
              />
            </label>

            <div className="mt-4">
              <span className="eyebrow flex items-center justify-between">
                <span>Hashtags</span>
                <span className="numeric text-ink-600">{hashtags.length}/5</span>
              </span>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                {hashtags.map((tag) => (
                  <span key={tag} className="chip">
                    {tag}
                    {!locked && (
                      <button
                        onClick={() => setHashtags((current) => current.filter((item) => item !== tag))}
                        className="text-ink-500 hover:text-signal-bad"
                        aria-label={`Remove ${tag}`}
                      >
                        ×
                      </button>
                    )}
                  </span>
                ))}
                {!locked && hashtags.length < 5 && (
                  <input
                    value={hashtagDraft}
                    onChange={(e) => setHashtagDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ',' || e.key === ' ') {
                        e.preventDefault()
                        addHashtag()
                      }
                    }}
                    onBlur={addHashtag}
                    placeholder="add tag"
                    className="w-24 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-[11px] text-ink-100 outline-none focus:border-sodium-500/60"
                  />
                )}
              </div>
              {hashtags.length < 3 && (
                <p className="mt-1.5 text-[10px] text-ink-500">
                  Three to five hashtags is the useful range. #Shorts is not added automatically —
                  it is not a guarantee of the Shorts shelf.
                </p>
              )}
            </div>

            <label className="mt-4 block">
              <span className="eyebrow">Tags (optional)</span>
              <input
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                disabled={locked}
                className="field mt-1.5 text-sm"
                placeholder="comma, separated, tags"
              />
            </label>
          </section>

          <section className="glass p-5 sm:p-6">
            <p className="eyebrow">Visibility</p>
            <div className="mt-3 grid gap-2">
              {(Object.keys(PRIVACY_COPY) as Privacy[]).map((option) => (
                <button
                  key={option}
                  onClick={() => {
                    setPrivacy(option)
                    if (option !== 'public') setConfirmPublic(false)
                  }}
                  disabled={locked}
                  className={[
                    'rounded-[12px] border px-4 py-3 text-left transition-colors duration-200',
                    privacy === option
                      ? 'border-sodium-500/55 bg-sodium-500/[0.08]'
                      : 'border-white/10 bg-white/[0.02] hover:border-white/25',
                  ].join(' ')}
                >
                  <span className="flex items-center gap-2 text-[13px] font-semibold text-ink-100">
                    <span
                      className={`size-2 rounded-full ${privacy === option ? 'bg-sodium-500' : 'bg-ink-600'}`}
                    />
                    {PRIVACY_COPY[option].label}
                  </span>
                  <span className="mt-1 block pl-4 text-[11px] leading-relaxed text-ink-500">
                    {PRIVACY_COPY[option].note}
                  </span>
                </button>
              ))}
            </div>
          </section>

          {blocking.length > 0 && (
            <section className="rounded-[16px] border border-signal-bad/30 bg-signal-bad/[0.06] p-5">
              <p className="eyebrow text-signal-bad">This file cannot be published as-is</p>
              <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-ink-300">
                {blocking.map((check) => (
                  <li key={check.key}>
                    <span className="text-ink-100">{check.label}:</span> {check.detail}
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-[11px] leading-relaxed text-ink-400">
                AutoClip does not silently re-encode the file to make it pass. Go back to the clip,
                adjust the trim or ratio, and export again.
              </p>
            </section>
          )}

          <section className="glass p-5 sm:p-6">
            {locked ? (
              <p className="text-xs leading-relaxed text-ink-400">
                This export is already in the publish queue. Metadata cannot be changed while an
                upload is in flight; open the file in YouTube Studio to edit it after processing.
              </p>
            ) : (
              <>
                <label className="flex items-start gap-3 text-[12px] leading-relaxed text-ink-300">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                    className="mt-0.5 size-4 accent-sodium-500"
                  />
                  <span>
                    I have watched this file and checked the title, description, and visibility.
                  </span>
                </label>

                {privacy === 'public' && (
                  <label className="mt-3 flex items-start gap-3 rounded-[10px] border border-signal-warn/30 bg-signal-warn/[0.07] px-3 py-2.5 text-[12px] leading-relaxed text-ink-200">
                    <input
                      type="checkbox"
                      checked={confirmPublic}
                      onChange={(e) => setConfirmPublic(e.target.checked)}
                      className="mt-0.5 size-4 accent-sodium-500"
                    />
                    <span>
                      I understand this upload will be <strong>public immediately</strong>.
                    </span>
                  </label>
                )}

                {submitError && (
                  <div className="mt-3">
                    <ErrorNote error={submitError} onDismiss={() => setSubmitError(null)} />
                  </div>
                )}

                <button
                  onClick={() => void publish()}
                  disabled={!canPublish}
                  className="btn btn-primary mt-4 w-full"
                >
                  {submitting
                    ? 'Queueing…'
                    : privacy === 'private'
                      ? 'Upload as private'
                      : privacy === 'unlisted'
                        ? 'Upload as unlisted'
                        : 'Upload publicly'}
                </button>

                <p className="mt-2.5 text-center text-[10px] leading-relaxed text-ink-500">
                  {blocking.length > 0
                    ? 'Resolve the blocking checks above before uploading.'
                    : !confirmed
                      ? 'Confirm the review above to enable the upload.'
                      : !record.validation
                        ? 'The file check is still running.'
                        : 'The upload starts in the background and can be followed below.'}
                </p>
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}
