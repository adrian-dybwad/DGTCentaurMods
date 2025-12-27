import { useState } from 'react';
import { useGameStore } from '../stores/gameStore';
import { ApiSettingsDialog } from './ApiSettingsDialog';
import { getApiUrl, isCrossOriginApi } from '../utils/api';
import './ConnectionStatus.css';

/**
 * Connection status indicator - displays as a clickable tag in the navbar.
 * Clicking opens the API settings dialog to change the chess board URL.
 */
export function ConnectionStatus() {
  const connectionStatus = useGameStore((state) => state.connectionStatus);
  const [dialogOpen, setDialogOpen] = useState(false);

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

  const handleSave = () => {
    // Reload the page to reconnect with new API URL
    window.location.reload();
  };

  // Show custom API indicator if using a different origin
  const showApiIndicator = isCrossOriginApi();
  const apiUrl = getApiUrl();
  const apiHost = (() => {
    try {
      return new URL(apiUrl).host;
    } catch {
      return apiUrl;
    }
  })();

  return (
    <>
      <button
        className={`tag tag-button ${getStatusClass()}`}
        id="connection-status"
        onClick={() => setDialogOpen(true)}
        title={`Click to change connection settings\n${showApiIndicator ? `Connected to: ${apiHost}` : 'Using local server'}`}
      >
        <span className={`status-dot ${connectionStatus}`} />
        <span className="status-text">{getStatusText()}</span>
        {showApiIndicator && (
          <span className="api-host">{apiHost}</span>
        )}
      </button>

      <ApiSettingsDialog
        isOpen={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onSave={handleSave}
      />
    </>
  );
}
