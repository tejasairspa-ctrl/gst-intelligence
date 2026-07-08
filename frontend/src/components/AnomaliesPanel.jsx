/**
 * AnomaliesPanel — adaptive, peer-relative anomaly detection display.
 * Two axes: MOM (month-over-month) and YOY (year-over-year).
 * Each anomaly is judged against the metric's own normal behaviour; the flag
 * line is derived from how all metrics collectively responded this run.
 */
import React, { useEffect, useState } from 'react'
import {
  Activity, AlertTriangle, TrendingUp, TrendingDown,
  Plus, Minus, RefreshCw, ShieldCheck,
} from 'lucide-react'
import { getAnomalies } from '../api/client'

const SEV = {
  HIGH:   { bg: 'bg-red-500/10',     border: 'border-red-500/30',     text: 'text-red-400',     dot: 'bg-red-400' },
  MEDIUM: { bg: 'bg-amber-500/10',   border: 'border-amber-500/30',   text: 'text-amber-400',   dot: 'bg-amber-400' },
  LOW:    { bg: 'bg-slate-700/20',   border: 'border-slate-600/40',   text: 'text-slate-400',   dot: 'bg-slate-500' },
}

function fmtVal(v, unit) {
  if (v === null || v === undefined) return '—'
  if (unit === '%') return `${v}%`
  const a = Math.abs(v)
  if (a >= 1_00_00_000) return `₹${(v / 1_00_00_000).toFixed(2)} Cr`
  if (a >= 1_00_000)    return `₹${(v / 1_00_000).toFixed(2)} L`
  if (a >= 1_000)       return `₹${(v / 1_000).toFixed(1)} K`
  return `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

function DirIcon({ direction }) {
  if (direction === 'increase' || direction === 'appeared')
    return <TrendingUp className="w-3 h-3 text-red-400" />
  if (direction === 'decrease' || direction === 'ceased')
    return <TrendingDown className="w-3 h-3 text-amber-400" />
  return <Minus className="w-3 h-3 text-slate-500" />
}

export function AnomalyCard({ a, expandedView = false }) {
  const s = SEV[a.severity] || SEV.LOW
  const txt = expandedView ? 'text-[11px]' : 'text-[10px]'
  return (
    <div className={`rounded-lg border px-3 py-2 ${s.bg} ${s.border}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <DirIcon direction={a.direction} />
          <span className={`font-medium text-slate-200 truncate ${expandedView ? 'text-xs' : 'text-[11px]'}`}>
            {a.metric.replace('[ratio] ', '')}
          </span>
          {a.kind === 'ratio' && (
            <span className="text-[8px] px-1 rounded bg-slate-700/50 text-slate-400 flex-shrink-0">ratio</span>
          )}
        </div>
        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[8px] font-bold uppercase tracking-wider border flex-shrink-0 ${s.bg} ${s.border} ${s.text}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />{a.severity}
        </span>
      </div>
      <div className="flex items-center gap-2 mt-1">
        <span className="text-[9px] text-slate-500">{a.period}</span>
        <span className={`font-mono font-bold ${s.text} ${txt}`}>{fmtVal(a.value, a.unit)}</span>
        {a.deviation_pct !== null && a.deviation_pct !== undefined && (
          <span className={`font-mono ${a.deviation_pct >= 0 ? 'text-red-300' : 'text-amber-300'} ${txt}`}>
            {a.deviation_pct >= 0 ? '+' : ''}{a.deviation_pct}%
          </span>
        )}
        <span className="text-[9px] text-slate-600">vs ~{fmtVal(a.baseline, a.unit)}</span>
      </div>
      <p className={`text-slate-400 leading-snug mt-1 ${txt}`}>{a.reason}</p>
    </div>
  )
}

function AxisSection({ title, items, expandedView }) {
  if (!items || items.length === 0) return null
  return (
    <div className="mb-4">
      <p className={`section-label mb-2 ${expandedView ? 'text-xs' : ''}`}>{title} · {items.length}</p>
      <div className={expandedView ? 'grid grid-cols-2 gap-2' : 'space-y-1.5'}>
        {items.map((a, i) => <AnomalyCard key={`${a.metric}-${a.period}-${i}`} a={a} expandedView={expandedView} />)}
      </div>
    </div>
  )
}

export default function AnomaliesPanel({ uploadedFiles = [], expanded: expandedView = false }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [axis, setAxis]       = useState('all')   // all | mom | yoy

  const load = async () => {
    setLoading(true); setError(null)
    try {
      const { data: res } = await getAnomalies()
      setData(res)
    } catch (e) {
      setError('Failed to load anomalies')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { if (uploadedFiles.length > 0) load() }, [uploadedFiles.length])

  if (loading) return (
    <div className="flex items-center gap-2 py-6 justify-center text-slate-600 text-xs">
      <RefreshCw className="w-4 h-4 animate-spin" /> Scanning for anomalies…
    </div>
  )
  if (error) return (
    <div className="py-6 text-center text-xs text-red-400">
      {error}<button onClick={load} className="ml-2 underline">retry</button>
    </div>
  )
  if (!data || !data.available) return (
    <div className="flex flex-col items-center py-8 text-slate-700 text-xs gap-2">
      <Activity className="w-8 h-8 opacity-30" /> Upload GSTR files to scan for anomalies
    </div>
  )

  const sm = data.summary || {}
  const mom = data.mom || []
  const yoy = data.yoy || []
  const show = axis === 'mom' ? { mom, yoy: [] } : axis === 'yoy' ? { mom: [], yoy } : { mom, yoy }

  if (!data.has_anomalies) return (
    <div className="flex flex-col items-center py-8 text-slate-500 text-xs gap-2">
      <ShieldCheck className="w-8 h-8 text-emerald-500/60" />
      No unusual movements detected — every figure and ratio is within its normal band.
      <button onClick={load} className="mt-1 text-slate-600 hover:text-slate-400 underline text-[10px]">rescan</button>
    </div>
  )

  return (
    <div>
      {/* Summary strip */}
      <div className="flex items-center gap-2 mb-3 px-2 py-1.5 rounded-lg bg-slate-900/60 border border-slate-800">
        <AlertTriangle className={`w-3.5 h-3.5 flex-shrink-0 ${sm.high > 0 ? 'text-red-400' : sm.medium > 0 ? 'text-amber-400' : 'text-slate-500'}`} />
        <p className="text-[10px] text-slate-400">
          <span className="font-semibold text-white">{sm.total}</span> anomalies ·{' '}
          {sm.high > 0 && <span className="text-red-400 font-semibold">{sm.high} HIGH</span>}
          {sm.high > 0 && sm.medium > 0 && ' · '}
          {sm.medium > 0 && <span className="text-amber-400 font-semibold">{sm.medium} MED</span>}
          {sm.low > 0 && <span className="text-slate-500"> · {sm.low} low</span>}
        </p>
        <button onClick={load} className="ml-auto text-slate-600 hover:text-slate-400 transition-colors" title="Rescan">
          <RefreshCw className="w-3 h-3" />
        </button>
      </div>

      {/* Axis switcher */}
      <div className="flex gap-1 mb-3 bg-slate-900 border border-slate-800 rounded-lg p-0.5">
        {[['all', `All (${sm.total})`], ['mom', `MOM (${mom.length})`], ['yoy', `YOY (${yoy.length})`]].map(([id, label]) => (
          <button
            key={id}
            onClick={() => setAxis(id)}
            className={`flex-1 py-1 text-[10px] font-semibold rounded-md transition-all ${
              axis === id ? 'bg-slate-700 text-white' : 'text-slate-500 hover:text-slate-300'}`}
          >
            {label}
          </button>
        ))}
      </div>

      <AxisSection title="Month-over-Month"   items={show.mom} expandedView={expandedView} />
      <AxisSection title="Year-over-Year"      items={show.yoy} expandedView={expandedView} />

      <p className="text-[9px] text-slate-700 text-center pt-2 mt-2 border-t border-slate-800/40 leading-relaxed">
        Adaptive detection — each figure & ratio judged against its own normal spread;
        the flag line is set by how all metrics moved this run (no fixed % threshold).
      </p>
    </div>
  )
}
