import { useGameStore } from '../stores/gameStore';
import './ConnectionStatus.css';

/**
 * Connection status indicator - displays as a tag in the navbar.
 * Matches the original .tag.is-success style from Bulma.
 */
export function ConnectionStatus() {
  const connectionStatus = useGameStore((state) => state.connectionStatus);

  const getStatusClass = () => {
    switch (connectionStatus) {
      case 'connected':
        return 'is-success';
      case 'reconnecting':
        return 'is-warning';
      case 'disconnected':
        return 'is-danger';
      default:
        return 'is-light';
    }
  };

  const getStatusText = () => {
    switch (connectionStatus) {
      case 'connected':
        return 'Connected';
      case 'reconnecting':
        return 'Reconnecting...';
      case 'disconnected':
        return 'Offline';
      default:
        return 'Unknown';
    }
  };

  return (
    <span className={`tag ${getStatusClass()}`} id="connection-status">
      <span className={`status-dot ${connectionStatus}`} />
      {getStatusText()}
    </span>
  );
}
