import React from 'react'
import { useApp } from '../context/AppContext'
import DashboardLayout from '../layouts/DashboardLayout'
import LandingChat from '../components/ChatInterface'

export default function Home() {
  const { hasDashboard } = useApp()

  // Once a file is uploaded → full 3-panel dashboard
  if (hasDashboard) {
    return <DashboardLayout />
  }

  // Before upload → centered landing
  return (
    <div className="min-h-screen bg-slate-950 flex flex-col">
      {/* Subtle gradient background */}
      <div
        className="fixed inset-0 pointer-events-none"
        style={{
          background:
            'radial-gradient(ellipse 80% 50% at 50% -20%, rgba(59,130,246,0.08), transparent)',
        }}
      />
      <div className="relative flex-1 flex flex-col">
        <LandingChat />
      </div>
    </div>
  )
}
