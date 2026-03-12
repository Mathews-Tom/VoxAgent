"use client";

import { useState, useCallback, useEffect } from "react";
import { LiveKitRoom, RoomAudioRenderer } from "@livekit/components-react";
import VoiceSession from "./VoiceSession";

interface TokenResponse {
  token: string;
  roomName: string;
}

interface TenantConfig {
  greeting: string;
  widget_color: string;
  widget_position: string;
}

export default function VoiceWidget() {
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [roomName, setRoomName] = useState<string | null>(null);
  const [tenantConfig, setTenantConfig] = useState<TenantConfig | null>(null);

  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";
  const livekitUrl =
    process.env.NEXT_PUBLIC_LIVEKIT_URL ?? "ws://localhost:7880";

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const tenant = params.get("tenant") ?? "";

    fetch(`${apiUrl}/api/tenants/${tenant}/config`)
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Tenant config fetch failed: ${res.status}`);
        }
        return res.json() as Promise<TenantConfig>;
      })
      .then((config) => {
        setTenantConfig(config);
      })
      .catch((err: unknown) => {
        throw err;
      });
  }, [apiUrl]);

  const connect = useCallback(async () => {
    setConnecting(true);
    try {
      const params = new URLSearchParams(window.location.search);
      const tenant = params.get("tenant") ?? "";

      const res = await fetch(`${apiUrl}/api/token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenant_id: tenant }),
      });

      if (!res.ok) {
        throw new Error(`Token request failed: ${res.status}`);
      }

      const data: TokenResponse = await res.json();
      setToken(data.token);
      setRoomName(data.roomName);
      setConnected(true);
    } catch (err) {
      throw err;
    } finally {
      setConnecting(false);
    }
  }, [apiUrl]);

  const disconnect = useCallback(() => {
    setConnected(false);
    setToken(null);
    setRoomName(null);
  }, []);

  const handleClick = () => {
    if (connected) {
      disconnect();
    } else if (!connecting) {
      connect();
    }
  };

  const notifyResize = (width: number, height: number) => {
    window.parent.postMessage({ type: "voxagent:resize", width, height }, "*");
  };

  const buttonSize = connected ? 80 : 60;

  return (
    <>
      {connected && token && roomName && (
        <LiveKitRoom
          token={token}
          serverUrl={livekitUrl}
          connect={true}
          audio={true}
          video={false}
          onConnected={() => notifyResize(80, 80)}
          onDisconnected={disconnect}
        >
          <RoomAudioRenderer />
          <VoiceSession />
        </LiveKitRoom>
      )}

      <button
        onClick={handleClick}
        disabled={connecting}
        title={tenantConfig?.greeting}
        aria-label={connected ? "Disconnect voice chat" : "Start voice chat"}
        style={{
          position: "fixed",
          bottom: "16px",
          ...(tenantConfig?.widget_position === "bottom-left"
            ? { left: "16px" }
            : { right: "16px" }),
          width: `${buttonSize}px`,
          height: `${buttonSize}px`,
          borderRadius: "50%",
          border: "none",
          cursor: connecting ? "wait" : "pointer",
          backgroundColor: connected
            ? "#ef4444"
            : (tenantConfig?.widget_color ?? "#3b82f6"),
          color: "#fff",
          fontSize: "24px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          boxShadow: "0 4px 14px rgba(0,0,0,0.25)",
          transition: "background-color 0.2s, transform 0.1s",
          outline: "none",
          animation: connected ? "pulse 2s infinite" : "none",
        }}
      >
        {connecting ? (
          "\u2026"
        ) : connected ? (
          "\u2715"
        ) : (
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="currentColor"
            aria-hidden="true"
          >
            <path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V20H9v2h6v-2h-2v-2.08A7 7 0 0 0 19 11h-2z" />
          </svg>
        )}
      </button>

      <style>{`
        @keyframes pulse {
          0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,0.5); }
          50% { box-shadow: 0 0 0 12px rgba(239,68,68,0); }
        }
      `}</style>
    </>
  );
}
