// Centralised API helpers
const API_BASE = window.location.origin;

export async function apiFetch(path) {
  const resp = await fetch(API_BASE + path);
  if (!resp.ok) throw new Error(`API ${resp.status}: ${path}`);
  return resp.json();
}

export async function apiFetchSafe(path) {
  try { return await apiFetch(path); } catch { return null; }
}

export async function fetchBirdImageUrl(scientificName) {
  try {
    const wikiTitle = scientificName.trim().replace(/\s+/g, '_');
    const url = `https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(wikiTitle)}`;
    const resp = await fetch(url);
    if (!resp.ok) return null;
    const data = await resp.json();
    return data?.thumbnail?.source || data?.originalimage?.source || null;
  } catch { return null; }
}

export const NODES = [
  { id: 'E-NK', label: 'Nainital Lake', color: '#4a8b71' },
  { id: 'E-PG', label: 'Pangot Forest', color: '#7b6fcc' },
  { id: 'E-KB', label: 'Kilbury Reserve', color: '#e07b54' },
];

export function statusColorHex(status) {
  if (status === 'online') return '#48bb78';
  if (status === 'stale') return '#ecc94b';
  return '#e53e3e';
}
