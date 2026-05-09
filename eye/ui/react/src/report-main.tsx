import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import ReportBuilderPanel from './ReportBuilderPanel'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ReportBuilderPanel />
  </StrictMode>,
)
