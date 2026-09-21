import { HashRouter, Routes, Route } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import DiversityAnalytics from './pages/DiversityAnalytics'

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/diversity" element={<DiversityAnalytics />} />
      </Routes>
    </HashRouter>
  )
}
