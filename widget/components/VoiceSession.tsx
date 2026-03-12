"use client";

import { useVoiceAssistant } from "@livekit/components-react";

const STATE_LABEL: Record<string, string> = {
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
  idle: "Idle",
};

const STATE_COLOR: Record<string, string> = {
  listening: "#22c55e",
  thinking: "#f59e0b",
  speaking: "#3b82f6",
  idle: "#6b7280",
};

export default function VoiceSession() {
  const { state } = useVoiceAssistant();

  const label = STATE_LABEL[state] ?? state;
  const color = STATE_COLOR[state] ?? "#6b7280";

  return (
    <>
      <div
        style={{
          position: "fixed",
          bottom: "100px",
          right: "16px",
          display: "flex",
          alignItems: "center",
          gap: "6px",
          backgroundColor: "rgba(0,0,0,0.7)",
          color: "#fff",
          borderRadius: "12px",
          padding: "4px 10px",
          fontSize: "12px",
          fontFamily: "system-ui, sans-serif",
          pointerEvents: "none",
        }}
      >
        <span
          style={{
            width: "8px",
            height: "8px",
            borderRadius: "50%",
            backgroundColor: color,
            display: "inline-block",
            animation: state === "speaking" ? "blink 1s infinite" : "none",
          }}
        />
        {label}
      </div>

      <style>{`
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </>
  );
}
