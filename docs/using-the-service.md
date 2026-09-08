# First visit: from a personal key to the dashboard

On the private OCI website, open **Assistant → How it works** (`/assistant#system`). The dashboard's navigation has the same link. This is a seven-step, animated explanation of the existing service, not a model request or a replay of your traffic. It is separate from the public Sites academy.

## Take the guided path

Select any numbered step, use Previous/Next, or choose Play walkthrough. Playback advances every 12 seconds and stops at the last step. Manual selection pauses it. Playback stops when the page is hidden, the guide leaves the viewport or you follow an action. It does not automatically resume. Reduced-motion preferences disable playback/animation while preserving manual navigation. The complete text remains readable if the guide script is unavailable. Step links support keyboard navigation; automatic playback does not repeatedly announce every step to screen readers.

| Step | What you do | What the service does |
|---|---|---|
| 1. Personal key | Paste an existing key, or redeem an operator-issued invitation and save the new key securely | Consumes the expiring, single-use invite and stores a hash of the new high-entropy personal key |
| 2. Workspace | Review your name, allowance and recent request metadata | Returns an account-scoped view; it creates no VM, private model or ChatGPT workspace |
| 3. Authentication | Connect with the personal key, not the invitation or OCI password | Checks the Bearer key's hash and active status; separately enforces ownership and operator permissions |
| 4. Question | Ask one focused serving-related question, 3–800 characters | Accepts only the supported question shape; does not browse the web, run commands or inspect your tenancy |
| 5. Search or AI | Choose Search guides for excerpts, or Ask AI for an explanation | Search makes no model call; AI retrieves, checks context, reserves quota/capacity, and streams from the CPU model |
| 6. Receipt | Compare first-content time, total time, token subsets, finish reason and sources | Stores request metadata, not the question/answer; unknown token usage remains unknown |
| 7. Dashboard | Reconnect there with the same key; select personal or permitted operator views | Returns owned records by default; global metrics and all-project metadata require an explicit host-side role grant |

An example-question button **only fills the existing question box and focuses it**. It never submits the form, starts inference, redeems an invitation, changes a role or reads a credential. You remain in control of Search guides / Ask AI. Suggested questions are checked against the existing curated retrieval corpus.

## Useful questions and learning habits

- “How do TTFT, prefill and decode relate?” Start with search, open the sources, then compare the AI explanation.
- “How is CPU RAM different from GPU HBM?” Separate the real CPU deployment from GPU concepts and analytical estimates.
- “Are cached input and reasoning tokens added to total tokens?” They are overlapping subsets: total is input plus output, not input plus cache plus output plus reasoning.
- “What happens during KV cache transfer?” The real CPU assistant is combined serving; this host does not transfer KV between GPU workers.

Every question is independent. The assistant does not send earlier conversation turns as context, browse live dashboards or retain a replayable chat transcript. Keep questions narrow: the shared OCI pilot caps output at 64 tokens and admits one answer at a time. The Service snapshot reports the configured profile's limits; it is not a model-readiness probe. Small-model answers can be truncated or wrong. Source ID validity does not prove factual support.

Search does not generate an inference receipt. For real requests, use **Requests → My requests** on the dashboard. Operators can select **All project requests** and apply filters to inspect the existing project's metadata. Viewing the dashboard generates no model tokens. Gateway counters reset on gateway restart; time-series history, request receipts and sanitized events have separate lifetimes. Missing charts are not proof of zero activity.

## Access and troubleshooting

- Keep the key in a password manager, never in chat, URLs, screenshots or Git. Its hash cannot recover the original; contact the operator for replacement access if lost.
- The assistant and dashboard hold separate page-memory sessions. Reload or navigation requires reconnecting. Sign out clears that page; rotation revokes the old key but preserves the user's operator role. Protected calls recheck access.
- “Workspace” is an account-scoped view on shared infrastructure, not isolated hardware. Trusted operators can inspect all-project metadata/events, but those records contain no questions or answers.
- A localhost connection failure can mean the approved Bastion tunnel expired. Renew private access; do not open the gateway or Prometheus publicly as a workaround.
- 401 means the key is missing, invalid or revoked. 403 on global dashboard data means operator permission is missing. A normal invitation does not grant it.
- 429 can mean a busy model or an exhausted quota/rate budget. Wait for busy work; review the displayed allowance for quota denials. Do not retry in a loop.
- 503 can mean AI is disabled; Search guides remains the non-model path while the operator investigates. Oversized context or missing relevant sources can reject an AI request before inference.
- Stop cancels the stream but does not refund work already done or uncertain reservations. After an interrupted stream, inspect history before deciding to retry.

This shared profile does **not** store raw container logs or distributed traces, or export model-cgroup history, GPU/HBM or remote KV-transfer measurements. See the [dashboard field guide](observability-dashboard.md) and [shared-host runbook](oci-shared-host.md).

## Implementation boundary

`assistant.html` contains the complete readable guide; `guide.css` supplies responsive flow diagrams; `guide.js` adds bounded, opt-in step playback. The new controller makes no network calls, accesses no credential controls and uses no browser storage. Existing authentication, quotas, database schema, model and resource limits are unchanged. The optional full-stack Caddy allowlist permits only the two new explanatory assets; dashboard/API routes remain denied there. Neither asset is added to the public Sites export.

Automated checks cover controller transitions, timers, reduced motion, markup/link/controller wiring, existing example retrieval, HTTP asset serving and authentication/public-export boundaries. These checks do not constitute browser interaction or visual QA.
