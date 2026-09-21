import { useState, useEffect } from 'react'
import { apiFetch } from '../api'
import Navbar from '../components/Navbar'
import MapView from '../components/MapView'
import SidePanel from '../components/SidePanel'
import DetailCard from '../components/DetailCard'
import DeviceDetail from '../components/DeviceDetail'
import SpeciesDetail from '../components/SpeciesDetail'

const POLL_MS = 5000

export default function Dashboard() {
  const [apiOnline, setApiOnline] = useState(false)
  const [devices, setDevices] = useState([])
  const [detections, setDetections] = useState([])
  const [species, setSpecies] = useState([])
  const [metrics, setMetrics] = useState({})
  const [activityData, setActivityData] = useState(null)
  const [simTime, setSimTime] = useState(null)
  
  const [selectedDevice, setSelectedDevice] = useState(null)
  const [selectedSpecies, setSelectedSpecies] = useState(null)

  useEffect(() => {
    let mounted = true
    const fetchData = async () => {
      try {
        const [devs, dets, sps, actCurve, div, today] = await Promise.all([
          apiFetch('/api/devices'),
          apiFetch('/api/detections?limit=200'),
          apiFetch('/api/species'),
          apiFetch('/api/analytics/activity-curve'),
          apiFetch('/api/analytics/diversity'),
          apiFetch('/api/detections/today'),
        ])

        if (!mounted) return
        setApiOnline(true)

        // mock registration
        const knownIds = new Set(devs.map(d => d.id))
        const newIds = [...new Set(dets.map(d => d.device_id).filter(id => !knownIds.has(id)))]
        let updatedDevs = devs
        if (newIds.length) {
          await Promise.all(newIds.map(id => fetch(`${window.location.origin}/api/devices`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id, site_name: id, lat: 13.08 + Math.random() * 0.1, lng: 77.58 + Math.random() * 0.1, battery_pct: 100 })
          })))
          updatedDevs = await apiFetch('/api/devices')
        }

        const detCount = {}
        dets.forEach(dt => detCount[dt.device_id] = (detCount[dt.device_id] || 0) + 1)
        const normDevices = updatedDevs.map(d => ({ ...d, count: detCount[d.id] || 0 }))

        setDevices(normDevices)
        setDetections(dets)
        setSpecies(sps)
        setActivityData(actCurve?.mean_detections)

        // Keep selected entities updated with fresh data
        setSelectedDevice(prev => prev ? normDevices.find(d => d.id === prev.id) || prev : null)
        setSelectedSpecies(prev => prev ? sps.find(s => s.name === prev.name || s.name === prev.species) || prev : null)
        
        if (dets && dets.length > 0) {
          setSimTime(new Date(dets[0].timestamp).getTime())
        }

        const online = normDevices.filter(d => d.status === 'online').length
        setMetrics({
          shannon: div?.shannon_index != null ? Number(div.shannon_index).toFixed(2) : '—',
          richness: div?.species_richness ?? '—',
          detections: today?.count ?? '—',
          nodes: `${online}/${normDevices.length}`
        })
      } catch (err) {
        if (mounted) setApiOnline(false)
      }
    }

    fetchData()
    const timer = setInterval(fetchData, POLL_MS)
    return () => { mounted = false; clearInterval(timer) }
  }, [])

  return (
    <>
      <MapView devices={devices} detections={detections} onDeviceClick={(d) => { setSelectedDevice(d); setSelectedSpecies(null) }} />
      <div id="ui-layer">
        <Navbar metrics={metrics} apiOnline={apiOnline} simulationTime={simTime} />
        <SidePanel 
          devices={devices} 
          species={species} 
          activityData={activityData} 
          onDeviceClick={(d) => { setSelectedDevice(d); setSelectedSpecies(null) }}
          onSpeciesClick={(s) => { setSelectedSpecies(s); setSelectedDevice(null) }}
        />
      </div>

      <DetailCard open={!!(selectedDevice || selectedSpecies)} onClose={() => { setSelectedDevice(null); setSelectedSpecies(null) }}>
        {selectedDevice && <DeviceDetail device={selectedDevice} onSpeciesClick={(s) => { setSelectedSpecies(s); setSelectedDevice(null) }} />}
        {selectedSpecies && <SpeciesDetail species={selectedSpecies} />}
      </DetailCard>
    </>
  )
}
