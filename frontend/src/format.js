/** Format numeric results to exactly two decimal places. */
export function n2(v) {
  if (v === null || v === undefined || v === "") return "";
  const x = Number(v);
  if (Number.isNaN(x)) return String(v);
  return x.toFixed(2);
}

export function downloadText(filename, text, mime = "text/plain;charset=utf-8") {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function toCsv(rows) {
  if (!rows?.length) return "";
  const keys = Object.keys(rows[0]);
  const esc = (v) => {
    if (v === null || v === undefined) return "";
    if (typeof v === "number" && Number.isFinite(v)) return n2(v);
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [keys.join(","), ...rows.map((r) => keys.map((k) => esc(r[k])).join(","))].join("\n");
}
