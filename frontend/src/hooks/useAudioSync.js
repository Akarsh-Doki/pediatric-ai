import { useState, useRef, useCallback, useEffect } from 'react';

export function useAudioSync() {
  const [isPlaying, setIsPlaying] = useState(false);
  const audioRef = useRef(new Audio());

  const play = useCallback((base64Audio) => {
    if (!base64Audio) return;
    const audio = audioRef.current;
    audio.src = `data:audio/mp3;base64,${base64Audio}`;
    audio.onplay = () => setIsPlaying(true);
    audio.onended = () => setIsPlaying(false);
    audio.onerror = () => setIsPlaying(false);
    audio.play().catch(() => setIsPlaying(false));
  }, []);

  const stop = useCallback(() => {
    audioRef.current.pause();
    audioRef.current.currentTime = 0;
    setIsPlaying(false);
  }, []);

  useEffect(() => () => { audioRef.current.pause(); audioRef.current.src = ''; }, []);

  return { isPlaying, play, stop, audioRef };
}