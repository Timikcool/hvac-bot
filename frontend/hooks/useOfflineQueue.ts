'use client';

import { useState, useEffect, useCallback } from 'react';
import { openDB, DBSchema, IDBPDatabase } from 'idb';
import { EquipmentContext, ChatResponse } from '@/types';

interface PendingQuery {
  id: string;
  query: string;
  equipment: EquipmentContext | null;
  timestamp: number;
}

interface CachedManual {
  manualId: string;
  pages: ArrayBuffer[];
  metadata: Record<string, unknown>;
  cachedAt: number;
}

interface CachedResponse {
  queryHash: string;
  response: ChatResponse;
  cachedAt: number;
}

interface OfflineQueueDB extends DBSchema {
  pendingQueries: {
    key: string;
    value: PendingQuery;
  };
  cachedManuals: {
    key: string;
    value: CachedManual;
  };
  cachedResponses: {
    key: string;
    value: CachedResponse;
  };
}

const DB_NAME = 'hvac-assistant';
const DB_VERSION = 1;
const CACHE_TTL = 0; // Disabled for testing - was 24 * 60 * 60 * 1000 (24 hours)

export function useOfflineQueue() {
  const [db, setDb] = useState<IDBPDatabase<OfflineQueueDB> | null>(null);
  const [isOnline, setIsOnline] = useState(typeof navigator !== 'undefined' ? navigator.onLine : true);
  const [pendingCount, setPendingCount] = useState(0);
  const [isInitialized, setIsInitialized] = useState(false);

  // Initialize IndexedDB
  useEffect(() => {
    const initDB = async () => {
      try {
        const database = await openDB<OfflineQueueDB>(DB_NAME, DB_VERSION, {
          upgrade(db) {
            // Create object stores if they don't exist
            if (!db.objectStoreNames.contains('pendingQueries')) {
              db.createObjectStore('pendingQueries', { keyPath: 'id' });
            }
            if (!db.objectStoreNames.contains('cachedManuals')) {
              db.createObjectStore('cachedManuals', { keyPath: 'manualId' });
            }
            if (!db.objectStoreNames.contains('cachedResponses')) {
              db.createObjectStore('cachedResponses', { keyPath: 'queryHash' });
            }
          },
        });

        setDb(database);

        // Get initial pending count
        const count = await database.count('pendingQueries');
        setPendingCount(count);

        setIsInitialized(true);
      } catch (error) {
        console.error('Failed to initialize IndexedDB:', error);
        setIsInitialized(true); // Still set as initialized to allow app to work
      }
    };

    initDB();
  }, []);

  // Monitor online status
  useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  // Queue query for later when offline
  const queueQuery = useCallback(
    async (query: string, equipment: EquipmentContext | null): Promise<string | null> => {
      if (!db) return null;

      const id = crypto.randomUUID();
      const pendingQuery: PendingQuery = {
        id,
        query,
        equipment,
        timestamp: Date.now(),
      };

      await db.add('pendingQueries', pendingQuery);
      setPendingCount((prev) => prev + 1);

      return id;
    },
    [db]
  );

  // Get all pending queries
  const getPendingQueries = useCallback(async (): Promise<PendingQuery[]> => {
    if (!db) return [];
    return db.getAll('pendingQueries');
  }, [db]);

  // Remove a pending query
  const removePendingQuery = useCallback(
    async (id: string): Promise<void> => {
      if (!db) return;
      await db.delete('pendingQueries', id);
      setPendingCount((prev) => Math.max(0, prev - 1));
    },
    [db]
  );

  // Process queue when back online
  const processQueue = useCallback(
    async (
      sendMessage: (query: string, equipment: EquipmentContext | null) => Promise<ChatResponse>
    ): Promise<{ successful: number; failed: number }> => {
      if (!db || !isOnline) return { successful: 0, failed: 0 };

      const queries = await db.getAll('pendingQueries');
      let successful = 0;
      let failed = 0;

      for (const query of queries) {
        try {
          await sendMessage(query.query, query.equipment);
          await db.delete('pendingQueries', query.id);
          setPendingCount((prev) => Math.max(0, prev - 1));
          successful++;
        } catch (error) {
          console.error('Failed to process queued query:', error);
          failed++;
        }
      }

      return { successful, failed };
    },
    [db, isOnline]
  );

  // Cache frequently-used manuals for offline access
  const cacheManual = useCallback(
    async (
      manualId: string,
      pages: ArrayBuffer[],
      metadata: Record<string, unknown>
    ): Promise<void> => {
      if (!db) return;

      const cachedManual: CachedManual = {
        manualId,
        pages,
        metadata,
        cachedAt: Date.now(),
      };

      await db.put('cachedManuals', cachedManual);
    },
    [db]
  );

  // Get cached manual
  const getCachedManual = useCallback(
    async (manualId: string): Promise<CachedManual | undefined> => {
      if (!db) return undefined;
      return db.get('cachedManuals', manualId);
    },
    [db]
  );

  // Cache response for common queries
  const cacheResponse = useCallback(
    async (
      query: string,
      equipment: EquipmentContext | null,
      response: ChatResponse
    ): Promise<void> => {
      if (!db) return;

      const queryHash = await hashQuery(query, equipment);
      const cachedResponse: CachedResponse = {
        queryHash,
        response,
        cachedAt: Date.now(),
      };

      await db.put('cachedResponses', cachedResponse);
    },
    [db]
  );

  // Check for cached response
  const getCachedResponse = useCallback(
    async (
      query: string,
      equipment: EquipmentContext | null
    ): Promise<ChatResponse | null> => {
      if (!db) return null;

      const queryHash = await hashQuery(query, equipment);
      const cached = await db.get('cachedResponses', queryHash);

      // Only return if cached within TTL
      if (cached && Date.now() - cached.cachedAt < CACHE_TTL) {
        return cached.response;
      }

      return null;
    },
    [db]
  );

  // Clear old cached responses
  const clearExpiredCache = useCallback(async (): Promise<number> => {
    if (!db) return 0;

    const now = Date.now();
    const allCached = await db.getAll('cachedResponses');
    let cleared = 0;

    for (const cached of allCached) {
      if (now - cached.cachedAt > CACHE_TTL) {
        await db.delete('cachedResponses', cached.queryHash);
        cleared++;
      }
    }

    return cleared;
  }, [db]);

  // Get storage usage estimate
  const getStorageEstimate = useCallback(async (): Promise<{
    used: number;
    quota: number;
  } | null> => {
    if (!navigator.storage?.estimate) return null;

    const estimate = await navigator.storage.estimate();
    return {
      used: estimate.usage || 0,
      quota: estimate.quota || 0,
    };
  }, []);

  return {
    isOnline,
    isInitialized,
    pendingCount,
    queueQuery,
    getPendingQueries,
    removePendingQuery,
    processQueue,
    cacheManual,
    getCachedManual,
    cacheResponse,
    getCachedResponse,
    clearExpiredCache,
    getStorageEstimate,
  };
}

async function hashQuery(
  query: string,
  equipment: EquipmentContext | null
): Promise<string> {
  const data = JSON.stringify({ query: query.toLowerCase().trim(), equipment });
  const encoder = new TextEncoder();
  const hashBuffer = await crypto.subtle.digest('SHA-256', encoder.encode(data));
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
}
