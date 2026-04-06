import { useState, useCallback } from 'react';
import { api } from '../api/client';

const API_BASE = import.meta.env.VITE_API_URL || '';

export function useChat() {
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [conversationId, setConversationId] = useState(null);
  const [lastResponse, setLastResponse] = useState(null);

  const sendMessage = useCallback(async (text, patientId, doctorGender = 'male', voiceEnabled = true) => {
    if (!text.trim() || !patientId) return;

    const userMsg = { role: 'user', content: text, timestamp: new Date() };
    setMessages(prev => [...prev, userMsg]);
    setIsLoading(true);

    setMessages(prev => [...prev, {
      role: 'assistant', content: '', streaming: true, timestamp: new Date(),
    }]);

    let fullAnswer = '';

    try {
      const response = await fetch(API_BASE + '/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          patient_id: patientId,
          message: text,
          conversation_id: conversationId,
          doctor_gender: doctorGender,
          voice_enabled: false,  // No backend TTS needed anymore
        }),
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('event: token')) continue;

          if (line.startsWith('data: ') && !line.includes('"conversation_id"')) {
            const token = line.slice(6);
            if (token && token !== '[DONE]') {
              fullAnswer += token;
              setMessages(prev => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last && last.role === 'assistant') {
                  updated[updated.length - 1] = { ...last, content: fullAnswer };
                }
                return updated;
              });
            }
          }

          if (line.startsWith('data: ') && line.includes('"conversation_id"')) {
            try {
              const meta = JSON.parse(line.slice(6));
              setConversationId(meta.conversation_id);
              setLastResponse({
                answer: fullAnswer,
                confidence_score: meta.confidence_score,
                refused: meta.refused,
                urgency: meta.urgency,
                citations: meta.citations || [],
                speakText: voiceEnabled ? fullAnswer : null,  // Signal to App.jsx to speak
              });

              setMessages(prev => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last && last.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    content: meta.cleaned_answer || fullAnswer,
                    streaming: false,
                    citations: meta.citations,
                    confidence: meta.confidence_score,
                    refused: meta.refused,
                    urgency: meta.urgency,
                  };
                }
                return updated;
              });
            } catch (e) {
              console.warn('Failed to parse stream metadata:', e);
            }
          }
        }
      }
    } catch (error) {
      console.error('Stream error:', error);
      setMessages(prev => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last && last.role === 'assistant') {
          updated[updated.length - 1] = {
            ...last,
            content: "I'm sorry, I'm having trouble right now. Please try again.",
            streaming: false,
            error: true,
          };
        }
        return updated;
      });
    } finally {
      setIsLoading(false);
    }
  }, [conversationId]);

  const resetChat = useCallback(() => {
    setMessages([]);
    setConversationId(null);
    setLastResponse(null);
  }, []);

  const loadConversation = useCallback(async (convId) => {
    try {
      const data = await api.getHistory(convId);
      setConversationId(convId);
      setMessages(data.messages.map(m => ({
        role: m.role,
        content: m.content,
        citations: m.citations,
        confidence: m.confidence_score,
        refused: m.refused,
        timestamp: new Date(m.created_at),
      })));
    } catch (e) {
      console.error('Failed to load conversation:', e);
    }
  }, []);

  return { messages, isLoading, conversationId, lastResponse, sendMessage, resetChat, loadConversation };
}