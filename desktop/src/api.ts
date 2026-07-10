import { convertFileSrc, invoke } from "@tauri-apps/api/core";

import { mockBackendRequest } from "./mockBackend";
import type { DesktopResponse, WorkspaceResponseData } from "./types";

let requestSequence = 0;

function runningInTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export class BackendRequestError extends Error {
  readonly code: string;
  readonly retryable: boolean;

  constructor(code: string, message: string, retryable = false) {
    super(message);
    this.name = "BackendRequestError";
    this.code = code;
    this.retryable = retryable;
  }
}

export async function backendRequest<T extends Record<string, unknown>>(
  method: string,
  params: Record<string, unknown> = {},
): Promise<T> {
  requestSequence += 1;
  const request = {
    schema_version: 1 as const,
    request_id: `desktop-${Date.now()}-${requestSequence}`,
    method,
    params,
  };
  const response: DesktopResponse<T> = runningInTauri()
    ? await invoke("backend_request", { request })
    : await mockBackendRequest<T>(request);
  if (!response.ok || !response.data) {
    throw new BackendRequestError(
      response.error?.code ?? "empty_response",
      response.error?.message ?? "桌面后端没有返回数据。",
      response.error?.retryable ?? false,
    );
  }
  return response.data;
}

export function getWorkspace(gameId?: string, agentId?: string) {
  return backendRequest<WorkspaceResponseData>("workspace.get", {
    game_id: gameId ?? "",
    agent_id: agentId ?? "",
  });
}

export async function restartBackend(): Promise<void> {
  if (runningInTauri()) {
    await invoke("backend_restart");
  }
}

export async function resolveAssetUrl(relativePath?: string | null): Promise<string | null> {
  if (!relativePath || !runningInTauri()) {
    return null;
  }
  const absolutePath = await invoke<string>("resolve_asset_path", {
    relativePath,
  });
  return convertFileSrc(absolutePath);
}
