'use client';

import React from 'react';
import { Message, Citation } from '@/types';
import { SafetyWarning } from './SafetyWarning';
import { ConfidenceBadge } from './ConfidenceBadge';

interface Props {
  message: Message;
  onCitationClick: (citation: Citation) => void;
  onFollowupClick: (question: string) => void;
  onFeedback?: (messageId: string, rating: number) => void;
}

export function MessageBubble({ message, onCitationClick, onFollowupClick, onFeedback }: Props) {
  const [userRating, setUserRating] = React.useState<number | null>(message.userRating || null);
  const [hoveredStar, setHoveredStar] = React.useState<number>(0);
  const [feedbackSubmitted, setFeedbackSubmitted] = React.useState(false);

  const handleRating = (rating: number) => {
    setUserRating(rating);
    setFeedbackSubmitted(true);
    if (onFeedback && message.id) {
      onFeedback(message.id, rating);
    }
  };
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="bg-blue-600 text-white rounded-lg p-3 max-w-[80%]">
          {message.imageUrl && (
            <img
              src={message.imageUrl}
              alt="Uploaded image"
              className="max-w-full rounded mb-2"
            />
          )}
          <p className="whitespace-pre-wrap">{message.content}</p>
          <p className="text-xs text-blue-200 mt-1">
            {formatTime(message.timestamp)}
          </p>
        </div>
      </div>
    );
  }

  if (message.role === 'system') {
    return (
      <div className="flex justify-center">
        <div className="bg-gray-200 text-gray-600 rounded-full px-4 py-2 text-sm">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="bg-white rounded-lg shadow p-4 max-w-[90%] space-y-3">
        {/* Safety Warnings First */}
        {message.safetyWarnings?.map((warning, i) => (
          <SafetyWarning key={i} warning={warning} />
        ))}

        {/* Main Content */}
        <div className="prose prose-sm max-w-none">
          {formatContentWithCitations(message.content, message.citations || [], onCitationClick)}
        </div>

        {/* Confidence Indicator */}
        {message.confidence && (
          <div className="pt-2">
            <ConfidenceBadge level={message.confidence} />
          </div>
        )}

        {/* Source Legend */}
        {message.citations && message.citations.length > 0 && (
          <div className="border-t pt-2 mt-2">
            <p className="text-xs text-gray-500 mb-2">Sources:</p>
            <div className="space-y-1">
              {message.citations.map((citation, i) => (
                <button
                  key={i}
                  onClick={() => onCitationClick(citation)}
                  className="flex items-start gap-2 text-xs text-left w-full hover:bg-blue-50 p-1 rounded transition-colors"
                >
                  <span className="bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded font-medium shrink-0">
                    {citation.sourceNumber}
                  </span>
                  <span className="text-gray-700">
                    {citation.title || citation.manual || 'Unknown Source'}
                    {citation.page && citation.page.length > 0 && (
                      <span className="text-gray-500"> • p.{citation.page.join(', ')}</span>
                    )}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}


        {/* Rating and Timestamp */}
        <div className="flex items-center justify-between mt-3 pt-2 border-t border-gray-100">
          {/* Star Rating */}
          <div className="flex items-center gap-1">
            {!feedbackSubmitted ? (
              <>
                <span className="text-xs text-gray-400 mr-1">Rate:</span>
                {[1, 2, 3, 4, 5].map((star) => (
                  <button
                    key={star}
                    onClick={() => handleRating(star)}
                    onMouseEnter={() => setHoveredStar(star)}
                    onMouseLeave={() => setHoveredStar(0)}
                    className={`text-xl transition-transform hover:scale-110 ${
                      star <= (hoveredStar || userRating || 0) 
                        ? 'text-yellow-400' 
                        : 'text-gray-300'
                    }`}
                    aria-label={`Rate ${star} stars`}
                  >
                    {star <= (hoveredStar || userRating || 0) ? '★' : '☆'}
                  </button>
                ))}
              </>
            ) : (
              <span className="text-xs text-green-600 flex items-center gap-1">
                <span>✓</span> Thanks! Rated {userRating}★
              </span>
            )}
          </div>
          
          {/* Response Time & Timestamp */}
          <div className="text-xs text-gray-400 text-right">
            {message.responseTimeMs && (
              <span className="mr-2">{(message.responseTimeMs / 1000).toFixed(1)}s</span>
            )}
            {formatTime(message.timestamp)}
          </div>
        </div>
      </div>
    </div>
  );
}

function formatContentWithCitations(
  content: string,
  citations: Citation[],
  onCitationClick: (citation: Citation) => void
): React.ReactNode {
  // Match various citation patterns: [Source 1], [Source 1, Source 2], Source 1, etc.
  const citationPattern = /(\[Source \d+(?:,\s*Source \d+)*\]|\[Source \d+\])/g;
  const parts = content.split(citationPattern);

  return parts.map((part, i) => {
    // Check if this part contains source references
    const sourceMatches = part.match(/Source (\d+)/g);
    if (sourceMatches && part.startsWith('[')) {
      // Extract all source numbers from this part
      const sourceNumbers = sourceMatches.map(m => parseInt(m.replace('Source ', '')));
      
      return (
        <span key={i}>
          {'['}
          {sourceNumbers.map((num, idx) => {
            const citation = citations.find(c => c.sourceNumber === num) || { sourceNumber: num };
            return (
              <React.Fragment key={num}>
                {idx > 0 && ', '}
                <button
                  onClick={() => onCitationClick(citation as Citation)}
                  className="text-blue-600 hover:underline font-medium"
                >
                  Source {num}
                </button>
              </React.Fragment>
            );
          })}
          {']'}
        </span>
      );
    }

    // Handle line breaks and basic formatting
    return (
      <span key={i}>
        {part.split('\n').map((line, lineIndex) => (
          <React.Fragment key={lineIndex}>
            {lineIndex > 0 && <br />}
            {formatLine(line)}
          </React.Fragment>
        ))}
      </span>
    );
  });
}

function formatLine(line: string): React.ReactNode {
  // Handle headers
  if (line.startsWith('## ')) {
    return <h3 className="font-bold text-lg mt-3 mb-1">{formatInline(line.slice(3))}</h3>;
  }
  if (line.startsWith('# ')) {
    return <h2 className="font-bold text-xl mt-4 mb-2">{formatInline(line.slice(2))}</h2>;
  }
  
  // Handle numbered lists
  const numberedMatch = line.match(/^(\d+)\.\s+(.+)/);
  if (numberedMatch) {
    return (
      <div className="flex gap-2 ml-2">
        <span className="font-medium text-gray-600">{numberedMatch[1]}.</span>
        <span>{formatInline(numberedMatch[2])}</span>
      </div>
    );
  }
  
  // Handle bullet lists
  if (line.startsWith('- ') || line.startsWith('• ')) {
    return (
      <div className="flex gap-2 ml-2">
        <span className="text-gray-400">•</span>
        <span>{formatInline(line.slice(2))}</span>
      </div>
    );
  }
  
  return formatInline(line);
}

function formatInline(text: string): React.ReactNode {
  // Bold text between ** **
  const parts = text.split(/(\*\*[^*]+\*\*)/g);

  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}

function formatTime(date: Date): string {
  return new Intl.DateTimeFormat('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }).format(date);
}
