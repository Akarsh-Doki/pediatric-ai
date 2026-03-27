import { useState, useRef, useEffect } from 'react';
import CitationPanel from './CitationPanel';

export default function ChatInterface({ messages, isLoading, onSend, disabled }) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef(null);

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, isLoading]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!input.trim() || disabled) return;
    onSend(input.trim());
    setInput('');
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] rounded-2xl px-4 py-3 ${msg.role === 'user' ? 'rounded-br-md' : 'rounded-bl-md'}`}
              style={{
                backgroundColor: msg.role === 'user' ? 'var(--bubble-user)' : 'var(--bubble-assistant)',
                color: msg.role === 'user' ? 'var(--bubble-user-text)' : 'var(--bubble-assistant-text)',
              }}>
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{msg.content}</p>
              {msg.role === 'assistant' && msg.citations && <CitationPanel citations={msg.citations} />}
              {msg.refused && <div className="mt-2 text-xs opacity-70">⚠️ Limited confidence — please consult your pediatrician</div>}
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex justify-start">
            <div className="rounded-2xl rounded-bl-md px-4 py-3" style={{ backgroundColor: 'var(--bubble-assistant)' }}>
              <div className="flex gap-1.5">
                <div className="w-2 h-2 rounded-full animate-bounce" style={{ backgroundColor: 'var(--text-secondary)', animationDelay: '0ms' }} />
                <div className="w-2 h-2 rounded-full animate-bounce" style={{ backgroundColor: 'var(--text-secondary)', animationDelay: '150ms' }} />
                <div className="w-2 h-2 rounded-full animate-bounce" style={{ backgroundColor: 'var(--text-secondary)', animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      <form onSubmit={handleSubmit} className="p-4 border-t" style={{ borderColor: 'var(--border)' }}>
        <div className="flex gap-2">
          <input type="text" value={input} onChange={(e) => setInput(e.target.value)}
            placeholder="Describe your symptoms..." disabled={disabled}
            className="flex-1 px-4 py-3 rounded-xl border text-sm outline-none focus:ring-2 focus:ring-blue-400 transition-all disabled:opacity-50"
            style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border)', color: 'var(--text-primary)' }} />
          <button type="submit" disabled={disabled || !input.trim()}
            className="px-6 py-3 rounded-xl font-medium text-sm text-white transition-all disabled:opacity-50 cursor-pointer"
            style={{ backgroundColor: 'var(--accent)' }}>Send</button>
        </div>
      </form>
    </div>
  );
}