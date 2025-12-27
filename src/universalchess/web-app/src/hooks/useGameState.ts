import { useEffect, useRef, useCallback } from 'react';
import { useGameStore } from '../stores/gameStore';
import type { GameState } from '../types/game';

/**
 * Hook that manages SSE connection to /events for real-time game updates.
 * Automatically reconnects on disconnect.
 */
export function useGameState() {
  const eventSourceRef = useRef<EventSource | null>(null);
  const { setGameState, setConnectionStatus, connectionStatus, gameState } = useGameStore();

  const connect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    setConnectionStatus('reconnecting');
    const es = new EventSource('/events');
    eventSourceRef.current = es;

    es.onopen = () => {
      setConnectionStatus('connected');
    };

    es.onmessage = (event) => {
      try {
        const state: GameState = JSON.parse(event.data);
        setGameState(state);
      } catch (e) {
        console.error('Failed to parse game state:', e);
      }
    };

    es.onerror = () => {
      setConnectionStatus('reconnecting');
      // EventSource auto-reconnects, but we track status
    };
  }, [setGameState, setConnectionStatus]);

  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setConnectionStatus('disconnected');
  }, [setConnectionStatus]);

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return { gameState, connectionStatus, reconnect: connect };
}
