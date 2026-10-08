const DRAFT_KEY = "canopy_journal_draft";

export function handleSaveDraft(defaultResponse: string) {
  const draft = { defaultResponse, timestamp: Date.now() };
  localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
}

export function restoreDraft() {
  const raw = localStorage.getItem(DRAFT_KEY);
  return raw ? JSON.parse(raw) : null;
}
