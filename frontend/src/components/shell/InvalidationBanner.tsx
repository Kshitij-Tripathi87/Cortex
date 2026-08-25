"use client";

import React from "react";

interface InvalidationBannerProps {
  isValid: boolean;
  invalidationReason?: string | null;
  onRedeliberate?: () => void;
}

export const InvalidationBanner: React.FC<InvalidationBannerProps> = ({
  isValid,
  invalidationReason,
  onRedeliberate,
}) => {
  if (isValid) return null;

  return (
    <div className="bg-red-950/80 border-b border-red-800/90 px-5 py-2.5 flex items-center justify-between text-xs text-red-200 font-mono animate-in fade-in duration-200">
      <div className="flex items-center gap-3">
        <span className="px-2 py-0.5 rounded bg-red-900 text-white font-bold text-[10px] tracking-wider uppercase">
          DECISION INVALIDATED
        </span>
        <span className="text-red-300">
          {invalidationReason ||
            "World State mutation detected: Dependent entity state changed, rendering prior policy decision stale."}
        </span>
      </div>
      {onRedeliberate && (
        <button
          onClick={onRedeliberate}
          className="px-3 py-1 rounded bg-red-800 hover:bg-red-700 text-white font-sans text-xs font-semibold shadow-sm transition flex items-center gap-1.5"
        >
          <span>Re-deliberate & Re-simulate</span>
          <span className="font-mono text-[10px]">→</span>
        </button>
      )}
    </div>
  );
};
