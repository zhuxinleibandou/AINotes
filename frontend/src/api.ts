export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch("/api" + path, {
    ...options,
    headers:
      options.body instanceof FormData
        ? options.headers
        : { "Content-Type": "application/json", ...options.headers },
  });
  if (!response.ok) {
    const body = await response
      .json()
      .catch(() => ({ detail: "无法连接本地服务，请检查服务是否运行。" }));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : "提交的内容不完整，请检查后重试。",
    );
  }
  return response.json();
}
export function post<T>(path: string, body?: unknown) {
  return api<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });
}
export function put<T>(path: string, body: unknown) {
  return api<T>(path, { method: "PUT", body: JSON.stringify(body) });
}
export function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
export const date = (time: number) =>
  new Date(time * 1000).toLocaleDateString("zh-CN", {
    month: "long",
    day: "numeric",
  });
export function filename(name: string) {
  return name.replace(/[\\/:*?"<>|]/g, "-").slice(0, 100);
}
