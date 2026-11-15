/**
 * Workspace context — manages current workspace ID across pages.
 * Falls back to localStorage for persistence.
 */

import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/lib/auth";

const STORAGE_KEY = "cortex:workspace_id";

export function useWorkspace(): [string, (ws: string) => void] {
  const { workspace } = useAuth();
  const [workspaceId, setWorkspaceId] = useState<string>("");

  useEffect(() => {
    if (!workspace?.id) {
      setWorkspaceId("");
      return;
    }
    setWorkspaceId(workspace.id);
    localStorage.setItem(STORAGE_KEY, workspace.id);
  }, [workspace?.id]);

  const setWorkspace = useCallback((ws: string) => {
    setWorkspaceId(ws);
    localStorage.setItem(STORAGE_KEY, ws);
  }, []);

  return [workspaceId, setWorkspace];
}
