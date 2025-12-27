import { useEffect, useRef, useCallback } from 'react';
import { useGameStore } from '../stores/gameStore';
import type { GameState } from '../types/game';

/**
 * Hook that manages SSE connection to /events for real-time game updates.
 * Automatically reconnects on disconnect.
 */
export function useGameState() {
  const eventSourceRef = useRef<EventSource | null>(null);
  const { setGameState, setConnected, connected, gameState } = useGameStore();

  const connect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const es = new EventSource('/events');
    eventSourceRef.current = es;

    es.onopen = () => {
      setConnected(true);
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
      setConnected(false);
      // EventSource auto-reconnects, but we track status
    };
  }, [setGameState, setConnected]);

  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setConnected(false);
  }, [setConnected]);

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return { gameState, connected, reconnect: connect };
}

