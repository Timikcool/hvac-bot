'use client';

import React from 'react';

interface Props {
  warning: string;
}

export function SafetyWarning({ warning }: Props) {
  const severityLevel = getSeverityLevel(warning);

  const bgColors = {
    danger: 'bg-red-100 border-red-400',
    warning: 'bg-orange-100 border-orange-400',
    caution: 'bg-yellow-100 border-yellow-400',
  };

  const textColors = {
    danger: 'text-red-800',
    warning: 'text-orange-800',
    caution: 'text-yellow-800',
  };

  const icons = {
    danger: '🚨',
    warning: '⚠️',
    caution: '⚡',
  };

  return (
    <div
      className={`border-l-4 p-3 rounded-r ${bgColors[severityLevel]} ${textColors[severityLevel]}`}
      role="alert"
    >
      <div className="flex items-start">
        <span className="text-lg mr-2" aria-hidden="true">
          {icons[severityLevel]}
        </span>
        <div>
          <p className="font-semibold text-sm uppercase mb-1">
            {severityLevel === 'danger' ? 'DANGER' : severityLevel === 'warning' ? 'WARNING' : 'CAUTION'}
          </p>
          <p className="text-sm">{warning}</p>
        </div>
      </div>
    </div>
  );
}

function getSeverityLevel(warning: string): 'danger' | 'warning' | 'caution' {
  const lowerWarning = warning.toLowerCase();

  if (
    lowerWarning.includes('danger') ||
    lowerWarning.includes('fatal') ||
    lowerWarning.includes('death') ||
    lowerWarning.includes('high voltage') ||
    lowerWarning.includes('electrocution')
  ) {
    return 'danger';
  }

  if (
    lowerWarning.includes('warning') ||
    lowerWarning.includes('injury') ||
    lowerWarning.includes('hazard') ||
    lowerWarning.includes('refrigerant') ||
    lowerWarning.includes('pressur')
  ) {
    return 'warning';
  }

  return 'caution';
}
