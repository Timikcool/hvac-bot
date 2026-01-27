'use client';

import React, { useState, useEffect } from 'react';
import { chatApi } from '@/api/chat';

interface Props {
  manualId: string;
  initialPage?: number;
  onClose: () => void;
}

export function ManualViewer({ manualId, initialPage = 1, onClose }: Props) {
  const [currentPage, setCurrentPage] = useState(initialPage);
  const [pageImage, setPageImage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [totalPages, setTotalPages] = useState(0);

  useEffect(() => {
    const loadPage = async () => {
      setIsLoading(true);
      setError(null);

      try {
        const blob = await chatApi.getManualPage(manualId, currentPage);
        const url = URL.createObjectURL(blob);
        setPageImage(url);
      } catch (err) {
        setError('Failed to load page');
        console.error('Manual page load error:', err);
      } finally {
        setIsLoading(false);
      }
    };

    loadPage();

    return () => {
      if (pageImage) {
        URL.revokeObjectURL(pageImage);
      }
    };
  }, [manualId, currentPage]);

  const handlePrevPage = () => {
    if (currentPage > 1) {
      setCurrentPage((p) => p - 1);
    }
  };

  const handleNextPage = () => {
    if (currentPage < totalPages) {
      setCurrentPage((p) => p + 1);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/80 z-50 flex flex-col">
      {/* Header */}
      <div className="bg-gray-900 text-white p-4 flex items-center justify-between">
        <button
          onClick={onClose}
          className="p-2 hover:bg-gray-700 rounded"
          aria-label="Close manual"
        >
          ✕
        </button>

        <div className="flex items-center space-x-4">
          <button
            onClick={handlePrevPage}
            disabled={currentPage <= 1}
            className="p-2 hover:bg-gray-700 rounded disabled:opacity-50"
            aria-label="Previous page"
          >
            ←
          </button>

          <span className="text-sm">
            Page {currentPage} {totalPages > 0 && `of ${totalPages}`}
          </span>

          <button
            onClick={handleNextPage}
            disabled={currentPage >= totalPages}
            className="p-2 hover:bg-gray-700 rounded disabled:opacity-50"
            aria-label="Next page"
          >
            →
          </button>
        </div>

        <div className="w-10" /> {/* Spacer */}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-4 flex items-center justify-center">
        {isLoading && (
          <div className="text-white">Loading...</div>
        )}

        {error && (
          <div className="text-red-400">{error}</div>
        )}

        {pageImage && !isLoading && (
          <img
            src={pageImage}
            alt={`Manual page ${currentPage}`}
            className="max-w-full max-h-full object-contain"
          />
        )}
      </div>

      {/* Page input */}
      <div className="bg-gray-900 p-4 flex justify-center">
        <div className="flex items-center space-x-2">
          <span className="text-white text-sm">Go to page:</span>
          <input
            type="number"
            min={1}
            max={totalPages || undefined}
            value={currentPage}
            onChange={(e) => {
              const page = parseInt(e.target.value);
              if (page >= 1 && (!totalPages || page <= totalPages)) {
                setCurrentPage(page);
              }
            }}
            className="w-16 p-1 rounded text-center"
          />
        </div>
      </div>
    </div>
  );
}
