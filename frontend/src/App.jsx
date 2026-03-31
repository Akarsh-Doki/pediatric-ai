import { useState, useEffect, useRef } from 'react';
import { useChat } from './hooks/useChat';
import { useAudioSync } from './hooks/useAudioSync';
import { api } from './api/client';
import DoctorFace from './components/DoctorFace';
import ChatInterface from './components/ChatInterface';
import Sidebar from './components/Sidebar';

const SUGGESTIONS = [
  "My child has a 102\u00b0F fever and won't eat",
  "Is this rash something to worry about?",
  "Can I give Tylenol with antibiotics?",
  "When should I take my child to the ER?",
  "My child burned their hand on the stove",
  "My toddler has a barking cough at night",
];

export default function App() {
  const { messages, isLoading, sendMessage, resetChat, lastResponse, conversationId, loadConversation } = useChat();
  const { isPlaying, play, stop } = useAudioSync();
  const [selectedPatient, setSelectedPatient] = useState(null);
  const [doctorGender, setDoctorGender] = useState('female');
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const [inputFocused, setInputFocused] = useState(false);
  const [showPatientPrompt, setShowPatientPrompt] = useState(false);
  const [patientForm, setPatientForm] = useState({ name: '', age: '', sex: 'male' });
  const [patientLoading, setPatientLoading] = useState(false);
  const inputRef = useRef(null);
  const suggestionsRef = useRef(null);

  const isConversationActive = messages.length > 0;
  const [expression, setExpression] = useState('idle');
  const lastMsg = messages.length > 0 ? messages[messages.length - 1] : null;
  const isStreaming = lastMsg?.streaming && lastMsg?.content?.length > 0;
  useEffect(() => {
    if (isStreaming) setExpression('talking');
    else if (isLoading) setExpression('thinking');
    else if (isPlaying) setExpression('talking');
    else if (lastResponse?.urgency === 'severe' || lastResponse?.urgency === 'moderate') setExpression('concerned');
    else if (lastResponse?.urgency === 'mild') setExpression('reassuring');
    else setExpression('idle');
  }, [isLoading, isPlaying, isStreaming, lastResponse]);

  useEffect(() => {
    if (lastResponse?.audio_base64 && voiceEnabled) play(lastResponse.audio_base64);
  }, [lastResponse]);

  useEffect(() => {
    const handleClick = (e) => {
      if (suggestionsRef.current && !suggestionsRef.current.contains(e.target) &&
          inputRef.current && !inputRef.current.contains(e.target)) {
        setInputFocused(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const handleSend = async (text) => {
    if (!text.trim()) return;
    if (!selectedPatient) {
      setShowPatientPrompt(true);
      setInputValue(text);
      return;
    }
    stop();
    setInputValue('');
    setInputFocused(false);
    sendMessage(text, selectedPatient.id, doctorGender, voiceEnabled);
  };

  const handleQuickPatientCreate = async () => {
    if (!patientForm.name.trim() || !patientForm.age) return;
    setPatientLoading(true);
    try {
      const patient = await api.createPatient({
        name: patientForm.name.trim(),
        age: parseInt(patientForm.age),
        sex: patientForm.sex,
      });
      setSelectedPatient(patient);
      setShowPatientPrompt(false);
      if (inputValue.trim()) {
        stop();
        sendMessage(inputValue.trim(), patient.id, doctorGender, voiceEnabled);
        setInputValue('');
      }
    } catch (err) {
      alert('Failed to create patient: ' + err.message);
    }
    setPatientLoading(false);
  };

  const handleNewChat = () => { stop(); resetChat(); };

  const showSuggestions = inputFocused && !isConversationActive && !showPatientPrompt;

  return (
    <div className="h-screen flex overflow-hidden" style={{ backgroundColor: 'var(--bg-primary)' }}>
      {/* Sidebar overlay */}
      <div className={`fixed inset-y-0 left-0 z-40 w-72 transform transition-transform duration-300 ease-in-out ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}>
        <Sidebar selectedPatient={selectedPatient} onSelectPatient={setSelectedPatient}
          doctorGender={doctorGender} onDoctorGenderChange={setDoctorGender}
          voiceEnabled={voiceEnabled} onVoiceToggle={() => setVoiceEnabled(!voiceEnabled)}
          onNewChat={handleNewChat} onLoadConversation={loadConversation}
          currentConversationId={conversationId} />
      </div>
      {sidebarOpen && <div className="fixed inset-0 z-30 bg-black/30" onClick={() => setSidebarOpen(false)} />}

      {/* Main */}
      <div className="flex-1 flex flex-col h-full relative">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
          <button onClick={() => setSidebarOpen(!sidebarOpen)} className="p-2 rounded-lg cursor-pointer hover:opacity-70" style={{ color: 'var(--text-secondary)' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
          <span onClick={handleNewChat} className="text-sm font-medium cursor-pointer hover:opacity-70" style={{ color: 'var(--text-primary)' }}>PediatricAI</span>
          <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
            {selectedPatient ? selectedPatient.name + ' (' + selectedPatient.age + 'y)' : 'No patient selected'}
          </span>
        </div>

        {!isConversationActive ? (
          /* Landing screen — centered vertically and horizontally */
          <div className="flex-1 flex flex-col items-center justify-center px-4 -mt-36">
            {/* Doctor face — large and centered */}
            <div style={{ width: '350px', height: '350px' }}>
              <DoctorFace expression={expression} isPlaying={isPlaying} gender={doctorGender} size="centered" />
            </div>

            {/* Title directly under doctor */}
            <h1 className="text-2xl font-semibold mt-3" style={{ color: 'var(--text-primary)' }}>Hi, I'm PediatricAI</h1>
            <p className="text-sm mt-1 mb-6" style={{ color: 'var(--text-secondary)' }}>I'm here to help with your child's health questions.</p>

            {/* Search area */}
            <div className="w-full max-w-2xl relative">
              {/* Inline patient form */}
              {showPatientPrompt && (
                <div className="mb-3 p-4 rounded-xl border" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border)' }}>
                  <p className="text-sm font-medium mb-2" style={{ color: 'var(--text-primary)' }}>Tell me about your child:</p>
                  <div className="flex gap-2 mb-2">
                    <input placeholder="Name" value={patientForm.name}
                      onChange={e => setPatientForm(p => ({ ...p, name: e.target.value }))}
                      className="flex-1 px-3 py-2 rounded-lg border text-sm outline-none"
                      style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border)', color: 'var(--text-primary)' }} />
                    <input placeholder="Age" type="number" min="0" max="18" value={patientForm.age}
                      onChange={e => setPatientForm(p => ({ ...p, age: e.target.value }))}
                      className="w-20 px-3 py-2 rounded-lg border text-sm outline-none"
                      style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border)', color: 'var(--text-primary)' }} />
                    <select value={patientForm.sex} onChange={e => setPatientForm(p => ({ ...p, sex: e.target.value }))}
                      className="px-3 py-2 rounded-lg border text-sm outline-none"
                      style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border)', color: 'var(--text-primary)' }}>
                      <option value="male">Male</option>
                      <option value="female">Female</option>
                    </select>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={handleQuickPatientCreate} disabled={patientLoading || !patientForm.name.trim() || !patientForm.age}
                      className="px-4 py-2 rounded-lg text-sm font-medium text-white disabled:opacity-50 cursor-pointer"
                      style={{ backgroundColor: 'var(--accent)' }}>
                      {patientLoading ? 'Creating...' : 'Start Chat'}
                    </button>
                    <button onClick={() => setShowPatientPrompt(false)}
                      className="px-4 py-2 rounded-lg text-sm cursor-pointer"
                      style={{ color: 'var(--text-secondary)' }}>Cancel</button>
                  </div>
                </div>
              )}

              <form onSubmit={e => { e.preventDefault(); handleSend(inputValue); }} className="flex gap-3">
                <input ref={inputRef} name="message" placeholder="Describe your symptoms..."
                  value={inputValue} onChange={e => setInputValue(e.target.value)}
                  onFocus={() => setInputFocused(true)}
                  className="flex-1 px-5 py-4 rounded-2xl border text-base outline-none focus:ring-2 focus:ring-blue-400"
                  style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border)', color: 'var(--text-primary)' }} />
                <button type="submit" disabled={isLoading || !inputValue.trim()}
                  className="px-8 py-4 rounded-2xl font-medium text-base text-white disabled:opacity-50 cursor-pointer"
                  style={{ backgroundColor: 'var(--accent)' }}>Send</button>
              </form>

              {/* Suggestions dropdown */}
              {showSuggestions && (
                <div ref={suggestionsRef}
                  className="absolute left-0 right-0 mt-2 rounded-xl border shadow-lg overflow-hidden z-10"
                  style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border)' }}>
                  <p className="px-4 py-2 text-xs font-medium" style={{ color: 'var(--text-secondary)', borderBottom: '1px solid var(--border)' }}>
                    Try asking...
                  </p>
                  {SUGGESTIONS.map((s, i) => (
                    <button key={i} onClick={() => { setInputValue(s); setInputFocused(false); handleSend(s); }}
                      className="w-full text-left px-4 py-3 text-sm hover:brightness-95 cursor-pointer transition-colors"
                      style={{ color: 'var(--text-primary)', borderBottom: i < SUGGESTIONS.length - 1 ? '1px solid var(--border)' : 'none' }}>
                      {s}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          /* Chat active screen */
          <div className="flex-1 flex overflow-hidden">
            <div className="hidden md:flex flex-col items-center justify-center w-56 p-3 shrink-0" style={{ borderRight: '1px solid var(--border)' }}>
              <DoctorFace expression={expression} isPlaying={isPlaying} gender={doctorGender} size="sidebar" />
              <p className="text-xs mt-3 text-center" style={{ color: 'var(--text-secondary)' }}>
                PediatricAI is {expression === 'thinking' ? 'thinking...' : expression === 'talking' ? 'speaking...' : 'listening'}
              </p>
            </div>
            <div className="flex-1 flex flex-col">
              <ChatInterface messages={messages} isLoading={isLoading} onSend={handleSend} disabled={!selectedPatient || isLoading} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
