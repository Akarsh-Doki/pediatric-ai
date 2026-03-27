import { useState, useEffect } from 'react';
import { api } from '../api/client';
import { useTheme } from '../hooks/useTheme';
import PatientForm from './PatientForm';
import DocumentUpload from './DocumentUpload';
import ConversationList from './ConversationList';

export default function Sidebar({
  selectedPatient, onSelectPatient, doctorGender, onDoctorGenderChange,
  voiceEnabled, onVoiceToggle, onNewChat, onLoadConversation, currentConversationId,
}) {
  const { isDark, toggleTheme } = useTheme();
  const [patients, setPatients] = useState([]);
  const [showForm, setShowForm] = useState(false);

  useEffect(() => { api.getPatients().then(setPatients).catch(console.error); }, []);

  const handleCreatePatient = async (data) => {
    try {
      const p = await api.createPatient(data);
      setPatients(prev => [p, ...prev]);
      onSelectPatient(p);
      setShowForm(false);
    } catch (e) { alert('Failed: ' + e.message); }
  };

  const label = "text-xs font-semibold uppercase tracking-wider mb-2";

  return (
    <div className="w-full h-full p-4 overflow-y-auto space-y-5"
      style={{ backgroundColor: 'var(--bg-secondary)', borderRight: '1px solid var(--border)' }}>

      <button onClick={onNewChat} className="w-full py-2 rounded-lg text-sm font-medium cursor-pointer"
        style={{ backgroundColor: 'var(--accent)', color: '#fff' }}>+ New Conversation</button>

      {/* Patient */}
      <div>
        <h3 className={label} style={{ color: 'var(--text-secondary)' }}>Patient</h3>
        {showForm ? <PatientForm onSubmit={handleCreatePatient} onCancel={() => setShowForm(false)} /> : (
          <>
            <select value={selectedPatient?.id || ''}
              onChange={e => { const p = patients.find(p => p.id === e.target.value); if (p) onSelectPatient(p); }}
              className="w-full px-3 py-2 rounded-lg border text-sm outline-none"
              style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border)', color: 'var(--text-primary)' }}>
              <option value="">Select patient...</option>
              {patients.map(p => <option key={p.id} value={p.id}>{p.name} ({p.age}y, {p.sex})</option>)}
            </select>
            <button onClick={() => setShowForm(true)} className="mt-2 text-xs cursor-pointer" style={{ color: 'var(--accent)' }}>
              + Add new patient
            </button>
          </>
        )}
      </div>

      {/* Conversation History */}
      <ConversationList patientId={selectedPatient?.id} onSelect={onLoadConversation}
        currentConversationId={currentConversationId} />

      {/* Doctor Gender */}
      <div>
        <h3 className={label} style={{ color: 'var(--text-secondary)' }}>Doctor</h3>
        <div className="flex gap-2">
          {['female', 'male'].map(g => (
            <button key={g} onClick={() => onDoctorGenderChange(g)}
              className={`flex-1 py-1.5 rounded-lg text-xs font-medium cursor-pointer transition-all ${doctorGender === g ? 'ring-2 ring-blue-400' : ''}`}
              style={{ backgroundColor: doctorGender === g ? 'var(--accent-light)' : 'var(--bg-primary)',
                color: 'var(--text-primary)', border: '1px solid var(--border)' }}>
              {g === 'female' ? '👩‍⚕️ Female' : '👨‍⚕️ Male'}
            </button>
          ))}
        </div>
      </div>

      {/* Voice */}
      <div>
        <h3 className={label} style={{ color: 'var(--text-secondary)' }}>Voice</h3>
        <button onClick={onVoiceToggle} className="w-full py-1.5 rounded-lg text-xs font-medium cursor-pointer"
          style={{ backgroundColor: voiceEnabled ? 'var(--accent-light)' : 'var(--bg-primary)',
            color: 'var(--text-primary)', border: '1px solid var(--border)' }}>
          {voiceEnabled ? '🔊 Voice On' : '🔇 Voice Off'}
        </button>
      </div>

      {/* Theme */}
      <div>
        <h3 className={label} style={{ color: 'var(--text-secondary)' }}>Theme</h3>
        <button onClick={toggleTheme} className="w-full py-1.5 rounded-lg text-xs font-medium cursor-pointer"
          style={{ backgroundColor: 'var(--bg-primary)', color: 'var(--text-primary)', border: '1px solid var(--border)' }}>
          {isDark ? '☀️ Light Mode' : '🌙 Dark Mode'}
        </button>
      </div>

      {/* Document Upload */}
      <div>
        <h3 className={label} style={{ color: 'var(--text-secondary)' }}>Knowledge Base</h3>
        <DocumentUpload />
      </div>
    </div>
  );
}