import { useState, useRef, useCallback, useEffect } from 'react';

export function useAudioSync() {
  const [isPlaying, setIsPlaying] = useState(false);
  const [canReplay, setCanReplay] = useState(false);
  const lastTextRef = useRef('');

  const getVoice = useCallback(() => {
    const voices = window.speechSynthesis.getVoices();
    const preferred = [
      'Google UK English Male',
      'Daniel',
      'Arthur',
      'Google US English',
      'Alex',
      'Samantha',
    ];
    for (const name of preferred) {
      const found = voices.find(v => v.name.includes(name));
      if (found) return found;
    }
    const english = voices.find(v => v.lang.startsWith('en'));
    return english || voices[0];
  }, []);

  const speak = useCallback((text) => {
    if (!text) return;
    window.speechSynthesis.cancel();

    lastTextRef.current = text;

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.voice = getVoice();
    utterance.rate = 1.25;
    utterance.pitch = 0.9;
    utterance.volume = 1.0;

    utterance.onstart = () => { setIsPlaying(true); setCanReplay(false); };
    utterance.onend = () => { setIsPlaying(false); setCanReplay(true); };
    utterance.onerror = () => { setIsPlaying(false); setCanReplay(true); };

    window.speechSynthesis.speak(utterance);
  }, [getVoice]);

  const stop = useCallback(() => {
    window.speechSynthesis.cancel();
    setIsPlaying(false);
    setCanReplay(true);
  }, []);

  const replay = useCallback(() => {
    if (lastTextRef.current) {
      speak(lastTextRef.current);
    }
  }, [speak]);

  // Load voices
  useEffect(() => {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.onvoiceschanged = () => window.speechSynthesis.getVoices();
    return () => { window.speechSynthesis.cancel(); };
  }, []);

  return { isPlaying, canReplay, speak, stop, replay };
}