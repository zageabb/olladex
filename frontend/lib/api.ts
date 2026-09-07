export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api";

export async function authHeaders(): Promise<Record<string, string>> {
  const desktop = window.olladexDesktop;
  const token = desktop?.connection ? (await desktop.connection()).token : sessionStorage.getItem("olladex-token") || "";
  return { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: { ...await authHeaders(), ...(options?.headers || {}) },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({ detail: response.statusText }));
    if (response.status === 401) window.dispatchEvent(new Event("olladex-auth-required"));
    throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || response.statusText));
  }
  return response.json();
}

export async function streamEvents(runId: number, after: number, signal: AbortSignal, onEvent: (event: any) => void) {
  const response = await fetch(`${API}/runs/${runId}/events?after=${after}`, { signal, headers: await authHeaders() });
  if (!response.ok || !response.body) throw new Error(`Unable to connect to conversation (${response.status})`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n"); buffer = lines.pop() || "";
      for (const line of lines) if (line.trim()) onEvent(JSON.parse(line));
      if (done) break;
    }
  } finally { reader.releaseLock(); }
}
