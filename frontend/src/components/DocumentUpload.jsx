import { useState } from 'react';
import { api } from '../api/client';

export default function DocumentUpload() {
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState(null);

  const handleUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    setUploading(true);
    setStatus('Uploading...');

    try {
      const uploadResult = await api.uploadDocument(file, file.name.replace('.pdf', ''));
      setStatus('Ingesting...');
      const ingestResult = await api.ingestDocument(uploadResult.document_id);
      setStatus(`Done! ${ingestResult.chunks_created} chunks created.`);
      setTimeout(() => setStatus(null), 5000);
    } catch (err) {
      setStatus(`Error: ${err.message}`);
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  return (
    <div>
      <label className="block w-full py-2 px-3 rounded-lg text-xs text-center cursor-pointer transition-colors"
        style={{ backgroundColor: 'var(--bg-primary)', border: '1px dashed var(--border)', color: 'var(--text-secondary)' }}>
        {uploading ? 'Processing...' : '📄 Upload PDF to knowledge base'}
        <input type="file" accept=".pdf" onChange={handleUpload} disabled={uploading} className="hidden" />
      </label>
      {status && <p className="text-xs mt-1 text-center" style={{ color: 'var(--accent)' }}>{status}</p>}
    </div>
  );
}