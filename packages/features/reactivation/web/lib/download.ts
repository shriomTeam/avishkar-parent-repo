/** Saves bytes as a file in the browser. The bytes stay on this device; nothing is sent anywhere. */
export function downloadBytes(bytes: Uint8Array<ArrayBuffer>, fileName: string, type: string) {
  const url = URL.createObjectURL(new Blob([bytes], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
