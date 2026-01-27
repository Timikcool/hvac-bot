'use client';

import React, { useState, useCallback } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface UploadResult {
  document_id: string;
  title: string;
  document_type: string;
  brand: string | null;
  model: string | null;
  chunks_created: number;
  pages_processed: number;
  tables_found: number;
  diagrams_found: number;
}

interface ManualStats {
  total_chunks: number;
  status: string;
}

export default function AdminPage() {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [documentType, setDocumentType] = useState('manual');
  const [brand, setBrand] = useState('');
  const [model, setModel] = useState('');
  const [systemType, setSystemType] = useState('');
  const [category, setCategory] = useState('');
  const [useVision, setUseVision] = useState(true);
  
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState('');
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<ManualStats | null>(null);

  // Fetch stats on load
  React.useEffect(() => {
    fetchStats();
  }, []);

  const fetchStats = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/admin/manuals`);
      const data = await res.json();
      setStats(data);
    } catch (e) {
      console.error('Failed to fetch stats:', e);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (selectedFile) {
      setFile(selectedFile);
      // Auto-fill title from filename
      if (!title) {
        setTitle(selectedFile.name.replace('.pdf', '').replace(/_/g, ' '));
      }
    }
  };

  const handleUpload = useCallback(async () => {
    if (!file || !title) {
      setError('Please select a file and enter a title');
      return;
    }

    setUploading(true);
    setError(null);
    setResult(null);
    setProgress('Uploading file...');

    const formData = new FormData();
    formData.append('file', file);
    formData.append('title', title);
    formData.append('document_type', documentType);
    if (brand) formData.append('brand', brand);
    if (model) formData.append('model', model);
    if (systemType) formData.append('system_type', systemType);
    if (category) formData.append('category', category);
    formData.append('use_vision', useVision.toString());

    try {
      setProgress(useVision 
        ? 'Processing with Claude Vision (this may take a few minutes)...' 
        : 'Processing document...'
      );

      const response = await fetch(`${API_BASE}/api/admin/documents/upload`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'Upload failed');
      }

      const data: UploadResult = await response.json();
      setResult(data);
      setProgress('');
      
      // Refresh stats
      fetchStats();
      
      // Clear form
      setFile(null);
      setTitle('');
      setDocumentType('manual');
      setBrand('');
      setModel('');
      setSystemType('');
      setCategory('');
      
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed');
      setProgress('');
    } finally {
      setUploading(false);
    }
  }, [file, title, brand, model, systemType, useVision]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      <div className="max-w-4xl mx-auto px-4 py-12">
        {/* Header */}
        <div className="text-center mb-12">
          <h1 className="text-4xl font-bold text-white mb-2">
            📚 Knowledge Base
          </h1>
          <p className="text-slate-400">
            Upload manuals, books, and articles to power the AI assistant
          </p>
        </div>

        {/* Stats Card */}
        {stats && (
          <div className="bg-slate-800/50 backdrop-blur border border-slate-700 rounded-2xl p-6 mb-8">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-slate-400 text-sm">Vector Database Status</p>
                <p className="text-2xl font-bold text-white">{stats.total_chunks.toLocaleString()} chunks</p>
              </div>
              <div className={`px-4 py-2 rounded-full text-sm font-medium ${
                stats.status === 'green' 
                  ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' 
                  : 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30'
              }`}>
                {stats.status === 'green' ? '● Online' : '● ' + stats.status}
              </div>
            </div>
          </div>
        )}

        {/* Upload Form */}
        <div className="bg-slate-800/50 backdrop-blur border border-slate-700 rounded-2xl p-8">
          <div className="space-y-6">
            {/* File Drop Zone */}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                PDF Manual *
              </label>
              <div 
                className={`border-2 border-dashed rounded-xl p-8 text-center transition-colors ${
                  file 
                    ? 'border-emerald-500 bg-emerald-500/10' 
                    : 'border-slate-600 hover:border-slate-500'
                }`}
              >
                <input
                  type="file"
                  accept=".pdf"
                  onChange={handleFileChange}
                  className="hidden"
                  id="file-upload"
                  disabled={uploading}
                />
                <label htmlFor="file-upload" className="cursor-pointer">
                  {file ? (
                    <div className="text-emerald-400">
                      <svg className="w-12 h-12 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      <p className="font-medium">{file.name}</p>
                      <p className="text-sm text-slate-400 mt-1">
                        {(file.size / 1024 / 1024).toFixed(2)} MB
                      </p>
                    </div>
                  ) : (
                    <div className="text-slate-400">
                      <svg className="w-12 h-12 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                      </svg>
                      <p className="font-medium">Drop PDF here or click to browse</p>
                      <p className="text-sm mt-1">Max 50MB</p>
                    </div>
                  )}
                </label>
              </div>
            </div>

            {/* Document Type */}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Document Type *
              </label>
              <div className="grid grid-cols-4 gap-2">
                {[
                  { value: 'manual', label: '📋 Manual', desc: 'Service/installation' },
                  { value: 'book', label: '📚 Book', desc: 'Textbooks/training' },
                  { value: 'article', label: '📄 Article', desc: 'Technical papers' },
                  { value: 'reference', label: '📖 Reference', desc: 'Codes/standards' },
                ].map((type) => (
                  <button
                    key={type.value}
                    type="button"
                    onClick={() => setDocumentType(type.value)}
                    disabled={uploading}
                    className={`p-3 rounded-xl border-2 transition-all text-left ${
                      documentType === type.value
                        ? 'border-blue-500 bg-blue-500/20 text-white'
                        : 'border-slate-600 hover:border-slate-500 text-slate-300'
                    }`}
                  >
                    <div className="font-medium">{type.label}</div>
                    <div className="text-xs text-slate-400 mt-1">{type.desc}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* Title */}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Title *
              </label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={
                  documentType === 'manual' ? 'e.g., Carrier 24ACC Service Manual' :
                  documentType === 'book' ? 'e.g., Modern Refrigeration and Air Conditioning' :
                  documentType === 'article' ? 'e.g., Troubleshooting VRF Systems' :
                  'e.g., EPA 608 Certification Guide'
                }
                className="w-full px-4 py-3 bg-slate-900/50 border border-slate-600 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                disabled={uploading}
              />
            </div>

            {/* Category (for books/articles/reference) */}
            {documentType !== 'manual' && (
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">
                  Category
                </label>
                <select
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  className="w-full px-4 py-3 bg-slate-900/50 border border-slate-600 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  disabled={uploading}
                >
                  <option value="">Select category...</option>
                  <option value="refrigeration">Refrigeration</option>
                  <option value="electrical">Electrical</option>
                  <option value="controls">Controls & Thermostats</option>
                  <option value="airflow">Airflow & Ductwork</option>
                  <option value="heat_transfer">Heat Transfer</option>
                  <option value="psychrometrics">Psychrometrics</option>
                  <option value="troubleshooting">Troubleshooting</option>
                  <option value="installation">Installation</option>
                  <option value="safety">Safety & Codes</option>
                  <option value="epa">EPA Regulations</option>
                  <option value="hvac_fundamentals">HVAC Fundamentals</option>
                  <option value="commercial">Commercial Systems</option>
                  <option value="residential">Residential Systems</option>
                </select>
              </div>
            )}

            {/* Brand & Model Row (only for manuals) */}
            {documentType === 'manual' && (
              <>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-300 mb-2">
                      Brand
                    </label>
                    <select
                      value={brand}
                      onChange={(e) => setBrand(e.target.value)}
                      className="w-full px-4 py-3 bg-slate-900/50 border border-slate-600 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      disabled={uploading}
                    >
                      <option value="">Select brand...</option>
                      <option value="Carrier">Carrier</option>
                      <option value="Trane">Trane</option>
                      <option value="Lennox">Lennox</option>
                      <option value="Rheem">Rheem</option>
                      <option value="Goodman">Goodman</option>
                      <option value="Daikin">Daikin</option>
                      <option value="York">York</option>
                      <option value="Bryant">Bryant</option>
                      <option value="American Standard">American Standard</option>
                      <option value="Mitsubishi">Mitsubishi</option>
                      <option value="Fujitsu">Fujitsu</option>
                      <option value="LG">LG</option>
                      <option value="Samsung">Samsung</option>
                      <option value="Other">Other</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-300 mb-2">
                      Model Number
                    </label>
                    <input
                      type="text"
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                      placeholder="e.g., 24ACC36"
                      className="w-full px-4 py-3 bg-slate-900/50 border border-slate-600 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      disabled={uploading}
                    />
                  </div>
                </div>

                {/* System Type */}
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-2">
                    System Type
                  </label>
                  <select
                    value={systemType}
                    onChange={(e) => setSystemType(e.target.value)}
                    className="w-full px-4 py-3 bg-slate-900/50 border border-slate-600 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    disabled={uploading}
                  >
                    <option value="">Select type...</option>
                    <option value="air_conditioner">Air Conditioner</option>
                    <option value="heat_pump">Heat Pump</option>
                    <option value="furnace">Furnace</option>
                    <option value="mini_split">Mini Split / Ductless</option>
                    <option value="package_unit">Package Unit / Rooftop</option>
                    <option value="boiler">Boiler</option>
                    <option value="chiller">Chiller</option>
                    <option value="air_handler">Air Handler</option>
                    <option value="thermostat">Thermostat</option>
                  </select>
                </div>
              </>
            )}

            {/* Vision Toggle */}
            <div className="flex items-center justify-between p-4 bg-slate-900/50 rounded-xl border border-slate-600">
              <div>
                <p className="text-white font-medium">Use Claude Vision</p>
                <p className="text-sm text-slate-400">
                  Extract tables, wiring diagrams, and schematics (recommended)
                </p>
              </div>
              <button
                type="button"
                onClick={() => setUseVision(!useVision)}
                disabled={uploading}
                className={`relative w-14 h-8 rounded-full transition-colors ${
                  useVision ? 'bg-blue-500' : 'bg-slate-600'
                }`}
              >
                <span className={`absolute top-1 w-6 h-6 bg-white rounded-full transition-transform ${
                  useVision ? 'left-7' : 'left-1'
                }`} />
              </button>
            </div>

            {/* Error Message */}
            {error && (
              <div className="p-4 bg-red-500/20 border border-red-500/30 rounded-xl text-red-400">
                <p className="font-medium">Upload Failed</p>
                <p className="text-sm mt-1">{error}</p>
              </div>
            )}

            {/* Progress */}
            {progress && (
              <div className="p-4 bg-blue-500/20 border border-blue-500/30 rounded-xl text-blue-400">
                <div className="flex items-center gap-3">
                  <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  <span>{progress}</span>
                </div>
              </div>
            )}

            {/* Success Result */}
            {result && (
              <div className="p-4 bg-emerald-500/20 border border-emerald-500/30 rounded-xl text-emerald-400">
                <p className="font-medium flex items-center gap-2">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  {result.document_type === 'manual' ? 'Manual' : 
                   result.document_type === 'book' ? 'Book' :
                   result.document_type === 'article' ? 'Article' : 'Reference'} Uploaded Successfully!
                </p>
                <div className="mt-3 text-sm space-y-1 text-emerald-300">
                  <p>📄 <strong>{result.pages_processed}</strong> pages processed</p>
                  <p>🧩 <strong>{result.chunks_created}</strong> chunks created</p>
                  {result.tables_found > 0 && <p>📊 <strong>{result.tables_found}</strong> tables extracted</p>}
                  {result.diagrams_found > 0 && <p>📐 <strong>{result.diagrams_found}</strong> diagrams found</p>}
                  <p>🔑 ID: <code className="bg-slate-800 px-2 py-0.5 rounded">{result.document_id}</code></p>
                </div>
              </div>
            )}

            {/* Submit Button */}
            <button
              onClick={handleUpload}
              disabled={uploading || !file || !title}
              className={`w-full py-4 rounded-xl font-semibold text-lg transition-all ${
                uploading || !file || !title
                  ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                  : 'bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700 text-white shadow-lg shadow-blue-500/25'
              }`}
            >
              {uploading ? 'Processing...' : 'Upload & Process Manual'}
            </button>
          </div>
        </div>

        {/* Info Cards */}
        <div className="grid md:grid-cols-2 gap-4 mt-8">
          <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
            <h3 className="text-white font-medium mb-2">⚡ Vision Processing</h3>
            <p className="text-sm text-slate-400">
              When enabled, Claude Vision reads each page as an image to extract tables, 
              wiring diagrams, and technical schematics. Takes longer but captures everything.
            </p>
          </div>
          <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
            <h3 className="text-white font-medium mb-2">🔍 What Gets Indexed</h3>
            <p className="text-sm text-slate-400">
              Error codes, specifications, troubleshooting steps, wiring diagrams, 
              refrigerant charts, and safety warnings become searchable.
            </p>
          </div>
        </div>

        {/* Back Link */}
        <div className="text-center mt-8">
          <a href="/" className="text-slate-400 hover:text-white transition-colors">
            ← Back to Chat
          </a>
        </div>
      </div>
    </div>
  );
}

