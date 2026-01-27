'use client';

import React from 'react';
import { ConfidenceLevel } from '@/types';

interface Props {
  level: ConfidenceLevel;
}

export function ConfidenceBadge({ level }: Props) {
  const config = {
    high: {
      bg: 'bg-green-100',
      text: 'text-green-800',
      border: 'border-green-300',
      label: 'High confidence',
      icon: '✓',
    },
    medium: {
      bg: 'bg-yellow-100',
      text: 'text-yellow-800',
      border: 'border-yellow-300',
      label: 'Medium confidence',
      icon: '~',
    },
    low: {
      bg: 'bg-orange-100',
      text: 'text-orange-800',
      border: 'border-orange-300',
      label: 'Low confidence - verify',
      icon: '!',
    },
    none: {
      bg: 'bg-red-100',
      text: 'text-red-800',
      border: 'border-red-300',
      label: 'No source found',
      icon: '?',
    },
  };

  const { bg, text, border, label, icon } = config[level];

  return (
    <div
      className={`inline-flex items-center px-2 py-1 rounded text-xs border ${bg} ${text} ${border}`}
      title={`Confidence level: ${level}`}
    >
      <span className="font-bold mr-1">{icon}</span>
      <span>{label}</span>
    </div>
  );
}
