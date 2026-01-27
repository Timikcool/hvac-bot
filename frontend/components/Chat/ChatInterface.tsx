'use client';

import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Message, EquipmentContext, ChatResponse, Citation } from '@/types';
import { chatApi } from '@/api/chat';
import { MessageBubble } from './MessageBubble';
import { VoiceInput } from './VoiceInput';
import { EquipmentSelector } from '../Equipment/EquipmentSelector';
import { ImageCapture } from '../Camera/ImageCapture';
import { useOfflineQueue } from '@/hooks/useOfflineQueue';

// Debug logging
const DEBUG = process.env.NODE_ENV === 'development';
function log(action: string, data?: unknown) {
  if (DEBUG) {
    const timestamp = new Date().toISOString().slice(11, 23);
    console.log(`[${timestamp}] [ChatInterface] ${action}`, data ?? '');
  }
}

export function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [equipment, setEquipment] = useState<EquipmentContext | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [showCamera, setShowCamera] = useState(false);
  const [isProcessingImage, setIsProcessingImage] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const {
    isOnline,
    pendingCount,
    queueQuery,
    processQueue,
    cacheResponse,
    getCachedResponse,
  } = useOfflineQueue();

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Process queued messages when back online
  useEffect(() => {
    if (isOnline && pendingCount > 0) {
      processQueue(async (query, eq) => {
        const response = await chatApi.sendMessage({
          message: query,
          equipment: eq || undefined,
          conversationId: conversationId || undefined,
        });
        return response;
      });
    }
  }, [isOnline, pendingCount, processQueue, conversationId]);

  // Chat mutation
  const chatMutation = useMutation({
    mutationFn: async (message: string) => {
      log('mutationFn called', { messageLength: message.length, hasEquipment: !!equipment });

      // Check cache first
      const cached = await getCachedResponse(message, equipment);
      if (cached) {
        log('Cache hit - returning cached response');
        return { ...cached, fromCache: true };
      }

      log('Cache miss - calling API');
      const response = await chatApi.sendMessage({
        message,
        equipment: equipment || undefined,
        conversationId: conversationId || undefined,
      });

      // Cache the response
      await cacheResponse(message, equipment, response);
      log('Response cached');

      return response;
    },
    onSuccess: (response: ChatResponse & { fromCache?: boolean }) => {
      log('onSuccess', {
        fromCache: response.fromCache,
        confidence: response.confidence,
        requiresEscalation: response.requiresEscalation,
      });

      setConversationId(response.conversationId);

      const assistantMessage: Message = {
        id: response.messageId || crypto.randomUUID(),
        role: 'assistant',
        content: response.answer,
        citations: response.citations,
        safetyWarnings: response.safetyWarnings,
        confidence: response.confidence,
        requiresEscalation: response.requiresEscalation,
        suggestedFollowups: response.suggestedFollowups,
        timestamp: new Date(),
        responseTimeMs: response.responseTimeMs,
      };

      setMessages((prev) => [...prev, assistantMessage]);
    },
    onError: async (error: Error, message: string) => {
      log('onError', { error: error.message, isOnline });
      console.error('Chat error:', error);

      if (!isOnline) {
        // Queue for later
        await queueQuery(message, equipment);

        const offlineMessage: Message = {
          id: crypto.randomUUID(),
          role: 'system',
          content: 'You are offline. Your question has been saved and will be processed when you reconnect.',
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, offlineMessage]);
      } else {
        const errorMessage: Message = {
          id: crypto.randomUUID(),
          role: 'system',
          content: 'Sorry, there was an error processing your request. Please try again.',
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, errorMessage]);
      }
    },
  });

  const handleSend = useCallback(() => {
    const trimmedInput = input.trim();
    if (!trimmedInput) return;

    log('handleSend', { inputLength: trimmedInput.length, equipment });

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: trimmedInput,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    chatMutation.mutate(trimmedInput);
    setInput('');
    inputRef.current?.focus();
  }, [input, chatMutation, equipment]);

  const handleKeyPress = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  const handleImageCapture = useCallback(
    async (imageBlob: Blob, type: 'equipment' | 'problem') => {
      log('handleImageCapture', { type, blobSize: imageBlob.size });
      setShowCamera(false);
      setIsProcessingImage(true);

      try {
        if (type === 'equipment') {
          // Scan nameplate
          log('Scanning equipment nameplate...');
          const result = await chatApi.scanEquipment(imageBlob);
          log('Equipment scan result', { brand: result.brand, model: result.model, confidence: result.confidence });

          setEquipment({
            brand: result.brand,
            model: result.model,
            serial: result.serial,
          });

          const systemMessage: Message = {
            id: crypto.randomUUID(),
            role: 'system',
            content: `Equipment identified: ${result.brand} ${result.model}${
              result.manualsAvailable.length > 0
                ? ` (${result.manualsAvailable.length} manuals available)`
                : ''
            }`,
            timestamp: new Date(),
          };
          setMessages((prev) => [...prev, systemMessage]);

          if (result.confidence < 0.7) {
            const warningMessage: Message = {
              id: crypto.randomUUID(),
              role: 'system',
              content:
                'Low confidence in equipment identification. Please verify the model number is correct.',
              timestamp: new Date(),
            };
            setMessages((prev) => [...prev, warningMessage]);
          }
        } else {
          // Analyze problem image
          const description = input || 'Analyze this component for issues';
          log('Analyzing problem image', { description, hasEquipment: !!equipment });
          const result = await chatApi.analyzeImage(imageBlob, description, equipment);
          log('Image analysis result', {
            issuesFound: result.visibleIssues.length,
            confidence: result.confidence,
          });

          // Create URL for the image
          const imageUrl = URL.createObjectURL(imageBlob);

          const userMessage: Message = {
            id: crypto.randomUUID(),
            role: 'user',
            content: description,
            imageUrl,
            timestamp: new Date(),
          };

          // Build analysis response
          let analysisContent = '';

          if (result.visibleIssues.length > 0) {
            analysisContent += '**Visible Issues:**\n';
            result.visibleIssues.forEach((issue) => {
              const severityEmoji =
                issue.severity === 'critical'
                  ? '🚨'
                  : issue.severity === 'high'
                  ? '⚠️'
                  : issue.severity === 'medium'
                  ? '⚡'
                  : 'ℹ️';
              analysisContent += `${severityEmoji} ${issue.description}\n`;
            });
            analysisContent += '\n';
          }

          if (result.suggestedCauses.length > 0) {
            analysisContent += '**Possible Causes:**\n';
            result.suggestedCauses.forEach((cause) => {
              analysisContent += `• ${cause}\n`;
            });
            analysisContent += '\n';
          }

          if (result.recommendedChecks.length > 0) {
            analysisContent += '**Recommended Checks:**\n';
            result.recommendedChecks.forEach((check, i) => {
              analysisContent += `${i + 1}. ${check}\n`;
            });
          }

          if (result.requiresPhysicalInspection) {
            analysisContent +=
              '\n⚠️ Physical inspection recommended for accurate diagnosis.';
          }

          const analysisMessage: Message = {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: analysisContent || 'No visible issues detected in the image.',
            confidence:
              result.confidence > 0.8
                ? 'high'
                : result.confidence > 0.5
                ? 'medium'
                : 'low',
            timestamp: new Date(),
          };

          setMessages((prev) => [...prev, userMessage, analysisMessage]);
          setInput('');
        }
      } catch (error) {
        console.error('Image processing error:', error);
        const errorMessage: Message = {
          id: crypto.randomUUID(),
          role: 'system',
          content: 'Failed to process image. Please try again.',
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, errorMessage]);
      } finally {
        setIsProcessingImage(false);
      }
    },
    [equipment, input]
  );

  const handleCitationClick = useCallback((citation: Citation) => {
    // In a full implementation, this would open a manual viewer
    console.log('Citation clicked:', citation);
    const title = citation.title || citation.manual || 'Unknown Source';
    const pages = citation.page && citation.page.length > 0 
      ? `page ${citation.page.join(', ')}` 
      : 'page not specified';
    alert(
      `📖 ${title}\n\n${pages}\n\n(Manual viewer coming soon)`
    );
  }, []);

  const handleFollowupClick = useCallback((question: string) => {
    setInput(question);
    inputRef.current?.focus();
  }, []);

  const handleFeedback = useCallback(async (messageId: string, rating: number) => {
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api'}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message_id: messageId, rating }),
      });
      
      if (response.ok) {
        console.log('Feedback submitted:', { messageId, rating });
        // Update the message with the rating
        setMessages((prev) => 
          prev.map((m) => m.id === messageId ? { ...m, userRating: rating } : m)
        );
      }
    } catch (error) {
      console.error('Failed to submit feedback:', error);
    }
  }, []);

  return (
    <div className="flex flex-col h-screen bg-gray-100">
      {/* Offline Banner */}
      {!isOnline && (
        <div className="bg-yellow-500 text-yellow-900 px-4 py-2 text-center text-sm">
          You are offline. Messages will be sent when you reconnect.
          {pendingCount > 0 && ` (${pendingCount} pending)`}
        </div>
      )}

      {/* Equipment Header */}
      <header className="bg-blue-600 text-white p-4 shadow-md">
        <EquipmentSelector
          value={equipment}
          onChange={setEquipment}
          onScanRequest={() => setShowCamera(true)}
        />
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-gray-500 mt-8">
            <div className="text-6xl mb-4">🔧</div>
            <h2 className="text-xl font-semibold mb-2">HVAC AI Assistant</h2>
            <p className="text-sm max-w-md mx-auto">
              Ask questions about equipment troubleshooting, error codes, specifications,
              or take a photo to identify equipment and diagnose issues.
            </p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              <QuickAction
                text="What does error code E1 mean?"
                onClick={() => setInput('What does error code E1 mean?')}
              />
              <QuickAction
                text="Compressor not starting"
                onClick={() => setInput('Compressor not starting, what should I check?')}
              />
              <QuickAction
                text="Check refrigerant charge"
                onClick={() => setInput('How do I check the refrigerant charge?')}
              />
            </div>
          </div>
        )}

        {messages.map((message) => (
          <MessageBubble
            key={message.id}
            message={message}
            onCitationClick={handleCitationClick}
            onFollowupClick={handleFollowupClick}
            onFeedback={handleFeedback}
          />
        ))}

        {(chatMutation.isPending || isProcessingImage) && (
          <div className="flex items-center space-x-2 text-gray-500">
            <LoadingSpinner />
            <span>
              {isProcessingImage ? 'Analyzing image...' : 'Searching manuals...'}
            </span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="border-t bg-white p-4 shadow-lg">
        <div className="flex items-center space-x-2 max-w-4xl mx-auto">
          <button
            onClick={() => setShowCamera(true)}
            className="p-3 rounded-full bg-gray-100 hover:bg-gray-200 transition-colors"
            aria-label="Take photo"
            title="Camera"
          >
            <CameraIcon className="w-5 h-5 text-gray-600" />
          </button>

          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Describe the issue or ask a question..."
            className="flex-1 p-3 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            disabled={chatMutation.isPending || isProcessingImage}
          />

          <VoiceInput onTranscript={(text) => setInput((prev) => prev + ' ' + text)} />

          <button
            onClick={handleSend}
            disabled={!input.trim() || chatMutation.isPending || isProcessingImage}
            className="p-3 bg-blue-600 text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed hover:bg-blue-700 transition-colors"
            aria-label="Send message"
          >
            <SendIcon className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Camera Modal */}
      {showCamera && (
        <ImageCapture
          onCapture={handleImageCapture}
          onClose={() => setShowCamera(false)}
        />
      )}
    </div>
  );
}

function QuickAction({ text, onClick }: { text: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="bg-white border border-gray-300 px-3 py-2 rounded-full text-sm hover:bg-gray-50 transition-colors"
    >
      {text}
    </button>
  );
}

function LoadingSpinner() {
  return (
    <svg
      className="animate-spin h-5 w-5 text-blue-600"
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
}

function CameraIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"
      />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M15 13a3 3 0 11-6 0 3 3 0 016 0z"
      />
    </svg>
  );
}

function SendIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
      />
    </svg>
  );
}
