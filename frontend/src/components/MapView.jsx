import { useEffect, useRef, useCallback } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { statusColorHex } from '../api'

// Lazy-load leaflet.heat from CDN
function ensureHeatScript() {
  if (window.L && window.L.heatLayer) return Promise.resolve()
  if (window.__heatScriptLoading) return window.__heatScriptLoading
  window.__heatScriptLoading = new Promise((res) => {
    const s = document.createElement('script')
    s.src = 'https://unpkg.com/leaflet.heat/dist/leaflet-heat.js'
    s.onload = () => res()
    document.head.appendChild(s)
  })
  return window.__heatScriptLoading
}

export default function MapView({ devices, detections, onDeviceClick }) {
  const mapRef = useRef(null)
  const mapInstanceRef = useRef(null)
  const heatRef = useRef(null)
  const markersRef = useRef([])
  // Keep a ref to the latest callback so markers never close over stale state
  const onDeviceClickRef = useRef(onDeviceClick)
  useEffect(() => { onDeviceClickRef.current = onDeviceClick }, [onDeviceClick])

  // Init map once
  useEffect(() => {
    if (mapInstanceRef.current) return
    const map = L.map(mapRef.current, { zoomControl: false, attributionControl: false })
      .setView([29.39, 79.43], 12)
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', { maxZoom: 19 }).addTo(map)
    mapInstanceRef.current = map
  }, [])

  // Rebuild markers + heat layer whenever devices/detections change
  useEffect(() => {
    const map = mapInstanceRef.current
    if (!map || !devices.length) return

    ensureHeatScript().then(() => {
      // ── Clear previous layers ──────────────────────
      markersRef.current.forEach(m => m.remove())
      markersRef.current = []
      if (heatRef.current) { heatRef.current.remove(); heatRef.current = null }

      // ── Coord lookup from device list ──────────────
      const coordMap = {}
      devices.forEach(d => {
        const lat = d.lat ?? d.latitude
        const lng = d.lng ?? d.longitude
        if (lat != null) coordMap[d.id] = [lat, lng]
      })

      // ── Heat layer ─────────────────────────────────
      const heatPts = detections
        .filter(dt => coordMap[dt.device_id])
        .map(dt => [...coordMap[dt.device_id], dt.confidence || 0.6])
      if (!heatPts.length) {
        devices.forEach(d => {
          const lat = d.lat ?? d.latitude, lng = d.lng ?? d.longitude
          if (lat != null) heatPts.push([lat, lng, 0.5])
        })
      }
      heatRef.current = window.L.heatLayer(heatPts, {
        radius: 35, blur: 25,
        gradient: { 0.4: '#e6efe9', 0.65: '#8ebf9d', 1.0: '#4a8b71' },
      }).addTo(map)

      // ── Circle markers ─────────────────────────────
      devices.forEach(d => {
        const lat = d.lat ?? d.latitude, lng = d.lng ?? d.longitude
        if (lat == null) return
        const m = L.circleMarker([lat, lng], {
          radius: 10, fillColor: statusColorHex(d.status),
          color: '#fff', weight: 2.5, fillOpacity: 1, opacity: 1,
        })
          .bindTooltip(
            `<div style="font-family:'Inter',sans-serif;font-weight:600;font-size:12px;color:#2d3748;padding:2px 4px;">
               ${d.site_name || d.id}
               <br/><span style="font-weight:400;color:#718096;font-size:11px;">${d.count ?? 0} detections</span>
             </div>`,
            { direction: 'top', offset: [0, -12], opacity: 1 }
          )
          .on('click', () => onDeviceClickRef.current(d))
          .addTo(map)
        markersRef.current.push(m)
      })
    })
  }, [devices, detections])

  return <div id="map-container"><div ref={mapRef} id="map" /></div>
}
