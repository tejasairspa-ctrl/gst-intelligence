import React from 'react'
import { Routes, Route } from 'react-router-dom'
import { AppProvider } from './context/AppContext'
import Home from './pages/Home'
import FullReport from './pages/FullReport'

export default function App() {
  return (
    <AppProvider>
      <Routes>
        <Route path="/"       element={<Home />} />
        <Route path="/report" element={<FullReport />} />
      </Routes>
    </AppProvider>
  )
}
