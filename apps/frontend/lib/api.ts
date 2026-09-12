"use client";

export const API_URL = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";

type ValidationIssue = {
  msg?: unknown;
  loc?: unknown;
  type?: unknown;
};

function validationIssueText(issue: ValidationIssue): string | null {
  if (typeof issue.msg !== "string") return null;
  const location = Array.isArray(issue.loc)
    ? issue.loc.filter((part) => part !== "body").map(String).join(".")
    : "";
  return location ? `${location}: ${issue.msg}` : issue.msg;
}

export function apiError(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  if (!error || typeof error !== "object") return "Unexpected request error";

  const value = error as {
    data?: unknown;
    error?: unknown;
    status?: unknown;
  };

  if (typeof value.data === "string" && value.data.trim()) {
    return value.data;
  }

  if (value.data && typeof value.data === "object") {
    const detail = (value.data as { detail?: unknown }).detail;

    if (typeof detail === "string") return detail;

    if (Array.isArray(detail)) {
      const messages = detail
        .map((issue) =>
          issue && typeof issue === "object"
            ? validationIssueText(issue as ValidationIssue)
            : typeof issue === "string"
              ? issue
              : null,
        )
        .filter((message): message is string => Boolean(message));

      if (messages.length) return messages.join(" · ");
    }
  }

  if (typeof value.error === "string" && value.error.trim()) {
    return value.error;
  }

  return typeof value.status === "number"
    ? `Request failed with status ${value.status}.`
    : "Unexpected request error";
}
