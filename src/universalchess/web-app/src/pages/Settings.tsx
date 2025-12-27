import { useState, useEffect, useCallback } from 'react';
import { Button, Card, Input, Select, Toggle, Badge } from '../components/ui';
import type { EngineDefinition } from '../types/game';
import './Settings.css';

interface SettingsData {
  [section: string]: {
    [key: string]: string;
  };
}

type SettingsTab = 'general' | 'players' | 'display' | 'sound' | 'engines' | 'system';

const tabs: { id: SettingsTab; label: string; icon: string }[] = [
  { id: 'general', label: 'General', icon: '⚙️' },
  { id: 'players', label: 'Players', icon: '👤' },
  { id: 'display', label: 'Display', icon: '🖥️' },
  { id: 'sound', label: 'Sound', icon: '🔊' },
  { id: 'engines', label: 'Engines', icon: '🤖' },
  { id: 'system', label: 'System', icon: '🔧' },
];

/**
 * Settings page with tabbed navigation.
 */
export function Settings() {
  const [activeTab, setActiveTab] = useState<SettingsTab>('general');
  const [settings, setSettings] = useState<SettingsData>({});
  const [engines, setEngines] = useState<EngineDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

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

  const toggleEngine = useCallback(async (engineName: string, install: boolean) => {
    const endpoint = install ? 'install' : 'uninstall';
    try {
      await fetch(`/api/engines/${endpoint}/${engineName}`, { method: 'POST' });
      const enginesData = await fetch('/api/engines/all').then((r) => r.json());
      setEngines(enginesData);
    } catch (e) {
      console.error(`Failed to ${endpoint} engine:`, e);
    }
  }, []);

  if (loading) {
    return (
      <div className="page container--lg">
        <div className="loading">Loading settings...</div>
      </div>
    );
  }

  return (
    <div className="settings-layout">
      <aside className="settings-sidebar">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={`sidebar-item ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            <span className="sidebar-icon">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </aside>

      <main className="settings-content">
        <Card>
          {saving && <Badge variant="primary">Saving...</Badge>}

          {activeTab === 'general' && (
            <section>
              <h2 className="page-title">General Settings</h2>
              <FormRow label="Lichess Token">
                <Input
                  type="password"
                  value={settings.lichess?.token || ''}
                  onChange={(e) => saveSetting('lichess', 'token', e.target.value)}
                />
              </FormRow>
            </section>
          )}

          {activeTab === 'players' && (
            <section>
              <h2 className="page-title">Player Settings</h2>
              <FormRow label="Default Player 1 Type">
                <Select
                  value={settings.players?.player1_type || 'human'}
                  options={[
                    { value: 'human', label: 'Human' },
                    { value: 'engine', label: 'Engine' },
                    { value: 'lichess', label: 'Lichess' },
                    { value: 'hand_brain', label: 'Hand + Brain' },
                  ]}
                  onChange={(e) => saveSetting('players', 'player1_type', e.target.value)}
                />
              </FormRow>
              <FormRow label="Default Player 2 Type">
                <Select
                  value={settings.players?.player2_type || 'engine'}
                  options={[
                    { value: 'human', label: 'Human' },
                    { value: 'engine', label: 'Engine' },
                    { value: 'lichess', label: 'Lichess' },
                    { value: 'hand_brain', label: 'Hand + Brain' },
                  ]}
                  onChange={(e) => saveSetting('players', 'player2_type', e.target.value)}
                />
              </FormRow>
            </section>
          )}

          {activeTab === 'display' && (
            <section>
              <h2 className="page-title">Display Settings</h2>
              <Toggle
                label="Show Coordinates"
                checked={settings.display?.show_coordinates === 'true'}
                onChange={(v) => saveSetting('display', 'show_coordinates', v ? 'true' : 'false')}
              />
              <Toggle
                label="Flip Board for Black"
                checked={settings.display?.flip_board === 'true'}
                onChange={(v) => saveSetting('display', 'flip_board', v ? 'true' : 'false')}
              />
            </section>
          )}

          {activeTab === 'sound' && (
            <section>
              <h2 className="page-title">Sound Settings</h2>
              <Toggle
                label="Sound Effects (Master)"
                checked={settings.sound?.enabled !== 'false'}
                onChange={(v) => saveSetting('sound', 'enabled', v ? 'true' : 'false')}
              />
              <Toggle
                label="Key Press"
                checked={settings.sound?.key_press !== 'false'}
                onChange={(v) => saveSetting('sound', 'key_press', v ? 'true' : 'false')}
              />
              <Toggle
                label="Game Events"
                checked={settings.sound?.game_events !== 'false'}
                onChange={(v) => saveSetting('sound', 'game_events', v ? 'true' : 'false')}
              />
              <Toggle
                label="Piece Events"
                checked={settings.sound?.piece_events !== 'false'}
                onChange={(v) => saveSetting('sound', 'piece_events', v ? 'true' : 'false')}
              />
              <Toggle
                label="Errors"
                checked={settings.sound?.errors !== 'false'}
                onChange={(v) => saveSetting('sound', 'errors', v ? 'true' : 'false')}
              />
            </section>
          )}

          {activeTab === 'engines' && (
            <section>
              <h2 className="page-title">Chess Engines</h2>
              <div className="grid grid--auto-fit mt-6">
                {engines.map((engine) => (
                  <EngineCard
                    key={engine.name}
                    engine={engine}
                    onToggle={toggleEngine}
                  />
                ))}
              </div>
            </section>
          )}

          {activeTab === 'system' && (
            <section>
              <h2 className="page-title">System Settings</h2>
              <Toggle
                label="Developer Mode"
                checked={settings.system?.developer_mode === 'true'}
                onChange={(v) => saveSetting('system', 'developer_mode', v ? 'true' : 'false')}
              />
              <p className="form-help">
                Enables debug logging. View logs with: <code>journalctl -u universal-chess -f</code>
              </p>
            </section>
          )}
        </Card>
      </main>
    </div>
  );
}

// Helper components

function FormRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="form-row">
      <label className="form-label">{label}</label>
      {children}
    </div>
  );
}

function EngineCard({
  engine,
  onToggle,
}: {
  engine: EngineDefinition;
  onToggle: (name: string, install: boolean) => void;
}) {
  return (
    <Card variant="muted">
      <div className="flex justify-between items-center mb-4">
        <h3 style={{ margin: 0, fontSize: 'var(--text-base)' }}>{engine.display_name}</h3>
        <Badge variant={engine.installed ? 'success' : 'default'}>
          {engine.installed ? '✓ Installed' : 'Not installed'}
        </Badge>
      </div>
      <p className="text-muted" style={{ fontSize: 'var(--text-sm)', marginBottom: 'var(--space-3)' }}>
        {engine.summary}
      </p>
      {engine.install_time && (
        <p className="text-muted" style={{ fontSize: 'var(--text-xs)', marginBottom: 'var(--space-4)' }}>
          Install time: {engine.install_time}
        </p>
      )}
      <Button
        variant={engine.installed ? 'danger' : 'primary'}
        block
        onClick={() => onToggle(engine.name, !engine.installed)}
      >
        {engine.installed ? 'Uninstall' : 'Install'}
      </Button>
    </Card>
  );
}
