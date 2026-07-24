/**
 * ThemeToggle — switches the app between dark (default) and light mode.
 * Persists the choice in localStorage and sets data-theme on <html>, which the
 * light-mode override layer in index.css keys off. See main.jsx for the early
 * init that applies the saved theme before first paint (avoids a flash).
 */
import React, { useState } from 'react'
import { Sun, Moon } from 'lucide-react'

export function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme)
  try { localStorage.setItem('gst-theme', theme) } catch { /* ignore */ }
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState(
    () => document.documentElement.getAttribute('data-theme') || 'dark'
  )
  const toggle = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    applyTheme(next)
  }
  return (
    <button
      onClick={toggle}
      title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      className="w-7 h-7 flex items-center justify-center rounded-lg border border-slate-700
                 text-slate-400 hover:text-blue-400 hover:border-blue-500/40 transition-colors"
    >
      {theme === 'dark'
        ? <Sun className="w-3.5 h-3.5" />
        : <Moon className="w-3.5 h-3.5" />}
    </button>
  )
}
