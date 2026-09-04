import React, { useState, useEffect, useRef, useImperativeHandle, forwardRef } from 'react';
import { SakuraLogo } from './SakuraLogo';
import { authFetch } from '../lib/auth';

export interface VoiceRecorderProps {
  onTranscriptionComplete: (text: string) => void;
  apiBase?: string;
  className?: string;
}

export interface VoiceRecorderHandle {
  startRecording: () => void;
  stopRecording: () => void;
  isRecording: boolean;
}

type PermissionStatus = 'UNKNOWN' | 'REQUESTING' | 'ALLOWED' | 'DENIED' | 'UNAVAILABLE';

export const VoiceRecorder = forwardRef<VoiceRecorderHandle, VoiceRecorderProps>(({
  onTranscriptionComplete,
  apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  className = ''
}, ref) => {
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [permissionStatus, setPermissionStatus] = useState<PermissionStatus>('UNKNOWN');
  const [liveTranscript, setLiveTranscript] = useState('');

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const recognitionRef = useRef<any | null>(null);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);

  // Clear timers on unmount
  useEffect(() => {
    return () => {
      cleanupAudio();
    };
  }, []);

  const cleanupAudio = () => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);

    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {}
      recognitionRef.current = null;
    }

    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      try {
        mediaRecorderRef.current.stop();
      } catch {}
      mediaRecorderRef.current = null;
    }

    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }

    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      try {
        audioContextRef.current.close();
      } catch {}
      audioContextRef.current = null;
    }
  };

  // Draw Audio Waveform Visualization
  const startWaveformVisualizer = (stream: MediaStream) => {
    try {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      if (!AudioCtx) return;
      const audioCtx = new AudioCtx();
      audioContextRef.current = audioCtx;

      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 64;
      analyserRef.current = analyser;

      const source = audioCtx.createMediaStreamSource(stream);
      source.connect(analyser);

      const bufferLength = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);

      const draw = () => {
        if (!canvasRef.current || !isRecording) return;
        const canvas = canvasRef.current;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        analyser.getByteFrequencyData(dataArray);

        ctx.clearRect(0, 0, canvas.width, canvas.height);

        const barWidth = 3;
        const gap = 2;
        const totalBars = Math.floor(canvas.width / (barWidth + gap));
        let x = 0;

        for (let i = 0; i < totalBars; i++) {
          const dataIndex = Math.floor((i / totalBars) * bufferLength);
          const barHeight = Math.max(2, (dataArray[dataIndex] / 255) * (canvas.height - 2));

          const y = (canvas.height - barHeight) / 2;

          ctx.fillStyle = '#35D0BA';
          ctx.beginPath();
          ctx.roundRect(x, y, barWidth, barHeight, 1.5);
          ctx.fill();

          x += barWidth + gap;
        }

        animationFrameRef.current = requestAnimationFrame(draw);
      };

      draw();
    } catch (e) {
      console.warn('Audio visualization initialization skipped:', e);
    }
  };

  const startRecording = async () => {
    setErrorMessage(null);
    setLiveTranscript('');
    setRecordingSeconds(0);
    audioChunksRef.current = [];

    // Check device support
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setPermissionStatus('UNAVAILABLE');
      setErrorMessage('Voice input unavailable on this device.');
      return;
    }

    setPermissionStatus('REQUESTING');

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      setPermissionStatus('ALLOWED');
      setIsRecording(true);

      // Start Waveform Visualizer
      startWaveformVisualizer(stream);

      // Timer
      timerRef.current = setInterval(() => {
        setRecordingSeconds((prev) => prev + 1);
      }, 1000);

      // Feature-detect browser Web Speech API for real-time live preview
      const SpeechRecognition =
        (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

      if (SpeechRecognition) {
        try {
          const recognition = new SpeechRecognition();
          recognition.continuous = true;
          recognition.interimResults = true;
          recognition.lang = 'en-US';

          recognition.onresult = (event: any) => {
            let current = '';
            for (let i = 0; i < event.results.length; i++) {
              current += event.results[i][0].transcript + ' ';
            }
            setLiveTranscript(current.trim());
          };

          recognition.onerror = (e: any) => {
            console.warn('Speech recognition warning:', e);
          };

          recognition.start();
          recognitionRef.current = recognition;
        } catch (e) {
          console.warn('Web Speech API could not start, will rely on audio upload:', e);
        }
      }

      // Record audio via MediaRecorder for guaranteed server-side Whisper transcription
      let mimeType = 'audio/webm';
      if (!MediaRecorder.isTypeSupported('audio/webm')) {
        if (MediaRecorder.isTypeSupported('audio/mp4')) {
          mimeType = 'audio/mp4';
        } else if (MediaRecorder.isTypeSupported('audio/ogg')) {
          mimeType = 'audio/ogg';
        } else {
          mimeType = '';
        }
      }

      const mediaRecorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);

      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.start(250); // Slice chunks every 250ms
    } catch (err: any) {
      console.error('Microphone error:', err);
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        setPermissionStatus('DENIED');
        setErrorMessage(
          'Microphone access is blocked. Enable microphone access in your browser or system settings.'
        );
      } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
        setPermissionStatus('UNAVAILABLE');
        setErrorMessage('No microphone found on this device.');
      } else {
        setErrorMessage(`Recording failed: ${err.message || 'Unknown error'}`);
      }
      setIsRecording(false);
      cleanupAudio();
    }
  };

  const handleDone = async () => {
    if (!isRecording) return;
    setIsRecording(false);
    setIsProcessing(true);

    const capturedLiveTranscript = liveTranscript.trim();

    // If live transcript exists and is substantial, inject immediately
    if (capturedLiveTranscript) {
      cleanupAudio();
      setIsProcessing(false);
      onTranscriptionComplete(capturedLiveTranscript);
      return;
    }

    // Otherwise, perform server-side Whisper transcription from MediaRecorder chunks
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.onstop = async () => {
        await processAudioBlob();
      };
      mediaRecorderRef.current.stop();
    } else {
      await processAudioBlob();
    }
  };

  const processAudioBlob = async () => {
    try {
      const blob = new Blob(audioChunksRef.current, {
        type: mediaRecorderRef.current?.mimeType || 'audio/webm'
      });

      if (blob.size === 0) {
        if (liveTranscript) {
          onTranscriptionComplete(liveTranscript);
        } else {
          setErrorMessage("No speech detected. Couldn't transcribe audio.");
        }
        cleanupAudio();
        setIsProcessing(false);
        return;
      }

      const formData = new FormData();
      formData.append('file', blob, 'recording.webm');

      const response = await authFetch(`${apiBase}/api/v1/audio/transcribe`, {
        method: 'POST',
        body: formData
      });

      if (response.ok) {
        const result = await response.json();
        const transcribedText = (result.text || '').trim();
        if (transcribedText) {
          onTranscriptionComplete(transcribedText);
        } else if (liveTranscript) {
          onTranscriptionComplete(liveTranscript);
        } else {
          setErrorMessage('No speech detected.');
        }
      } else {
        if (liveTranscript) {
          onTranscriptionComplete(liveTranscript);
        } else {
          setErrorMessage("Couldn't transcribe that audio.");
        }
      }
    } catch (e: any) {
      if (liveTranscript) {
        onTranscriptionComplete(liveTranscript);
      } else {
        setErrorMessage(`Transcription failed: ${e.message || 'Network error'}`);
      }
    } finally {
      cleanupAudio();
      setIsProcessing(false);
    }
  };

  const handleCancel = () => {
    cleanupAudio();
    setIsRecording(false);
    setIsProcessing(false);
    setLiveTranscript('');
  };

  const formatSeconds = (sec: number) => {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  };

  useImperativeHandle(ref, () => ({
    startRecording,
    stopRecording: handleDone,
    isRecording
  }), [isRecording]);

  return (
    <div className={`relative ${className}`}>
      {/* Microphone Trigger Button */}
      {!isRecording && !isProcessing && (
        <button
          type="button"
          onClick={startRecording}
          aria-label="Start voice input"
          title="Dictate message with speech-to-text"
          className="w-10 h-10 text-[#E0E0E0] hover:text-white hover:bg-white/[0.08] rounded-full transition-colors cursor-pointer flex items-center justify-center select-none"
        >
          <svg
            className="w-5 h-5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" x2="12" y1="19" y2="22" />
          </svg>
        </button>
      )}

      {/* Active Recording State Bar Overlay */}
      {isRecording && (
        <div
          role="status"
          aria-live="polite"
          className="absolute inset-0 bg-[#262626] rounded-full px-3 py-1.5 flex items-center justify-between z-20 border border-white/[0.1] animate-in fade-in duration-100"
        >
          <div className="flex items-center gap-2 min-w-0">
            <div className="relative flex items-center justify-center flex-shrink-0">
              <span className="absolute w-5 h-5 rounded-full bg-[#FF453A]/25 animate-ping" />
              <SakuraLogo size={18} alt="" />
            </div>
            <span className="text-[13px] font-medium text-white select-none whitespace-nowrap">
              Listening...
            </span>
            <span className="text-[11px] font-mono text-[#888888]">{formatSeconds(recordingSeconds)}</span>

            {/* Waveform Canvas */}
            <canvas ref={canvasRef} width={70} height={18} className="ml-1 opacity-80" />

            {liveTranscript && (
              <span className="text-[11.5px] text-[#C0C0C0] italic truncate max-w-[140px] ml-1">
                "{liveTranscript}"
              </span>
            )}
          </div>

          <div className="flex items-center gap-1.5 flex-shrink-0">
            <button
              type="button"
              onClick={handleCancel}
              className="px-2.5 py-1 text-[12px] text-[#888888] hover:text-white hover:bg-white/[0.08] rounded-full transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleDone}
              className="px-3 py-1 text-[12px] font-medium text-white bg-[#2F95F6] hover:bg-[#2580D8] rounded-full transition-colors cursor-pointer flex items-center gap-1"
            >
              <span>Done</span>
            </button>
          </div>
        </div>
      )}

      {/* Processing State */}
      {isProcessing && (
        <div
          role="status"
          aria-live="polite"
          className="absolute inset-0 bg-[#1E1E1E] rounded-full px-4 py-1.5 flex items-center justify-center gap-2.5 z-20 border border-[#3A3A3A]"
        >
          <SakuraLogo size={18} className="animate-pulse" alt="" />
          <span className="text-[12px] text-[#D0D0D0]">Transcribing speech...</span>
        </div>
      )}

      {/* Error Message Toast */}
      {errorMessage && (
        <div
          role="alert"
          className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-max max-w-[320px] bg-[#2A1515] border border-[#5C2323] text-[#FF8585] text-[11.5px] px-3 py-2 rounded-xl shadow-xl z-50 flex items-center justify-between gap-2"
        >
          <span>{errorMessage}</span>
          <button
            onClick={() => setErrorMessage(null)}
            className="text-[#FF8585] hover:text-white font-bold text-xs"
          >
            ✕
          </button>
        </div>
      )}
    </div>
  );
});

VoiceRecorder.displayName = 'VoiceRecorder';
