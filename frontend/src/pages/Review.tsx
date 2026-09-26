import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";
import {
  AlertCircle,
  AlertTriangle,
  ArrowRightLeft,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleDot,
  Clock,
  Copy,
  FileText,
  FlaskConical,
  Gauge,
  Inbox,
  ListChecks,
  Loader2,
  RefreshCw,
  Scale,
  Undo2,
  X,
  XCircle,
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { get, post } from "@/lib/api";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Wire shapes — mirrored from ontologylab/server/routes.py (GET /proposals,
// GET /review/triage, GET /review/calibration, POST /proposals/{approve,
// reject,reopen}) and the rows kgstore.pending_review() enriches.
// ---------------------------------------------------------------------------

type Kind = "node" | "edge";

type Proposal = {
  kind: Kind;
  id: string;
  type_name: string;
  /** Node name, or "출발 개념 -> 도착 개념" with endpoint names resolved. */
  label: string;
  confidence: number | null;
  source_doc_id: string | null;
  created_ts: number;
  critic_score: number | null;
  critic_rationale: string | null;
  critic_engine: string | null;
  critic_disagreement: boolean;
  doc_title: string | null;
  doc_source: string;
  evidence_grade: string;
  excerpt: string;
  /** Edge qualifiers as stored; `polarity` says whether the claim supports,
   *  refutes, or reports no effect. Absent on nodes. */
  qualifiers?: Record<string, unknown>;
  /** Present only on rows from /proposals/decided. */
  status?: "verified" | "rejected";
  verified_ts?: number | null;
  verified_by?: string | null;
  review_note?: string | null;
};

type DecidedPage = { items: Proposal[]; count: number };

type BulkResult = {
  approved: string[];
  skipped: { id: string; reason: string }[];
  failed: { id: string; reason: string }[];
};

type StaleItem = {
  kind: Kind;
  id: string;
  label: string;
  type_name: string;
  verified_ts: number | null;
  verified_by: string | null;
  doc_title: string | null;
  doc_ts: number;
  newer_ts: number;
  newer_doc_id: string;
};

type ReviewCounts = {
  nodes_proposed: number;
  nodes_verified: number;
  nodes_rejected: number;
  edges_proposed: number;
  edges_verified: number;
  edges_rejected: number;
  documents: number;
  merge_candidates_pending: number;
};

type ProposalPage = {
  items: Proposal[];
  counts: ReviewCounts;
  count: number;
  has_more: boolean;
  next_cursor: string | null;
};

type TriageLine = {
  available: boolean;
  alpha: number;
  threshold: number | null;
  n_rejected: number;
  n_verified: number;
  needed_rejected: number;
  guarantee: string | null;
};

type CalibrationBin = {
  low: number;
  high: number;
  count: number;
  claimed: number;
  observed: number;
};

type Calibration = {
  n: number;
  min_required: number;
  available: boolean;
  raw: { ece: number | null; n: number; bins: CalibrationBin[] };
  curve: { boundaries: number[]; values: number[] } | null;
};

// ---------------------------------------------------------------------------
// Status vocabulary. DESIGN.md §5 requires icon plus text — never color alone.
// ---------------------------------------------------------------------------

type Tone = "ok" | "warn" | "danger" | "muted" | "busy";

const TONE_CLASS: Record<Tone, string> = {
  ok: "border-ok/40 bg-ok-soft text-ok-text",
  warn: "border-warn/40 bg-warn-soft text-warn-text",
  danger: "border-destructive/40 bg-destructive-soft text-destructive",
  muted: "border-border bg-muted text-muted-foreground",
  busy: "border-point/40 bg-point-soft text-point",
};

const TONE_TEXT: Record<Tone, string> = {
  ok: "text-ok-text",
  warn: "text-warn-text",
  danger: "text-destructive",
  muted: "text-muted-foreground",
  busy: "text-point",
};

type IconType = ComponentType<{ className?: string }>;

type StatusView = { label: string; tone: Tone; icon: IconType; spin?: boolean };

const PAGE_SIZE = 50;

type Decision = "approved" | "rejected";
type StatusFilter = "pending" | Decision;

/** The product's own Korean (legacy web/app.js + DESIGN.md §5 terminology). */
const KIND_LABEL: Record<Kind, string> = { node: "개념", edge: "관계" };
const KIND_ICON: Record<Kind, IconType> = { node: CircleDot, edge: ArrowRightLeft };
const DECISION_VERB: Record<Decision, string> = { approved: "승인", rejected: "거부" };

const STATUS_VIEW: Record<StatusFilter, StatusView> = {
  pending: { label: "대기", tone: "warn", icon: Clock },
  approved: { label: "승인됨", tone: "ok", icon: CheckCircle2 },
  rejected: { label: "거부됨", tone: "danger", icon: XCircle },
};

/** Evidence grade sits beside the excerpt because whether the paper was
 *  reviewed is the first material for trusting the sentence. `unknown` is
 *  never hidden — not knowing is itself actionable. */
const GRADE_LABEL: Record<string, string> = {
  peer_reviewed: "동료심사",
  preprint: "preprint · 미심사",
  registration: "임상시험 등록 · 논문 아님",
  other: "저널 논문 아님",
  unknown: "심사 여부 모름",
};

const GRADE_TONE: Record<string, Tone> = {
  peer_reviewed: "ok",
  preprint: "warn",
  registration: "muted",
  other: "muted",
  unknown: "muted",
};

/** Which count bucket a row belongs to, per kind — used to move one row
 *  between buckets without re-reading the queue. */
const COUNT_KEY: Record<Kind, Record<"proposed" | Decision, keyof ReviewCounts>> = {
  node: {
    proposed: "nodes_proposed",
    approved: "nodes_verified",
    rejected: "nodes_rejected",
  },
  edge: {
    proposed: "edges_proposed",
    approved: "edges_verified",
    rejected: "edges_rejected",
  },
};

const NUM = new Intl.NumberFormat("ko-KR");
const DATETIME_FMT = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "medium",
  timeStyle: "short",
});
const RELATIVE_FMT = new Intl.RelativeTimeFormat("ko-KR", { numeric: "auto" });

// ---------------------------------------------------------------------------
// Failure shaping. DESIGN.md §5 ErrorSurface: one Korean sentence typed by
// variant, a retry control, and the server's own words kept in a collapsed
// disclosure — never a raw `Failed to fetch` as the first layer.
// ---------------------------------------------------------------------------

type Failure = { sentence: string; detail: string; retryLabel: string };

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** `api()` throws `"<status>: <body>"`; take that apart again. */
function splitFailure(raw: string): { status: number | null; detail: string } {
  const match = /^(\d{3}):\s*([\s\S]*)$/.exec(raw);
  if (!match) return { status: null, detail: raw };
  const body = match[2].trim();
  try {
    const parsed: unknown = JSON.parse(body);
    if (parsed && typeof parsed === "object" && "detail" in parsed) {
      const detail = (parsed as { detail: unknown }).detail;
      if (typeof detail === "string") return { status: Number(match[1]), detail };
    }
  } catch {
    // FastAPI answers JSON, a proxy in front of it answers text. Both are
    // legitimate bodies, so a parse miss is not an error — keep the text.
  }
  return { status: Number(match[1]), detail: body };
}

/** 409 is the status whose body names the blocking condition, so it gets a
 *  sentence that says what to do rather than that something conflicted. */
function conflictSentence(detail: string): string {
  if (/endpoint/i.test(detail)) {
    return "관계를 승인하려면 양끝 개념을 먼저 승인해야 합니다.";
  }
  if (/grounding/i.test(detail)) {
    return "근거 검사를 통과하지 못해 승인할 수 없습니다. 출처 문장을 확인해 주세요.";
  }
  if (/transition|status/i.test(detail)) {
    return "이미 처리된 항목입니다. 목록을 새로고침한 뒤 다시 확인해 주세요.";
  }
  return "다른 항목과 충돌해 처리하지 못했습니다.";
}

/** Reopen refuses with 400 when a verified relation still hangs off the
 *  concept; the body names the blocking relations. */
function requestSentence(detail: string): string {
  if (/edge/i.test(detail)) {
    return "승인된 관계가 이 개념에 매달려 있어 되돌릴 수 없습니다. 관계를 먼저 되돌려 주세요.";
  }
  return "요청 값이 올바르지 않아 서버가 거부했습니다.";
}

function asFailure(err: unknown): Failure {
  const raw = errorText(err);
  const { status, detail } = splitFailure(raw);
  const retryLabel = status === 401 ? "화면 새로고침" : "다시 시도";
  let sentence: string;
  if (status === null) {
    sentence = /fetch|network/i.test(raw)
      ? "서버에 연결하지 못했습니다. 네트워크 상태를 확인한 뒤 다시 시도해 주세요."
      : "요청을 처리하지 못했습니다.";
  } else if (status === 401) {
    sentence = "인증이 만료되었습니다. 화면을 새로고침한 뒤 다시 시도해 주세요.";
  } else if (status === 403) {
    sentence = "이 작업을 수행할 권한이 없습니다.";
  } else if (status === 404) {
    sentence = "대상을 찾을 수 없습니다. 목록을 새로고침해 주세요.";
  } else if (status === 409) {
    sentence = conflictSentence(detail);
  } else if (status === 400 || status === 422) {
    sentence = requestSentence(detail);
  } else if (status === 429 || status === 503) {
    sentence = "서버가 바쁩니다. 잠시 후 다시 시도해 주세요.";
  } else if (status >= 500) {
    sentence = "서버에서 오류가 발생했습니다.";
  } else {
    sentence = "요청을 처리하지 못했습니다.";
  }
  return { sentence, detail, retryLabel };
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

function ratio(value: number | null | undefined): number {
  if (value == null || !Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

function percent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

/** ECE is a probability gap, so it reads in percentage points, not percent. */
function points(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(1)}%p`;
}

function shortId(value: string): string {
  return value.length <= 14 ? value : `${value.slice(0, 8)}…${value.slice(-4)}`;
}

function moveCount(
  counts: ReviewCounts,
  kind: Kind,
  from: "proposed" | Decision,
  to: "proposed" | Decision
): ReviewCounts {
  const keys = COUNT_KEY[kind];
  const next = { ...counts };
  next[keys[from]] = Math.max(0, next[keys[from]] - 1);
  next[keys[to]] = next[keys[to]] + 1;
  return next;
}

// ---------------------------------------------------------------------------
// Presentational primitives
// ---------------------------------------------------------------------------

/** DESIGN.md §5 Relative timestamp: Korean relative text, exact locale value
 *  in `title`, machine time in `datetime`, em dash when unusable. */
function RelativeTime({ ts, className }: { ts: number; className?: string }) {
  if (!Number.isFinite(ts) || ts <= 0) return <span className={className}>—</span>;
  // pending_review stores epoch seconds (REAL); tolerate millisecond rows.
  const ms = ts > 1e12 ? ts : ts * 1000;
  const date = new Date(ms);
  const seconds = (ms - Date.now()) / 1000;
  const absolute = Math.abs(seconds);
  const [value, unit]: [number, Intl.RelativeTimeFormatUnit] =
    absolute < 60
      ? [seconds, "second"]
      : absolute < 3600
        ? [seconds / 60, "minute"]
        : absolute < 86400
          ? [seconds / 3600, "hour"]
          : [seconds / 86400, "day"];
  return (
    <time
      dateTime={date.toISOString()}
      title={DATETIME_FMT.format(date)}
      className={className}
    >
      {RELATIVE_FMT.format(Math.round(value), unit)}
    </time>
  );
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    if (state === "idle") return;
    const timer = window.setTimeout(() => setState("idle"), 1500);
    return () => window.clearTimeout(timer);
  }, [state]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setState("copied");
    } catch {
      // The clipboard is permission-gated; say it failed instead of
      // reporting a copy that never happened.
      setState("failed");
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => void copy()}
        aria-label={`${label} 복사`}
        title={`${label} 복사`}
        className="rounded-sm p-0.5 text-muted-foreground transition-colors hover:text-foreground"
      >
        {state === "copied" ? (
          <Check className="h-3 w-3 text-ok-text" />
        ) : state === "failed" ? (
          <X className="h-3 w-3 text-destructive" />
        ) : (
          <Copy className="h-3 w-3" />
        )}
      </button>
      <span role="status" aria-live="polite" className="sr-only">
        {state === "copied" ? `${label}를 복사했습니다.` : ""}
        {state === "failed" ? `${label} 복사에 실패했습니다.` : ""}
      </span>
    </>
  );
}

/** DESIGN.md §5 CopyableIdentifier: a shortened visible value that never
 *  decides layout width, the full value in the accessible name, and a copy
 *  action that writes the exact string. */
function CopyableId({ value, label }: { value: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <code className="font-mono text-xs text-muted-foreground" title={value}>
        {shortId(value)}
      </code>
      <CopyButton value={value} label={label} />
    </span>
  );
}

/** `kgstore.span_excerpt` marks the cited span with `>>> <<<` inside the
 *  surrounding sentence. Paint that range — printing the markers would hand
 *  the reviewer the one thing they must read as punctuation. */
function Excerpt({ text }: { text: string }) {
  const open = text.indexOf(">>>");
  const close = open < 0 ? -1 : text.indexOf("<<<", open + 3);
  if (open < 0 || close < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, open)}
      <mark className="rounded-sm bg-point-soft px-0.5 text-point">
        {text.slice(open + 3, close)}
      </mark>
      {text.slice(close + 3)}
    </>
  );
}

function StatusBadge({ view, title }: { view: StatusView; title?: string }) {
  const Icon = view.icon;
  return (
    <Badge
      variant="outline"
      className={cn("gap-1.5 font-medium", TONE_CLASS[view.tone])}
      title={title}
    >
      <Icon className={cn("h-3.5 w-3.5 shrink-0", view.spin && "animate-spin")} />
      {view.label}
    </Badge>
  );
}

function SectionIcon({ icon: Icon }: { icon: IconType }) {
  return (
    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
      <Icon className="h-4 w-4" />
    </span>
  );
}

/** A quantity bar. Confidence is a machine claim, so it uses the interaction
 *  point colour; observed approval rate is a verdict, so it may use `--ok`. */
function Meter({
  value,
  tone = "point",
  label,
}: {
  value: number | null;
  tone?: "point" | "ok";
  label: string;
}) {
  return (
    <div
      className="h-1 w-full overflow-hidden rounded-full bg-border"
      role="img"
      aria-label={label}
    >
      <div
        className={cn("h-full rounded-full", tone === "ok" ? "bg-ok" : "bg-point")}
        style={{ width: `${ratio(value) * 100}%` }}
      />
    </div>
  );
}

function FieldCaption({ children }: { children: ReactNode }) {
  return (
    <span className="text-label font-medium uppercase tracking-[0.08em] text-muted-foreground">
      {children}
    </span>
  );
}

function MetricTile({
  label,
  value,
  hint,
  tone = "muted",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: Tone;
}) {
  return (
    <div className="rounded-md border bg-muted/40 p-3">
      <FieldCaption>{label}</FieldCaption>
      <div className={cn("mt-1 font-mono text-lg tabular-nums", TONE_TEXT[tone])}>
        {value}
      </div>
      {hint ? <div className="mt-1 text-xs text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

function SummaryCard({
  icon: Icon,
  tone,
  label,
  value,
  hint,
  loading,
}: {
  icon: IconType;
  tone: Tone;
  label: string;
  value: number;
  hint: string;
  loading: boolean;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-2">
        <FieldCaption>{label}</FieldCaption>
        <Icon className={cn("h-4 w-4 shrink-0", TONE_TEXT[tone])} />
      </div>
      {loading ? (
        <Skeleton className="mt-2 h-7 w-16" />
      ) : (
        <div className="mt-2 font-mono text-2xl tabular-nums">{NUM.format(value)}</div>
      )}
      {loading ? (
        <Skeleton className="mt-2 h-3 w-28" />
      ) : (
        <div className="mt-1 text-xs text-muted-foreground">{hint}</div>
      )}
    </Card>
  );
}

function TableSkeleton({ rows, cols }: { rows: number; cols: number }) {
  return (
    <div className="space-y-2 p-2">
      {Array.from({ length: rows }, (_, row) => (
        <div key={row} className="flex items-center gap-4">
          {Array.from({ length: cols }, (_, col) => (
            <Skeleton key={col} className={cn("h-4", col === 0 ? "w-48" : "flex-1")} />
          ))}
        </div>
      ))}
    </div>
  );
}

function MetricSkeleton({ tiles }: { tiles: number }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {Array.from({ length: tiles }, (_, index) => (
        <Skeleton key={index} className="h-20 w-full" />
      ))}
    </div>
  );
}

/** DESIGN.md §5 CTA EmptyState: semantic icon, formal title, one sentence,
 *  and a control that performs the next action. */
function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: IconType;
  title: string;
  description: string;
  action: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 px-4 py-10 text-center">
      <span className="flex h-10 w-10 items-center justify-center rounded-full border bg-muted text-muted-foreground">
        <Icon className="h-5 w-5" />
      </span>
      <div className="space-y-1">
        <p className="font-medium">{title}</p>
        <p className="mx-auto max-w-[72ch] text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  );
}

function ErrorSurface({
  failure,
  onRetry,
  retrying,
}: {
  failure: Failure;
  onRetry: () => void;
  retrying: boolean;
}) {
  return (
    <Alert variant="destructive" aria-live="polite">
      <AlertCircle className="h-4 w-4" />
      <AlertTitle>요청을 완료하지 못했습니다</AlertTitle>
      <AlertDescription className="space-y-3">
        <p className="break-words">{failure.sentence}</p>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            className="text-foreground"
            onClick={onRetry}
            disabled={retrying}
          >
            {retrying ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            {retrying ? "다시 시도 중…" : failure.retryLabel}
          </Button>
          {failure.detail ? <CopyButton value={failure.detail} label="서버 응답" /> : null}
        </div>
        {failure.detail ? (
          <details className="text-foreground">
            <summary className="cursor-pointer text-xs text-muted-foreground">
              서버 응답 보기
            </summary>
            <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-md border bg-background p-2 font-mono text-xs text-muted-foreground">
              {failure.detail}
            </pre>
          </details>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}

// ---------------------------------------------------------------------------
// One queue row. The same cells serve the pending queue and the session
// history; only the status view and the action control differ.
// ---------------------------------------------------------------------------

function ConfidenceCell({
  item,
  threshold,
}: {
  item: Proposal;
  threshold: number | null;
}) {
  const belowLine = threshold != null && item.critic_score != null && item.critic_score <= threshold;
  return (
    <div className="w-28 space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-sm tabular-nums">{percent(item.confidence)}</span>
        {item.critic_score != null ? (
          <span
            className="font-mono text-xs tabular-nums text-muted-foreground"
            title={item.critic_rationale ?? undefined}
          >
            비평 {percent(item.critic_score)}
          </span>
        ) : null}
      </div>
      <Meter value={item.confidence} label={`추출 신뢰도 ${percent(item.confidence)}`} />
      {item.critic_disagreement || belowLine ? (
        <div className="flex flex-wrap gap-1.5">
          {item.critic_disagreement ? (
            <StatusBadge
              view={{ label: "비평 불일치", tone: "warn", icon: AlertTriangle }}
              title="추출 신뢰도와 비평 점수가 크게 다릅니다."
            />
          ) : null}
          {belowLine ? (
            <StatusBadge
              view={{ label: "기준선 이하", tone: "warn", icon: Scale }}
              title={`비평 점수가 트리아지 기준선 ${threshold?.toFixed(2)} 이하입니다 — 거부될 가능성이 높은 구간입니다.`}
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function DocumentCell({ item }: { item: Proposal }) {
  if (!item.source_doc_id) {
    return <span className="text-sm text-muted-foreground">—</span>;
  }
  const grade = item.evidence_grade || "unknown";
  return (
    <div className="max-w-xs space-y-1.5">
      <div className="line-clamp-2 text-sm">{item.doc_title || "제목 없음"}</div>
      <CopyableId value={item.source_doc_id} label="문서 ID" />
      <div className="flex flex-wrap items-center gap-1.5">
        <StatusBadge
          view={{
            label: GRADE_LABEL[grade] ?? grade,
            tone: GRADE_TONE[grade] ?? "muted",
            icon: FileText,
          }}
        />
        {item.doc_source ? (
          <span className="font-mono text-xs text-muted-foreground">{item.doc_source}</span>
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Master-detail queue. The list on the left stays compact (one line of
// identity + the numbers needed to triage); the detail on the right carries
// the full evidence — excerpt, source document, confidence breakdown, and
// the action control. j/k moves the focus on the pending tab and the detail
// follows it, so the evidence under review is always the keyboard target.
// ---------------------------------------------------------------------------

function ProposalListItem({
  item,
  view,
  threshold,
  checked,
  onCheckedChange,
  active,
  decisionBadge,
  onSelect,
}: {
  item: Proposal;
  view: StatusView;
  threshold: number | null;
  checked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
  active?: boolean;
  decisionBadge?: ReactNode;
  onSelect: () => void;
}) {
  const Icon = KIND_ICON[item.kind];
  const belowLine =
    threshold != null && item.critic_score != null && item.critic_score <= threshold;
  return (
    <li data-focused={active || undefined}>
      <div
        className={cn(
          "flex items-start gap-2 rounded-md border px-2.5 py-2 transition-colors",
          active ? "border-point bg-accent/60" : "border-transparent hover:bg-accent/40"
        )}
      >
        {onCheckedChange ? (
          <input
            type="checkbox"
            aria-label={`${item.label} 선택`}
            className="mt-1 h-4 w-4 shrink-0 accent-point"
            checked={checked ?? false}
            onChange={(event) => onCheckedChange(event.target.checked)}
          />
        ) : null}
        <button
          type="button"
          onClick={onSelect}
          className="flex min-w-0 flex-1 items-start gap-2 text-left"
          aria-current={active || undefined}
        >
          <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{item.label}</span>
            <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
              <span>{KIND_LABEL[item.kind]}</span>
              <Badge variant="outline" className="px-1 py-0 font-mono text-[10px]">
                {item.type_name}
              </Badge>
              <PolarityBadge item={item} compact />
              <span className="font-mono tabular-nums">{percent(item.confidence)}</span>
              {item.critic_disagreement || belowLine ? (
                <AlertTriangle className="h-3 w-3 text-warn-text" aria-label="비평 경고" />
              ) : null}
            </span>
          </span>
          <span className="flex shrink-0 items-center gap-1.5">
            {decisionBadge}
            <StatusBadge view={view} />
          </span>
        </button>
      </div>
    </li>
  );
}

// A claim's polarity decides what approving it means, so the reviewer sees it
// next to the relation type rather than buried in a qualifier dump.
const POLARITY_LABEL: Record<string, { text: string; variant: "success" | "error" | "warning" }> = {
  supports: { text: "지지", variant: "success" },
  refutes: { text: "반박", variant: "error" },
  no_effect: { text: "효과 없음", variant: "warning" },
};

function qualifierText(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

function PolarityBadge({ item, compact }: { item: Proposal; compact?: boolean }) {
  const raw = item.qualifiers?.polarity;
  if (typeof raw !== "string" || raw === "") return null;
  const known = POLARITY_LABEL[raw];
  return (
    <Badge
      variant={known?.variant ?? "outline"}
      className={cn(compact ? "px-1 py-0 text-[10px]" : "text-xs")}
      aria-label={`극성: ${known?.text ?? raw}`}
    >
      {known?.text ?? raw}
    </Badge>
  );
}

function QualifierList({ item }: { item: Proposal }) {
  const entries = Object.entries(item.qualifiers ?? {});
  if (entries.length === 0) return null;
  return (
    <section className="space-y-1.5">
      <FieldCaption>수식어</FieldCaption>
      <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-xs">
        {entries.map(([key, value]) => (
          <div key={key} className="contents">
            <dt className="font-mono text-muted-foreground">{key}</dt>
            <dd className="break-words">{qualifierText(value)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function ProposalDetail({
  item,
  view,
  threshold,
  stale,
  decision,
  actions,
}: {
  item: Proposal | null;
  view: StatusView;
  threshold: number | null;
  stale?: boolean;
  decision?: ReactNode;
  actions?: ReactNode;
}) {
  if (!item) {
    return (
      <div className="flex h-full min-h-40 flex-col items-center justify-center gap-2 rounded-md border border-dashed px-4 py-8 text-center">
        <ListChecks className="h-5 w-5 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          왼쪽 목록에서 항목을 고르면 근거 문장과 신뢰도가 여기에 표시됩니다.
        </p>
      </div>
    );
  }
  const Icon = KIND_ICON[item.kind];
  return (
    <div className="flex flex-col gap-4 rounded-md border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2">
          <Icon className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0 space-y-1">
            <div className="font-medium leading-snug">{item.label}</div>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="text-xs text-muted-foreground">{KIND_LABEL[item.kind]}</span>
              <Badge variant="outline" className="font-mono">
                {item.type_name}
              </Badge>
              <PolarityBadge item={item} />
              <CopyableId value={item.id} label="항목 ID" />
              <RelativeTime ts={item.created_ts} className="text-xs text-muted-foreground" />
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {stale ? (
            <Badge variant="warning" className="text-[10px]">
              원본 변경됨
            </Badge>
          ) : null}
          <StatusBadge view={view} />
        </div>
      </div>

      {item.excerpt ? (
        <section className="space-y-1.5">
          <FieldCaption>근거 문장</FieldCaption>
          <p className="max-w-[72ch] text-sm leading-relaxed text-muted-foreground">
            “<Excerpt text={item.excerpt} />”
          </p>
        </section>
      ) : null}

      <QualifierList item={item} />

      <div className="grid gap-4 sm:grid-cols-2">
        <section className="space-y-1.5">
          <FieldCaption>출처 문서</FieldCaption>
          <DocumentCell item={item} />
        </section>
        <section className="space-y-1.5">
          <FieldCaption>신뢰도</FieldCaption>
          <ConfidenceCell item={item} threshold={threshold} />
        </section>
      </div>

      {item.critic_rationale ? (
        <section className="space-y-1.5">
          <FieldCaption>비평 근거</FieldCaption>
          <p className="break-words text-xs leading-relaxed text-muted-foreground">
            {item.critic_rationale}
          </p>
        </section>
      ) : null}

      {decision ? <div className="border-t pt-3">{decision}</div> : null}

      {actions ? (
        <div className="flex flex-wrap justify-end gap-2 border-t pt-3">{actions}</div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const QUEUE_DESCRIPTION: Record<StatusFilter, string> = {
  pending:
    "승인한 제안만 그래프의 사실로 기록됩니다. 근거 문장과 신뢰도를 확인한 뒤 판단합니다.",
  approved:
    "서버는 대기 중인 제안만 목록으로 제공합니다. 이 표는 이번 세션에서 승인한 항목이며, 되돌리면 다시 대기 큐로 돌아갑니다.",
  rejected:
    "서버는 대기 중인 제안만 목록으로 제공합니다. 이 표는 이번 세션에서 거부한 항목이며, 되돌리면 다시 대기 큐로 돌아갑니다.",
};

export default function ReviewPage() {
  const [items, setItems] = useState<Proposal[]>([]);
  const [counts, setCounts] = useState<ReviewCounts | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [triage, setTriage] = useState<TriageLine | null>(null);
  const [calibration, setCalibration] = useState<Calibration | null>(null);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadFailure, setLoadFailure] = useState<Failure | null>(null);
  const [statsFailure, setStatsFailure] = useState<Failure | null>(null);
  const [actionFailure, setActionFailure] = useState<Failure | null>(null);

  const [filter, setFilter] = useState<StatusFilter>("pending");
  const [decided, setDecided] = useState<Proposal[]>([]);
  const [decidedLoading, setDecidedLoading] = useState(false);
  const [decidedFailure, setDecidedFailure] = useState<Failure | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<string | null>(null);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [bulkConfirm, setBulkConfirm] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkResult, setBulkResult] = useState<BulkResult | null>(null);
  const [rejectTarget, setRejectTarget] = useState<Proposal | null>(null);
  const [rejectNote, setRejectNote] = useState("");
  const [focusedIdx, setFocusedIdx] = useState(-1);
  const [staleIds, setStaleIds] = useState<ReadonlySet<string>>(new Set());
  /** Master-detail selection on the decided tabs (pending uses focusedIdx). */
  const [detailId, setDetailId] = useState<string | null>(null);

  const load = useCallback(async (mode: "initial" | "refresh") => {
    if (mode === "initial") setLoading(true);
    else setRefreshing(true);

    const [queueResult, triageResult, calibrationResult] = await Promise.allSettled([
      get<ProposalPage>(`/proposals?limit=${PAGE_SIZE}`),
      get<TriageLine>("/review/triage"),
      get<Calibration>("/review/calibration"),
    ]);

    if (queueResult.status === "fulfilled") {
      setItems(queueResult.value.items ?? []);
      setCounts(queueResult.value.counts ?? null);
      setCursor(queueResult.value.next_cursor ?? null);
      setHasMore(Boolean(queueResult.value.has_more));
      setLoadFailure(null);
    } else {
      setLoadFailure(asFailure(queueResult.reason));
    }

    // The two statistics endpoints read review history through optional
    // modules; one of them failing must not blank the queue, so the failure
    // is reported beside them instead of replacing the page.
    setTriage(triageResult.status === "fulfilled" ? triageResult.value : null);
    setCalibration(
      calibrationResult.status === "fulfilled" ? calibrationResult.value : null
    );
    const statsRejection = [triageResult, calibrationResult].find(
      (result): result is PromiseRejectedResult => result.status === "rejected"
    );
    setStatsFailure(statsRejection ? asFailure(statsRejection.reason) : null);

    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    void load("initial");
  }, [load]);

  /** A decision changes the review history the two statistics are computed
   *  from, so they are re-read. The queue itself is not: the decided row is
   *  already gone locally and the pages below it must keep their place. */
  const syncStats = useCallback(async () => {
    const [triageResult, calibrationResult] = await Promise.allSettled([
      get<TriageLine>("/review/triage"),
      get<Calibration>("/review/calibration"),
    ]);
    if (triageResult.status === "fulfilled") setTriage(triageResult.value);
    if (calibrationResult.status === "fulfilled") setCalibration(calibrationResult.value);
  }, []);

  async function loadMore() {
    if (!cursor) return;
    setLoadingMore(true);
    setActionFailure(null);
    try {
      // One user action, one cursor request (DESIGN.md §5 Progressive
      // ReviewList): pages append in server order, nothing polls.
      const next = await get<ProposalPage>(
        `/proposals?limit=${PAGE_SIZE}&cursor=${encodeURIComponent(cursor)}`
      );
      setItems((prev) => {
        const seen = new Set(prev.map((row) => row.id));
        return [...prev, ...(next.items ?? []).filter((row) => !seen.has(row.id))];
      });
      setCounts(next.counts ?? null);
      setCursor(next.next_cursor ?? null);
      setHasMore(Boolean(next.has_more));
    } catch (err) {
      setActionFailure(asFailure(err));
    } finally {
      setLoadingMore(false);
    }
  }

  const loadDecided = useCallback(async (decision: Decision) => {
    setDecidedLoading(true);
    setDecidedFailure(null);
    try {
      const serverDecision = decision === "approved" ? "verified" : "rejected";
      const res = await get<DecidedPage>(
        `/proposals/decided?decision=${serverDecision}`
      );
      setDecided(res.items ?? []);
      if (decision === "approved") {
        const stale = await get<{ items: StaleItem[] }>("/proposals/stale");
        setStaleIds(new Set(stale.items.map((row) => row.id)));
      }
    } catch (err) {
      setDecidedFailure(asFailure(err));
    } finally {
      setDecidedLoading(false);
    }
  }, []);

  useEffect(() => {
    if (filter !== "pending") void loadDecided(filter);
  }, [filter, loadDecided]);

  async function decide(item: Proposal, decision: Decision, note?: string) {
    setBusyId(item.id);
    setActionFailure(null);
    setReceipt(null);
    try {
      await post<{ ok: boolean }>(
        decision === "approved" ? "/proposals/approve" : "/proposals/reject",
        { id: item.id, ...(note ? { note } : {}) }
      );
      setItems((prev) => prev.filter((row) => row.id !== item.id));
      setSelected((prev) => {
        const next = new Set(prev);
        next.delete(item.id);
        return next;
      });
      setCounts((prev) => (prev ? moveCount(prev, item.kind, "proposed", decision) : prev));
      setReceipt(`${DECISION_VERB[decision]}했습니다 — ${item.label}`);
      await syncStats();
    } catch (err) {
      setActionFailure(asFailure(err));
    } finally {
      setBusyId(null);
    }
  }

  async function reopen(item: Proposal) {
    setBusyId(item.id);
    setActionFailure(null);
    setReceipt(null);
    try {
      await post<{ ok: boolean }>("/proposals/reopen", { id: item.id });
      setDecided((prev) => prev.filter((entry) => entry.id !== item.id));
      // The row is back in the queue; the queue is ordered by creation time,
      // so it goes back where the server would have served it.
      setItems((prev) =>
        [...prev.filter((entry) => entry.id !== item.id), item].sort(
          (a, b) => a.created_ts - b.created_ts
        )
      );
      const decision: Decision =
        item.status === "verified" ? "approved" : "rejected";
      setCounts((prev) =>
        prev ? moveCount(prev, item.kind, decision, "proposed") : prev
      );
      setReceipt(`되돌렸습니다 — ${item.label}`);
      await syncStats();
    } catch (err) {
      setActionFailure(asFailure(err));
    } finally {
      setBusyId(null);
    }
  }

  async function bulkApprove() {
    setBulkBusy(true);
    setActionFailure(null);
    setReceipt(null);
    try {
      const res = await post<BulkResult & { ok: boolean }>(
        "/proposals/bulk-approve",
        { ids: [...selected] }
      );
      setBulkResult(res);
      const approved = new Set(res.approved);
      setItems((prev) => prev.filter((row) => !approved.has(row.id)));
      setSelected(new Set());
      setCounts((prev) => {
        if (!prev) return prev;
        let next = prev;
        for (const row of items) {
          if (approved.has(row.id)) {
            next = moveCount(next, row.kind, "proposed", "approved");
          }
        }
        return next;
      });
      await syncStats();
    } catch (err) {
      setActionFailure(asFailure(err));
    } finally {
      setBulkBusy(false);
      setBulkConfirm(false);
    }
  }

  /** Both the receipt and the action failure describe one row in the list
   *  being left behind, so neither may survive the switch. */
  function changeFilter(next: StatusFilter) {
    setFilter(next);
    setActionFailure(null);
    setReceipt(null);
    setDetailId(null);
  }

  const pendingTotal = counts ? counts.nodes_proposed + counts.edges_proposed : 0;
  const approvedTotal = counts ? counts.nodes_verified + counts.edges_verified : 0;
  const rejectedTotal = counts ? counts.nodes_rejected + counts.edges_rejected : 0;
  const decidedTotal: Record<Decision, number> = {
    approved: approvedTotal,
    rejected: rejectedTotal,
  };

  const threshold = triage?.available ? triage.threshold : null;

  const selectedItems = useMemo(
    () => items.filter((row) => selected.has(row.id)),
    [items, selected]
  );
  const selectedNodes = selectedItems.filter((row) => row.kind === "node").length;
  const selectedEdges = selectedItems.filter((row) => row.kind === "edge").length;

  const belowLine = useMemo(() => {
    if (threshold == null) return 0;
    return items.filter(
      (item) => item.critic_score != null && item.critic_score <= threshold
    ).length;
  }, [items, threshold]);

  /* Keyboard shortcuts: j/k navigate, a approve, r reject, x toggle select.
     Only active on the pending tab with no dialog open and no input focused. */
  useEffect(() => {
    if (filter !== "pending") return;
    const handler = (event: KeyboardEvent) => {
      const tag = (event.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (bulkConfirm || bulkResult || rejectTarget) return;
      const item = items[focusedIdx];
      switch (event.key) {
        case "j":
          event.preventDefault();
          setFocusedIdx((prev) => Math.min(prev + 1, items.length - 1));
          break;
        case "k":
          event.preventDefault();
          setFocusedIdx((prev) => Math.max(prev - 1, 0));
          break;
        case "a":
          if (item) void decide(item, "approved");
          break;
        case "r":
          if (item) {
            setRejectTarget(item);
            setRejectNote("");
          }
          break;
        case "x":
          if (item) {
            setSelected((prev) => {
              const next = new Set(prev);
              if (next.has(item.id)) next.delete(item.id);
              else next.add(item.id);
              return next;
            });
          }
          break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [filter, items, focusedIdx, bulkConfirm, bulkResult, rejectTarget]);

  /* Master-detail: the detail pane always shows the focused row. When a
     decision removes a row, the focus slides onto what is now in its place;
     an empty queue or an unstarted focus picks the first row. */
  useEffect(() => {
    if (filter !== "pending" || items.length === 0) return;
    setFocusedIdx((prev) => (prev < 0 ? 0 : Math.min(prev, items.length - 1)));
  }, [filter, items.length]);

  useEffect(() => {
    if (filter === "pending") return;
    if (detailId && decided.some((row) => row.id === detailId)) return;
    setDetailId(decided[0]?.id ?? null);
  }, [filter, decided, detailId]);

  /* j/k can walk the focus past the visible window — keep it on screen. */
  useEffect(() => {
    if (focusedIdx < 0) return;
    document.querySelector("[data-focused]")?.scrollIntoView({ block: "nearest" });
  }, [focusedIdx]);

  const decidedDetail = decided.find((row) => row.id === detailId) ?? null;

  const filterCount: Record<StatusFilter, number> = {
    pending: pendingTotal,
    approved: approvedTotal,
    rejected: rejectedTotal,
  };

  const busy = loading || refreshing;

  return (
    <div className="mx-auto w-full max-w-[1080px] space-y-6 p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold leading-tight tracking-tight">검토</h1>
          <p className="text-sm text-muted-foreground">
            AI가 추출한 제안을 승인하거나 거부합니다. 승인된 항목만 그래프의 사실이 됩니다.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <FieldCaption>상태</FieldCaption>
          <Select value={filter} onValueChange={(value) => changeFilter(value as StatusFilter)}>
            <SelectTrigger className="h-7 w-36" aria-label="상태 필터">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="pending">대기 {NUM.format(filterCount.pending)}</SelectItem>
              <SelectItem value="approved">
                승인됨 {NUM.format(filterCount.approved)}
              </SelectItem>
              <SelectItem value="rejected">
                거부됨 {NUM.format(filterCount.rejected)}
              </SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void load("refresh")}
            disabled={busy}
          >
            <RefreshCw className={cn(refreshing && "animate-spin")} />
            새로고침
          </Button>
        </div>
      </header>

      {loadFailure ? (
        <ErrorSurface
          failure={loadFailure}
          onRetry={() => void load("refresh")}
          retrying={refreshing}
        />
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard
          icon={Clock}
          tone="warn"
          label="대기"
          value={pendingTotal}
          hint={
            counts
              ? `개념 ${NUM.format(counts.nodes_proposed)} · 관계 ${NUM.format(counts.edges_proposed)}`
              : "—"
          }
          loading={loading}
        />
        <SummaryCard
          icon={CheckCircle2}
          tone="ok"
          label="승인됨"
          value={approvedTotal}
          hint={
            counts
              ? `개념 ${NUM.format(counts.nodes_verified)} · 관계 ${NUM.format(counts.edges_verified)}`
              : "—"
          }
          loading={loading}
        />
        <SummaryCard
          icon={XCircle}
          tone="danger"
          label="거부됨"
          value={rejectedTotal}
          hint={
            counts
              ? `개념 ${NUM.format(counts.nodes_rejected)} · 관계 ${NUM.format(counts.edges_rejected)}`
              : "—"
          }
          loading={loading}
        />
        <SummaryCard
          icon={FileText}
          tone="muted"
          label="문서"
          value={counts?.documents ?? 0}
          hint={
            counts ? `병합 대기 ${NUM.format(counts.merge_candidates_pending)}건` : "—"
          }
          loading={loading}
        />
      </div>

      <Tabs defaultValue="queue" className="space-y-4">
        <TabsList>
          <TabsTrigger value="queue" className="gap-1.5">
            <ListChecks className="h-3.5 w-3.5" />
            검토 큐
          </TabsTrigger>
          <TabsTrigger value="triage" className="gap-1.5">
            <Scale className="h-3.5 w-3.5" />
            트리아지
          </TabsTrigger>
          <TabsTrigger value="calibration" className="gap-1.5">
            <Gauge className="h-3.5 w-3.5" />
            캘리브레이션
          </TabsTrigger>
        </TabsList>

        <TabsContent value="queue">
          <Card>
            <CardHeader className="flex-row items-start gap-3 space-y-0">
              <SectionIcon icon={filter === "pending" ? Inbox : STATUS_VIEW[filter].icon} />
              <div className="space-y-1.5">
                <CardTitle>
                  {filter === "pending"
                    ? "대기 중인 제안"
                    : `${DECISION_VERB[filter]}한 항목`}
                </CardTitle>
                <CardDescription>
                  {filter === "pending"
                    ? QUEUE_DESCRIPTION.pending
                    : `서버에 기록된 ${DECISION_VERB[filter]} 이력입니다. 되돌리면 대기 큐로 돌아갑니다.`}
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {receipt ? (
                <p
                  role="status"
                  aria-live="polite"
                  className="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-xs text-muted-foreground"
                >
                  <Check className="h-3.5 w-3.5 shrink-0 text-ok-text" />
                  <span className="break-words">{receipt}</span>
                </p>
              ) : null}

              {actionFailure ? (
                <ErrorSurface
                  failure={actionFailure}
                  onRetry={() => void load("refresh")}
                  retrying={refreshing}
                />
              ) : null}

              {loading ? (
                <TableSkeleton rows={5} cols={5} />
              ) : loadFailure ? (
                <p className="py-8 text-center text-sm text-muted-foreground">
                  목록을 불러오지 못했습니다. 위의 안내에 따라 다시 시도해 주세요.
                </p>
              ) : filter === "pending" ? (
                items.length === 0 ? (
                  <EmptyState
                    icon={Inbox}
                    title="검토할 제안이 없습니다"
                    description="문서를 추출하면 제안이 이 큐에 쌓입니다. 리서치 화면에서 수집과 추출을 실행할 수 있습니다."
                    action={
                      <Button asChild size="sm">
                        <Link to="/sources">
                          <FlaskConical />
                          리서치로 이동
                        </Link>
                      </Button>
                    }
                  />
                ) : (
                  <>
                    {selected.size > 0 ? (
                      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border bg-muted/40 px-3 py-2">
                        <span className="text-xs text-muted-foreground">
                          {NUM.format(selected.size)}건 선택됨
                          {selectedNodes > 0 || selectedEdges > 0
                            ? ` (개념 ${NUM.format(selectedNodes)} · 관계 ${NUM.format(selectedEdges)})`
                            : ""}
                        </span>
                        <div className="flex items-center gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setSelected(new Set())}
                          >
                            선택 해제
                          </Button>
                          <Button
                            size="sm"
                            onClick={() => setBulkConfirm(true)}
                            disabled={bulkBusy}
                          >
                            {bulkBusy ? (
                              <Loader2 className="animate-spin" />
                            ) : (
                              <Check />
                            )}
                            선택 승인
                          </Button>
                        </div>
                      </div>
                    ) : null}
                    <div className="grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
                      <div className="min-w-0 space-y-2">
                        <div className="flex items-center gap-2 border-b pb-2">
                          <input
                            type="checkbox"
                            aria-label="전체 선택"
                            className="h-4 w-4 accent-point"
                            checked={
                              items.length > 0 &&
                              items.every((row) => selected.has(row.id))
                            }
                            onChange={(event) => {
                              if (event.target.checked) {
                                setSelected(new Set(items.map((row) => row.id)));
                              } else {
                                setSelected(new Set());
                              }
                            }}
                          />
                          <span className="text-xs text-muted-foreground">
                            {NUM.format(items.length)}건
                          </span>
                        </div>
                        <ScrollArea className="h-[30rem] pr-2">
                          <ul className="space-y-1">
                            {items.map((item, idx) => (
                              <ProposalListItem
                                key={item.id}
                                item={item}
                                view={STATUS_VIEW.pending}
                                threshold={threshold}
                                active={idx === focusedIdx}
                                checked={selected.has(item.id)}
                                onCheckedChange={(checked) => {
                                  setSelected((prev) => {
                                    const next = new Set(prev);
                                    if (checked) next.add(item.id);
                                    else next.delete(item.id);
                                    return next;
                                  });
                                }}
                                onSelect={() => setFocusedIdx(idx)}
                              />
                            ))}
                          </ul>
                        </ScrollArea>
                        <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3">
                          <span className="text-xs text-muted-foreground">
                            {NUM.format(items.length)}건 표시 · 대기 전체{" "}
                            {NUM.format(pendingTotal)}건
                            {belowLine > 0 ? ` · 기준선 이하 ${NUM.format(belowLine)}건` : ""}
                          </span>
                          {hasMore ? (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => void loadMore()}
                              disabled={loadingMore}
                            >
                              {loadingMore ? (
                                <Loader2 className="animate-spin" />
                              ) : (
                                <ChevronDown />
                              )}
                              더 보기
                            </Button>
                          ) : null}
                        </div>
                      </div>
                      <div className="min-w-0">
                        <ProposalDetail
                          item={items[focusedIdx] ?? null}
                          view={STATUS_VIEW.pending}
                          threshold={threshold}
                          actions={
                            items[focusedIdx] ? (
                              <>
                                <Button
                                  size="sm"
                                  onClick={() =>
                                    void decide(items[focusedIdx], "approved")
                                  }
                                  disabled={busyId === items[focusedIdx].id}
                                >
                                  {busyId === items[focusedIdx].id ? (
                                    <Loader2 className="animate-spin" />
                                  ) : (
                                    <Check />
                                  )}
                                  승인 <kbd className="ml-1 text-[10px] opacity-60">a</kbd>
                                </Button>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => {
                                    setRejectTarget(items[focusedIdx]);
                                    setRejectNote("");
                                  }}
                                  disabled={busyId === items[focusedIdx].id}
                                >
                                  <X />
                                  거부 <kbd className="ml-1 text-[10px] opacity-60">r</kbd>
                                </Button>
                              </>
                            ) : undefined
                          }
                        />
                      </div>
                    </div>
                  </>
                )
              ) : decidedLoading ? (
                <TableSkeleton rows={3} cols={5} />
              ) : decidedFailure ? (
                <ErrorSurface
                  failure={decidedFailure}
                  onRetry={() => void loadDecided(filter)}
                  retrying={decidedLoading}
                />
              ) : decided.length === 0 ? (
                <EmptyState
                  icon={STATUS_VIEW[filter].icon}
                  title={`${DECISION_VERB[filter]}한 항목이 없습니다`}
                  description={`대기 큐에서 제안을 ${DECISION_VERB[filter]}하면 여기에 기록됩니다.`}
                  action={
                    <Button variant="outline" size="sm" onClick={() => changeFilter("pending")}>
                      <Inbox />
                      대기 큐 보기
                    </Button>
                  }
                />
              ) : (
                <div className="grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
                  <div className="min-w-0 space-y-2">
                    <ScrollArea className="h-[30rem] pr-2">
                      <ul className="space-y-1">
                        {decided.map((item) => (
                          <ProposalListItem
                            key={item.id}
                            item={item}
                            view={STATUS_VIEW[item.status === "verified" ? "approved" : "rejected"]}
                            threshold={threshold}
                            active={item.id === detailId}
                            decisionBadge={
                              staleIds.has(item.id) ? (
                                <Badge variant="warning" className="text-[10px]">
                                  원본 변경됨
                                </Badge>
                              ) : undefined
                            }
                            onSelect={() => setDetailId(item.id)}
                          />
                        ))}
                      </ul>
                    </ScrollArea>
                    <p className="border-t pt-3 text-xs text-muted-foreground">
                      {NUM.format(decided.length)}건 표시 · 누적{" "}
                      {DECISION_VERB[filter]} {NUM.format(decidedTotal[filter])}건
                    </p>
                  </div>
                  <div className="min-w-0">
                    <ProposalDetail
                      item={decidedDetail}
                      view={
                        decidedDetail
                          ? STATUS_VIEW[
                              decidedDetail.status === "verified" ? "approved" : "rejected"
                            ]
                          : STATUS_VIEW[filter]
                      }
                      threshold={threshold}
                      stale={decidedDetail ? staleIds.has(decidedDetail.id) : false}
                      decision={
                        decidedDetail ? (
                          <div className="space-y-1 text-xs">
                            {decidedDetail.verified_by ? (
                              <div className="text-muted-foreground">
                                {decidedDetail.verified_by}
                              </div>
                            ) : null}
                            {decidedDetail.verified_ts ? (
                              <RelativeTime
                                ts={decidedDetail.verified_ts}
                                className="text-muted-foreground"
                              />
                            ) : null}
                            {decidedDetail.review_note ? (
                              <div className="text-muted-foreground">
                                {decidedDetail.review_note}
                              </div>
                            ) : null}
                          </div>
                        ) : undefined
                      }
                      actions={
                        decidedDetail ? (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => void reopen(decidedDetail)}
                            disabled={busyId === decidedDetail.id}
                          >
                            {busyId === decidedDetail.id ? (
                              <Loader2 className="animate-spin" />
                            ) : (
                              <Undo2 />
                            )}
                            되돌리기
                          </Button>
                        ) : undefined
                      }
                    />
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="triage">
          <Card>
            <CardHeader className="flex-row items-start gap-3 space-y-0">
              <SectionIcon icon={Scale} />
              <div className="space-y-1.5">
                <CardTitle>트리아지 기준선</CardTitle>
                <CardDescription>
                  검토 이력으로 계산한 컨포멀 기준선입니다. 큐의 순서와 배지만 바꾸며, 자동으로
                  승인하지 않습니다.
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {loading ? (
                <MetricSkeleton tiles={4} />
              ) : !triage ? (
                statsFailure ? (
                  <ErrorSurface
                    failure={statsFailure}
                    onRetry={() => void load("refresh")}
                    retrying={refreshing}
                  />
                ) : (
                  <p className="py-6 text-center text-sm text-muted-foreground">
                    기준선 정보를 불러오지 못했습니다.
                  </p>
                )
              ) : triage.available ? (
                <>
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <MetricTile
                      label="기준선"
                      value={triage.threshold?.toFixed(2) ?? "—"}
                      hint="비평 점수 기준"
                      tone="warn"
                    />
                    <MetricTile
                      label="유의수준"
                      value={triage.alpha.toFixed(2)}
                      hint="허용 오류 확률 α"
                    />
                    <MetricTile
                      label="거부 표본"
                      value={NUM.format(triage.n_rejected)}
                      hint="기준선 계산에 쓰인 거부 이력"
                      tone="danger"
                    />
                    <MetricTile
                      label="승인 표본"
                      value={NUM.format(triage.n_verified)}
                      hint="대조용 승인 이력"
                      tone="ok"
                    />
                  </div>
                  <div className="space-y-1.5 rounded-md border bg-muted/40 p-3">
                    <FieldCaption>보장</FieldCaption>
                    <p className="break-words font-mono text-xs leading-relaxed text-muted-foreground">
                      {triage.guarantee}
                    </p>
                  </div>
                  <p className="max-w-[72ch] text-sm text-muted-foreground">
                    불러온 대기 {NUM.format(items.length)}건 가운데{" "}
                    <span className="font-mono tabular-nums text-warn-text">
                      {NUM.format(belowLine)}건
                    </span>
                    이 기준선 이하입니다. 거부될 가능성이 높은 구간이므로 먼저 확인하는 편이
                    낫습니다.
                  </p>
                </>
              ) : (
                <Alert className={TONE_CLASS.warn}>
                  <AlertDescription className="flex items-start gap-2 text-xs leading-relaxed">
                    <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />
                    <span className="break-words">
                      기준선을 계산할 수 없습니다. 유의수준 {triage.alpha.toFixed(2)}에서는 비평
                      점수가 있는 거부 이력이 최소 {NUM.format(triage.needed_rejected)}건
                      필요하지만, 현재{" "}
                      {NUM.format(triage.n_rejected)}건입니다(승인{" "}
                      {NUM.format(triage.n_verified)}건). 숫자가 채워질 때까지 기준선 없이
                      검토합니다.
                    </span>
                  </AlertDescription>
                </Alert>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="calibration">
          <Card>
            <CardHeader className="flex-row items-start gap-3 space-y-0">
              <SectionIcon icon={Gauge} />
              <div className="space-y-1.5">
                <CardTitle>신뢰도 캘리브레이션</CardTitle>
                <CardDescription>
                  추출기가 말한 신뢰도가 실제 승인률과 얼마나 맞는지 측정합니다. 측정값은 큐를
                  설명할 뿐이며, 저장된 신뢰도를 바꾸지 않습니다.
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {loading ? (
                <MetricSkeleton tiles={4} />
              ) : !calibration ? (
                statsFailure ? (
                  <ErrorSurface
                    failure={statsFailure}
                    onRetry={() => void load("refresh")}
                    retrying={refreshing}
                  />
                ) : (
                  <p className="py-6 text-center text-sm text-muted-foreground">
                    캘리브레이션 정보를 불러오지 못했습니다.
                  </p>
                )
              ) : (
                <>
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <MetricTile
                      label="ECE"
                      value={points(calibration.raw.ece)}
                      hint="주장 신뢰도와 실제 승인률의 평균 차이"
                      tone={
                        calibration.raw.ece == null
                          ? "muted"
                          : calibration.raw.ece >= 0.1
                            ? "warn"
                            : "ok"
                      }
                    />
                    <MetricTile
                      label="검토 표본"
                      value={NUM.format(calibration.n)}
                      hint={`최소 ${NUM.format(calibration.min_required)}건 필요`}
                    />
                    <MetricTile
                      label="구간"
                      value={NUM.format(calibration.raw.bins.length)}
                      hint="표본이 있는 신뢰도 구간 수"
                    />
                    <MetricTile
                      label="보정 곡선"
                      value={
                        calibration.curve
                          ? `${NUM.format(calibration.curve.values.length)}단계`
                          : "미적합"
                      }
                      hint={calibration.curve ? "단조 증가 계단 함수" : "표본이 모이면 적합됩니다"}
                      tone={calibration.curve ? "ok" : "muted"}
                    />
                  </div>

                  {!calibration.available ? (
                    <Alert className={TONE_CLASS.warn}>
                      <AlertDescription className="flex items-start gap-2 text-xs leading-relaxed">
                        <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />
                        <span className="break-words">
                          검토 이력 {NUM.format(calibration.n)}건으로는 곡선을 적합하지
                          않습니다(최소 {NUM.format(calibration.min_required)}건). 측정값은 표본이
                          있는 구간까지만 계산되며, 부족한 수치를 추정해 채우지 않습니다.
                        </span>
                      </AlertDescription>
                    </Alert>
                  ) : null}

                  {calibration.raw.bins.length === 0 ? (
                    <EmptyState
                      icon={Gauge}
                      title="측정할 검토 이력이 없습니다"
                      description="승인 또는 거부가 쌓이면 각 신뢰도 구간의 실제 승인률을 여기서 비교할 수 있습니다."
                      action={
                        <Button variant="outline" size="sm" onClick={() => changeFilter("pending")}>
                          <Inbox />
                          대기 큐 보기
                        </Button>
                      }
                    />
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow className="hover:bg-transparent">
                          <TableHead>신뢰도 구간</TableHead>
                          <TableHead className="text-right">건수</TableHead>
                          <TableHead>주장</TableHead>
                          <TableHead>실제 승인률</TableHead>
                          <TableHead className="text-right">차이</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {calibration.raw.bins.map((bin) => {
                          const gap = bin.claimed - bin.observed;
                          const wide = Math.abs(gap) >= 0.1;
                          return (
                            <TableRow key={`${bin.low}-${bin.high}`}>
                              <TableCell className="py-3 font-mono text-xs">
                                {bin.low.toFixed(1)} – {bin.high.toFixed(1)}
                              </TableCell>
                              <TableCell className="py-3 text-right font-mono text-sm tabular-nums">
                                {NUM.format(bin.count)}
                              </TableCell>
                              <TableCell className="py-3">
                                <div className="w-24 space-y-1">
                                  <span className="font-mono text-xs tabular-nums">
                                    {percent(bin.claimed)}
                                  </span>
                                  <Meter
                                    value={bin.claimed}
                                    label={`주장 신뢰도 ${percent(bin.claimed)}`}
                                  />
                                </div>
                              </TableCell>
                              <TableCell className="py-3">
                                <div className="w-24 space-y-1">
                                  <span className="font-mono text-xs tabular-nums">
                                    {percent(bin.observed)}
                                  </span>
                                  <Meter
                                    value={bin.observed}
                                    tone="ok"
                                    label={`실제 승인률 ${percent(bin.observed)}`}
                                  />
                                </div>
                              </TableCell>
                              <TableCell className="py-3 text-right">
                                <span
                                  className={cn(
                                    "font-mono text-xs tabular-nums",
                                    wide ? TONE_TEXT.warn : "text-muted-foreground"
                                  )}
                                  title={
                                    gap > 0
                                      ? "주장한 신뢰도가 실제 승인률보다 높습니다 (과신)."
                                      : "주장한 신뢰도가 실제 승인률보다 낮습니다 (과소평가)."
                                  }
                                >
                                  {gap > 0 ? "+" : ""}
                                  {points(gap)}
                                </span>
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  )}

                  {calibration.curve ? (
                    <div className="space-y-2 rounded-md border bg-muted/40 p-3">
                      <FieldCaption>보정 곡선 — 주장 신뢰도 이상일 때의 보정값</FieldCaption>
                      <div className="flex flex-wrap gap-1.5">
                        {calibration.curve.boundaries.map((boundary, index) => (
                          <span
                            key={`${boundary}-${index}`}
                            className="rounded-sm border bg-card px-2 py-0.5 font-mono text-xs tabular-nums"
                          >
                            ≥{boundary.toFixed(2)} → {calibration.curve?.values[index]?.toFixed(2)}
                          </span>
                        ))}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        적합에 쓰인 자료로 평가한 값이므로 낙관적입니다. 측정값(ECE)은 적합과
                        무관하게 계산됩니다.
                      </p>
                    </div>
                  ) : null}
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Bulk-approve confirmation */}
      <Dialog open={bulkConfirm} onOpenChange={setBulkConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>선택한 {selected.size}건을 승인할까요?</DialogTitle>
            <DialogDescription>
              개념 {selectedNodes}건 · 관계 {selectedEdges}건. 관계는 양쪽 개념이
              이미 승인됐거나 같은 선택 안에 있을 때만 승인됩니다 — 그렇지 않은
              관계는 건너뛰고 결과에 표시됩니다.
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => setBulkConfirm(false)}
              disabled={bulkBusy}
            >
              취소
            </Button>
            <Button onClick={() => void bulkApprove()} disabled={bulkBusy}>
              {bulkBusy ? <Loader2 className="animate-spin" /> : <Check />}
              승인
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Bulk-approve result receipt */}
      <Dialog
        open={bulkResult !== null}
        onOpenChange={(open) => {
          if (!open) setBulkResult(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>일괄 승인 결과</DialogTitle>
            <DialogDescription>
              승인 {bulkResult?.approved.length ?? 0}건 · 건너뜀{" "}
              {bulkResult?.skipped.length ?? 0}건 · 실패{" "}
              {bulkResult?.failed.length ?? 0}건
            </DialogDescription>
          </DialogHeader>
          {bulkResult && bulkResult.skipped.length + bulkResult.failed.length > 0 ? (
            <div className="max-h-48 space-y-1 overflow-y-auto text-xs">
              {bulkResult.skipped.map((row) => (
                <p key={row.id} className="text-muted-foreground">
                  건너뜀 {row.id} — {row.reason}
                </p>
              ))}
              {bulkResult.failed.map((row) => (
                <p key={row.id} className="text-destructive">
                  실패 {row.id} — {row.reason}
                </p>
              ))}
            </div>
          ) : null}
          <div className="flex justify-end">
            <Button variant="outline" onClick={() => setBulkResult(null)}>
              닫기
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Reject with optional reason */}
      <Dialog
        open={rejectTarget !== null}
        onOpenChange={(open) => {
          if (!open) setRejectTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{rejectTarget?.label}을(를) 거부할까요?</DialogTitle>
            <DialogDescription>
              거부 사유를 남기면 나중에 같은 제안이 올라왔을 때 참고할 수 있습니다.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={rejectNote}
            onChange={(event) => setRejectNote(event.target.value)}
            placeholder="거부 사유 (선택)"
            rows={3}
          />
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => setRejectTarget(null)}
              disabled={busyId === rejectTarget?.id}
            >
              취소
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (rejectTarget) {
                  void decide(
                    rejectTarget,
                    "rejected",
                    rejectNote.trim() || undefined
                  );
                  setRejectTarget(null);
                }
              }}
              disabled={busyId === rejectTarget?.id}
            >
              {busyId === rejectTarget?.id ? (
                <Loader2 className="animate-spin" />
              ) : (
                <X />
              )}
              거부
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}




