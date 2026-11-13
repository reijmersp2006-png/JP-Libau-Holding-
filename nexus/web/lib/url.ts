/** Nieuws- en sociale bronnen zijn onvertrouwd: alleen http(s)-links worden klikbaar gemaakt. */
export function safeUrl(u: string | null | undefined): string | undefined {
  return u && /^https?:\/\//i.test(u.trim()) ? u.trim() : undefined;
}
