const base = (
  process.env.NEXT_PUBLIC_ATHAR_API_URL || "http://localhost:8000"
).replace(/\/$/, "");
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(
    () => controller.abort(),
    path === "/api/search" ? 180000 : 30000,
  );
  try {
    const response = await fetch(base + path, {
      ...options,
      signal: controller.signal,
      headers:
        options.body instanceof FormData
          ? options.headers
          : { "Content-Type": "application/json", ...options.headers },
    });
    if (!response.ok) {
      // Only display the API's deliberately small public error contract.
      const body = await response.json().catch(() => null);
      throw new Error(
        typeof body?.detail === "string"
          ? body.detail
          : "The request could not finish. Please retry.",
      );
    }
    return (await response.json()) as T;
  } catch (error) {
    if (
      error instanceof TypeError ||
      (error instanceof Error && error.name === "AbortError")
    )
      throw new Error(
        "Cannot reach the local API. Check that the Python server is running on port 8000, then retry.",
      );
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}
export function post<T>(path: string, data?: unknown): Promise<T> {
  return api<T>(path, {
    method: "POST",
    body: data === undefined ? undefined : JSON.stringify(data),
  });
}
