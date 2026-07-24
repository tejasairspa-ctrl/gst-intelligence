import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'

// Apply the saved theme before first paint to avoid a flash of the wrong theme.
try {
  document.documentElement.setAttribute(
    'data-theme', localStorage.getItem('gst-theme') || 'dark'
  )
} catch { document.documentElement.setAttribute('data-theme', 'dark') }

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
)
