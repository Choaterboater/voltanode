import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Shield,
  Plug,
  Activity,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Loader2,
  Save,
  TestTube,
  KeyRound,
  Plus,
} from 'lucide-react';
import Layout from '@/components/Layout';
import Badge from '@/components/Badge';
import { useSettings } from '@/hooks/useSettings';
import { toast } from 'sonner';

type TabKey = 'brokers' | 'safety' | 'live';

const tabs: { key: TabKey; label: string; icon: React.ElementType }[] = [
  { key: 'brokers', label: 'Brokers', icon: Plug },
  { key: 'safety', label: 'Safety', icon: Shield },
  { key: 'live', label: 'Live Mode', icon: Activity },
];

// ── Broker Card Component ──
function BrokerCard({
  name,
  description,
  onTest,
  onSaveKeys,
  onConfigure,
  onDisconnect,
  loading,
  liveMode,
}: {
  name: string;
  description: string;
  onTest: (name: string, testnet: boolean, paper: boolean) => Promise<void>;
  onSaveKeys: (name: string, key: string, secret: string) => Promise<void>;
  onConfigure: (name: string, testnet: boolean, paper: boolean) => Promise<void>;
  onDisconnect: () => Promise<unknown>;
  loading: boolean;
  liveMode: ReturnType<typeof useSettings>['liveMode'];
}) {
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [testnet, setTestnet] = useState(name === 'binance');
  const [paper, setPaper] = useState(name === 'alpaca');
  const [testResult, setTestResult] = useState<{ connected: boolean; message: string } | null>(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);

  const isConnected = liveMode?.broker_connected && liveMode?.broker_name === name;

  const isMock = name === 'mock';

  const handleDisconnect = async () => {
    setDisconnecting(true);
    try {
      await onDisconnect();
      toast.success(`${name} disconnected`);
    } catch {
      toast.error(`${name}: Disconnect failed`);
    } finally {
      setDisconnecting(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      await onTest(name, testnet, paper);
      setTestResult({ connected: true, message: 'Connection successful' });
      toast.success(`${name}: Connection successful`);
    } catch (err) {
      setTestResult({ connected: false, message: err instanceof Error ? err.message : 'Connection failed' });
      toast.error(`${name}: Connection failed`);
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    if (!apiKey || !apiSecret) {
      toast.error('API Key and Secret are required');
      return;
    }
    setSaving(true);
    try {
      await onSaveKeys(name, apiKey, apiSecret);
      toast.success(`${name}: API keys saved securely`);
      setApiKey('');
      setApiSecret('');
    } catch {
      toast.error(`${name}: Failed to save API keys`);
    } finally {
      setSaving(false);
    }
  };

  const handleModeChange = async (field: 'testnet' | 'paper', value: boolean) => {
    if (field === 'testnet') setTestnet(value);
    if (field === 'paper') setPaper(value);
    try {
      await onConfigure(name, field === 'testnet' ? value : testnet, field === 'paper' ? value : paper);
      toast.success(`${name}: Configuration updated`);
    } catch {
      toast.error(`${name}: Failed to update configuration`);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
    >
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text-primary capitalize">{name}</h3>
          <p className="mt-0.5 text-xs text-text-muted">{description}</p>
        </div>
        <div className="flex items-center gap-2">
          {isConnected && (
            <Badge variant={liveMode?.live_mode ? 'danger' : 'success'}>
              {liveMode?.live_mode ? 'LIVE' : 'Connected'}
            </Badge>
          )}
          {testResult && !isConnected && (
            <Badge variant={testResult.connected ? 'success' : 'danger'}>
              {testResult.connected ? 'Test OK' : 'Failed'}
            </Badge>
          )}
        </div>
      </div>

      {!isMock && (
        <>
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
            {name === 'binance' && (
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={testnet}
                  onChange={(e) => handleModeChange('testnet', e.target.checked)}
                  className="h-4 w-4 rounded border-border-subtle bg-bg-input accent-accent-cyan"
                />
                <span className="text-xs text-text-secondary">Testnet</span>
              </label>
            )}
            {name === 'alpaca' && (
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={paper}
                  onChange={(e) => handleModeChange('paper', e.target.checked)}
                  className="h-4 w-4 rounded border-border-subtle bg-bg-input accent-accent-cyan"
                />
                <span className="text-xs text-text-secondary">Paper Trading</span>
              </label>
            )}
          </div>

          <div className="mt-3 space-y-2">
            <div className="relative">
              <KeyRound className="absolute left-3 top-2.5 h-4 w-4 text-text-muted" />
              <input
                type="password"
                placeholder="API Key"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="w-full rounded-md border border-border-subtle bg-bg-input py-2 pl-9 pr-3 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-cyan focus:outline-none"
              />
            </div>
            <div className="relative">
              <KeyRound className="absolute left-3 top-2.5 h-4 w-4 text-text-muted" />
              <input
                type="password"
                placeholder="API Secret"
                value={apiSecret}
                onChange={(e) => setApiSecret(e.target.value)}
                className="w-full rounded-md border border-border-subtle bg-bg-input py-2 pl-9 pr-3 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-cyan focus:outline-none"
              />
            </div>
          </div>

          <div className="mt-3 flex items-center gap-2">
            <button
              onClick={handleSave}
              disabled={saving || loading}
              className="inline-flex items-center gap-1.5 rounded-md bg-accent-cyan px-3 py-1.5 text-xs font-semibold text-text-inverse hover:brightness-110 transition-all disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
              Save Keys
            </button>
            <button
              onClick={handleTest}
              disabled={testing || loading}
              className="inline-flex items-center gap-1.5 rounded-md border border-border-subtle bg-bg-input px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-bg-elevated hover:text-text-primary transition-colors disabled:opacity-50"
            >
              {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <TestTube className="h-3.5 w-3.5" />}
              Test Connection
            </button>
            {isConnected && (
              <button
                onClick={handleDisconnect}
                disabled={disconnecting || loading}
                className="inline-flex items-center gap-1.5 rounded-md border border-border-subtle bg-bg-input px-3 py-1.5 text-xs font-medium text-danger-red hover:bg-danger-red-glow transition-colors disabled:opacity-50"
              >
                {disconnecting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <XCircle className="h-3.5 w-3.5" />}
                Disconnect
              </button>
            )}
          </div>
        </>
      )}

      {isMock && (
        <div className="mt-3 flex items-center gap-2 text-xs text-text-muted">
          <CheckCircle className="h-4 w-4 text-success-green" />
          Mock broker requires no configuration
        </div>
      )}
    </motion.div>
  );
}

// ── Safety Tab ──
function SafetyTab({
  safetyStatus,
  loading,
  onRefresh,
  onKillSwitch,
}: {
  safetyStatus: ReturnType<typeof useSettings>['safetyStatus'];
  loading: boolean;
  onRefresh: () => void;
  onKillSwitch: (action: 'activate' | 'deactivate') => Promise<unknown>;
}) {
  const [activating, setActivating] = useState(false);

  useEffect(() => {
    onRefresh();
  }, [onRefresh]);

  const handleKillSwitch = async (action: 'activate' | 'deactivate') => {
    setActivating(true);
    try {
      await onKillSwitch(action);
      toast.success(`Kill switch ${action}d`);
      onRefresh();
    } catch {
      toast.error(`Kill switch ${action} failed`);
    } finally {
      setActivating(false);
    }
  };

  if (!safetyStatus && loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-accent-cyan" />
      </div>
    );
  }

  if (!safetyStatus) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-3">
        <p className="text-sm text-text-muted">Unable to load safety status</p>
        <button onClick={onRefresh} className="text-xs text-accent-cyan hover:underline">
          Retry
        </button>
      </div>
    );
  }

  const ks = safetyStatus.kill_switch;
  const limits = safetyStatus.safety_limits || {};

  return (
    <div className="space-y-4">
      {/* Kill Switch Card */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <AlertTriangle className={`h-5 w-5 ${ks.activated ? 'text-danger-red' : 'text-success-green'}`} />
            <div>
              <h3 className="text-sm font-semibold text-text-primary">Kill Switch</h3>
              <p className="text-xs text-text-muted">
                {ks.activated ? `Activated: ${ks.reason || 'Manual'}` : 'System is operational'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {ks.activated ? (
              <button
                onClick={() => handleKillSwitch('deactivate')}
                disabled={activating}
                className="inline-flex items-center gap-1.5 rounded-md bg-success-green px-3 py-1.5 text-xs font-semibold text-text-inverse hover:brightness-110 transition-all disabled:opacity-50"
              >
                {activating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle className="h-3.5 w-3.5" />}
                Deactivate
              </button>
            ) : (
              <button
                onClick={() => handleKillSwitch('activate')}
                disabled={activating}
                className="inline-flex items-center gap-1.5 rounded-md bg-danger-red px-3 py-1.5 text-xs font-semibold text-text-inverse hover:brightness-110 transition-all disabled:opacity-50"
              >
                {activating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <XCircle className="h-3.5 w-3.5" />}
                Activate
              </button>
            )}
          </div>
        </div>
      </motion.div>

      {/* Safety Limits */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
      >
        <h3 className="text-sm font-semibold text-text-primary mb-3">Safety Limits</h3>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(limits).map(([key, value]) => (
            <div key={key} className="rounded-md bg-bg-input p-3">
              <p className="text-xs text-text-muted capitalize">{key.replace(/_/g, ' ')}</p>
              <p className="mt-1 font-mono text-sm text-text-primary">
                {typeof value === 'number' ? `${value}${key.includes('pct') ? '%' : ''}` : String(value)}
              </p>
            </div>
          ))}
        </div>
      </motion.div>
    </div>
  );
}

// ── Live Mode Tab ──
function LiveModeTab({
  liveMode,
  brokers,
  loading,
  onRefresh,
  onToggle,
}: {
  liveMode: ReturnType<typeof useSettings>['liveMode'];
  brokers: ReturnType<typeof useSettings>['brokers'];
  loading: boolean;
  onRefresh: () => void;
  onToggle: (enabled: boolean, brokerName?: string) => Promise<unknown>;
}) {
  const [selectedBroker, setSelectedBroker] = useState('');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [toggling, setToggling] = useState(false);

  useEffect(() => {
    onRefresh();
  }, [onRefresh]);

  useEffect(() => {
    if (liveMode) {
      setSelectedBroker(liveMode.broker_name);
    }
  }, [liveMode]);

  const handleToggle = async () => {
    if (!liveMode) return;
    if (!liveMode.live_mode && !selectedBroker) {
      toast.error('Select a broker before enabling live mode');
      return;
    }
    if (!liveMode.live_mode) {
      setConfirmOpen(true);
      return;
    }
    // Disabling doesn't need confirmation
    await doToggle(false);
  };

  const doToggle = async (enabled: boolean) => {
    setToggling(true);
    try {
      await onToggle(enabled, selectedBroker || undefined);
      toast.success(`Live mode ${enabled ? 'enabled' : 'disabled'}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to toggle live mode');
    } finally {
      setToggling(false);
      setConfirmOpen(false);
    }
  };

  if (!liveMode && loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-accent-cyan" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
      >
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-text-primary">Live Trading Mode</h3>
            <p className="text-xs text-text-muted">
              {liveMode?.live_mode
                ? 'Live trading is active. Orders will execute on the selected broker.'
                : 'Paper trading mode. No real orders are placed.'}
            </p>
          </div>
          <Badge variant={liveMode?.live_mode ? 'danger' : 'success'}>
            {liveMode?.live_mode ? 'LIVE' : 'PAPER'}
          </Badge>
        </div>

        <div className="mt-4 space-y-3">
          <div>
            <label className="block text-xs text-text-muted mb-1">Default Broker</label>
            <select
              value={selectedBroker}
              onChange={(e) => setSelectedBroker(e.target.value)}
              disabled={liveMode?.live_mode || toggling}
              className="w-full rounded-md border border-border-subtle bg-bg-input py-2 px-3 text-sm text-text-primary focus:border-accent-cyan focus:outline-none disabled:opacity-50"
            >
              <option value="">Select a broker</option>
              {Object.entries(brokers).map(([key, desc]) => (
                <option key={key} value={key}>
                  {key.charAt(0).toUpperCase() + key.slice(1)} — {desc}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={handleToggle}
              disabled={toggling || loading || (!liveMode?.live_mode && !selectedBroker)}
              className={`inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-semibold text-text-inverse transition-all disabled:opacity-50 ${
                liveMode?.live_mode
                  ? 'bg-danger-red hover:brightness-110'
                  : 'bg-success-green hover:brightness-110'
              }`}
            >
              {toggling ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {liveMode?.live_mode ? 'Switch to Paper Mode' : 'Enable Live Mode'}
            </button>
            {liveMode?.broker_connected && (
              <span className="flex items-center gap-1.5 text-xs text-success-green">
                <CheckCircle className="h-3.5 w-3.5" />
                Broker connected
              </span>
            )}
          </div>
        </div>
      </motion.div>

      {/* Confirmation Modal */}
      {confirmOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="w-full max-w-sm rounded-[10px] border border-border-subtle bg-bg-surface p-5"
          >
            <div className="flex items-center gap-3">
              <AlertTriangle className="h-6 w-6 text-warning-amber" />
              <h3 className="text-base font-semibold text-text-primary">Enable Live Trading?</h3>
            </div>
            <p className="mt-2 text-sm text-text-secondary">
              This will send real orders to <span className="font-medium text-text-primary capitalize">{selectedBroker}</span>. 
              Make sure your API keys are configured and you understand the risks.
            </p>
            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                onClick={() => setConfirmOpen(false)}
                className="rounded-md border border-border-subtle bg-bg-input px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-bg-elevated hover:text-text-primary transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => doToggle(true)}
                disabled={toggling}
                className="rounded-md bg-danger-red px-3 py-1.5 text-xs font-semibold text-text-inverse hover:brightness-110 transition-all disabled:opacity-50"
              >
                {toggling ? <Loader2 className="h-3.5 w-3.5 animate-spin inline" /> : null}
                Confirm Live Mode
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </div>
  );
}

// ── Main Settings Page ──
export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('brokers');
  const [showAddBroker, setShowAddBroker] = useState(false);
  const [newBrokerName, setNewBrokerName] = useState('');
  const [registering, setRegistering] = useState(false);
  const {
    brokers,
    liveMode,
    safetyStatus,
    loading,
    listBrokers,
    getLiveMode,
    setLiveModeEnabled,
    configureBroker,
    storeApiKeys,
    testConnection,
    getSafetyStatus,
    killSwitchAction,
    disconnectBroker,
    registerBroker,
  } = useSettings();

  useEffect(() => {
    listBrokers();
  }, [listBrokers]);

  const handleTest = useCallback(
    async (name: string, testnet: boolean, paper: boolean) => {
      await testConnection(name, testnet, paper);
    },
    [testConnection]
  );

  const handleSaveKeys = useCallback(
    async (name: string, key: string, secret: string) => {
      await storeApiKeys(name, key, secret);
    },
    [storeApiKeys]
  );

  const handleConfigure = useCallback(
    async (name: string, testnet: boolean, paper: boolean) => {
      await configureBroker(name, testnet, paper);
    },
    [configureBroker]
  );

  return (
    <Layout title="Settings">
      <div className="mx-auto max-w-4xl space-y-5">
        {/* Tabs */}
        <div className="flex items-center gap-1 rounded-md bg-bg-surface border border-border-subtle p-1">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`flex flex-1 items-center justify-center gap-2 rounded px-3 py-2 text-xs font-medium transition-colors ${
                  isActive
                    ? 'bg-bg-elevated text-accent-cyan'
                    : 'text-text-secondary hover:text-text-primary hover:bg-bg-input'
                }`}
              >
                <Icon className="h-4 w-4" />
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* Tab Content */}
        {activeTab === 'brokers' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-text-primary">Broker Connections</h2>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setShowAddBroker(true)}
                  className="inline-flex items-center gap-1.5 rounded-md bg-accent-cyan px-3 py-1.5 text-xs font-semibold text-text-inverse hover:brightness-110 transition-all"
                >
                  <Plus className="h-3.5 w-3.5" />
                  Add Broker
                </button>
                <button
                  onClick={() => listBrokers()}
                  disabled={loading}
                  className="text-xs text-accent-cyan hover:underline disabled:opacity-50"
                >
                  Refresh
                </button>
              </div>
            </div>

            {/* Add Broker Modal */}
            {showAddBroker && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
              >
                <h3 className="text-sm font-semibold text-text-primary mb-3">Register New Broker</h3>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    placeholder="Broker name (e.g. kraken, coinbase)"
                    value={newBrokerName}
                    onChange={(e) => setNewBrokerName(e.target.value)}
                    className="flex-1 rounded-md border border-border-subtle bg-bg-input py-2 px-3 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-cyan focus:outline-none"
                  />
                  <button
                    onClick={async () => {
                      if (!newBrokerName.trim()) return;
                      setRegistering(true);
                      try {
                        await registerBroker(newBrokerName.trim());
                        toast.success(`${newBrokerName} registered successfully`);
                        setNewBrokerName('');
                        setShowAddBroker(false);
                        listBrokers();
                      } catch (err) {
                        toast.error(err instanceof Error ? err.message : 'Failed to register broker');
                      } finally {
                        setRegistering(false);
                      }
                    }}
                    disabled={registering || !newBrokerName.trim()}
                    className="inline-flex items-center gap-1.5 rounded-md bg-accent-cyan px-3 py-2 text-xs font-semibold text-text-inverse hover:brightness-110 transition-all disabled:opacity-50"
                  >
                    {registering ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
                    Register
                  </button>
                  <button
                    onClick={() => { setShowAddBroker(false); setNewBrokerName(''); }}
                    className="rounded-md border border-border-subtle bg-bg-input px-3 py-2 text-xs font-medium text-text-secondary hover:bg-bg-elevated hover:text-text-primary transition-colors"
                  >
                    Cancel
                  </button>
                </div>
                <p className="mt-2 text-xs text-text-muted">
                  Registering a broker creates a configuration slot. A backend adapter is required for live connections.
                </p>
              </motion.div>
            )}

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {Object.entries(brokers).map(([name, description]) => (
                <BrokerCard
                  key={name}
                  name={name}
                  description={description}
                  onTest={handleTest}
                  onSaveKeys={handleSaveKeys}
                  onConfigure={handleConfigure}
                  onDisconnect={disconnectBroker}
                  loading={loading}
                  liveMode={liveMode}
                />
              ))}
            </div>
          </div>
        )}

        {activeTab === 'safety' && (
          <SafetyTab
            safetyStatus={safetyStatus}
            loading={loading}
            onRefresh={getSafetyStatus}
            onKillSwitch={killSwitchAction}
          />
        )}

        {activeTab === 'live' && (
          <LiveModeTab
            liveMode={liveMode}
            brokers={brokers}
            loading={loading}
            onRefresh={getLiveMode}
            onToggle={setLiveModeEnabled}
          />
        )}
      </div>
    </Layout>
  );
}
