import { useEffect, useRef, useState, useCallback } from "react";
import type { MVSData, WSMessage } from "../types/variance";

const WS_URL = `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws/variance`;

interface UseVarianceWSReturn {
  mvsData: MVSData | null;
  connected: boolean;
  error: string | null;
}

export function useVarianceWS(): UseVarianceWSReturn {
  const [mvsData, setMvsData] = useState<MVSData | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      setError(null);
    };

    ws.onmessage = (event) => {
      try {
        const message: WSMessage = JSON.parse(event.data);
        if (message.type === "mvs_update" && message.payload) {
          setMvsData(message.payload);
        }
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onerror = () => {
      setError("WebSocket connection error");
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      // Auto-reconnect after 3s
      reconnectTimeoutRef.current = setTimeout(connect, 3000);
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      wsRef.current?.close();
    };
  }, [connect]);

  return { mvsData, connected, error };
}
