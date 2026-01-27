'use client';

import React, { useState, useRef, useCallback, useEffect } from 'react';

type CaptureType = 'equipment' | 'problem';

interface Props {
  onCapture: (imageBlob: Blob, type: CaptureType) => void;
  onClose: () => void;
}

export function ImageCapture({ onCapture, onClose }: Props) {
  const [captureType, setCaptureType] = useState<CaptureType>('equipment');
  const [mode, setMode] = useState<'camera' | 'preview'>('camera');
  const [capturedImage, setCapturedImage] = useState<string | null>(null);
  const [capturedBlob, setCapturedBlob] = useState<Blob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [facingMode, setFacingMode] = useState<'environment' | 'user'>('environment');

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const startCamera = useCallback(async () => {
    try {
      setError(null);

      // Stop any existing stream
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
      }

      const constraints: MediaStreamConstraints = {
        video: {
          facingMode: facingMode,
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
      };

      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      streamRef.current = stream;

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
    } catch (err) {
      console.error('Camera error:', err);
      setError('Unable to access camera. Please check permissions.');
    }
  }, [facingMode]);

  const stopCamera = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }
  }, []);

  useEffect(() => {
    startCamera();
    return () => stopCamera();
  }, [startCamera, stopCamera]);

  const handleCapture = useCallback(() => {
    if (!videoRef.current || !canvasRef.current) return;

    const video = videoRef.current;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');

    if (!ctx) return;

    // Set canvas dimensions to match video
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    // Draw the current video frame
    ctx.drawImage(video, 0, 0);

    // Convert to blob
    canvas.toBlob(
      (blob) => {
        if (blob) {
          setCapturedBlob(blob);
          setCapturedImage(URL.createObjectURL(blob));
          setMode('preview');
          stopCamera();
        }
      },
      'image/jpeg',
      0.9
    );
  }, [stopCamera]);

  const handleRetake = useCallback(() => {
    if (capturedImage) {
      URL.revokeObjectURL(capturedImage);
    }
    setCapturedImage(null);
    setCapturedBlob(null);
    setMode('camera');
    startCamera();
  }, [capturedImage, startCamera]);

  const handleConfirm = useCallback(() => {
    if (capturedBlob) {
      onCapture(capturedBlob, captureType);
    }
  }, [capturedBlob, captureType, onCapture]);

  const handleFileInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setCapturedBlob(file);
      setCapturedImage(URL.createObjectURL(file));
      setMode('preview');
      stopCamera();
    }
  }, [stopCamera]);

  const toggleCamera = useCallback(() => {
    setFacingMode(prev => prev === 'environment' ? 'user' : 'environment');
  }, []);

  return (
    <div className="fixed inset-0 bg-black z-50 flex flex-col">
      {/* Header */}
      <div className="bg-gray-900 p-4 flex items-center justify-between">
        <button
          onClick={onClose}
          className="text-white p-2"
          aria-label="Close camera"
        >
          ✕
        </button>

        <div className="flex space-x-2">
          <button
            onClick={() => setCaptureType('equipment')}
            className={`px-4 py-2 rounded-full text-sm ${
              captureType === 'equipment'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-700 text-gray-300'
            }`}
          >
            📋 Nameplate
          </button>
          <button
            onClick={() => setCaptureType('problem')}
            className={`px-4 py-2 rounded-full text-sm ${
              captureType === 'problem'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-700 text-gray-300'
            }`}
          >
            🔍 Problem
          </button>
        </div>

        <div className="w-10" /> {/* Spacer for centering */}
      </div>

      {/* Camera/Preview Area */}
      <div className="flex-1 relative">
        {mode === 'camera' ? (
          <>
            <video
              ref={videoRef}
              className="w-full h-full object-cover"
              playsInline
              muted
            />

            {/* Guide Overlay */}
            {captureType === 'equipment' && (
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div className="border-2 border-white border-dashed rounded-lg w-[80%] h-[40%] opacity-50" />
                <p className="absolute bottom-[35%] text-white text-sm bg-black/50 px-3 py-1 rounded">
                  Align nameplate within frame
                </p>
              </div>
            )}

            {error && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/80">
                <div className="text-center p-4">
                  <p className="text-red-400 mb-4">{error}</p>
                  <label className="bg-blue-600 text-white px-4 py-2 rounded cursor-pointer">
                    Upload Image Instead
                    <input
                      type="file"
                      accept="image/*"
                      onChange={handleFileInput}
                      className="hidden"
                    />
                  </label>
                </div>
              </div>
            )}
          </>
        ) : (
          <img
            src={capturedImage || ''}
            alt="Captured"
            className="w-full h-full object-contain bg-black"
          />
        )}
      </div>

      {/* Hidden canvas for capture */}
      <canvas ref={canvasRef} className="hidden" />

      {/* Controls */}
      <div className="bg-gray-900 p-4">
        {mode === 'camera' ? (
          <div className="flex items-center justify-around">
            {/* File upload button */}
            <label className="text-white p-3 cursor-pointer">
              📁
              <input
                type="file"
                accept="image/*"
                onChange={handleFileInput}
                className="hidden"
              />
            </label>

            {/* Capture button */}
            <button
              onClick={handleCapture}
              className="w-16 h-16 bg-white rounded-full border-4 border-gray-400 hover:bg-gray-200 transition-colors"
              aria-label="Take photo"
            />

            {/* Switch camera button */}
            <button
              onClick={toggleCamera}
              className="text-white p-3 text-2xl"
              aria-label="Switch camera"
            >
              🔄
            </button>
          </div>
        ) : (
          <div className="flex items-center justify-around">
            <button
              onClick={handleRetake}
              className="bg-gray-700 text-white px-6 py-3 rounded-lg"
            >
              Retake
            </button>

            <button
              onClick={handleConfirm}
              className="bg-blue-600 text-white px-6 py-3 rounded-lg font-semibold"
            >
              {captureType === 'equipment' ? 'Identify Equipment' : 'Analyze Problem'}
            </button>
          </div>
        )}
      </div>

      {/* Tips */}
      <div className="bg-gray-800 px-4 py-2 text-center">
        <p className="text-gray-400 text-xs">
          {captureType === 'equipment'
            ? 'Tip: Ensure model and serial numbers are clearly visible'
            : 'Tip: Include the component and any visible damage or wear'}
        </p>
      </div>
    </div>
  );
}
