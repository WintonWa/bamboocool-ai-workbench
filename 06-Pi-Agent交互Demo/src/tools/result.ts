export function toolSuccess<T>(details: T) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(details) }],
    details,
  };
}

export function toolFailure(code: string, message: string, details: Record<string, unknown> = {}) {
  const payload = { ok: false, error: code, message, ...details };
  return {
    content: [{ type: "text" as const, text: JSON.stringify(payload) }],
    details: payload,
    isError: true,
  };
}
