// Vercel serverless function: persists phone lock toggles to state/locks.json
// on the main branch via the GitHub Contents API. Deploy with these env vars:
//   LOCKIN_PASSCODE  shared secret checked against x-lockin-passcode (optional;
//                    unset means the endpoint accepts any schema-valid write)
//   GITHUB_TOKEN     fine-grained PAT, Contents: Read and write on the repo (required)
//   GITHUB_REPO      e.g. "mkodithuwakku/LockInModel" (required)
//   GITHUB_BRANCH    defaults to "main"
//   LOCKIN_ORIGIN    allowed CORS origin; defaults to "https://<owner>.github.io"

import {timingSafeEqual} from "node:crypto";
import {applyLock, emptyDocument, validatePayload} from "../shared/locks-core.cjs";

const PATH = "state/locks.json";
const RETRIES = 3;

interface LockRequest {
  method?: string;
  headers: Record<string, string | string[] | undefined>;
  body?: unknown;
}

interface LockResponse {
  status(code: number): LockResponse;
  json(payload: unknown): LockResponse;
  setHeader(name: string, value: string): LockResponse;
  end(): LockResponse;
}

function corsOrigin(): string {
  if (process.env.LOCKIN_ORIGIN) return process.env.LOCKIN_ORIGIN;
  const owner = (process.env.GITHUB_REPO || "/").split("/")[0];
  return `https://${owner}.github.io`;
}

function setCors(res: LockResponse): void {
  res.setHeader("Access-Control-Allow-Origin", corsOrigin());
  res.setHeader("Vary", "Origin");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader(
    "Access-Control-Allow-Headers",
    "Content-Type, x-lockin-passcode",
  );
}

function authorized(header: string | string[] | undefined): boolean {
  const expected = process.env.LOCKIN_PASSCODE || "";
  // With no passcode configured the endpoint accepts any schema-valid write;
  // the origin check below is the only casual-abuse barrier.
  if (!expected) return true;
  const given = Array.isArray(header) ? String(header[0]) : String(header ?? "");
  if (expected.length !== given.length) return false;
  return timingSafeEqual(Buffer.from(given), Buffer.from(expected));
}

function originAllowed(req: LockRequest): boolean {
  const header = req.headers["origin"] ?? req.headers["referer"];
  const value = Array.isArray(header) ? header[0] : header;
  if (!value) return true; // Non-browser callers send no Origin header.
  return String(value).startsWith(corsOrigin());
}

function repo(): {repo: string; branch: string; token: string} {
  const repo = process.env.GITHUB_REPO || "";
  const token = process.env.GITHUB_TOKEN || "";
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repo) || !token)
    throw Object.assign(new Error("Server is not configured."), {status: 500});
  return {repo, token, branch: process.env.GITHUB_BRANCH || "main"};
}

async function github(
  path: string,
  init: Record<string, unknown> = {},
): Promise<{status: number; body: any}> {
  const {repo, token} = repo();
  const response = await fetch(`https://api.github.com/repos/${repo}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
    },
  });
  const body = await response.json().catch(() => null);
  return {status: response.status, body};
}

async function readFile(
  branch: string,
): Promise<{doc: any; sha: string | null}> {
  const {status, body} = await github(
    `/contents/${PATH}?ref=${encodeURIComponent(branch)}`,
  );
  if (status === 404) return {doc: emptyDocument(), sha: null};
  if (status !== 200 || typeof body?.content !== "string")
    throw Object.assign(new Error("GitHub read failed."), {status: 500});
  let doc;
  try {
    doc = JSON.parse(Buffer.from(body.content, "base64").toString("utf8"));
  } catch {
    doc = emptyDocument();
  }
  return {doc, sha: String(body.sha)};
}

export default async function handler(
  req: LockRequest,
  res: LockResponse,
): Promise<LockResponse> {
  setCors(res); // The Pages origin is cross-site; answer the CORS preflight.
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method === "GET") {
    // The published site reads this to show phone-made locks before the next
    // daily publish; the same records are already allowlisted in report.json.
    try {
      const {branch} = repo();
      const {doc} = await readFile(branch);
      return res.status(200).json(doc);
    } catch {
      return res.status(500).json({error: "Could not load locks."});
    }
  }
  if (req.method !== "POST")
    return res.status(405).json({error: "Method not allowed."});
  if (!originAllowed(req))
    return res.status(403).json({error: "Unexpected request origin."});
  if (!authorized(req.headers["x-lockin-passcode"]))
    return res.status(401).json({error: "Invalid passcode."});
  let payload;
  try {
    payload = validatePayload(req.body);
  } catch (error) {
    return res.status(400).json({error: (error as Error).message});
  }
  let branch: string;
  try {
    ({branch} = repo());
  } catch {
    return res.status(500).json({error: "Server is not configured."});
  }
  for (let attempt = 0; attempt < RETRIES; attempt++) {
    const {doc, sha} = await readFile(branch);
    const updated = applyLock(doc, payload);
    const content = Buffer.from(
      JSON.stringify(updated, null, 2) + "\n",
      "utf8",
    ).toString("base64");
    const name = payload.player.player_name || payload.player.player_id;
    const {status} = await github(`/contents/${PATH}`, {
      method: "PUT",
      body: JSON.stringify({
        message: `Update locks: ${payload.action} ${name} (Week ${payload.schedule_week})`,
        content,
        ...(sha ? {sha} : {}),
        branch,
        committer: {
          name: "LockIn Phone",
          email: "lockin-phone@users.noreply.github.com",
        },
      }),
    });
    if (status === 200 || status === 201)
      return res.status(200).json({
        status: "ok",
        action: payload.action,
        player_id: payload.player.player_id,
        schedule_week: payload.schedule_week,
        updated_at: updated.updated_at,
      });
    if (status !== 409)
      return res.status(500).json({error: "GitHub update failed."});
    await new Promise((resolve) => setTimeout(resolve, 250 * (attempt + 1)));
  }
  return res
    .status(409)
    .json({error: "Concurrent lock updates. Try again in a moment."});
}
