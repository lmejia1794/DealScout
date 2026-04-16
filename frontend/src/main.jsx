import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import App from './App.jsx'
import ReportView from './components/ReportView.jsx'
import './index.css'
import { SettingsProvider } from './components/SettingsContext.jsx'
import { PipelineProvider } from './components/PipelineContext.jsx'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <SettingsProvider>
      <PipelineProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<App />} />
            <Route path="/report" element={<ReportView />} />
          </Routes>
        </BrowserRouter>
      </PipelineProvider>
    </SettingsProvider>
  </React.StrictMode>
)
