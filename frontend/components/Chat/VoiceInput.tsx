'use client';

import React, { useState, useRef, useCallback, useEffect } from 'react';
import type { SpeechRecognition, SpeechRecognitionEvent, SpeechRecognitionErrorEvent } from '@/types';

interface Props {
  onTranscript: (text: string) => void;
}

export function VoiceInput({ onTranscript }: Props) {
  const [isListening, setIsListening] = useState(false);
  const [isSupported, setIsSupported] = useState(true);
  const [interimTranscript, setInterimTranscript] = useState('');
  const recognitionRef = useRef<SpeechRecognition | null>(null);

  useEffect(() => {
    const hasSpeechRecognition =
      'webkitSpeechRecognition' in window || 'SpeechRecognition' in window;
    setIsSupported(hasSpeechRecognition);
  }, []);

  const startListening = useCallback(() => {
    if (!isSupported) {
      alert('Speech recognition is not supported in this browser');
      return;
    }

    const SpeechRecognitionAPI =
      (window as Window).SpeechRecognition ||
      (window as Window).webkitSpeechRecognition;

    const recognition = new SpeechRecognitionAPI();

    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    // Add HVAC terminology to grammar if supported
    if ('webkitSpeechGrammarList' in window) {
      try {
        const SpeechGrammarListAPI = (window as Window).webkitSpeechGrammarList;
        const grammar = `
          #JSGF V1.0;
          grammar hvac;
          public <hvac_terms> = compressor | condenser | evaporator |
            refrigerant | thermostat | capacitor | contactor |
            blower | heat pump | air handler | superheat | subcooling |
            TXV | expansion valve | R410A | R22 | R134a |
            amp draw | voltage | ohms | pressure | PSI |
            error code | fault code | LED | flashing ;
        `;
        const speechGrammarList = new SpeechGrammarListAPI();
        speechGrammarList.addFromString(grammar, 1);
        recognition.grammars = speechGrammarList;
      } catch {
        // Grammar not supported, continue without it
      }
    }

    recognition.onstart = () => {
      setIsListening(true);
      setInterimTranscript('');
    };

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let interim = '';
      let final = '';

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          final += transcript;
        } else {
          interim += transcript;
        }
      }

      setInterimTranscript(interim);

      if (final) {
        onTranscript(final);
        setInterimTranscript('');
      }
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      console.error('Speech recognition error:', event.error);
      setIsListening(false);
      setInterimTranscript('');

      if (event.error === 'not-allowed') {
        alert('Microphone access denied. Please enable microphone permissions.');
      }
    };

    recognition.onend = () => {
      setIsListening(false);
      setInterimTranscript('');
    };

    recognitionRef.current = recognition;
    recognition.start();
  }, [isSupported, onTranscript]);

  const stopListening = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }
  }, []);

  if (!isSupported) {
    return null;
  }

  return (
    <div className="relative">
      <button
        onClick={isListening ? stopListening : startListening}
        className={`p-2 rounded-full transition-all ${
          isListening
            ? 'bg-red-500 text-white animate-pulse scale-110'
            : 'bg-gray-100 hover:bg-gray-200 text-gray-600'
        }`}
        aria-label={isListening ? 'Stop listening' : 'Start voice input'}
        title={isListening ? 'Click to stop' : 'Voice input'}
      >
        <MicrophoneIcon className="w-5 h-5" />
      </button>

      {/* Interim transcript tooltip */}
      {isListening && interimTranscript && (
        <div className="absolute bottom-full mb-2 left-1/2 transform -translate-x-1/2 bg-black/80 text-white text-sm px-3 py-1 rounded whitespace-nowrap max-w-[200px] truncate">
          {interimTranscript}
        </div>
      )}

      {/* Listening indicator */}
      {isListening && (
        <div className="absolute -top-1 -right-1 w-3 h-3 bg-red-500 rounded-full animate-ping" />
      )}
    </div>
  );
}

function MicrophoneIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"
      />
    </svg>
  );
}
