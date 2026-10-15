/** Downloads what a GET returns as a file, or returns why the server refused. */
export async function download(url: string, fallbackName: string): Promise<string | null> {
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    return body.detail ?? `download failed: ${response.status}`;
  }
  const name = /filename="([^"]+)"/.exec(response.headers.get("content-disposition") ?? "")?.[1];
  const link = document.createElement("a");
  link.href = URL.createObjectURL(await response.blob());
  link.download = name ?? fallbackName;
  link.click();
  URL.revokeObjectURL(link.href);
  return null;
}
