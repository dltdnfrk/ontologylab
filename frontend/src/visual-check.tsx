/* Throwaway visual harness: renders the Artifacts screen against payloads
   captured from the live server (curl, 2026-09-12) so the surface can be
   screenshotted without a browser session. Delete with visual-check.html. */
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";

import "@/index.css";
import ArtifactsPage from "@/pages/Artifacts";
import docReview from "@/__fixtures__/doc-review.json";
import documents from "@/__fixtures__/documents.json";
import packs from "@/__fixtures__/packs.json";

const params = new URLSearchParams(window.location.search);
const scenario = params.get("scenario") ?? "loaded";
const open = params.get("open");

let reviewCalls = 0;
const probe = document.createElement("div");
probe.style.cssText =
  "position:fixed;left:8px;bottom:8px;z-index:99;background:#000;color:#0f0;font:12px monospace;padding:4px 8px";
probe.textContent = "review-calls=0";
document.body.appendChild(probe);

function reply(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

window.fetch = async (input: RequestInfo | URL): Promise<Response> => {
  const url =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url;

  if (scenario === "error") {
    return reply({ detail: "kg store unavailable" }, 500);
  }
  if (url.endsWith("/api/documents")) {
    if (scenario === "empty") return reply({ documents: [], count: 0 });
    const limit = Number(params.get("docs") ?? 0);
    const rows = limit > 0 ? documents.documents.slice(0, limit) : documents.documents;
    return reply({ documents: rows, count: rows.length });
  }
  if (url.endsWith("/api/packs")) {
    return reply(
      scenario === "empty"
        ? { packs: [], count: 0, unusable: [{ pack_dir: "half-built", reason: "manifest.json has no usable 'pack_id'" }] }
        : packs,
    );
  }
  if (/\/api\/document\/[^/]+\/review$/.test(url)) {
    reviewCalls += 1;
    probe.textContent = `review-calls=${reviewCalls}`;
    return reply(docReview);
  }
  if (/\/api\/packs\/[^/]+$/.test(url)) {
    return reply({ detail: "Not Found" }, 404);
  }
  return reply({ detail: `unstubbed ${url}` }, 404);
};

createRoot(document.getElementById("root") as HTMLElement).render(
  <MemoryRouter>
    <ArtifactsPage />
  </MemoryRouter>,
);

// 스크린샷용 자동 조작: 버튼이 DOM에 나타나는 순간을 관찰해 누른다
// (고정 대기 없음).
if (open) {
  const selector =
    open === "pack"
      ? 'button[aria-label^="팩 "]'
      : 'button[aria-label$="원문 열기"]';
  const click = () => {
    const button = document.querySelector<HTMLButtonElement>(selector);
    if (!button) return false;
    button.click();
    return true;
  };
  if (!click()) {
    const observer = new MutationObserver(() => {
      if (click()) observer.disconnect();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }
}
