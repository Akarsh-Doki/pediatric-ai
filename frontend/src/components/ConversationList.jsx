import { useState, useEffect } from 'react';
import { api } from '../api/client';

export default function ConversationList({ patientId, onSelect, currentConversationId }) {
  const [conversations, setConversations] = useState([]);

  useEffect(() => {
    if (!patientId) return;
    api.getPatientConversations(patientId).then(setConversations).catch(console.error);
  }, [patientId]);

  if (!patientId || conversations.length === 0) return null;

  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--text-secondary)' }}>
        History
      </h3>
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {conversations.map(conv => (
          <button key={conv.id} onClick={() => onSelect(conv.id)}
            className={`w-full text-left px-3 py-2 rounded-lg text-xs transition-colors cursor-pointer ${
              currentConversationId === conv.id ? 'ring-1 ring-blue-400' : ''
            }`}
            style={{ backgroundColor: 'var(--bg-primary)', color: 'var(--text-primary)', border: '1px solid var(--border)' }}>
            <div className="truncate">{conv.last_message_preview || 'Empty conversation'}</div>
            <div style={{ color: 'var(--text-secondary)' }}>
              {new Date(conv.started_at).toLocaleDateString()} · {conv.message_count} msgs
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}