"use client";

import { useState, useCallback } from "react";
import { LiveKitRoom, RoomAudioRenderer } from "@livekit/components-react";
import VoiceSession from "./VoiceSession";

interface TokenResponse {
  token: string;
  roomName: string;
}

export default function VoiceWidget() {
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [roomName, setRoomName] = useState<string | null>(null);

  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";
  const livekitUrl =
    process.env.NEXT_PUBLIC_LIVEKIT_URL ?? "ws://localhost:7880";

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
      console.error("[VoiceWidget] connect error:", err);
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
        aria-label={connected ? "Disconnect voice chat" : "Start voice chat"}
        style={{
          position: "fixed",
          bottom: "16px",
          right: "16px",
          width: `${buttonSize}px`,
          height: `${buttonSize}px`,
          borderRadius: "50%",
          border: "none",
          cursor: connecting ? "wait" : "pointer",
          backgroundColor: connected ? "#ef4444" : "#3b82f6",
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
        {connecting ? "…" : connected ? "✕" : "🎙"}
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
