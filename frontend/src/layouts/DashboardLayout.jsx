import React from 'react'
import LeftPanel from '../components/LeftPanel'
import MainDashboard from '../components/MainDashboard'
import RightPanel from '../components/RightPanel'
import ExpandedView from '../components/ExpandedView'

export default function DashboardLayout() {
  return (
    <div className="flex h-screen overflow-hidden bg-slate-950 relative">
      {/* Left panel — 220px fixed */}
      <div className="w-[220px] flex-shrink-0 h-full overflow-hidden">
        <LeftPanel />
      </div>

      {/* Center — dashboard — flexible */}
      <div className="flex-1 flex flex-col h-full min-w-0 border-x border-slate-800/40">
        <MainDashboard />
      </div>

      {/* Right panel — 290px fixed */}
      <div className="w-[290px] flex-shrink-0 h-full overflow-hidden">
        <RightPanel />
      </div>

      {/* Expanded view overlay (double-click) — rendered on top */}
      <ExpandedView />
    </div>
  )
}
