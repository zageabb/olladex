"use client";

import { useEffect, useState } from "react";

type UpdateState = { status: string; message: string; version: string };

declare global {
  interface Window {
    olladexDesktop?: {
      platform: string;
      versions: { chrome: string; electron: string };
      updates: { getState: () => Promise<UpdateState>; check: () => Promise<UpdateState>; onStatus: (callback: (state: UpdateState) => void) => () => void };
    };
  }
}

export function DesktopUpdateBadge() {
  const [state, setState] = useState<UpdateState | null>(null);
  useEffect(() => {
    const updates = window.olladexDesktop?.updates;
    if (!updates) return;
    updates.getState().then(setState).catch(() => {});
    return updates.onStatus(setState);
  }, []);
  if (!state || state.status === "disabled") return null;
  const label = state.status === "available" || state.status === "downloaded" ? "Update ready" : state.status === "checking" || state.status === "downloading" ? state.message : "Check updates";
  return <button className={`update-badge ${state.status}`} title={state.message} onClick={() => window.olladexDesktop?.updates.check().catch(() => {})}>{label}</button>;
}
