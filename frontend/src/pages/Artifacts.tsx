import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  CircleAlert,
  Eye,
  FileSearch,
  FileText,
  Inbox,
  Layers,
  Package,
  RefreshCw,
  Search,
  TriangleAlert,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { get } from "@/lib/api";
import { cn } from "@/lib/utils";

/* ---------------------------------------------------------------------------
   Server shapes. Only the fields this screen reads are declared; the packs
   endpoint returns whole manifests, and typing every key would make this file
   a second copy of packbuilder's manifest contract.
   --------------------------------------------------------------------------- */

type DocumentRow = {
  id: string;
  title: string | null;
  source_kind: string | null;
  source_uri: string | null;
  fetched_ts: number | null;
  content_hash: string | null;
  doi: string | null;
  source: string | null;
  evidence_grade: string | null;
};

type DocumentsResponse = { documents: DocumentRow[]; count: number };

type DocumentItem = {
  kind: "node" | "edge";
  id: string;
  label: string;
  type: string;
  status: string;
  invalidated: boolean | null;
  span: { start: number; end: number } | null;
};

type DocumentDetail = {
  doc_id: string;
  title: string | null;
  source_uri: string | null;
  source_kind: string | null;
  fetched_ts: number | null;
  text: string;
  truncated: boolean;
  total_chars: number;
  items: DocumentItem[];
};

type PackCounts = {
  documents?: number;
  nodes_verified?: number;
  edges_verified?: number;
  entity_types?: number;
  relation_types?: number;
  communities?: number;
};

type Pack = {
  pack_id: string;
  created_ts?: number | null;
  counts?: PackCounts;
  content_hash?: string | null;
  search_tier?: string | null;
  schema_label?: string | null;
  schema_version_id?: string | number | null;
  source_job_id?: string | null;
  embedding_model?: string | null;
  ontologylab_version?: string | null;
};

type UnusablePack = { pack_dir: string; reason: string };

type PacksResponse = {
  packs: Pack[];
  count: number;
  unusable?: UnusablePack[];
};

type PackEntity = {
  id?: string;
  name?: string;
  entity_type?: string;
  status?: string;
};

type PackRelation = {
  id?: string;
  relation_type?: string;
  src_name?: string;
  dst_name?: string;
  status?: string;
};

type PackDetail = {
  pack_id?: string;
  counts?: PackCounts;
  entities?: PackEntity[];
  relations?: PackRelation[];
};

/* ---------------------------------------------------------------------------
   Copy. Machine values keep their own display (mono + full value in `title`);
   Korean labels sit beside them, never instead of them.
   --------------------------------------------------------------------------- */

const STATUS_KO: Record<string, string> = {
  proposed: "검토 대기",
  verified: "승인됨",
  rejected: "거부됨",
  invalidated: "무효화됨",
  merged: "병합됨",
  dismissed: "기각",
  stale: "만료",
};

const SOURCE_KO: Record<string, string> = {
  paper_api: "논문 API",
  upload: "업로드",
  file: "파일",
  url: "URL",
};

const SEARCH_TIER_KO: Record<string, string> = {
  fts5: "어휘 검색",
  "fts5+vec-rrf": "혼합 검색",
};

/** Evidence state is information, so it carries a glyph as well as a hue. */
const STATUS_TONE: Record<string, { className: string; glyph: string }> = {
  verified: { className: "border-ok/40 bg-ok/15 text-ok", glyph: "✓" },
  merged: { className: "border-ok/40 bg-ok/15 text-ok", glyph: "✓" },
  proposed: { className: "border-warn/40 bg-warn/15 text-warn", glyph: "○" },
  stale: { className: "border-warn/40 bg-warn/15 text-warn", glyph: "○" },
  rejected: {
    className: "border-destructive/40 bg-destructive/15 text-destructive",
    glyph: "×",
  },
  invalidated: {
    className: "border-destructive/40 bg-destructive/15 text-destructive",
    glyph: "×",
  },
  dismissed: {
    className: "border-border bg-muted text-muted-foreground",
    glyph: "–",
  },
};

const SPAN_TONE: Record<string, string> = {
  verified: "bg-ok/25",
  merged: "bg-ok/25",
  proposed: "bg-warn/25",
  rejected: "bg-destructive/20",
  invalidated: "bg-destructive/20",
};

/** Viewport-relative panel heights: the modal panes scroll inside the dialog
    rather than growing it, and both panes must agree on one value. */
const DIALOG_MAX_HEIGHT = "max-h-[88vh]";
const PANE_HEIGHT = "h-[38vh] lg:h-[56vh]";

/* ---------------------------------------------------------------------------
   Typed failure. `api()` throws `Error("<status>: <body>")`, so the status is
   read back rather than guessed, and every surface says one Korean sentence
   plus a collapsed technical detail.
   --------------------------------------------------------------------------- */

type TypedFailure = { message: string; help: string; detail: string };

function classifyFailure(error: unknown, fallback: string): TypedFailure {
  const raw =
    error instanceof Error ? error.message : String(error ?? "").trim();
  const status = Number(/^\s*(\d{3})\s*:/.exec(raw)?.[1] ?? 0);
  const offline = /failed to fetch|networkerror|load failed/i.test(raw);

  const variant = offline
    ? "network"
    : status === 401
      ? "auth"
      : status === 403
        ? "forbidden"
        : status === 404
          ? "missing"
          : status === 503
            ? "busy"
            : status >= 500
              ? "server"
              : "request";

  const messages: Record<string, string> = {
    network: "서버에 연결할 수 없습니다.",
    auth: "인증 세션이 만료되었습니다.",
    forbidden: "이 작업을 실행할 권한이 없습니다.",
    missing: "요청한 항목을 서버에서 찾을 수 없습니다.",
    busy: "다른 작업이 진행 중이어서 지금 불러올 수 없습니다.",
    server: "서버에서 요청을 처리하지 못했습니다.",
    request: fallback,
  };
  const help: Record<string, string> = {
    network: "서버 실행 상태를 확인한 뒤 다시 시도합니다.",
    auth: "화면을 새로고침하여 로컬 인증 세션을 다시 만듭니다.",
    forbidden: "현재 데이터 경로와 접근 권한을 확인합니다.",
    missing: "목록을 새로고침한 뒤 다시 엽니다.",
    busy: "진행 중인 작업이 끝난 뒤 다시 시도합니다.",
    server:
      "잠시 후 다시 시도합니다. 같은 문제가 계속되면 세부 정보를 확인합니다.",
    request: "값을 확인한 뒤 다시 시도합니다.",
  };

  const body = raw.replace(/\s+/g, " ").slice(0, 500) || "세부 정보 없음";
  return {
    message: messages[variant],
    help: help[variant],
    detail: status ? `HTTP ${status} · ${body}` : body,
  };
}

function ErrorSurface({
  error,
  fallback,
  onRetry,
  retrying,
  className,
}: {
  error: unknown;
  fallback: string;
  onRetry: () => void;
  retrying: boolean;
  className?: string;
}) {
  const typed = classifyFailure(error, fallback);
  return (
    <Alert
      variant="destructive"
      className={cn("border-destructive/40 bg-destructive/10", className)}
    >
      <CircleAlert className="h-4 w-4" />
      <AlertTitle>{typed.message}</AlertTitle>
      <AlertDescription className="text-muted-foreground">
        <p>{typed.help}</p>
        <Button
          variant="outline"
          size="sm"
          className="mt-3"
          onClick={onRetry}
          disabled={retrying}
        >
          {retrying ? "다시 시도 중…" : "다시 시도"}
        </Button>
        <details className="mt-2">
          <summary className="cursor-pointer text-xs text-muted-foreground">
            기술 세부 정보
          </summary>
          <pre className="mt-2 overflow-x-auto rounded-md bg-background p-3 font-mono text-xs text-muted-foreground">
            {typed.detail}
          </pre>
        </details>
      </AlertDescription>
    </Alert>
  );
}

/* ---------------------------------------------------------------------------
   Presentation helpers
   --------------------------------------------------------------------------- */

const HTML_ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
};

/** Paper titles arrive carrying markup and entities (`<i>Brca1</i>`,
    `&#x3b2;`). React renders them as literal text, so they are flattened to
    reading order here — the same normalisation the retired dashboard did. */
function plainText(value: string | null | undefined): string {
  return String(value ?? "")
    .replace(/<[^>]*>/g, " ")
    .replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (match: string, entity: string) => {
      const lowered = entity.toLowerCase();
      if (lowered.startsWith("#")) {
        const hex = lowered.startsWith("#x");
        const code = Number.parseInt(hex ? lowered.slice(2) : lowered.slice(1), hex ? 16 : 10);
        return Number.isFinite(code) && code >= 0 && code <= 0x10ffff
          ? String.fromCodePoint(code)
          : match;
      }
      return HTML_ENTITIES[lowered] ?? match;
    })
    .replace(/\s+/g, " ")
    .trim();
}

function documentTitle(title: string | null | undefined, id?: string): string {
  const plain = plainText(title);
  if (plain) return plain;
  const tail = String(id ?? "").slice(0, 8);
  return tail ? `(제목 없음 · ${tail})` : "(제목 없음)";
}

function toDate(ts: number | string | null | undefined): Date | null {
  if (ts === null || ts === undefined || ts === "") return null;
  const numeric = Number(ts);
  const parsed = Number.isFinite(numeric)
    ? new Date(numeric > 1e12 ? numeric : numeric * 1000)
    : new Date(String(ts));
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function relativeKo(date: Date): string {
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return "방금";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}분 전`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}시간 전`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}일 전`;
  if (seconds < 2592000) return `${Math.floor(seconds / 604800)}주 전`;
  if (seconds < 31536000) return `${Math.floor(seconds / 2592000)}개월 전`;
  return `${Math.floor(seconds / 31536000)}년 전`;
}

function RelativeTime({
  ts,
  className,
}: {
  ts: number | string | null | undefined;
  className?: string;
}) {
  const date = toDate(ts);
  if (!date) return <time className={className}>—</time>;
  return (
    <time
      className={className}
      dateTime={date.toISOString()}
      title={date.toLocaleString("ko-KR")}
    >
      {relativeKo(date)}
    </time>
  );
}

/** `sha256:…` fingerprints are compared by eye, so the algorithm prefix must
    not eat the twelve characters that carry the comparison. */
function shortHash(value: string | null | undefined): string | undefined {
  const full = String(value ?? "");
  if (!full) return undefined;
  const separator = full.indexOf(":");
  return (separator === -1 ? full : full.slice(separator + 1)).slice(0, 12);
}

/** A URL must not decide the column width, so the display is shortened and
    the untouched value stays reachable through `title` and the copy action. */
function shortIdentifier(value: string | null | undefined): string {
  const full = String(value ?? "");
  if (!full) return "—";
  try {
    const parsed = new URL(full);
    const tail = parsed.pathname.split("/").filter(Boolean).pop() ?? "";
    return parsed.hostname + (tail ? `/…/${tail.slice(-18)}` : "");
  } catch {
    return full.length > 28
      ? `${full.slice(0, 12)}…${full.slice(-12)}`
      : full;
  }
}

function CopyableIdentifier({
  value,
  label,
  display,
  className,
}: {
  value: string | null | undefined;
  label: string;
  display?: string;
  className?: string;
}) {
  const full = String(value ?? "");
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  if (!full) return <code className={cn("font-mono", className)}>—</code>;

  const copy = async () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    try {
      await navigator.clipboard.writeText(full);
      setState("copied");
    } catch {
      // 클립보드를 쓸 수 없는 맥락(권한 거부, 비보안 컨텍스트)도 결과다.
      // 조용히 넘기면 복사된 것과 구분되지 않는다.
      setState("failed");
    }
    timer.current = window.setTimeout(() => setState("idle"), 1600);
  };

  return (
    <span className={cn("inline-flex min-w-0 items-center gap-1.5", className)}>
      <code className="truncate font-mono text-xs" title={full}>
        {display ?? shortIdentifier(full)}
      </code>
      {/* 복사는 행마다 반복되는 보조 동작이다 — 기본은 무채색으로 두고
          hover/focus에서만 동작 색을 켜서 제목 훑기를 방해하지 않는다. */}
      <Button
        variant="link"
        size="sm"
        className="h-auto shrink-0 px-0 text-xs text-muted-foreground hover:text-primary"
        onClick={() => void copy()}
        aria-label={label}
      >
        {state === "copied" ? "복사됨" : state === "failed" ? "복사 실패" : "복사"}
      </Button>
    </span>
  );
}

function StatusBadge({ status }: { status: string | null | undefined }) {
  const key = String(status ?? "").toLowerCase();
  const tone = STATUS_TONE[key];
  return (
    <Badge
      variant="outline"
      className={cn(
        "gap-1 font-medium",
        tone?.className ?? "border-border text-muted-foreground",
      )}
    >
      <span aria-hidden="true">{tone?.glyph ?? "○"}</span>
      {STATUS_KO[key] ?? (key || "—")}
    </Badge>
  );
}

function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: typeof Inbox;
  title: string;
  description: string;
  action: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed bg-background px-6 py-10 text-center">
      <Icon className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
      <div className="space-y-1">
        <p className="font-medium">{title}</p>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  );
}

function MetricCell({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-card px-2 py-1.5 text-center">
      <div className="font-mono text-md font-semibold tabular-nums">
        {value.toLocaleString("ko-KR")}
      </div>
      <div className="text-label uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Document text with cited spans marked. Segments are plain React children,
   so document text can never reach the DOM as markup.
   --------------------------------------------------------------------------- */

type Segment = { text: string; status: string | null };

function markSegments(
  text: string,
  items: DocumentItem[],
): { segments: Segment[]; dropped: number } {
  const spans = items.flatMap((item) =>
    item.span && item.span.end > item.span.start
      ? [{ start: item.span.start, end: item.span.end, status: item.status }]
      : [],
  );
  const dropped = items.filter((item) => item.span).length - spans.length;
  if (spans.length === 0) {
    return { segments: [{ text, status: null }], dropped };
  }

  const points = Array.from(
    new Set(spans.flatMap((span) => [span.start, span.end])),
  ).sort((a, b) => a - b);

  const segments: Segment[] = [];
  const head = text.slice(0, points[0]);
  if (head) segments.push({ text: head, status: null });

  for (let index = 0; index < points.length - 1; index += 1) {
    const from = points[index];
    const to = points[index + 1];
    const piece = text.slice(from, to);
    if (!piece) continue;
    const covering = spans.filter((span) => span.start <= from && span.end >= to);
    // 겹치는 근거는 가장 안쪽 것의 상태로 칠한다 — 바깥 문장 상태로 칠하면
    // 좁은 근거가 승인 여부를 잘못 말한다.
    const innermost = covering.reduce<{ start: number; status: string } | null>(
      (kept, span) => (kept === null || span.start >= kept.start ? span : kept),
      null,
    );
    segments.push({ text: piece, status: innermost?.status ?? null });
  }

  const tail = text.slice(points[points.length - 1]);
  if (tail) segments.push({ text: tail, status: null });
  return { segments, dropped };
}

function SpanLegend() {
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
      <span>본문 표시</span>
      {(["verified", "proposed", "rejected"] as const).map((status) => (
        <span key={status} className="inline-flex items-center gap-1.5">
          <span
            className={cn("h-3 w-3 rounded-sm", SPAN_TONE[status])}
            aria-hidden="true"
          />
          {STATUS_KO[status]}
        </span>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Entity count cell. `/api/documents` carries no proposal counts, so the
   count comes from the document panel payload — requested only when the row
   is actually on screen, and kept so that opening the row costs no request.
   --------------------------------------------------------------------------- */

function EntityCountCell({
  docId,
  detail,
  failed,
  onNeeded,
}: {
  docId: string;
  detail: DocumentDetail | undefined;
  failed: boolean;
  onNeeded: (id: string) => void;
}) {
  const anchor = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (detail || failed) return;
    const element = anchor.current;
    if (!element) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          observer.disconnect();
          onNeeded(docId);
        }
      },
      { rootMargin: "320px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [docId, detail, failed, onNeeded]);

  let content: React.ReactNode;
  if (failed) {
    content = (
      <span
        className="text-muted-foreground"
        title="개념·관계 수를 불러오지 못했습니다"
      >
        —
      </span>
    );
  } else if (!detail) {
    content = <Skeleton className="h-4 w-10" />;
  } else {
    const nodes = detail.items.filter((item) => item.kind === "node").length;
    const edges = detail.items.filter((item) => item.kind === "edge").length;
    content = (
      <span
        className="font-mono tabular-nums"
        title={`개념 ${nodes}개 · 관계 ${edges}개`}
      >
        {nodes.toLocaleString("ko-KR")}
        <span className="text-muted-foreground">
          {" · "}
          {edges.toLocaleString("ko-KR")}
        </span>
      </span>
    );
  }

  return (
    <span ref={anchor} className="inline-flex items-center">
      {content}
    </span>
  );
}

/* ---------------------------------------------------------------------------
   Screen
   --------------------------------------------------------------------------- */

export default function ArtifactsPage() {
  const [documents, setDocuments] = useState<DocumentRow[] | null>(null);
  const [documentsError, setDocumentsError] = useState<unknown>(null);
  const [packs, setPacks] = useState<Pack[] | null>(null);
  const [unusable, setUnusable] = useState<UnusablePack[]>([]);
  const [packsError, setPacksError] = useState<unknown>(null);
  const [reloading, setReloading] = useState(false);
  const [query, setQuery] = useState("");

  const [details, setDetails] = useState<Record<string, DocumentDetail>>({});
  const [detailErrors, setDetailErrors] = useState<Record<string, unknown>>({});
  const detailInflight = useRef<Set<string>>(new Set());

  const [packDetails, setPackDetails] = useState<Record<string, PackDetail>>({});
  const [packDetailErrors, setPackDetailErrors] = useState<
    Record<string, unknown>
  >({});
  const packInflight = useRef<Set<string>>(new Set());

  const [openDocument, setOpenDocument] = useState<DocumentRow | null>(null);
  const [openPack, setOpenPack] = useState<Pack | null>(null);
  const documentPanel = useRef<HTMLDivElement>(null);
  const packPanel = useRef<HTMLDivElement>(null);

  const loadDocuments = useCallback(async () => {
    setDocumentsError(null);
    try {
      const data = await get<DocumentsResponse>("/documents");
      setDocuments(data.documents ?? []);
    } catch (error) {
      setDocuments(null);
      setDocumentsError(error);
    }
  }, []);

  const loadPacks = useCallback(async () => {
    setPacksError(null);
    try {
      const data = await get<PacksResponse>("/packs");
      setPacks(data.packs ?? []);
      setUnusable(data.unusable ?? []);
    } catch (error) {
      setPacks(null);
      // 목록을 못 받았으면 지난번 거부 안내도 근거가 없다.
      setUnusable([]);
      setPacksError(error);
    }
  }, []);

  const reload = useCallback(async () => {
    setReloading(true);
    detailInflight.current.clear();
    packInflight.current.clear();
    setDetails({});
    setDetailErrors({});
    setPackDetails({});
    setPackDetailErrors({});
    await Promise.all([loadDocuments(), loadPacks()]);
    setReloading(false);
  }, [loadDocuments, loadPacks]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const requestDetail = useCallback((id: string) => {
    if (!id || detailInflight.current.has(id)) return;
    detailInflight.current.add(id);
    get<DocumentDetail>(`/document/${encodeURIComponent(id)}/review`)
      .then((detail) => {
        setDetails((current) => ({ ...current, [id]: detail }));
      })
      .catch((error: unknown) => {
        setDetailErrors((current) => ({ ...current, [id]: error }));
      });
  }, []);

  const retryDetail = useCallback(
    (id: string) => {
      detailInflight.current.delete(id);
      setDetailErrors((current) => {
        const next = { ...current };
        delete next[id];
        return next;
      });
      requestDetail(id);
    },
    [requestDetail],
  );

  const requestPackDetail = useCallback((id: string) => {
    if (!id || packInflight.current.has(id)) return;
    packInflight.current.add(id);
    get<PackDetail>(`/packs/${encodeURIComponent(id)}`)
      .then((detail) => {
        setPackDetails((current) => ({ ...current, [id]: detail }));
      })
      .catch((error: unknown) => {
        setPackDetailErrors((current) => ({ ...current, [id]: error }));
      });
  }, []);

  const retryPackDetail = useCallback(
    (id: string) => {
      packInflight.current.delete(id);
      setPackDetailErrors((current) => {
        const next = { ...current };
        delete next[id];
        return next;
      });
      requestPackDetail(id);
    },
    [requestPackDetail],
  );

  const viewDocument = useCallback(
    (row: DocumentRow) => {
      setOpenDocument(row);
      requestDetail(row.id);
    },
    [requestDetail],
  );

  const viewPack = useCallback(
    (pack: Pack) => {
      setOpenPack(pack);
      requestPackDetail(pack.pack_id);
    },
    [requestPackDetail],
  );

  const filtered = useMemo(() => {
    if (!documents) return [];
    const needle = query.trim().toLowerCase();
    if (!needle) return documents;
    return documents.filter((row) =>
      [row.title, row.source, row.source_kind, row.source_uri, row.doi, row.id]
        .some((field) => String(field ?? "").toLowerCase().includes(needle)),
    );
  }, [documents, query]);

  const documentsLoading = documents === null && documentsError === null;
  const packsLoading = packs === null && packsError === null;

  return (
    <div className="mx-auto flex w-full max-w-content flex-col gap-6 p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-display font-semibold tracking-tight">
            아티팩트
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            수집한 문서와 빌드한 팩 — 산출물을 여기서 열람합니다.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void reload()}
          disabled={reloading}
          aria-label="아티팩트 목록 새로고침"
        >
          <RefreshCw className={cn(reloading && "animate-spin")} />
          {reloading ? "새로고침 중…" : "새로고침"}
        </Button>
      </header>

      {/* ── 문서 ─────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-4 space-y-0">
          <div className="space-y-1.5">
            <CardTitle className="flex items-center gap-2 text-md">
              <FileText
                className="h-4 w-4 text-muted-foreground"
                aria-hidden="true"
              />
              문서
              {documents !== null && (
                <Badge variant="secondary" className="font-mono tabular-nums">
                  {documents.length.toLocaleString("ko-KR")}
                </Badge>
              )}
            </CardTitle>
            <CardDescription>
              수집한 원문과 그 문서에서 뽑아낸 개념·관계 제안 수입니다.
            </CardDescription>
          </div>
          <div className="relative w-full sm:w-72">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="제목 · 출처 · DOI 검색"
              aria-label="문서 검색"
              className="pl-9"
            />
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {documentsError !== null ? (
            <ErrorSurface
              error={documentsError}
              fallback="문서 목록을 불러오지 못했습니다."
              onRetry={() => void loadDocuments()}
              retrying={reloading}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-56">제목</TableHead>
                  <TableHead className="min-w-40">출처</TableHead>
                  <TableHead className="w-28">날짜</TableHead>
                  <TableHead className="w-28">개념 · 관계</TableHead>
                  <TableHead className="w-28 text-right">작업</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documentsLoading &&
                  Array.from({ length: 5 }, (_unused, index) => (
                    <TableRow key={`doc-skeleton-${index}`}>
                      <TableCell>
                        <Skeleton className="h-4 w-64" />
                      </TableCell>
                      <TableCell>
                        <Skeleton className="h-4 w-32" />
                      </TableCell>
                      <TableCell>
                        <Skeleton className="h-4 w-16" />
                      </TableCell>
                      <TableCell>
                        <Skeleton className="h-4 w-10" />
                      </TableCell>
                      <TableCell>
                        <Skeleton className="ml-auto h-7 w-20" />
                      </TableCell>
                    </TableRow>
                  ))}

                {!documentsLoading &&
                  filtered.map((row) => (
                    <TableRow key={row.id}>
                      <TableCell className="max-w-96">
                        <div className="truncate font-medium" title={documentTitle(row.title, row.id)}>
                          {documentTitle(row.title, row.id)}
                        </div>
                        {row.doi ? (
                          <div className="text-xs text-muted-foreground">
                            DOI <span className="font-mono">{row.doi}</span>
                          </div>
                        ) : null}
                      </TableCell>
                      <TableCell className="max-w-72">
                        <div className="text-sm">
                          {/* `source`는 빈 문자열로 오는 행이 있다 — null 검사만
                              하면 출처 칸이 비어 버리므로 참/거짓으로 넘긴다. */}
                          {SOURCE_KO[String(row.source || row.source_kind || "")] ??
                            (row.source || row.source_kind || "—")}
                        </div>
                        <CopyableIdentifier
                          value={row.source_uri}
                          label="전체 출처 URL 복사"
                          className="text-muted-foreground"
                        />
                      </TableCell>
                      <TableCell>
                        <RelativeTime
                          ts={row.fetched_ts}
                          className="text-sm text-muted-foreground"
                        />
                      </TableCell>
                      <TableCell className="text-sm">
                        <EntityCountCell
                          docId={row.id}
                          detail={details[row.id]}
                          failed={row.id in detailErrors}
                          onNeeded={requestDetail}
                        />
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => viewDocument(row)}
                          aria-label={`${documentTitle(row.title, row.id)} 원문 열기`}
                        >
                          <Eye />
                          원문
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}

                {!documentsLoading && filtered.length === 0 && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={5} className="p-0 pt-4">
                      {documents !== null && documents.length > 0 ? (
                        <EmptyState
                          icon={FileSearch}
                          title="검색 결과가 없습니다"
                          description={`"${query.trim()}"과 일치하는 문서를 찾지 못했습니다.`}
                          action={
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => setQuery("")}
                            >
                              검색어 지우기
                            </Button>
                          }
                        />
                      ) : (
                        <EmptyState
                          icon={Inbox}
                          title="수집한 문서가 없습니다"
                          description="리서치 화면에서 문서를 수집하면 여기에 표시됩니다."
                          action={
                            <Button asChild size="sm">
                              <Link to="/sources">리서치로 이동</Link>
                            </Button>
                          }
                        />
                      )}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* ── 릴리스 (팩) ──────────────────────────────────────── */}
      <Card>
        <CardHeader className="space-y-1.5">
          <CardTitle className="flex items-center gap-2 text-md">
            <Package
              className="h-4 w-4 text-muted-foreground"
              aria-hidden="true"
            />
            릴리스 (팩)
            {packs !== null && (
              <Badge variant="secondary" className="font-mono tabular-nums">
                {packs.length.toLocaleString("ko-KR")}
              </Badge>
            )}
          </CardTitle>
          <CardDescription>
            빌드된 팩은 변경되지 않습니다 — 각 팩의 개체와 관계를 열람합니다.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {packsError !== null && (
            <ErrorSurface
              error={packsError}
              fallback="팩 목록을 불러오지 못했습니다."
              onRetry={() => void loadPacks()}
              retrying={reloading}
            />
          )}

          {packsLoading && (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 3 }, (_unused, index) => (
                <div
                  key={`pack-skeleton-${index}`}
                  className="space-y-3 rounded-lg border bg-background p-4"
                >
                  <Skeleton className="h-4 w-40" />
                  <Skeleton className="h-12 w-full" />
                  <Skeleton className="h-7 w-24" />
                </div>
              ))}
            </div>
          )}

          {packs !== null && packs.length > 0 && (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {packs.map((pack) => {
                const counts = pack.counts ?? {};
                const tier = String(pack.search_tier ?? "");
                return (
                  <div
                    key={pack.pack_id}
                    className="flex flex-col gap-3 rounded-lg border bg-background p-4"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <code
                        className="min-w-0 truncate font-mono text-sm font-medium"
                        title={pack.pack_id}
                      >
                        {pack.pack_id}
                      </code>
                      {tier ? (
                        <Badge
                          variant="outline"
                          className="shrink-0 text-label text-muted-foreground"
                          title={`기계 값: ${tier}`}
                        >
                          {SEARCH_TIER_KO[tier] ?? tier}
                        </Badge>
                      ) : null}
                    </div>
                    <div className="grid grid-cols-3 gap-2">
                      <MetricCell label="문서" value={counts.documents ?? 0} />
                      <MetricCell
                        label="개념"
                        value={counts.nodes_verified ?? 0}
                      />
                      <MetricCell
                        label="관계"
                        value={counts.edges_verified ?? 0}
                      />
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <RelativeTime
                        ts={pack.created_ts}
                        className="text-xs text-muted-foreground"
                      />
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => viewPack(pack)}
                        aria-label={`팩 ${pack.pack_id} 상세 보기`}
                      >
                        <Eye />
                        보기
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {packs !== null && packs.length === 0 && (
            <EmptyState
              icon={Package}
              title="빌드한 팩이 없습니다"
              description="팩 화면에서 팩을 빌드하면 릴리스가 여기에 표시됩니다."
              action={
                <Button asChild size="sm">
                  <Link to="/packs">팩으로 이동</Link>
                </Button>
              }
            />
          )}

          {unusable.length > 0 && (
            <Alert className="border-warn/40 bg-warn/10">
              <TriangleAlert className="h-4 w-4 text-warn" />
              <AlertTitle className="text-warn">
                쓸 수 없는 팩 디렉터리 {unusable.length}개
              </AlertTitle>
              <AlertDescription className="text-muted-foreground">
                <p>
                  매니페스트가 있지만 팩으로 열 수 없어 목록에서 제외했습니다.
                </p>
                <ul className="mt-2 space-y-1">
                  {unusable.map((item) => (
                    <li key={item.pack_dir} className="text-xs">
                      <code className="font-mono">{item.pack_dir}</code> —{" "}
                      {item.reason}
                    </li>
                  ))}
                </ul>
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      {/* ── 문서 상세 ────────────────────────────────────────── */}
      <Dialog
        open={openDocument !== null}
        onOpenChange={(next) => {
          if (!next) setOpenDocument(null);
        }}
      >
        <DialogContent
          ref={documentPanel}
          tabIndex={-1}
          // 기본 자동 포커스는 첫 탭 대상(출처 복사 버튼)에 링을 남긴다.
          // 포커스는 패널 자체로 보내 트랩과 Esc는 그대로 유지한다.
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            documentPanel.current?.focus();
          }}
          className={cn(
            "flex w-[calc(100vw-2rem)] flex-col gap-4 focus-visible:outline-none sm:max-w-5xl",
            DIALOG_MAX_HEIGHT,
          )}
        >
          {openDocument !== null && (
            <DocumentDetailView
              row={openDocument}
              detail={details[openDocument.id]}
              error={detailErrors[openDocument.id]}
              onRetry={() => retryDetail(openDocument.id)}
            />
          )}
        </DialogContent>
      </Dialog>

      {/* ── 팩 상세 ──────────────────────────────────────────── */}
      <Dialog
        open={openPack !== null}
        onOpenChange={(next) => {
          if (!next) setOpenPack(null);
        }}
      >
        <DialogContent
          ref={packPanel}
          tabIndex={-1}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            packPanel.current?.focus();
          }}
          className={cn(
            "flex w-[calc(100vw-2rem)] flex-col gap-4 overflow-y-auto sm:max-w-3xl",
            DIALOG_MAX_HEIGHT,
          )}
        >
          {openPack !== null && (
            <PackDetailView
              pack={openPack}
              detail={packDetails[openPack.pack_id]}
              error={packDetailErrors[openPack.pack_id]}
              onRetry={() => retryPackDetail(openPack.pack_id)}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Document detail — raw text with cited spans marked, plus every proposal
   drawn from the document.
   --------------------------------------------------------------------------- */

function DocumentDetailView({
  row,
  detail,
  error,
  onRetry,
}: {
  row: DocumentRow;
  detail: DocumentDetail | undefined;
  error: unknown;
  onRetry: () => void;
}) {
  const title = documentTitle(detail?.title ?? row.title, row.id);
  const sourceKind = detail?.source_kind ?? row.source_kind;
  const sourceUri = detail?.source_uri ?? row.source_uri;
  const fetchedTs = detail?.fetched_ts ?? row.fetched_ts;

  const marked = useMemo(
    () =>
      detail
        ? markSegments(detail.text, detail.items)
        : { segments: [] as Segment[], dropped: 0 },
    [detail],
  );

  const notes: string[] = [];
  if (detail?.truncated) {
    notes.push(
      `문서가 길어 앞부분 ${detail.text.length.toLocaleString("ko-KR")}자만 표시합니다 (전체 ${detail.total_chars.toLocaleString("ko-KR")}자).`,
    );
  }
  if (marked.dropped > 0) {
    notes.push(
      `근거 ${marked.dropped}개는 범위가 비어 있어 본문에 표시하지 못했습니다.`,
    );
  }
  const unplaced = detail?.items.filter((item) => !item.span).length ?? 0;
  if (unplaced > 0) {
    notes.push(
      `제안 ${unplaced}개는 본문에 근거 문장이 없습니다. 검토 시 주의합니다.`,
    );
  }

  return (
    <>
      <DialogHeader className="pr-10">
        <DialogTitle className="truncate" title={title}>
          {title}
        </DialogTitle>
        <DialogDescription asChild>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span>
              {SOURCE_KO[String(sourceKind || "")] ?? (sourceKind || "—")}
            </span>
            <span aria-hidden="true">·</span>
            <CopyableIdentifier
              value={sourceUri}
              label="전체 출처 URL 복사"
              className="max-w-72"
            />
            <span aria-hidden="true">·</span>
            <RelativeTime ts={fetchedTs} />
            <span aria-hidden="true">·</span>
            <CopyableIdentifier
              value={row.id}
              label="문서 ID 복사"
              display={row.id.slice(0, 12)}
            />
          </div>
        </DialogDescription>
      </DialogHeader>

      {error !== undefined ? (
        <ErrorSurface
          error={error}
          fallback="문서 원문을 불러오지 못했습니다."
          onRetry={onRetry}
          retrying={false}
        />
      ) : !detail ? (
        <div className="space-y-3">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-56 w-full" />
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <section className="flex min-h-0 flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-medium">원문</h2>
              <SpanLegend />
            </div>
            <ScrollArea
              className={cn("rounded-lg border bg-background", PANE_HEIGHT)}
            >
              <pre className="whitespace-pre-wrap break-words p-4 font-sans text-sm leading-relaxed">
                {detail.text ? (
                  marked.segments.map((segment, index) => {
                    const tone = segment.status
                      ? SPAN_TONE[segment.status]
                      : undefined;
                    return tone ? (
                      <mark
                        key={index}
                        className={cn("rounded-sm text-foreground", tone)}
                        title={STATUS_KO[segment.status ?? ""] ?? segment.status ?? ""}
                      >
                        {segment.text}
                      </mark>
                    ) : (
                      <span key={index}>{segment.text}</span>
                    );
                  })
                ) : (
                  <span className="text-muted-foreground">
                    원문 파일이 없어 본문을 표시할 수 없습니다. 제안 목록은 그대로
                    유효합니다.
                  </span>
                )}
              </pre>
            </ScrollArea>
            {notes.length > 0 && (
              <ul className="space-y-1">
                {notes.map((note) => (
                  <li key={note} className="text-xs text-muted-foreground">
                    {note}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="flex min-h-0 flex-col gap-2">
            <h2 className="flex items-center gap-2 text-sm font-medium">
              추출된 개체
              <Badge variant="secondary" className="font-mono tabular-nums">
                {detail.items.length.toLocaleString("ko-KR")}
              </Badge>
            </h2>
            <ScrollArea
              className={cn("rounded-lg border bg-background", PANE_HEIGHT)}
            >
              {detail.items.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">
                  이 문서에서 생성된 제안이 없습니다.
                </p>
              ) : (
                <ul className="divide-y">
                  {detail.items.map((item) => (
                    <li key={item.id} className="space-y-1.5 p-3">
                      <div className="flex items-start justify-between gap-2">
                        <span className="min-w-0 break-words text-sm font-medium">
                          {item.label}
                        </span>
                        <Badge
                          variant="outline"
                          className="shrink-0 text-label text-muted-foreground"
                        >
                          {item.kind === "node" ? "개념" : "관계"}
                        </Badge>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <code
                          className="font-mono text-xs text-muted-foreground"
                          title={`기계 값: ${item.type}`}
                        >
                          {item.type}
                        </code>
                        <StatusBadge status={item.status} />
                        {item.invalidated ? (
                          <Badge
                            variant="outline"
                            className="border-destructive/40 text-destructive"
                          >
                            무효화됨
                          </Badge>
                        ) : null}
                        {!item.span ? (
                          <span
                            className="text-xs text-warn"
                            title="추출기가 본문 근거 없이 낸 제안입니다"
                          >
                            근거 없음
                          </span>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </ScrollArea>
          </section>
        </div>
      )}
    </>
  );
}

/* ---------------------------------------------------------------------------
   Pack detail — the manifest is already in hand from the list, so counts and
   lineage render without a request; the entity and relation lists come from
   the pack endpoint.
   --------------------------------------------------------------------------- */

function PackDetailView({
  pack,
  detail,
  error,
  onRetry,
}: {
  pack: Pack;
  detail: PackDetail | undefined;
  error: unknown;
  onRetry: () => void;
}) {
  const counts = { ...(pack.counts ?? {}), ...(detail?.counts ?? {}) };
  const entities = detail?.entities ?? [];
  const relations = detail?.relations ?? [];
  const lineage: { label: string; value: string }[] = [
    {
      label: "스키마",
      value: `${pack.schema_label ?? "—"} (v${pack.schema_version_id ?? "?"})`,
    },
    { label: "빌드 작업", value: String(pack.source_job_id ?? "—") },
    { label: "개체 종류", value: `${counts.entity_types ?? 0}종` },
    { label: "관계 종류", value: `${counts.relation_types ?? 0}종` },
    { label: "커뮤니티", value: `${counts.communities ?? 0}개` },
    {
      label: "임베딩",
      value: pack.embedding_model ?? "없음 (어휘 검색만)",
    },
    { label: "빌드 버전", value: String(pack.ontologylab_version ?? "—") },
  ];

  return (
    <>
      <DialogHeader className="pr-10">
        <DialogTitle className="flex items-center gap-2">
          <Layers className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <code className="min-w-0 truncate font-mono" title={pack.pack_id}>
            {pack.pack_id}
          </code>
        </DialogTitle>
        <DialogDescription asChild>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <RelativeTime ts={pack.created_ts} />
            <span aria-hidden="true">·</span>
            <span>지문</span>
            <CopyableIdentifier
              value={pack.content_hash}
              label="콘텐츠 해시 전체 복사"
              display={shortHash(pack.content_hash)}
            />
          </div>
        </DialogDescription>
      </DialogHeader>

      <div className="grid grid-cols-3 gap-2">
        <MetricCell label="문서" value={counts.documents ?? 0} />
        <MetricCell label="개념" value={counts.nodes_verified ?? 0} />
        <MetricCell label="관계" value={counts.edges_verified ?? 0} />
      </div>

      <section className="space-y-2">
        <h2 className="text-sm font-medium">계보 — 무엇이 이 팩에 들어갔나</h2>
        <dl className="grid gap-x-4 gap-y-1.5 sm:grid-cols-2">
          {lineage.map((entry) => (
            <div
              key={entry.label}
              className="flex items-baseline justify-between gap-2 border-b border-dashed py-1"
            >
              <dt className="text-xs text-muted-foreground">{entry.label}</dt>
              <dd
                className="min-w-0 truncate text-right text-sm"
                title={entry.value}
              >
                {entry.value}
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <Separator />

      {error !== undefined ? (
        <ErrorSurface
          error={error}
          fallback="팩의 개체·관계 목록을 불러오지 못했습니다."
          onRetry={onRetry}
          retrying={false}
        />
      ) : !detail ? (
        <div className="space-y-3">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 gap-4 sm:grid-cols-2">
          <section className="flex min-h-0 flex-col gap-2">
            <h2 className="flex items-center gap-2 text-sm font-medium">
              개체
              <Badge variant="secondary" className="font-mono tabular-nums">
                {entities.length.toLocaleString("ko-KR")}
              </Badge>
            </h2>
            <ScrollArea className={cn("rounded-lg border bg-background", PANE_HEIGHT)}>
              {entities.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">
                  이 팩에 표시할 개체가 없습니다.
                </p>
              ) : (
                <ul className="divide-y">
                  {entities.map((entity, index) => (
                    <li
                      key={entity.id ?? `entity-${index}`}
                      className="flex items-start justify-between gap-2 p-3"
                    >
                      <span className="min-w-0 break-words text-sm">
                        {entity.name ?? entity.id ?? "—"}
                      </span>
                      {entity.entity_type ? (
                        <code
                          className="shrink-0 font-mono text-xs text-muted-foreground"
                          title={`기계 값: ${entity.entity_type}`}
                        >
                          {entity.entity_type}
                        </code>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </ScrollArea>
          </section>

          <section className="flex min-h-0 flex-col gap-2">
            <h2 className="flex items-center gap-2 text-sm font-medium">
              관계
              <Badge variant="secondary" className="font-mono tabular-nums">
                {relations.length.toLocaleString("ko-KR")}
              </Badge>
            </h2>
            <ScrollArea className={cn("rounded-lg border bg-background", PANE_HEIGHT)}>
              {relations.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">
                  이 팩에 표시할 관계가 없습니다.
                </p>
              ) : (
                <ul className="divide-y">
                  {relations.map((relation, index) => (
                    <li
                      key={relation.id ?? `relation-${index}`}
                      className="space-y-1 p-3"
                    >
                      <div className="flex min-w-0 items-center gap-1.5 text-sm">
                        <span className="min-w-0 truncate">
                          {relation.src_name ?? "—"}
                        </span>
                        <ArrowRight
                          className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                          aria-hidden="true"
                        />
                        <span className="min-w-0 truncate">
                          {relation.dst_name ?? "—"}
                        </span>
                      </div>
                      {relation.relation_type ? (
                        <code
                          className="font-mono text-xs text-muted-foreground"
                          title={`기계 값: ${relation.relation_type}`}
                        >
                          {relation.relation_type}
                        </code>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </ScrollArea>
          </section>
        </div>
      )}
    </>
  );
}
