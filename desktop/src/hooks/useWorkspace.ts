import { useCallback, useEffect, useRef, useState } from "react";

import { backendRequest, getWorkspace } from "../api";
import type { Workspace, WorkspaceResponseData } from "../types";

export interface WorkspaceController {
  workspace: Workspace | null;
  loading: boolean;
  saving: boolean;
  error: string;
  lastSavedAt: Date | null;
  reload: (gameId?: string, agentId?: string) => Promise<void>;
  mutate: (method: string, params?: Record<string, unknown>) => Promise<Workspace>;
}

export function useWorkspace(): WorkspaceController {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);
  const requestSequence = useRef(0);
  const workspaceRef = useRef<Workspace | null>(null);

  const updateWorkspace = useCallback((next: Workspace) => {
    workspaceRef.current = next;
    setWorkspace(next);
  }, []);

  const reload = useCallback(
    async (gameId?: string, agentId?: string) => {
      requestSequence.current += 1;
      const sequence = requestSequence.current;
      setLoading(true);
      setError("");
      try {
        const data = await getWorkspace(gameId, agentId);
        if (sequence === requestSequence.current) updateWorkspace(data.workspace);
      } catch (caught) {
        if (sequence === requestSequence.current) {
          setError(caught instanceof Error ? caught.message : String(caught));
        }
      } finally {
        if (sequence === requestSequence.current) setLoading(false);
      }
    },
    [updateWorkspace],
  );

  const mutate = useCallback(
    async (method: string, params: Record<string, unknown> = {}) => {
      const current = workspaceRef.current;
      if (!current) throw new Error("工作区尚未载入。请稍后重试。");
      setSaving(true);
      setError("");
      try {
        const data = await backendRequest<WorkspaceResponseData>(method, {
          game_id: current.game_id,
          agent_id: current.agent_id,
          ...params,
        });
        updateWorkspace(data.workspace);
        setLastSavedAt(new Date());
        return data.workspace;
      } catch (caught) {
        const message = caught instanceof Error ? caught.message : String(caught);
        setError(message);
        throw caught;
      } finally {
        setSaving(false);
      }
    },
    [updateWorkspace],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  return { workspace, loading, saving, error, lastSavedAt, reload, mutate };
}
