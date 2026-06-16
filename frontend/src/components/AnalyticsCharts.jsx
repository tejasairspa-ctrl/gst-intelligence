import React from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts'

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']

const INR = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })
const fmtINR = (v) => `₹${INR.format(v)}`
const fmtShort = (v) => {
  if (v >= 10000000) return `₹${(v / 10000000).toFixed(1)}Cr`
  if (v >= 100000)   return `₹${(v / 100000).toFixed(1)}L`
  if (v >= 1000)     return `₹${(v / 1000).toFixed(1)}K`
  return `₹${v}`
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div className="glass-card px-3 py-2 text-xs shadow-xl">
      <p className="text-slate-400 mb-1">{label || payload[0]?.name}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color }} className="font-semibold">
          {fmtINR(p.value)}
        </p>
      ))}
    </div>
  )
}

export function TaxDistributionChart({ data }) {
  if (!data || data.length === 0) {
    return <EmptyChart label="Tax Distribution" />
  }
  return (
    <ChartWrapper title="Tax Distribution">
      <ResponsiveContainer width="100%" height={160}>
        <BarChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
          <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
          <YAxis tickFormatter={fmtShort} tick={{ fontSize: 9, fill: '#64748b' }} axisLine={false} tickLine={false} width={40} />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Bar dataKey="value" radius={[4, 4, 0, 0]}>
            {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartWrapper>
  )
}

export function ITCChart({ data }) {
  if (!data || data.length === 0) {
    return <EmptyChart label="ITC Analysis" />
  }
  return (
    <ChartWrapper title="ITC Breakdown">
      <ResponsiveContainer width="100%" height={160}>
        <BarChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
          <XAxis dataKey="label" tick={{ fontSize: 9, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
          <YAxis tickFormatter={fmtShort} tick={{ fontSize: 9, fill: '#64748b' }} axisLine={false} tickLine={false} width={40} />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Bar dataKey="value" radius={[4, 4, 0, 0]}>
            {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartWrapper>
  )
}

export function SalesBreakdownChart({ data }) {
  if (!data || data.length === 0) {
    return <EmptyChart label="Sales Breakdown" />
  }
  return (
    <ChartWrapper title="Sales Breakdown">
      <ResponsiveContainer width="100%" height={160}>
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="label"
            cx="50%"
            cy="50%"
            innerRadius={40}
            outerRadius={65}
            paddingAngle={2}
          >
            {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
          </Pie>
          <Tooltip content={<CustomTooltip />} />
          <Legend
            formatter={(v) => <span className="text-[10px] text-slate-400">{v}</span>}
            iconSize={8}
          />
        </PieChart>
      </ResponsiveContainer>
    </ChartWrapper>
  )
}

function ChartWrapper({ title, children }) {
  return (
    <div className="glass-card p-3">
      <p className="text-xs font-semibold text-slate-400 mb-2">{title}</p>
      {children}
    </div>
  )
}

function EmptyChart({ label }) {
  return (
    <div className="glass-card p-3 flex items-center justify-center h-28">
      <p className="text-xs text-slate-700">{label} — data not available</p>
    </div>
  )
}
