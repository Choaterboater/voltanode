import { useState, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface BrokerInfo {
  name: string;
  description: string;
}

export interface BrokerConfig {
  broker_name: string;
  testnet: boolean;
  paper: boolean;
  api_key_configured: boolean;
  api_secret_configured: boolean;
}

export interface LiveModeStatus {
  live_mode: boolean;
  broker_name: string;
  broker_connected: boolean;
  confirmation_required: boolean;
}

export interface SafetyStatus {
  live_mode: boolean;
  broker_connected: boolean;
  kill_switch: {
    activated: boolean;
    reason?: string;
    activated_at?: string;
  };
  daily_tracker: Record<string, unknown>;
  safety_limits: Record<string, unknown>;
}

export interface TestConnectionResult {
  broker_name: string;
  connected: boolean;
  message: string;
}

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  } catch (e) {
    if (e instanceof TypeError) {
      throw new Error('Backend unreachable — is the API server running on ' + API_BASE + '?');
    }
    throw e;
  }
}

export function useSettings() {
  const [brokers, setBrokers] = useState<Record<string, string>>({});
  const [liveMode, setLiveMode] = useState<LiveModeStatus | null>(null);
  const [safetyStatus, setSafetyStatus] = useState<SafetyStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const listBrokers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchJson<{ brokers: Record<string, string> }>('/settings/brokers');
      setBrokers(data.brokers);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to list brokers');
    } finally {
      setLoading(false);
    }
  }, []);

  const getLiveMode = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchJson<LiveModeStatus>('/settings/live-mode');
      setLiveMode(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to get live mode');
    } finally {
      setLoading(false);
    }
  }, []);

  const setLiveModeEnabled = useCallback(async (enabled: boolean, brokerName?: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchJson<LiveModeStatus>('/settings/live-mode', {
        method: 'POST',
        body: JSON.stringify({ enabled, broker_name: brokerName }),
      });
      setLiveMode(data);
      return data;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to set live mode');
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  const configureBroker = useCallback(async (brokerName: string, testnet?: boolean, paper?: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchJson<BrokerConfig>('/settings/broker', {
        method: 'POST',
        body: JSON.stringify({ broker_name: brokerName, testnet, paper }),
      });
      return data;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to configure broker');
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  const storeApiKeys = useCallback(async (brokerName: string, apiKey: string, apiSecret: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchJson<{ broker_name: string; api_key_stored: boolean; api_secret_stored: boolean; message: string }>('/settings/api-keys', {
        method: 'POST',
        body: JSON.stringify({ broker_name: brokerName, api_key: apiKey, api_secret: apiSecret }),
      });
      return data;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to store API keys');
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  const testConnection = useCallback(async (brokerName: string, testnet?: boolean, paper?: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchJson<TestConnectionResult>('/settings/test-connection', {
        method: 'POST',
        body: JSON.stringify({ broker_name: brokerName, testnet, paper }),
      });
      return data;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to test connection');
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  const getSafetyStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchJson<SafetyStatus>('/settings/safety-status');
      setSafetyStatus(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to get safety status');
    } finally {
      setLoading(false);
    }
  }, []);

  const killSwitchAction = useCallback(async (action: 'activate' | 'deactivate', reason?: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchJson<{ activated: boolean; reason?: string; activated_at?: string }>('/settings/kill-switch', {
        method: 'POST',
        body: JSON.stringify({ action, reason }),
      });
      return data;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Kill switch action failed');
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  const disconnectBroker = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchJson<{ status: string; broker?: string; message?: string }>('/settings/disconnect', {
        method: 'POST',
      });
      return data;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to disconnect');
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  const registerBroker = useCallback(async (brokerName: string, description?: string, testnet?: boolean, paper?: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchJson<BrokerConfig>('/settings/register-broker', {
        method: 'POST',
        body: JSON.stringify({ broker_name: brokerName, description, testnet, paper }),
      });
      return data;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to register broker');
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  const getBrokerConfig = useCallback(async (brokerName: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchJson<BrokerConfig>(`/settings/broker/${brokerName}`);
      return data;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to get broker config');
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  return {
    brokers,
    liveMode,
    safetyStatus,
    loading,
    error,
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
    getBrokerConfig,
  };
}
