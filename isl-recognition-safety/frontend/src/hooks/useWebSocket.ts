import { useCallback, useEffect, useRef, useState } from "react";
import type { ClientMessage, ConnectionStatus, Hello, ServerMessage, Update } from "../types";

export interface WsState {
  status: ConnectionStatus;
  hello: Hello | null;
  update: Update | null;
  lastError: string | null;
  attempts: number;
  /** Send a message if the socket is open. Returns false when it was dropped. */
  send: (msg: ClientMessage) => boolean;
}

const UPDATE_THROTTLE_MS = 50;
const BACKOFF_MIN_MS = 800;
const BACKOFF_MAX_MS = 12000;

function streamUrl(): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws/stream`;
}

/**
 * Persistent connection to /ws/stream. Reconnects with exponential backoff.
 * Only the latest `update` is kept and React state is flushed at most every 50 ms.
 */
export function useWebSocket(enabled = true): WsState {
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [hello, setHello] = useState<Hello | null>(null);
  const [update, setUpdate] = useState<Update | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [attempts, setAttempts] = useState(0);

  const socketRef = useRef<WebSocket | null>(null);
  const pendingRef = useRef<Update | null>(null);
  const flushTimerRef = useRef<number | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const attemptRef = useRef(0);
  const closedByUsRef = useRef(false);

  useEffect(() => {
    if (!enabled) return;
    closedByUsRef.current = false;

    const scheduleFlush = () => {
      if (flushTimerRef.current != null) return;
      flushTimerRef.current = window.setTimeout(() => {
        flushTimerRef.current = null;
        if (pendingRef.current) {
          setUpdate(pendingRef.current);
          pendingRef.current = null;
        }
      }, UPDATE_THROTTLE_MS);
    };

    const connect = () => {
      if (closedByUsRef.current) return;
      setStatus(attemptRef.current === 0 ? "connecting" : "reconnecting");
      let ws: WebSocket;
      try {
        ws = new WebSocket(streamUrl());
      } catch (e) {
        setLastError(e instanceof Error ? e.message : String(e));
        scheduleReconnect();
        return;
      }
      socketRef.current = ws;

      ws.onopen = () => {
        attemptRef.current = 0;
        setAttempts(0);
        setStatus("open");
        setLastError(null);
      };
      ws.onmessage = (ev: MessageEvent<string>) => {
        let msg: ServerMessage;
        try {
          msg = JSON.parse(ev.data) as ServerMessage;
        } catch {
          setLastError("Received a non-JSON message from the server");
          return;
        }
        switch (msg.type) {
          case "hello":
            setHello(msg);
            break;
          case "update":
            pendingRef.current = msg;
            scheduleFlush();
            break;
          case "error":
            setLastError(msg.message);
            break;
          default:
            break;
        }
      };
      ws.onerror = () => {
        /* onclose follows and carries the reconnect */
      };
      ws.onclose = () => {
        if (socketRef.current === ws) socketRef.current = null;
        if (closedByUsRef.current) {
          setStatus("closed");
          return;
        }
        scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      if (closedByUsRef.current) return;
      attemptRef.current += 1;
      setAttempts(attemptRef.current);
      setStatus("reconnecting");
      const delay = Math.min(BACKOFF_MAX_MS, BACKOFF_MIN_MS * 2 ** Math.min(attemptRef.current - 1, 5));
      const jitter = Math.random() * 250;
      reconnectTimerRef.current = window.setTimeout(connect, delay + jitter);
    };

    connect();

    return () => {
      closedByUsRef.current = true;
      if (reconnectTimerRef.current != null) window.clearTimeout(reconnectTimerRef.current);
      if (flushTimerRef.current != null) window.clearTimeout(flushTimerRef.current);
      reconnectTimerRef.current = null;
      flushTimerRef.current = null;
      const ws = socketRef.current;
      socketRef.current = null;
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) ws.close();
      setStatus("closed");
    };
  }, [enabled]);

  const send = useCallback((msg: ClientMessage): boolean => {
    const ws = socketRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(msg));
    return true;
  }, []);

  return { status, hello, update, lastError, attempts, send };
}
