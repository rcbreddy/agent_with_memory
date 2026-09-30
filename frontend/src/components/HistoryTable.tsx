import type { IncidentSummary } from '../services/api'
import { severityTone } from './styles'
import { Badge, Card } from './ui'

const COLUMNS = ['Incident', 'Service', 'Severity', 'Environment', 'Date', 'Root cause', 'Outcome', 'Memory']

export default function HistoryTable({ incidents }: { incidents: IncidentSummary[] }) {
  const retained = incidents.filter((i) => i.retained_in_hindsight).length
  return (
    <Card
      title="Incident History"
      icon={<span className="text-slate-400">≡</span>}
      right={<span className="text-xs text-slate-400">{retained} of {incidents.length} confirmed in Hindsight</span>}
    >
      {incidents.length === 0 ? (
        <p className="text-sm text-slate-400">No incidents yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Your incidents, newest first, and whether each confirmed resolution is stored in Hindsight</caption>
            <thead className="text-[11px] uppercase tracking-wider text-slate-400">
              <tr>
                {COLUMNS.map((h) => (
                  <th key={h} scope="col" className="px-3 py-2 font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {incidents.map((i) => (
                <tr key={i.id} className="align-top">
                  <th scope="row" className="px-3 py-2 text-left font-normal">
                    <div className="font-medium text-white">{i.title}</div>
                    <div className="text-xs text-slate-400">{i.id}</div>
                  </th>
                  <td className="px-3 py-2 font-mono text-xs">{i.service}</td>
                  <td className="px-3 py-2"><Badge tone={severityTone(i.severity)}>{i.severity}</Badge></td>
                  <td className="px-3 py-2">{i.environment}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-300">{new Date(i.created_at).toLocaleString()}</td>
                  <td className="px-3 py-2 text-slate-200">{i.root_cause ?? <span className="text-slate-400">—</span>}</td>
                  <td className="px-3 py-2 text-slate-200">{i.outcome ?? <span className="text-slate-400">—</span>}</td>
                  <td className="px-3 py-2">
                    {i.retained_in_hindsight ? <Badge tone="green">✓ Confirmed</Badge> : <Badge>Open</Badge>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
