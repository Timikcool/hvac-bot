'use client';

import React, { useState } from 'react';
import { EquipmentContext } from '@/types';

interface Props {
  value: EquipmentContext | null;
  onChange: (equipment: EquipmentContext | null) => void;
  onScanRequest: () => void;
}

const COMMON_BRANDS = [
  'Carrier',
  'Trane',
  'Lennox',
  'Rheem',
  'Goodman',
  'York',
  'Daikin',
  'Mitsubishi',
  'Fujitsu',
  'Bryant',
  'American Standard',
  'Ruud',
];

const SYSTEM_TYPES = [
  { value: 'split', label: 'Split System' },
  { value: 'package', label: 'Package Unit' },
  { value: 'mini_split', label: 'Mini-Split' },
  { value: 'heat_pump', label: 'Heat Pump' },
  { value: 'furnace', label: 'Furnace' },
  { value: 'boiler', label: 'Boiler' },
  { value: 'rooftop', label: 'Rooftop Unit' },
  { value: 'chiller', label: 'Chiller' },
];

export function EquipmentSelector({ value, onChange, onScanRequest }: Props) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [manualEntry, setManualEntry] = useState(false);

  const handleFieldChange = (field: keyof EquipmentContext, fieldValue: string) => {
    const newEquipment: EquipmentContext = {
      ...value,
      [field]: fieldValue || undefined,
    };
    onChange(newEquipment);
  };

  const handleClear = () => {
    onChange(null);
    setManualEntry(false);
  };

  if (value && !isExpanded) {
    return (
      <div className="flex items-center justify-between">
        <button
          onClick={() => setIsExpanded(true)}
          className="flex items-center space-x-2 text-left"
        >
          <span className="text-2xl">🔧</span>
          <div>
            <p className="font-semibold">
              {value.brand || 'Unknown Brand'} {value.model || ''}
            </p>
            {value.systemType && (
              <p className="text-sm text-blue-200">
                {SYSTEM_TYPES.find(t => t.value === value.systemType)?.label || value.systemType}
              </p>
            )}
          </div>
        </button>
        <button
          onClick={handleClear}
          className="p-2 hover:bg-blue-700 rounded"
          aria-label="Clear equipment"
        >
          ✕
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">Equipment Selection</h2>
        {value && (
          <button
            onClick={() => setIsExpanded(false)}
            className="text-sm hover:underline"
          >
            Collapse
          </button>
        )}
      </div>

      {!manualEntry ? (
        <div className="space-y-2">
          <button
            onClick={onScanRequest}
            className="w-full bg-white text-blue-600 font-semibold py-3 px-4 rounded-lg flex items-center justify-center space-x-2 hover:bg-blue-50 transition-colors"
          >
            <span>📷</span>
            <span>Scan Nameplate</span>
          </button>

          <button
            onClick={() => setManualEntry(true)}
            className="w-full bg-blue-700 text-white py-2 px-4 rounded-lg text-sm hover:bg-blue-800 transition-colors"
          >
            Enter Manually
          </button>
        </div>
      ) : (
        <div className="space-y-3 bg-blue-700 rounded-lg p-3">
          {/* Brand Selection */}
          <div>
            <label className="block text-sm mb-1">Brand</label>
            <select
              value={value?.brand || ''}
              onChange={(e) => handleFieldChange('brand', e.target.value)}
              className="w-full p-2 rounded bg-white text-gray-900"
            >
              <option value="">Select brand...</option>
              {COMMON_BRANDS.map((brand) => (
                <option key={brand} value={brand}>
                  {brand}
                </option>
              ))}
              <option value="other">Other</option>
            </select>
          </div>

          {/* Model Number */}
          <div>
            <label className="block text-sm mb-1">Model Number</label>
            <input
              type="text"
              value={value?.model || ''}
              onChange={(e) => handleFieldChange('model', e.target.value)}
              placeholder="e.g., 24ACC636A003"
              className="w-full p-2 rounded bg-white text-gray-900"
            />
          </div>

          {/* System Type */}
          <div>
            <label className="block text-sm mb-1">System Type</label>
            <select
              value={value?.systemType || ''}
              onChange={(e) => handleFieldChange('systemType', e.target.value)}
              className="w-full p-2 rounded bg-white text-gray-900"
            >
              <option value="">Select type...</option>
              {SYSTEM_TYPES.map((type) => (
                <option key={type.value} value={type.value}>
                  {type.label}
                </option>
              ))}
            </select>
          </div>

          {/* Serial Number (optional) */}
          <div>
            <label className="block text-sm mb-1">Serial Number (optional)</label>
            <input
              type="text"
              value={value?.serial || ''}
              onChange={(e) => handleFieldChange('serial', e.target.value)}
              placeholder="e.g., 1234567890"
              className="w-full p-2 rounded bg-white text-gray-900"
            />
          </div>

          <div className="flex space-x-2 pt-2">
            <button
              onClick={() => setManualEntry(false)}
              className="flex-1 bg-blue-800 text-white py-2 rounded hover:bg-blue-900 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                setManualEntry(false);
                setIsExpanded(false);
              }}
              className="flex-1 bg-white text-blue-600 font-semibold py-2 rounded hover:bg-blue-50 transition-colors"
            >
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
