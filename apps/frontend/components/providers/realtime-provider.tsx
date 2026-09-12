"use client";

import { useEffect } from "react";
import { useAppDispatch } from "@/store/hooks";
import { gatewayApi } from "@/store/gateway-api";
import { receiveEvent, setConnected } from "@/store/realtime-slice";

export function RealtimeProvider({ children }: { children: React.ReactNode }) {
  const dispatch = useAppDispatch();

  useEffect(() => {
    let socket: WebSocket | null = null;
    let timer: number | undefined;
    let stopped = false;

    const connect = async () => {
      try {
        await fetch("/api/v1/auth/websocket-session", { method: "POST", credentials: "include", headers: {
          "X-CSRF-Token": decodeURIComponent(document.cookie.split(";").map(v=>v.trim()).find(v=>v.startsWith("ipb_csrf="))?.split("=").slice(1).join("=") ?? ""),
        }});
      } catch { /* reconnect loop handles it */ }
      if (stopped) return;
      const configured = process.env.NEXT_PUBLIC_WS_URL;
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      const url = configured || `${scheme}://${location.host}/api/v1/ws`;
      socket = new WebSocket(url);
      socket.onopen = () => dispatch(setConnected(true));
      socket.onclose = () => {
        dispatch(setConnected(false));
        if (!stopped) timer = window.setTimeout(connect, 2500);
      };
      socket.onerror = () => socket?.close();
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as { type?: string; event_type?: string; data?: unknown };
          const type = payload.type || payload.event_type || "gateway.event";
          dispatch(receiveEvent({ type, data: payload.data }));
          if (/payment|payout|transfer|authorization|transaction|mandate|settlement|reversal|checkout/.test(type)) {
            dispatch(gatewayApi.util.invalidateTags(["Dashboard", "Payments", "Payouts", "Transactions", "Transfers", "Authorizations", "Reversals", "Mandates", "Accounting", "Reconciliation", "Checkout"]));
          }
        } catch { /* ignore non-json keepalive frames */ }
      };
    };

    void connect();
    return () => { stopped = true; if (timer) clearTimeout(timer); socket?.close(); };
  }, [dispatch]);

  return children;
}
