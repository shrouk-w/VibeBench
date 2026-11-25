export type Side = "a" | "b";
export type Model = {
  provider: string;
  id: string;
  provider_name: string;
  name: string;
  free: boolean;
  requires_key: boolean;
  available: boolean;
};
export type Integration = {
  id: string;
  name: string;
  description: string;
  available: boolean;
};
export type Run = {
  model: string;
  provider: string;
  status:
    "created" | "provisioning" | "running" | "stopped" | "ready" | "failed";
  preview_url: string | null;
};
export type Comparison = {
  id: string;
  expires_in: number;
  runs: Record<Side, Run>;
};
export type Activity = { id: number; side: Side; kind: string; text: string };

export async function call(
  path: string,
  options: RequestInit = {},
  token?: string,
) {
  const headers = new Headers(options.headers);
  if (typeof options.body === "string")
    headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", "Bearer " + token);
  const response = await fetch(path, {
    ...options,
    headers,
    cache: "no-store",
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(
      error?.detail || "Request failed (" + response.status + ")",
    );
  }
  return response;
}
