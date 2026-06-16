import React from 'react'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'

function fmt(value, unit) {
  if (value === null || value === undefined) return null
  if (unit === '₹') return `₹${Number(value).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  if (unit === '%') return `${Number(value).toFixed(2)}%`
  if (unit === 'x') return `${Number(value).toFixed(2)}x`
  return String(value)
}

export default function KPICard({ kpi, compact = false }) {
  const { label, value, unit = '₹', available } = kpi
  const formatted = fmt(value, unit)

  const isLarge = value !== null && value !== undefined && Math.abs(value) >= 100000
  const displayVal = available && formatted
    ? formatted
    : null

  return (
    <div className={`kpi-card ${compact ? 'p-3' : 'p-4'}`}>
      <p className={`text-slate-500 font-medium leading-tight ${compact ? 'text-[10px]' : 'text-xs'}`}>
        {label}
      </p>
      {displayVal ? (
        <p className={`font-bold text-white mt-1 leading-none ${
          compact ? 'text-base' : 'text-xl'
        } ${unit === '₹' ? 'font-mono' : ''}`}>
          {displayVal}
        </p>
      ) : (
        <p className={`value-na mt-1 ${compact ? 'text-[10px]' : 'text-xs'}`}>
          Not in document
        </p>
      )}
    </div>
  )
}

export function KPIGrid({ kpis, compact = false }) {
  if (!kpis || kpis.length === 0) return null
  return (
    <div className={`grid gap-2 ${compact ? 'grid-cols-2' : 'grid-cols-2'}`}>
      {kpis.map((k) => (
        <KPICard key={k.label} kpi={k} compact={compact} />
      ))}
    </div>
  )
}
