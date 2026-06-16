/**
 * ReconciliationPanel — Shows GSTR-1 vs GSTR-3B comparison results.
 */
import React from 'react'
import { CheckCircle2, AlertTriangle, MinusCircle, ArrowRight } from 'lucide-react'
import { useApp } from '../context/AppContext'

function fmt(value) {
  if (value === null || value === undefined) return '—'
  return `₹${Number(value).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function DiffBadge({ pct, flag }) {
  if (pct === null || pct === undefined) return <span className="text-slate-600 text-xs">—</span>
  const color = flag
    ? 'text-red-400 bg-red-500/10 border-red-500/30'
    : 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30'
  return (
    <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full border ${color}`}>
      {flag ? '⚠' : '✓'} {Number(pct).toFixed(2)}%
    </span>
  )
}

function ReconRow({ item }) {
  const { label, gstr1, gstr3b, difference, difference_pct, flag, note } = item
  return (
    <div className={`p-3 rounded-lg border ${
      flag
        ? 'bg-red-500/5 border-red-500/20'
        : 'bg-slate-900/40 border-slate-800/40'
    }`}>
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs font-medium text-slate-300">{label}</p>
        <DiffBadge pct={difference_pct} flag={flag} />
      </div>
      <div className="flex items-center gap-2 text-[10px]">
        <div className="flex-1 bg-slate-800/60 rounded p-1.5 text-center">
          <p className="text-slate-500 mb-0.5">GSTR-1</p>
          <p className={`font-mono font-medium ${gstr1 !== null ? 'text-blue-300' : 'text-slate-600'}`}>
            {fmt(gstr1)}
          </p>
        </div>
        <ArrowRight className="w-3 h-3 text-slate-600 flex-shrink-0" />
        <div className="flex-1 bg-slate-800/60 rounded p-1.5 text-center">
          <p className="text-slate-500 mb-0.5">GSTR-3B</p>
          <p className={`font-mono font-medium ${gstr3b !== null ? 'text-emerald-300' : 'text-slate-600'}`}>
            {fmt(gstr3b)}
          </p>
        </div>
      </div>
      {difference !== null && (
        <div className="mt-2 flex justify-between items-center">
          <p className="text-[10px] text-slate-500">Difference</p>
          <p className={`text-[10px] font-mono font-medium ${
            Math.abs(difference) < 1 ? 'text-slate-500' : flag ? 'text-red-400' : 'text-emerald-400'
          }`}>
            {difference >= 0 ? '+' : ''}{fmt(difference)}
          </p>
        </div>
      )}
      {note && flag && (
        <p className="text-[10px] text-red-400/80 mt-1 leading-tight">{note}</p>
      )}
    </div>
  )
}

export default function ReconciliationPanel({ reconciliation }) {
  if (!reconciliation) {
    return (
      <div className="text-center py-8 px-4">
        <MinusCircle className="w-8 h-8 text-slate-700 mx-auto mb-3" />
        <p className="text-sm text-slate-500 mb-2">No reconciliation data yet</p>
        <p className="text-[11px] text-slate-600 leading-relaxed">
          Upload both GSTR-1 and GSTR-3B for the same period — reconciliation will trigger automatically.
        </p>
      </div>
    )
  }

  const { available, items = [], flags = [], summary = {} } = reconciliation
  const status = summary.status || 'UNKNOWN'

  if (!available && flags.length > 0) {
    return (
      <div className="space-y-2 p-1">
        <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg">
          <p className="text-xs text-amber-400 font-medium mb-1">Status</p>
          {flags.map((f, i) => (
            <p key={i} className="text-[11px] text-amber-400/80 leading-relaxed">{f}</p>
          ))}
        </div>
      </div>
    )
  }

  const StatusIcon = status === 'RECONCILED' ? CheckCircle2 : AlertTriangle
  const statusColor = status === 'RECONCILED' ? 'text-emerald-400' : 'text-red-400'

  return (
    <div className="space-y-3">
      {/* Status summary */}
      <div className={`flex items-center gap-2 p-3 rounded-lg border ${
        status === 'RECONCILED'
          ? 'bg-emerald-500/10 border-emerald-500/20'
          : 'bg-red-500/10 border-red-500/20'
      }`}>
        <StatusIcon className={`w-4 h-4 flex-shrink-0 ${statusColor}`} />
        <div>
          <p className={`text-xs font-bold ${statusColor}`}>{status}</p>
          <p className="text-[10px] text-slate-500">
            {summary.flagged_items || 0} mismatch{(summary.flagged_items || 0) !== 1 ? 'es' : ''} out of {summary.total_items || 0} items
          </p>
        </div>
      </div>

      {/* Comparison items */}
      {items.length > 0 ? (
        <div className="space-y-2">
          {items.map((item, i) => (
            <ReconRow key={i} item={item} />
          ))}
        </div>
      ) : (
        <p className="text-xs text-slate-600 text-center py-4">No comparable data points</p>
      )}

      {/* Flags */}
      {flags.filter((f) => !f.startsWith('✅')).length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] text-slate-500 uppercase tracking-wider px-1">Audit Flags</p>
          {flags.map((f, i) => (
            <div key={i} className="flex gap-2 p-2.5 bg-red-500/8 border border-red-500/15 rounded-lg">
              <AlertTriangle className="w-3 h-3 text-red-400 flex-shrink-0 mt-0.5" />
              <p className="text-[10px] text-red-400/90 leading-relaxed">{f}</p>
            </div>
          ))}
        </div>
      )}

      {flags.filter((f) => f.startsWith('✅')).length > 0 && (
        <div className="p-2.5 bg-emerald-500/8 border border-emerald-500/15 rounded-lg">
          <p className="text-[10px] text-emerald-400 leading-relaxed">
            {flags.find((f) => f.startsWith('✅'))}
          </p>
        </div>
      )}

      <p className="text-[9px] text-slate-700 text-center">
        Threshold: 1% difference triggers a flag
      </p>
    </div>
  )
}
