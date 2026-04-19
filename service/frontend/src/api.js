/** Shared API state — set during app init */
let _authToken = null;  // null until the user provides a real token or server sets one
let _activeRepo = null;

export function setAuthToken(token) {
  _authToken = token;
}

export function setActiveRepo(repo) {
  _activeRepo = repo;
}

export function getActiveRepo() {
  return _activeRepo;
}

export function buildHeaders(extra = {}) {
  const h = { "Content-Type": "application/json" };
  if (_authToken) h["Authorization"] = _authToken;
  if (_activeRepo) {
    h["X-Kairos-Repo-Owner"] = _activeRepo.owner;
    h["X-Kairos-Repo-Name"] = _activeRepo.name;
  }
  return { ...h, ...extra };
}

export async function apiFetch(method, path, body) {
  const opts = { method, headers: buildHeaders(), credentials: "same-origin" };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}
