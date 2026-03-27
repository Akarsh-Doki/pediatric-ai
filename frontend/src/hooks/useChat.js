import { useState, useCallback } from 'react';
import { api } from '../api/client';

export function useChat() {
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [conversationId, setConversationId] = useState(null);
  const [lastResponse, setLastResponse] = useState(null);

  const sendMessage = useCallback(async (text, patientId, doctorGender = 'female', voiceEnabled = true) => {
    if (!text.trim() || !patientId) return;

    const userMsg = { role: 'user', content: text, timestamp: new Date() };
    setMessages(prev => [...prev, userMsg]);
    setIsLoading(true);

    try {
      const response = await api.sendMessage({
        patient_id: patientId, message: text,
        conversation_id: conversationId,
        doctor_gender: doctorGender, voice_enabled: voiceEnabled,
      });

      setConversationId(response.conversation_id);
      setLastResponse(response);

      setMessages(prev => [...prev, {
        role: 'assistant', content: response.answer,
        citations: response.citations, confidence: response.confidence_score,
        refused: response.refused, urgency: response.urgency, timestamp: new Date(),
      }]);
      return response;
    } catch (error) {
      setMessages(prev => [...prev, {
        role: 'assistant', content: "I'm sorry, I'm having trouble right now. Please try again.",
        error: true, timestamp: new Date(),
      }]);
      throw error;
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
        role: m.role, content: m.content, citations: m.citations,
        confidence: m.confidence_score, refused: m.refused, timestamp: new Date(m.created_at),
      })));
    } catch (e) { console.error('Failed to load conversation:', e); }
  }, []);

  return { messages, isLoading, conversationId, lastResponse, sendMessage, resetChat, loadConversation };
}