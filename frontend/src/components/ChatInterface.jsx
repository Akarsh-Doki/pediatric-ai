import { useState, useRef, useEffect } from 'react';
import CitationPanel from './CitationPanel';

function cleanText(text) {
  if (!text) return '';
  return text
    .replace(/\s+([.,!?;:])/g, '$1')           // remove space before punctuation
    .replace(/\(\s+/g, '(')                      // remove space after opening paren
    .replace(/\s+\)/g, ')')                      // remove space before closing paren
    .replace(/(\w)\s{2,}(\w)/g, '$1 $2')         // collapse multiple spaces
    .replace(/\b(\w+)\s+(\w+)\b/g, (match, a, b) => {
      // Rejoin common medical terms that got split
      const joined = a + b;
      const medTerms = ['acetaminophen','ibuprofen','tylenol','motrin','amoxicillin',
        'pediatrician','dehydration','temperature','typically','relieving'];
      if (medTerms.includes(joined.toLowerCase())) return joined;
      return match;
    });
}

function formatMessage(text) {
  if (!text) return null;
  text = cleanText(text);

  // Split into paragraphs by double newline or numbered list items
  const blocks = text.split(/\n\n+/);

  return blocks.map((block, blockIdx) => {
    // Check if block is a numbered list
    const listItems = block.split(/\n/).filter(l => l.trim());
    const isNumberedList = listItems.length > 1 && listItems.every(l => /^\d+[\.\)]/.test(l.trim()));

    if (isNumberedList) {
      return (
        <ol key={blockIdx} className="list-decimal list-inside space-y-1 my-2">
          {listItems.map((item, i) => (
            <li key={i} className="text-sm leading-relaxed">
              {renderInline(item.replace(/^\d+[\.\)]\s*/, ''))}
            </li>
          ))}
        </ol>
      );
    }

    // Check if block has bullet points
    const bulletItems = block.split(/\n/).filter(l => l.trim());
    const isBulletList = bulletItems.length > 1 && bulletItems.every(l => /^[\*\-•]/.test(l.trim()));

    if (isBulletList) {
      return (
        <ul key={blockIdx} className="list-disc list-inside space-y-1 my-2">
          {bulletItems.map((item, i) => (
            <li key={i} className="text-sm leading-relaxed">
              {renderInline(item.replace(/^[\*\-•]\s*/, ''))}
            </li>
          ))}
        </ul>
      );
    }

    // Regular paragraph - handle single newlines as line breaks
    const lines = block.split(/\n/);
    return (
      <p key={blockIdx} className="text-sm leading-relaxed mb-2">
        {lines.map((line, i) => (
          <span key={i}>
            {renderInline(line)}
            {i < lines.length - 1 && <br />}
          </span>
        ))}
      </p>
    );
  });
}

function renderInline(text) {
  // Handle **bold** and *italic*
  const parts = [];
  let remaining = text;
  let key = 0;

  while (remaining.length > 0) {
    // Match **bold**
    const boldMatch = remaining.match(/\*\*(.+?)\*\*/);
    if (boldMatch) {
      const beforeBold = remaining.slice(0, boldMatch.index);
      if (beforeBold) parts.push(<span key={key++}>{beforeBold}</span>);
      parts.push(<strong key={key++} className="font-semibold">{boldMatch[1]}</strong>);
      remaining = remaining.slice(boldMatch.index + boldMatch[0].length);
      continue;
    }

    // No more formatting found
    parts.push(<span key={key++}>{remaining}</span>);
    break;
  }

  return parts;
}

export default function ChatInterface({ messages, isLoading, onSend, disabled }) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

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
              {msg.role === 'user' ? (
                <p className="text-sm leading-relaxed">{msg.content}</p>
              ) : (
                <div>{formatMessage(msg.content)}</div>
              )}
              {msg.role === 'assistant' && !msg.streaming && msg.citations && msg.citations.length > 0 && (
                <CitationPanel citations={msg.citations} />
              )}
              {msg.confidence && msg.confidence < 0.5 && !msg.streaming && (
                <div className="mt-2 text-xs opacity-70">Low confidence — consider consulting your pediatrician</div>
              )}
            </div>
          </div>
        ))}
        {isLoading && messages.length > 0 && !messages[messages.length - 1]?.streaming && (
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
