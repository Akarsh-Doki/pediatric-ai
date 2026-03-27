import { useState, useEffect } from 'react';
import { useChat } from './hooks/useChat';
import { useAudioSync } from './hooks/useAudioSync';
import DoctorFace from './components/DoctorFace';
import ChatInterface from './components/ChatInterface';
import PromptChips from './components/PromptChips';
import Sidebar from './components/Sidebar';

export default function App() {
  const { messages, isLoading, sendMessage, resetChat, lastResponse, conversationId, loadConversation } = useChat();
  const { isPlaying, play, stop } = useAudioSync();
  const [selectedPatient, setSelectedPatient] = useState(null);
  const [doctorGender, setDoctorGender] = useState('female');
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const isConversationActive = messages.length > 0;

  const [expression, setExpression] = useState('idle');
  useEffect(() => {
    if (isLoading) setExpression('thinking');
    else if (isPlaying) setExpression('talking');
    else if (lastResponse?.urgency === 'severe' || lastResponse?.urgency === 'moderate') setExpression('concerned');
    else if (lastResponse?.urgency === 'mild') setExpression('reassuring');
    else setExpression('idle');
  }, [isLoading, isPlaying, lastResponse]);

  useEffect(() => {
    if (lastResponse?.audio_base64 && voiceEnabled) play(lastResponse.audio_base64);
  }, [lastResponse]);

  const handleSend = (text) => {
    if (!selectedPatient) { alert('Please select or create a patient first.'); setSidebarOpen(true); return; }
    stop();
    sendMessage(text, selectedPatient.id, doctorGender, voiceEnabled);
  };

  const handleNewChat = () => { stop(); resetChat(); };

  return (
    <div className="h-screen flex overflow-hidden" style={{ backgroundColor: 'var(--bg-primary)' }}>
      {/* Sidebar */}
      <div className={`fixed inset-y-0 left-0 z-40 w-72 transform transition-transform duration-300 ease-in-out
        ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} md:relative md:translate-x-0 ${isConversationActive ? 'md:block' : 'md:hidden'}`}>
        <Sidebar selectedPatient={selectedPatient} onSelectPatient={setSelectedPatient}
          doctorGender={doctorGender} onDoctorGenderChange={setDoctorGender}
          voiceEnabled={voiceEnabled} onVoiceToggle={() => setVoiceEnabled(!voiceEnabled)}
          onNewChat={handleNewChat} onLoadConversation={loadConversation}
          currentConversationId={conversationId} />
      </div>
      {sidebarOpen && <div className="fixed inset-0 z-30 bg-black/30 md:hidden" onClick={() => setSidebarOpen(false)} />}

      {/* Main */}
      <div className="flex-1 flex flex-col h-full relative">
        <div className="flex items-center justify-between px-4 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
          <button onClick={() => setSidebarOpen(!sidebarOpen)} className="p-2 rounded-lg cursor-pointer md:hidden" style={{ color: 'var(--text-secondary)' }}>☰</button>
          <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>PediatricAI</span>
          <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
            {selectedPatient ? `${selectedPatient.name} (${selectedPatient.age}y)` : 'No patient selected'}
          </span>
        </div>

        {!isConversationActive ? (
          <div className="flex-1 flex flex-col items-center justify-center p-8 gap-8">
            <DoctorFace expression={expression} isPlaying={isPlaying} gender={doctorGender} size="centered" />
            <div className="text-center">
              <h1 className="text-2xl font-semibold mb-2" style={{ color: 'var(--text-primary)' }}>Hi, I'm PediatricAI</h1>
              <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>I'm here to help with your child's health questions.</p>
            </div>
            <PromptChips onSelect={handleSend} disabled={!selectedPatient || isLoading} />
            <div className="w-full max-w-xl">
              <form onSubmit={e => { e.preventDefault(); const v = e.target.elements.message.value.trim(); if (v) { handleSend(v); e.target.elements.message.value = ''; } }} className="flex gap-2">
                <input name="message" placeholder="Describe your symptoms..." disabled={!selectedPatient}
                  className="flex-1 px-4 py-3 rounded-xl border text-sm outline-none focus:ring-2 focus:ring-blue-400 disabled:opacity-50"
                  style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border)', color: 'var(--text-primary)' }} />
                <button type="submit" disabled={!selectedPatient}
                  className="px-6 py-3 rounded-xl font-medium text-sm text-white disabled:opacity-50 cursor-pointer"
                  style={{ backgroundColor: 'var(--accent)' }}>Send</button>
              </form>
              {!selectedPatient && <p className="text-xs text-center mt-2" style={{ color: 'var(--warning)' }}>Open sidebar to select or create a patient.</p>}
            </div>
          </div>
        ) : (
          <div className="flex-1 flex overflow-hidden">
            <div className="hidden md:flex flex-col items-center justify-center w-72 p-4" style={{ borderRight: '1px solid var(--border)' }}>
              <DoctorFace expression={expression} isPlaying={isPlaying} gender={doctorGender} size="sidebar" />
              <p className="text-xs mt-4 text-center" style={{ color: 'var(--text-secondary)' }}>
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