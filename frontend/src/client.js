const API_BASE = import.meta.env.VITE_API_URL || '';

async function request(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const config = { headers: { 'Content-Type': 'application/json' }, ...options };
  const response = await fetch(url, config);
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Request failed' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

export const api = {
  // Patients
  getPatients: () => request('/patients'),
  createPatient: (data) => request('/patients', { method: 'POST', body: JSON.stringify(data) }),
  getPatient: (id) => request(`/patients/${id}`),
  updatePatient: (id, data) => request(`/patients/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  getPatientConversations: (id) => request(`/patients/${id}/conversations`),

  // Chat
  sendMessage: (data) => request('/chat/query', { method: 'POST', body: JSON.stringify(data) }),
  getHistory: (conversationId) => request(`/chat/history/${conversationId}`),

  // Documents
  uploadDocument: async (file, title) => {
    const formData = new FormData();
    formData.append('file', file);
    if (title) formData.append('title', title);
    const response = await fetch(`${API_BASE}/documents/upload`, { method: 'POST', body: formData });
    if (!response.ok) throw new Error('Upload failed');
    return response.json();
  },
  ingestDocument: (docId) => request(`/documents/${docId}/ingest`, { method: 'POST' }),
  getDocuments: () => request('/documents'),

  // TTS
  synthesize: (data) => request('/tts/synthesize', { method: 'POST', body: JSON.stringify(data) }),

  // Other
  health: () => request('/health'),
  dashboard: () => request('/analytics/dashboard'),
};