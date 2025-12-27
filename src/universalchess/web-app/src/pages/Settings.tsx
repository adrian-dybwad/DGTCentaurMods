import { useState, useEffect, useCallback } from 'react';
import type { EngineDefinition } from '../types/game';
import './Settings.css';

interface SettingsData {
  [section: string]: {
    [key: string]: string;
  };
}

type SettingsTab = 'general' | 'players' | 'display' | 'sound' | 'engines' | 'system';

/**
 * Settings page with tabbed navigation.
 */
export function Settings() {
  const [activeTab, setActiveTab] = useState<SettingsTab>('general');
  const [settings, setSettings] = useState<SettingsData>({});
  const [engines, setEngines] = useState<EngineDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Fetch all settings
  useEffect(() => {
    Promise.all([
      fetch('/api/settings/all').then((r) => r.json()),
      fetch('/api/engines/all').then((r) => r.json()),
    ])
      .then(([settingsData, enginesData]) => {
        setSettings(settingsData);
        setEngines(enginesData);
        setLoading(false);
      })
      .catch((e) => {
        console.error('Failed to load settings:', e);
        setLoading(false);
      });
  }, []);

  // Save a setting
  const saveSetting = useCallback(async (section: string, key: string, value: string) => {
    setSaving(true);
    try {
      await fetch(`/api/settings/${section}/${key}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value }),
      });
      setSettings((prev) => ({
        ...prev,
        [section]: { ...prev[section], [key]: value },
      }));
    } catch (e) {
      console.error('Failed to save setting:', e);
    } finally {
      setSaving(false);
    }
  }, []);

  // Install/uninstall engine
  const toggleEngine = useCallback(async (engineName: string, install: boolean) => {
    const endpoint = install ? 'install' : 'uninstall';
    try {
      await fetch(`/api/engines/${endpoint}/${engineName}`, { method: 'POST' });
      // Refresh engines list
      const enginesData = await fetch('/api/engines/all').then((r) => r.json());
      setEngines(enginesData);
    } catch (e) {
      console.error(`Failed to ${endpoint} engine:`, e);
    }
  }, []);

  if (loading) {
    return (
      <div className="settings-page">
        <div className="loading">Loading settings...</div>
      </div>
    );
  }

  const tabs: { id: SettingsTab; label: string; icon: string }[] = [
    { id: 'general', label: 'General', icon: '⚙️' },
    { id: 'players', label: 'Players', icon: '👤' },
    { id: 'display', label: 'Display', icon: '🖥️' },
    { id: 'sound', label: 'Sound', icon: '🔊' },
    { id: 'engines', label: 'Engines', icon: '🤖' },
    { id: 'system', label: 'System', icon: '🔧' },
  ];

  return (
    <div className="settings-page">
      <div className="settings-sidebar">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={`tab-button ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            <span className="tab-icon">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      <div className="settings-content">
        {saving && <div className="saving-indicator">Saving...</div>}

        {activeTab === 'general' && (
          <div className="settings-section">
            <h2>General Settings</h2>
            <SettingRow
              label="Lichess Token"
              value={settings.lichess?.token || ''}
              type="password"
              onChange={(v) => saveSetting('lichess', 'token', v)}
            />
          </div>
        )}

        {activeTab === 'players' && (
          <div className="settings-section">
            <h2>Player Settings</h2>
            <SettingRow
              label="Default Player 1 Type"
              value={settings.players?.player1_type || 'human'}
              type="select"
              options={['human', 'engine', 'lichess', 'hand_brain']}
              onChange={(v) => saveSetting('players', 'player1_type', v)}
            />
            <SettingRow
              label="Default Player 2 Type"
              value={settings.players?.player2_type || 'engine'}
              type="select"
              options={['human', 'engine', 'lichess', 'hand_brain']}
              onChange={(v) => saveSetting('players', 'player2_type', v)}
            />
          </div>
        )}

        {activeTab === 'display' && (
          <div className="settings-section">
            <h2>Display Settings</h2>
            <SettingToggle
              label="Show Coordinates"
              checked={settings.display?.show_coordinates === 'true'}
              onChange={(v) => saveSetting('display', 'show_coordinates', v ? 'true' : 'false')}
            />
            <SettingToggle
              label="Flip Board for Black"
              checked={settings.display?.flip_board === 'true'}
              onChange={(v) => saveSetting('display', 'flip_board', v ? 'true' : 'false')}
            />
          </div>
        )}

        {activeTab === 'sound' && (
          <div className="settings-section">
            <h2>Sound Settings</h2>
            <SettingToggle
              label="Sound Effects (Master)"
              checked={settings.sound?.enabled !== 'false'}
              onChange={(v) => saveSetting('sound', 'enabled', v ? 'true' : 'false')}
            />
            <SettingToggle
              label="Key Press"
              checked={settings.sound?.key_press !== 'false'}
              onChange={(v) => saveSetting('sound', 'key_press', v ? 'true' : 'false')}
            />
            <SettingToggle
              label="Game Events"
              checked={settings.sound?.game_events !== 'false'}
              onChange={(v) => saveSetting('sound', 'game_events', v ? 'true' : 'false')}
            />
            <SettingToggle
              label="Piece Events"
              checked={settings.sound?.piece_events !== 'false'}
              onChange={(v) => saveSetting('sound', 'piece_events', v ? 'true' : 'false')}
            />
            <SettingToggle
              label="Errors"
              checked={settings.sound?.errors !== 'false'}
              onChange={(v) => saveSetting('sound', 'errors', v ? 'true' : 'false')}
            />
          </div>
        )}

        {activeTab === 'engines' && (
          <div className="settings-section">
            <h2>Chess Engines</h2>
            <div className="engines-grid">
              {engines.map((engine) => (
                <div key={engine.name} className="engine-card">
                  <div className="engine-header">
                    <h3>{engine.display_name}</h3>
                    <span className={`status ${engine.installed ? 'installed' : ''}`}>
                      {engine.installed ? '✓ Installed' : 'Not installed'}
                    </span>
                  </div>
                  <p className="engine-summary">{engine.summary}</p>
                  {engine.install_time && (
                    <p className="engine-time">Install time: {engine.install_time}</p>
                  )}
                  <button
                    className={engine.installed ? 'btn-danger' : 'btn-primary'}
                    onClick={() => toggleEngine(engine.name, !engine.installed)}
                  >
                    {engine.installed ? 'Uninstall' : 'Install'}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeTab === 'system' && (
          <div className="settings-section">
            <h2>System Settings</h2>
            <SettingToggle
              label="Developer Mode"
              checked={settings.system?.developer_mode === 'true'}
              onChange={(v) => saveSetting('system', 'developer_mode', v ? 'true' : 'false')}
            />
            <p className="setting-help">
              Enables debug logging. View logs with: <code>journalctl -u universal-chess -f</code>
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// Helper components
function SettingRow({
  label,
  value,
  type = 'text',
  options = [],
  onChange,
}: {
  label: string;
  value: string;
  type?: 'text' | 'password' | 'select';
  options?: string[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="setting-row">
      <label>{label}</label>
      {type === 'select' ? (
        <select value={value} onChange={(e) => onChange(e.target.value)}>
          {options.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
      ) : (
        <input
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={(e) => onChange(e.target.value)}
        />
      )}
    </div>
  );
}

function SettingToggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="setting-row toggle-row">
      <label>{label}</label>
      <button
        className={`toggle ${checked ? 'on' : 'off'}`}
        onClick={() => onChange(!checked)}
        role="switch"
        aria-checked={checked}
      >
        <span className="toggle-slider" />
      </button>
    </div>
  );
}

