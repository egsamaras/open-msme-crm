import type { Cam } from '@/lib/cam'
import { formatRatio } from '@/lib/format'

export type { Cam, CamSection } from '@/lib/cam'

const RATIO_ROWS: [string, string, (v: string | null) => string][] = [
  ['dscr_current', 'DSCR today', (v) => formatRatio(v)],
  ['dscr_pro_forma', 'DSCR with the new facility', (v) => formatRatio(v)],
  ['debt_to_ebitda_current', 'Debt / EBITDA today', (v) => formatRatio(v)],
  ['debt_to_ebitda_pro_forma', 'Debt / EBITDA pro forma', (v) => formatRatio(v)],
  ['current_ratio', 'Current ratio', (v) => formatRatio(v)],
  ['existing_utilization_pct', 'Existing lines drawn', (v) => (v ? `${Number(v).toFixed(1)}%` : 'n/a')],
  ['new_monthly_debt_service', 'New monthly debt service', (v) => (v ? Number(v).toLocaleString('en-US') : 'n/a')],
]

/** Computed figures behind a memo. Locked: the reviewer can edit prose, not numbers. */
export function CamRatios({ cam }: { cam: Pick<Cam, 'ratios' | 'assumptions'> }) {
  return (
    <div className="rounded-lg border border-slate-200">
      <table className="w-full text-sm">
        <caption className="border-b border-slate-200 bg-slate-50 px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
          Calculated by the system, not the model
        </caption>
        <tbody className="divide-y divide-slate-100">
          {RATIO_ROWS.map(([key, label, fmt]) => (
            <tr key={key}>
              <th scope="row" className="px-3 py-1.5 text-left font-normal text-slate-600">{label}</th>
              <td className="px-3 py-1.5 text-right tabular-nums">{fmt(cam.ratios[key] ?? null)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="border-t border-slate-100 px-3 py-2 text-xs text-slate-500">
        Assumes {cam.assumptions.rate_pct}% · {cam.assumptions.repayment} · EBITDA: {cam.assumptions.ebitda_basis}.
      </p>
    </div>
  )
}

export function CamView({ cam }: { cam: Cam }) {
  return (
    <div className="space-y-3">
      <CamRatios cam={cam} />
      {cam.sections.map((s) => (
        <details key={s.key} open={s.key === 'executive_summary'} className="rounded-lg border border-slate-200 px-3 py-2">
          <summary className="cursor-pointer font-medium">{s.title}</summary>
          <p className="mt-2 whitespace-pre-line text-slate-700">{s.body}</p>
        </details>
      ))}
    </div>
  )
}
