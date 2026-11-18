import type { ValidationReport } from '../api'

/**
 * Shorts readiness, shown as measurements rather than a verdict.
 *
 * The panel never says "ready" on its own authority — it lists what ffprobe
 * measured and what YouTube's rules are, so a blocked publish is explainable and
 * a warning can be judged instead of obeyed.
 */
export function ValidationPanel({
  report,
  compact = false,
}: {
  report: ValidationReport | null
  compact?: boolean
}) {
  if (report === null) {
    return (
      <p className="text-xs leading-relaxed text-ink-500">
        Checking the file against YouTube&apos;s Shorts requirements…
      </p>
    )
  }

  const ordered = [...report.checks].sort((a, b) => weight(a) - weight(b))
  const errors = report.errors.length
  const warnings = report.warnings.length

  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span
          className={`flex items-center gap-2 text-xs font-semibold ${
            errors > 0 ? 'text-signal-bad' : warnings > 0 ? 'text-signal-warn' : 'text-signal-good'
          }`}
        >
          <span className="status-dot" />
          {errors > 0
            ? `${errors} blocking ${errors === 1 ? 'issue' : 'issues'}`
            : warnings > 0
              ? `Ready to upload, ${warnings} ${warnings === 1 ? 'warning' : 'warnings'}`
              : 'Ready to upload'}
        </span>
        <span className="numeric text-[10px] text-ink-500">
          {report.width && report.height ? `${report.width}×${report.height}` : '—'}
          {report.fps ? ` · ${report.fps.toFixed(report.fps % 1 ? 2 : 0)} fps` : ''}
          {report.has_audio ? ' · audio' : ' · silent'}
        </span>
      </div>

      {!compact && (
        <ul className="mt-3 space-y-0.5">
          {ordered.map((check) => (
            <li
              key={check.key}
              className="grid grid-cols-[1.1rem_1fr] items-start gap-2 py-1.5 text-xs leading-relaxed"
            >
              <span
                className={
                  check.ok
                    ? 'text-signal-good'
                    : check.severity === 'error'
                      ? 'text-signal-bad'
                      : 'text-signal-warn'
                }
                aria-hidden
              >
                {check.ok ? '✓' : check.severity === 'error' ? '✕' : '!'}
              </span>
              <span>
                <span className={check.ok ? 'text-ink-300' : 'text-ink-100'}>{check.label}</span>
                <span className="text-ink-500"> — </span>
                <span className="text-ink-400">{check.detail}</span>
              </span>
            </li>
          ))}
        </ul>
      )}

      {compact && errors > 0 && (
        <ul className="mt-2 space-y-1 text-xs leading-relaxed">
          {report.errors.map((check) => (
            <li key={check.key} className="text-ink-400">
              <span className="text-ink-200">{check.label}:</span> {check.detail}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function weight(check: { ok: boolean; severity: string }): number {
  if (!check.ok) return check.severity === 'error' ? 0 : 1
  return 2
}
