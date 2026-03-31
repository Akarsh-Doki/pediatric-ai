import { useState, useEffect, useRef, useCallback } from 'react';
import './DoctorFace.css';

// Import all doctor face frames
import idle from '../assets/doctor/idle.png';
import idleWarm from '../assets/doctor/idle_warm.png';
import blink from '../assets/doctor/blink.png';
import thinking from '../assets/doctor/thinking.png';
import talkA from '../assets/doctor/talk_a.png';
import talkB from '../assets/doctor/talk_b.png';
import talkC from '../assets/doctor/talk_c.png';
import talkD from '../assets/doctor/talk_d.png';
import concernedMild from '../assets/doctor/concerned_mild.png';
import concernedSerious from '../assets/doctor/concerned_serious.png';
import concernedWorried from '../assets/doctor/concerned_worried.png';

/*
  EXPRESSION STATE MACHINE (11 PNGs - 5 states):

  IDLE:       idle <-> idle_warm (swap every 8-12s), blink every 2.8-5.5s
  THINKING:   thinking (static, eyes aside)
  TALKING:    cycle A -> B -> C -> B -> D -> B at 190ms per frame
  REASSURING: talk_d (reused as warm smile), blinks still active
  CONCERNED:  cycle concerned_mild -> serious -> worried (3s each)
*/

const TALK_FRAMES = [talkA, talkB, talkD, talkB, talkD, talkB, idle];
const TALK_INTERVAL_MS = 190;
const BLINK_MIN_MS = 2800;
const BLINK_MAX_MS = 5500;
const BLINK_DURATION_MS = 150;
const CONCERNED_FRAMES = [concernedMild, concernedSerious, concernedWorried];

export default function DoctorFace({ expression = 'idle', isPlaying = false, size = 'centered' }) {
  const [currentFrame, setCurrentFrame] = useState(idle);
  const [isBlinking, setIsBlinking] = useState(false);
  const [fadeClass, setFadeClass] = useState('');

  const talkIndexRef = useRef(0);
  const talkIntervalRef = useRef(null);
  const blinkTimeoutRef = useRef(null);
  const concernedIndexRef = useRef(0);
  const prevExpressionRef = useRef(expression);

  // Blink system
  const scheduleBlink = useCallback(() => {
    const delay = BLINK_MIN_MS + Math.random() * (BLINK_MAX_MS - BLINK_MIN_MS);
    blinkTimeoutRef.current = setTimeout(() => {
      setIsBlinking(true);
      setTimeout(() => {
        setIsBlinking(false);
        scheduleBlink();
      }, BLINK_DURATION_MS);
    }, delay);
  }, []);

  const stopBlink = useCallback(() => {
    clearTimeout(blinkTimeoutRef.current);
    setIsBlinking(false);
  }, []);

  // Crossfade on expression change
  useEffect(() => {
    if (prevExpressionRef.current !== expression) {
      setFadeClass('df-fade-out');
      const timer = setTimeout(() => setFadeClass('df-fade-in'), 120);
      prevExpressionRef.current = expression;
      return () => clearTimeout(timer);
    }
  }, [expression]);

  // Main expression state machine
  useEffect(() => {
    clearInterval(talkIntervalRef.current);
    stopBlink();

    if (expression === 'idle') {
      setCurrentFrame(idle);
      scheduleBlink();
      return () => { stopBlink(); };
    }

    if (expression === 'thinking') {
      setCurrentFrame(thinking);
      return;
    }

    // TALKING: animate mouth whether streaming text OR playing audio
    if (expression === 'talking') {
      talkIndexRef.current = 0;
      setCurrentFrame(TALK_FRAMES[0]);
      talkIntervalRef.current = setInterval(() => {
        talkIndexRef.current = (talkIndexRef.current + 1) % TALK_FRAMES.length;
        setCurrentFrame(TALK_FRAMES[talkIndexRef.current]);
      }, TALK_INTERVAL_MS);
      return () => clearInterval(talkIntervalRef.current);
    }

    if (expression === 'reassuring') {
      setCurrentFrame(talkD);
      scheduleBlink();
      return () => stopBlink();
    }

    if (expression === 'concerned') {
      concernedIndexRef.current = 0;
      setCurrentFrame(CONCERNED_FRAMES[0]);
      const concernedInterval = setInterval(() => {
        concernedIndexRef.current = (concernedIndexRef.current + 1) % CONCERNED_FRAMES.length;
        setCurrentFrame(CONCERNED_FRAMES[concernedIndexRef.current]);
      }, 3000);
      return () => clearInterval(concernedInterval);
    }

    setCurrentFrame(idle);
  }, [expression, scheduleBlink, stopBlink]);

  const displayFrame = isBlinking ? blink : currentFrame;

  return (
    <div className="df-container">
      <img
        src={displayFrame}
        alt="PediatricAI"
        className={`df-face ${fadeClass}`}
        draggable={false}
      />
    </div>
  );
}
