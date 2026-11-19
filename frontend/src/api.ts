/**
 * Typed client for the AutoClip API.
 *
 * Same-origin throughout: the server hands out the built bundle, so there is no
 * base URL to configure and no CORS to negotiate.
 */

export interface Source {
  id: string
  type: string
  title: string
  url: string | null
  filename: string | null
  channel: string | null
  duration_s: number
  width: number | null
  height: number | null
  fps: number | null
  has_audio: boolean
  has_video: boolean
  created_at: string
}

export type JobStatus = 'queued' | 'running' | 'failed' | 'done' | 'cancelled'

export interface Job {
  id: string
  source_id: string
  status: JobStatus
  current_stage: string
  progress: number
  error: string | null
  provider: string
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
  source: Source | null
}

export interface ExportRecord {
  id: string
  clip_id: string
  ratio: string
  style: string
  size_bytes: number
  created_at: string
  download_url: string
}

export type ClipStatus = 'candidate' | 'kept' | 'discarded' | 'exported'

export interface Clip {
  id: string
  job_id: string
  rank: number
  start_s: number
  end_s: number
  duration_s: number
  start_word: number
  end_word: number
  title: string
  hook: string
  score: number
  reason: string
  status: ClipStatus
  user_trimmed: boolean
  caption_style: string
  ratio: string
  caption_scale: number
  exports: ExportRecord[]
}

export interface Word {
  text: string
  start: number
  end: number
  speaker: string | null
}

export interface CropKeyframe {
  t: number
  x: number
  y: number
}

export interface CropSegment {
  start_s: number
  end_s: number
  width: number
  height: number
  keyframes: CropKeyframe[]
  strategy: 'track' | 'wide' | 'general'
  zoom: number
  fit: boolean
}

/** Mirrors autoclip.pipeline.reframe.croppath.CropPath. */
export interface CropPath {
  source_width: number
  source_height: number
  segments: CropSegment[]
}

export interface CaptionStyle {
  key: string
  label: string
  description: string
  preview: {
    font: string
    primary: string
    accent: string | null
    outline: string
    outlineWidth: number
    allCaps: boolean
    sizeRatio: number
    marginRatio: number
    boxed: boolean
    animation: string
    maxWords: number
  }
}

export interface ProviderStatus {
  name: string
  available: boolean
  detail: string
  models: string[]
  requires_key: boolean
  has_key: boolean
}

export interface Settings {
  active_provider: string
  providers: Record<string, { model: string; base_url: string | null }>
  whisper: { model: string; compute_type: string; language: string; diarization: boolean }
  clips: { min_duration_s: number; max_duration_s: number; max_clips: number }
  ingest: {
    ytdlp_format: string
    cookies_from_browser: string
    prefer_youtube_captions: boolean
  }
  export: {
    ratio: string
    caption_style: string
    loudness_lufs: number
    prefer_hardware_encoder: boolean
    crf: number
    write_srt: boolean
  }
  publish: {
    default_privacy: 'private' | 'unlisted' | 'public'
    description_style: 'concise' | 'story' | 'educational'
    default_hashtags: string
    default_tags: string
    hashtags_in_description: boolean
  }
  insecure_secret_storage: boolean
  keys_present: Record<string, boolean>
}

export interface SystemStatus {
  ready: boolean
  python_version: string
  platform: string
  ffmpeg_version: string | null
  has_libass: boolean
  nvenc_works: boolean
  videotoolbox_works: boolean
  accel: string
  gpu_name: string | null
  compute_type: string
  diarization_available: boolean
}

export type EngineState = 'stopped' | 'starting' | 'running' | 'stopping' | 'error'

export interface EngineStatus {
  state: EngineState
  error: string | null
  model: string
  model_loaded: string | null
  started_at: string | null
  active_job_id: string | null
  queued: number
  ffmpeg_version: string | null
  ready: boolean
}

export type PublishStatus = 'pending' | 'uploading' | 'processing' | 'published' | 'failed'
export type Privacy = 'private' | 'unlisted' | 'public'

export interface PublishRecord {
  id: string
  export_id: string
  title: string
  description: string
  hashtags: string[]
  tags: string[]
  privacy: Privacy
  status: PublishStatus
  progress: number
  video_id: string | null
  url: string | null
  error: string | null
  attempts: number
  created_at: string
  updated_at: string
  published_at: string | null
  thumbnail_url: string | null
  download_url: string | null
}

export interface ValidationCheck {
  key: string
  label: string
  ok: boolean
  severity: 'error' | 'warn' | 'info'
  detail: string
}

export interface ValidationReport {
  ok: boolean
  duration_s: number
  width: number | null
  height: number | null
  fps: number | null
  has_audio: boolean
  video_codec: string | null
  frozen_opening_s: number
  checks: ValidationCheck[]
  errors: ValidationCheck[]
  warnings: ValidationCheck[]
}

export interface ExportDetail {
  id: string
  clip_id: string
  job_id: string | null
  title: string
  hook: string
  filename: string
  duration_s: number
  ratio: string
  style: string
  size_bytes: number
  created_at: string
  download_url: string
  thumbnail_url: string
  preview_url: string
  publish: PublishRecord | null
  validation: ValidationReport | null
}

export interface GeneratedMetadata {
  titles: string[]
  recommended_title: string
  description: string
  hashtags: string[]
  tags: string[]
  generated_by: string
  warning: string
  notes: string[]
}

export interface PublishingStatus {
  configured: boolean
  connected: boolean
  redirect_uri: string
  client_project: string
  client_source: string
  configured_redirect_uris: string[]
  scopes: string[]
  expires_at: number | null
  has_refresh_token: boolean
  warnings: string[]
  detail: string
  hint: string
  export_directory: string
  analytics_scope: boolean
}

export interface InstagramStatus {
  configured: boolean
  missing: string[]
  public_url_ok: boolean
  account_id: string
  public_base_url: string
  account: {
    username?: string
    name?: string
    followers?: number
    media?: number
  }
}

export interface InstagramPublishRecord {
  id: string
  export_id: string
  caption: string
  status: 'pending' | 'processing' | 'published' | 'failed'
  container_id: string | null
  media_id: string | null
  url: string | null
  error: string | null
  created_at: string
  updated_at: string
  published_at: string | null
}

export interface PublishedVideo {
  job_id: string
  export_id: string
  video_id: string
  title: string
  url: string
  published_at: string | null
  views: number
  likes: number
  comments: number
  privacy: string
}

export interface PublishingAnalytics {
  videos: PublishedVideo[]
  totals: Record<string, number>
}

export interface PublishDraft {
  title: string
  description: string
  hashtags: string[]
  tags: string[]
  privacy: Privacy
  confirm: boolean
  confirm_public: boolean
}

export interface JobSettingsOverrides {
  provider?: string
  whisper_model?: string
  language?: string
  diarization?: boolean
  min_duration_s?: number
  max_duration_s?: number
  max_clips?: number
  caption_style?: string
  ratio?: string
}

/** An API error carrying the server's message and its actionable hint. */
export class ApiError extends Error {
  hint: string
  status: number

  constructor(message: string, status: number, hint = '') {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.hint = hint
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init?.headers,
    },
  })

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    let hint = ''
    try {
      const body = await response.json()
      const detail = body.detail
      if (typeof detail === 'string') {
        message = detail
      } else if (detail && typeof detail === 'object') {
        // The ingest endpoints return {message, hint} so the UI can show the
        // fix alongside the failure.
        message = detail.message ?? message
        hint = detail.hint ?? ''
      }
    } catch {
      /* Response had no JSON body; the status line is the best we have. */
    }
    throw new ApiError(message, response.status, hint)
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<{ status: string; version: string }>('/api/health'),
  system: () => request<SystemStatus>('/api/system'),
  fetchModels: () => request<void>('/api/system/models', { method: 'POST' }),

  listSources: () => request<Source[]>('/api/sources'),

  ingestYouTube: (url: string, cookiesFromBrowser?: string) =>
    request<Source>('/api/sources/youtube', {
      method: 'POST',
      body: JSON.stringify({ url, cookies_from_browser: cookiesFromBrowser || null }),
    }),

  uploadSource: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<Source>('/api/sources/upload', { method: 'POST', body: form })
  },

  listJobs: (limit = 25) => request<Job[]>(`/api/jobs?limit=${limit}`),
  getJob: (id: string) => request<Job>(`/api/jobs/${id}`),

  createJob: (sourceId: string, settings: JobSettingsOverrides = {}) =>
    request<Job>('/api/jobs', {
      method: 'POST',
      body: JSON.stringify({ source_id: sourceId, settings }),
    }),

  cancelJob: (id: string) => request<Job>(`/api/jobs/${id}/cancel`, { method: 'POST' }),
  retryJob: (id: string) => request<Job>(`/api/jobs/${id}/retry`, { method: 'POST' }),

  listClips: (jobId: string) => request<Clip[]>(`/api/jobs/${jobId}/clips`),
  getClip: (clipId: string) => request<Clip>(`/api/clips/${clipId}`),
  createManualClip: (jobId: string, startS: number, endS: number, title: string) =>
    request<Clip>(`/api/jobs/${jobId}/clips`, {
      method: 'POST',
      body: JSON.stringify({ start_s: startS, end_s: endS, title }),
    }),

  getCropPath: (clipId: string) => request<CropPath>(`/api/clips/${clipId}/crop-path`),
  getClipWords: (clipId: string) => request<Word[]>(`/api/clips/${clipId}/words`),

  patchClip: (
    clipId: string,
    patch: { start_s?: number; end_s?: number; title?: string; status?: ClipStatus },
  ) => request<Clip>(`/api/clips/${clipId}`, { method: 'PATCH', body: JSON.stringify(patch) }),

  patchCaptions: (
    clipId: string,
    patch: { words?: Word[]; caption_style?: string; ratio?: string; caption_scale?: number },
  ) =>
    request<Clip>(`/api/clips/${clipId}/captions`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  exportClip: (
    clipId: string,
    ratio: string,
    style: string,
    captionScale = 1,
    writeSrt = false,
  ) =>
    request<ExportRecord>(`/api/clips/${clipId}/export`, {
      method: 'POST',
      body: JSON.stringify({
        ratio,
        style,
        caption_scale: captionScale,
        write_srt: writeSrt,
      }),
    }),

  captionStyles: () => request<CaptionStyle[]>('/api/caption-styles'),
  providerStatus: () => request<ProviderStatus[]>('/api/providers/status'),

  engineStatus: () => request<EngineStatus>('/api/engine'),
  startEngine: () => request<EngineStatus>('/api/engine/start', { method: 'POST' }),
  stopEngine: (force = false) =>
    request<EngineStatus>('/api/engine/stop', {
      method: 'POST',
      body: JSON.stringify({ force }),
    }),

  listExports: (limit = 100) => request<ExportDetail[]>(`/api/exports?limit=${limit}`),
  deleteExport: (exportId: string) =>
    request<void>(`/api/exports/${exportId}`, { method: 'DELETE' }),
  getExport: (exportId: string, validate = true) =>
    request<ExportDetail>(`/api/exports/${exportId}?validate=${validate}`),

  generateMetadata: (
    exportId: string,
    body: { style?: string; extra_context?: string } = {},
  ) =>
    request<GeneratedMetadata>(`/api/exports/${exportId}/metadata`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  publishExport: (exportId: string, draft: PublishDraft) =>
    request<PublishRecord>(`/api/exports/${exportId}/publish`, {
      method: 'POST',
      body: JSON.stringify(draft),
    }),

  publishingStatus: () => request<PublishingStatus>('/api/publishing/status'),
  startYouTubeAuth: () =>
    request<{ auth_url: string; redirect_uri: string; state: string }>(
      '/api/publishing/auth/start',
      { method: 'POST' },
    ),
  disconnectYouTube: () =>
    request<void>('/api/publishing/auth/disconnect', { method: 'POST' }),
  publishingQueue: (limit = 100) =>
    request<PublishRecord[]>(`/api/publishing/queue?limit=${limit}`),
  publishingAnalytics: () =>
    request<PublishingAnalytics>('/api/publishing/analytics'),
  instagramStatus: () =>
    request<InstagramStatus>('/api/instagram/status'),
  instagramJobs: () =>
    request<InstagramPublishRecord[]>('/api/instagram/jobs'),
  publishInstagram: (exportId: string, caption: string, confirm: boolean) =>
    request<InstagramPublishRecord>(`/api/instagram/exports/${exportId}/publish`, {
      method: 'POST',
      body: JSON.stringify({ caption, confirm }),
    }),
  retryPublish: (jobId: string) =>
    request<PublishRecord>(`/api/publishing/queue/${jobId}/retry`, { method: 'POST' }),

  exportThumbnailUrl: (exportId: string) => `/api/exports/${exportId}/thumbnail`,

  getSettings: () => request<Settings>('/api/settings'),
  putSettings: (patch: Partial<Settings>) =>
    request<Settings>('/api/settings', { method: 'PUT', body: JSON.stringify(patch) }),

  putSecret: (key: string, value: string) =>
    request<void>('/api/settings/secrets', {
      method: 'PUT',
      body: JSON.stringify({ key, value }),
    }),

  deleteSecret: (key: string) =>
    request<void>(`/api/settings/secrets/${key}`, { method: 'DELETE' }),

  mediaUrl: (jobId: string) => `/api/jobs/${jobId}/media`,
}

/** Format seconds as m:ss, or h:mm:ss past an hour. */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  const s = total % 60
  const m = Math.floor(total / 60) % 60
  const h = Math.floor(total / 3600)
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
}

/** Format seconds as timecode with centiseconds, for trim handles. */
export function formatTimecode(seconds: number): string {
  const total = Math.max(0, seconds)
  const cs = Math.floor((total % 1) * 100)
  const s = Math.floor(total) % 60
  const m = Math.floor(total / 60)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(m)}:${pad(s)}.${pad(cs)}`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`
}
