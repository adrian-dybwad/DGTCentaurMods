import { useGameStore } from '../stores/gameStore';
import './ConnectionStatus.css';

/**
 * Connection status indicator for the navbar.
 */
export function ConnectionStatus() {
  const connected = useGameStore((state) => state.connected);

  return (
    <div className={`connection-status ${connected ? 'connected' : 'disconnected'}`}>
      <span className="status-dot" />
      <span className="status-text">{connected ? 'Connected' : 'Offline'}</span>
    </div>
  );
}

