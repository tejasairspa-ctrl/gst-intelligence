/**
 * AnomalyPopup — modal shown after upload when any anomaly is detected.
 * Groups the flags into one summary (so N anomalies ≠ N popups) and links
 * through to the full Anomalies tab.
 */
import React from 'react'
import { AlertTriangle, X } from 'lucide-react'
import { AnomalyCard } from './AnomaliesPanel'

export default function AnomalyPopup({ data, onClose, onViewAll }) {
  if (!data || !data.has_anomalies) return null
  const sm = data.summary || {}
  const all = [...(data.mom || []), ...(data.yoy || [])]   // already severity-sorted per axis
  const order = { HIGH: 0, MEDIUM: 1, LOW: 2 }
  all.sort((a, b) => order[a.severity] - order[b.severity] || b.score - a.score)
  const top = all.slice(0, 6)
  const rest = all.length - top.length

  return (
    <div className="fixed inset-0 z-[300] flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative z-10 bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl w-[440px] max-w-[92vw] max-h-[85vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-2 p-4 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${sm.high > 0 ? 'bg-red-500/15' : 'bg-amber-500/15'}`}>
              <AlertTriangle className={`w-5 h-5 ${sm.high > 0 ? 'text-red-400' : 'text-amber-400'}`} />
            </div>
            <div>
              <p className="text-sm font-semibold text-white">
                {sm.total} unusual movement{sm.total > 1 ? 's' : ''} detected
              </p>
              <p className="text-[11px] text-slate-500">
                {sm.high > 0 && <span className="text-red-400 font-semibold">{sm.high} high</span>}
                {sm.high > 0 && (sm.medium > 0 || sm.low > 0) && ' · '}
                {sm.medium > 0 && <span className="text-amber-400 font-semibold">{sm.medium} medium</span>}
                {sm.low > 0 && <span className="text-slate-500">{(sm.high || sm.medium) ? ' · ' : ''}{sm.low} low</span>}
                {' · '}{(sm.mom_counts?.HIGH || 0) + (sm.mom_counts?.MEDIUM || 0) + (sm.mom_counts?.LOW || 0)} MOM
                {' · '}{(sm.yoy_counts?.HIGH || 0) + (sm.yoy_counts?.MEDIUM || 0) + (sm.yoy_counts?.LOW || 0)} YOY
              </p>
            </div>
          </div>
          <button onClick={onClose} className="text-slate-600 hover:text-slate-300 transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Top anomalies */}
        <div className="p-4 overflow-y-auto space-y-1.5">
          {top.map((a, i) => (
            <AnomalyCard key={`${a.metric}-${a.period}-${i}`} a={a} />
          ))}
          {rest > 0 && (
            <p className="text-[10px] text-slate-500 text-center pt-1">+ {rest} more in the Anomalies tab</p>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 p-3 border-t border-slate-800">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-[11px] text-slate-400 hover:text-slate-200 transition-colors"
          >
            Dismiss
          </button>
          <button
            onClick={onViewAll}
            className="px-3 py-1.5 text-[11px] font-semibold rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors"
          >
            View all anomalies
          </button>
        </div>
      </div>
    </div>
  )
}
