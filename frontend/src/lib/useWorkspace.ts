/**
 * Workspace context — manages current workspace ID across pages.
 * Falls back to localStorage for persistence.
 */

import { useState, useEffect, useCallback } from "react";

const STORAGE_KEY = "cortex:workspace_id";

export function useWorkspace(): [string, (ws: string) => void] {
  const [workspaceId, setWorkspaceId] = useState<string>("");

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      setWorkspaceId(stored);
    } else {
      // Default workspace for dev
      const defaultWs = "workspace-default";
      setWorkspaceId(defaultWs);
      localStorage.setItem(STORAGE_KEY, defaultWs);
    }
  }, []);

  const setWorkspace = useCallback((ws: string) => {
    setWorkspaceId(ws);
    localStorage.setItem(STORAGE_KEY, ws);
  }, []);

  return [workspaceId, setWorkspace];
}
