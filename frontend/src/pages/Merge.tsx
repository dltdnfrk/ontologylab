import { useCallback, useEffect, useState } from "react";
import {
  ArrowRight,
  Ban,
  Check,
  Copy,
  GitMerge,
  Layers,
  LoaderCircle,
  RefreshCw,
  ScanSearch,
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
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { get, post } from "@/lib/api";
import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------
   Server shapes. These mirror `KGStore.merge_candidates_pending()` and the
   `/merge/*` handlers in `ontologylab/server/routes.py`; the candidate row
   already ships both nodes hydrated, so the preview needs no second fetch.
   ------------------------------------------------------------------------- */

type EntityNode = {
  id: string;
  entity_type: string;
  name: string;
  aliases: string[];
  properties: Record<string, unknown>;
  status: string;
  confidence: number | null;
  source_doc_id: string | null;
  citation_count: number;
};

type Candidate = {
  id: string;
  score: number;
  reasons: string[];
  created_ts: number;
  node_a: EntityNode;
  node_b: EntityNode;
};

type CandidateList = { items: Candidate[]; count: number };

type ScanStats = {
  nodes: number;
  pairs_possible: number;
  pairs_checked: number;
  candidates_new: number;
  candidates_existing: number;
};

type Failure = { message: string; detail: string };

const CANDIDATE_LIMIT = 100;

/* ---------------------------------- copy --------------------------------- */

const STATUS_LABEL: Record<string, string> = {
  verified: "검증됨",
  proposed: "제안됨",
  rejected: "거부됨",
};

const REASON_LABEL: Record<string, string> = {
  "name-similarity": "이름 유사도",
  "name-containment": "이름 포함",
  "shared-alias": "별칭 공유",
  "embedding-cosine": "의미 유사도",
};

/** `${status}: ${body}` from the api client, turned into one Korean sentence
 *  plus the sanitized detail the reviewer can copy. Never renders an object. */
function toFailure(err: unknown): Failure {
  const raw = err instanceof Error ? err.message : String(err);
  const parsed = /^(\d{3}):\s?([\s\S]*)$/.exec(raw);
  const status = parsed ? Number(parsed[1]) : 0;
  let detail = parsed ? parsed[2].trim() : raw;

  try {
    const body: unknown = JSON.parse(detail);
    if (body && typeof body === "object" && "detail" in body) {
      const inner = (body as { detail: unknown }).detail;
      if (typeof inner === "string") detail = inner;
    }
  } catch {
    /* detail is already plain text */
  }

  const message =
    status === 0
      ? "서버에 연결하지 못했습니다. 네트워크 상태를 확인해 주세요."
      : status === 401
        ? "인증이 만료되었습니다. 화면을 새로고침해 주세요."
        : status === 403
          ? "이 작업을 수행할 권한이 없습니다."
          : status === 404
            ? "해당 후보를 찾을 수 없습니다. 목록을 새로고침해 주세요."
            : status === 409
              ? "다른 곳에서 이미 처리된 후보입니다. 목록을 새로고침해 주세요."
              : status === 400 || status === 422
                ? "요청 값이 올바르지 않습니다."
                : status === 503
                  ? "서버가 바빠 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."
                  : status >= 500
                    ? "서버에서 오류가 발생했습니다."
                    : "요청을 처리하지 못했습니다.";

  return { message, detail: detail || `HTTP ${status}` };
}

function splitReason(reason: string): { label: string; value: string } {
  const at = reason.indexOf(":");
  if (at === -1) return { label: REASON_LABEL[reason] ?? reason, value: "" };
  const key = reason.slice(0, at);
  return { label: REASON_LABEL[key] ?? key, value: reason.slice(at + 1) };
}

function shortId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id;
}

function relativeTime(epochSeconds: number): {
  text: string;
  iso: string;
  exact: string;
} {
  const ms = epochSeconds * 1000;
  if (!Number.isFinite(ms) || ms <= 0) return { text: "—", iso: "", exact: "" };
  const date = new Date(ms);
  if (Number.isNaN(date.getTime())) return { text: "—", iso: "", exact: "" };

  const seconds = Math.max(0, Math.round((Date.now() - ms) / 1000));
  const text =
    seconds < 60
      ? "방금"
      : seconds < 3600
        ? `${Math.floor(seconds / 60)}분 전`
        : seconds < 86400
          ? `${Math.floor(seconds / 3600)}시간 전`
          : seconds < 2592000
            ? `${Math.floor(seconds / 86400)}일 전`
            : date.toLocaleDateString("ko-KR");

  return { text, iso: date.toISOString(), exact: date.toLocaleString("ko-KR") };
}

/* -------------------------------- fragments ------------------------------- */

function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "verified"
      ? "border-transparent bg-ok-soft text-ok-text"
      : status === "rejected"
        ? "border-transparent bg-destructive-soft text-destructive"
        : "border-transparent bg-warn-soft text-warn-text";
  return (
    <Badge variant="outline" className={cn("font-medium whitespace-nowrap", tone)}>
      {STATUS_LABEL[status] ?? status}
    </Badge>
  );
}

function CopyableIdentifier({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  };

  return (
    <span className="inline-flex items-center gap-1">
      <code className="font-mono text-xs text-muted-foreground" title={value}>
        {shortId(value)}
      </code>
      <button
        type="button"
        onClick={copy}
        aria-label={`식별자 ${value} 복사`}
        className="rounded-sm p-0.5 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        {copied ? (
          <Check className="size-3 text-ok-text" />
        ) : (
          <Copy className="size-3" />
        )}
      </button>
    </span>
  );
}

/** Certainty reads as ink density: an unverified surface sits back. */
function EntityCell({ node }: { node: EntityNode }) {
  return (
    <div className="min-w-40 space-y-1">
      <div
        className={cn(
          "font-medium",
          node.status === "verified" ? "text-foreground" : "text-ink-draft",
        )}
        title={node.name}
      >
        {node.name}
      </div>
      <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        <span>{node.entity_type}</span>
        <span aria-hidden>·</span>
        <StatusBadge status={node.status} />
      </div>
    </div>
  );
}

/** Magnitude is encoded by bar length. The saturated triad stays reserved for
 *  evidence state, so the bar uses the single interaction point color. */
function ScoreMeter({ score }: { score: number }) {
  // The bar spans the domain candidates can actually occupy. `min_similarity`
  // is floored at 0.5 server-side, so a 0..1 bar would spend half its length
  // on scores that cannot exist and render 0.82 and 0.97 as the same stripe.
  // The exact value stays in the label and in aria-valuetext.
  const floor = 0.5;
  const fill = Math.round(
    ((Math.min(1, Math.max(floor, score)) - floor) / (1 - floor)) * 100,
  );
  return (
    <div className="space-y-1.5">
      <div className="font-mono tabular-nums">{score.toFixed(2)}</div>
      <div
        className="h-1 w-16 overflow-hidden rounded-full bg-border"
        role="meter"
        aria-valuenow={score}
        aria-valuemin={0}
        aria-valuemax={1}
        aria-valuetext={`유사도 ${score.toFixed(2)}`}
      >
        <div className="h-full rounded-full bg-point" style={{ width: `${fill}%` }} />
      </div>
    </div>
  );
}

function ReasonList({ reasons }: { reasons: string[] }) {
  if (reasons.length === 0) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }
  const shown = reasons.slice(0, 2);
  const rest = reasons.length - shown.length;

  return (
    <div className="flex flex-wrap items-center gap-1">
      {shown.map((reason) => {
        const { label, value } = splitReason(reason);
        return (
          <Badge
            key={reason}
            variant="outline"
            className="border-border font-normal whitespace-nowrap text-muted-foreground"
            title={reason}
          >
            {label}
            {value && <span className="ml-1 font-mono tabular-nums">{value}</span>}
          </Badge>
        );
      })}
      {rest > 0 && (
        <span
          className="text-xs text-muted-foreground"
          title={reasons.slice(2).join(", ")}
        >
          +{rest}
        </span>
      )}
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
    <Alert variant="destructive" className="border-destructive/50 bg-destructive-soft">
      <TriangleAlert className="size-4" />
      <AlertTitle>요청을 완료하지 못했습니다</AlertTitle>
      <AlertDescription className="space-y-3">
        <p className="text-foreground">{failure.message}</p>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={onRetry} disabled={retrying}>
            {retrying ? (
              <LoaderCircle className="animate-spin" />
            ) : (
              <RefreshCw />
            )}
            {retrying ? "다시 시도 중…" : "다시 시도"}
          </Button>
        </div>
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer select-none">자세한 내용</summary>
          <p className="mt-1 font-mono break-all">{failure.detail}</p>
        </details>
      </AlertDescription>
    </Alert>
  );
}

function TableSkeleton() {
  return (
    <TableBody>
      {[0, 1, 2, 3, 4].map((row) => (
        <TableRow key={row}>
          <TableCell className="py-3">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="mt-2 h-3 w-24" />
          </TableCell>
          <TableCell className="py-3">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="mt-2 h-3 w-24" />
          </TableCell>
          <TableCell className="py-3">
            <Skeleton className="h-4 w-10" />
            <Skeleton className="mt-2 h-1 w-16" />
          </TableCell>
          <TableCell className="py-3">
            <Skeleton className="h-5 w-32" />
          </TableCell>
          <TableCell className="py-3">
            <Skeleton className="ml-auto h-8 w-32" />
          </TableCell>
        </TableRow>
      ))}
    </TableBody>
  );
}

function EmptyState({ onScan, scanning }: { onScan: () => void; scanning: boolean }) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <Layers className="size-6 text-muted-foreground" aria-hidden />
      <div className="space-y-1">
        <p className="font-medium">대기 중인 병합 후보가 없습니다</p>
        <p className="mx-auto max-w-[var(--measure)] text-sm text-muted-foreground">
          중복 검사를 실행하면 이름·별칭·임베딩이 비슷한 개념 쌍을 찾아 이 목록에
          쌓습니다.
        </p>
      </div>
      <Button size="sm" onClick={onScan} disabled={scanning}>
        {scanning ? <LoaderCircle className="animate-spin" /> : <ScanSearch />}
        {scanning ? "검사 중…" : "중복 검사"}
      </Button>
    </div>
  );
}

/* ------------------------------ preview panel ----------------------------- */

function PreviewPanel({
  node,
  kept,
  decided,
  onKeep,
}: {
  node: EntityNode;
  kept: boolean;
  decided: boolean;
  onKeep: () => void;
}) {
  const aliases = node.aliases ?? [];

  return (
    <button
      type="button"
      onClick={onKeep}
      aria-pressed={kept}
      className={cn(
        "flex h-full w-full flex-col gap-3 rounded-lg border p-4 text-left transition-colors",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        kept
          ? "border-point bg-point-soft"
          : decided
            ? "border-border bg-card opacity-70 hover:opacity-100"
            : "border-border bg-card hover:border-input",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span
          className={cn(
            "text-md font-medium",
            node.status === "verified" ? "text-foreground" : "text-ink-draft",
          )}
        >
          {node.name}
        </span>
        {kept ? (
          <Badge className="border-transparent bg-point text-point-foreground">
            <Check className="mr-1 size-3" />
            남김
          </Badge>
        ) : decided ? (
          <Badge variant="outline" className="border-border text-muted-foreground">
            병합됨
          </Badge>
        ) : null}
      </div>

      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
        <dt className="text-muted-foreground">유형</dt>
        <dd>{node.entity_type}</dd>

        <dt className="text-muted-foreground">상태</dt>
        <dd>
          <StatusBadge status={node.status} />
        </dd>

        <dt className="text-muted-foreground">확신도</dt>
        <dd className="font-mono tabular-nums">
          {typeof node.confidence === "number" ? node.confidence.toFixed(2) : "—"}
        </dd>

        <dt className="text-muted-foreground">인용</dt>
        <dd className="font-mono tabular-nums">{node.citation_count}건</dd>

        <dt className="text-muted-foreground">별칭</dt>
        <dd>
          {aliases.length === 0 ? (
            <span className="text-muted-foreground">—</span>
          ) : (
            <span className="flex flex-wrap gap-1">
              {aliases.map((alias) => (
                <Badge
                  key={alias}
                  variant="outline"
                  className="border-border font-normal text-muted-foreground"
                >
                  {alias}
                </Badge>
              ))}
            </span>
          )}
        </dd>

        <dt className="text-muted-foreground">식별자</dt>
        <dd>
          <CopyableIdentifier value={node.id} />
        </dd>
      </dl>
    </button>
  );
}

/* --------------------------------- page ---------------------------------- */

export default function MergePage() {
  const [items, setItems] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<Failure | null>(null);

  const [scanning, setScanning] = useState(false);
  const [scanStats, setScanStats] = useState<ScanStats | null>(null);

  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<Failure | null>(null);

  const [preview, setPreview] = useState<Candidate | null>(null);
  const [keepId, setKeepId] = useState<string | null>(null);
  const [merging, setMerging] = useState(false);
  const [dialogError, setDialogError] = useState<Failure | null>(null);

  const load = useCallback(async (): Promise<void> => {
    setLoading(true);
    setListError(null);
    try {
      const data = await get<CandidateList>(
        `/merge/candidates?limit=${CANDIDATE_LIMIT}`,
      );
      setItems(data.items ?? []);
    } catch (err) {
      setListError(toFailure(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const runScan = async () => {
    setScanning(true);
    setActionError(null);
    try {
      const stats = await post<ScanStats & { ok: boolean }>("/merge/scan", {
        min_similarity: 0.82,
      });
      setScanStats(stats);
      await load();
    } catch (err) {
      setActionError(toFailure(err));
    } finally {
      setScanning(false);
    }
  };

  const dismiss = async (candidate: Candidate) => {
    setBusyId(candidate.id);
    setActionError(null);
    try {
      await post(`/merge/candidates/${candidate.id}/dismiss`, {});
      setItems((prev) => prev.filter((row) => row.id !== candidate.id));
    } catch (err) {
      setActionError(toFailure(err));
    } finally {
      setBusyId(null);
    }
  };

  const openPreview = (candidate: Candidate) => {
    setPreview(candidate);
    setKeepId(null);
    setDialogError(null);
  };

  const closePreview = (open: boolean) => {
    if (open || merging) return;
    setPreview(null);
    setKeepId(null);
    setDialogError(null);
  };

  const confirmMerge = async () => {
    if (!preview || !keepId) return;
    const sourceId =
      keepId === preview.node_a.id ? preview.node_b.id : preview.node_a.id;

    setMerging(true);
    setDialogError(null);
    try {
      await post(`/merge/candidates/${preview.id}/merge`, {
        target_id: keepId,
        source_id: sourceId,
      });
      setItems((prev) => prev.filter((row) => row.id !== preview.id));
      setPreview(null);
      setKeepId(null);
    } catch (err) {
      setDialogError(toFailure(err));
    } finally {
      setMerging(false);
    }
  };

  const keptNode =
    preview && keepId
      ? keepId === preview.node_a.id
        ? preview.node_a
        : preview.node_b
      : null;
  const droppedNode =
    preview && keptNode
      ? keptNode.id === preview.node_a.id
        ? preview.node_b
        : preview.node_a
      : null;

  return (
    <div className="mx-auto w-full max-w-[var(--content-max)] space-y-6 p-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">병합</h1>
          <p className="max-w-[var(--measure)] text-sm text-muted-foreground">
            같은 대상을 가리키는 중복 개념을 찾아 하나로 합칩니다. 병합은 되돌릴 수
            없으므로 남길 항목을 직접 고릅니다.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void load()}
            disabled={loading || scanning}
          >
            <RefreshCw className={cn(loading && "animate-spin")} />
            새로고침
          </Button>
          <Button size="sm" onClick={() => void runScan()} disabled={scanning}>
            {scanning ? <LoaderCircle className="animate-spin" /> : <ScanSearch />}
            {scanning ? "검사 중…" : "중복 검사"}
          </Button>
        </div>
      </header>

      {scanStats && (
        <Alert className="border-border bg-card">
          <ScanSearch className="size-4" />
          <AlertTitle>중복 검사를 마쳤습니다</AlertTitle>
          <AlertDescription className="text-muted-foreground">
            노드 <span className="font-mono tabular-nums">{scanStats.nodes}</span>개 중{" "}
            <span className="font-mono tabular-nums">{scanStats.pairs_checked}</span>
            쌍을 검사해 새 후보{" "}
            <span className="font-mono tabular-nums text-foreground">
              {scanStats.candidates_new}
            </span>
            건, 기존 후보{" "}
            <span className="font-mono tabular-nums">
              {scanStats.candidates_existing}
            </span>
            건을 확인했습니다.
          </AlertDescription>
        </Alert>
      )}

      {actionError && (
        <ErrorSurface
          failure={actionError}
          onRetry={() => void load()}
          retrying={loading}
        />
      )}

      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-3 space-y-0">
          <div className="space-y-1.5">
            <CardTitle className="text-md">병합 후보</CardTitle>
            <CardDescription>
              유사도가 높은 순서로 정렬됩니다. 최대 {CANDIDATE_LIMIT}건까지 표시합니다.
            </CardDescription>
          </div>
          {!loading && !listError && items.length > 0 && (
            <Badge
              variant="outline"
              className="shrink-0 border-border whitespace-nowrap text-muted-foreground"
            >
              <span className="font-mono tabular-nums">{items.length}</span>건 대기
            </Badge>
          )}
        </CardHeader>

        <CardContent className="px-0">
          {listError ? (
            <div className="px-6">
              <ErrorSurface
                failure={listError}
                onRetry={() => void load()}
                retrying={loading}
              />
            </div>
          ) : !loading && items.length === 0 ? (
            <EmptyState onScan={() => void runScan()} scanning={scanning} />
          ) : (
            <div className="relative">
              <Table aria-busy={loading}>
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-6">항목 A</TableHead>
                    <TableHead>항목 B</TableHead>
                    <TableHead className="w-24">유사도</TableHead>
                    <TableHead>근거</TableHead>
                    <TableHead className="pr-6 text-right">작업</TableHead>
                  </TableRow>
                </TableHeader>

                {loading ? (
                  <TableSkeleton />
                ) : (
                  <TableBody>
                    {items.map((candidate) => {
                      const busy = busyId === candidate.id;
                      const created = relativeTime(candidate.created_ts);
                      return (
                        <TableRow key={candidate.id}>
                          <TableCell className="py-3 pl-6 align-top">
                            <EntityCell node={candidate.node_a} />
                          </TableCell>
                          <TableCell className="py-3 align-top">
                            <EntityCell node={candidate.node_b} />
                          </TableCell>
                          <TableCell className="py-3 align-top">
                            <ScoreMeter score={candidate.score} />
                          </TableCell>
                          <TableCell className="py-3 align-top">
                            <div className="space-y-1.5">
                              <ReasonList reasons={candidate.reasons} />
                              {created.iso && (
                                <time
                                  dateTime={created.iso}
                                  title={created.exact}
                                  className="block text-xs text-muted-foreground"
                                >
                                  {created.text}
                                </time>
                              )}
                            </div>
                          </TableCell>
                          <TableCell className="py-3 pr-6 align-top text-right">
                            <div className="inline-flex items-center gap-2">
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => openPreview(candidate)}
                                disabled={busy}
                              >
                                <GitMerge />
                                병합
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => void dismiss(candidate)}
                                disabled={busy}
                                className="text-muted-foreground hover:text-foreground"
                              >
                                {busy ? (
                                  <LoaderCircle className="animate-spin" />
                                ) : (
                                  <Ban />
                                )}
                                무시
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                )}
              </Table>
              <div
                aria-hidden
                className="pointer-events-none absolute inset-y-0 right-0 w-8 bg-gradient-to-l from-card to-transparent lg:hidden"
              />
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={preview !== null} onOpenChange={closePreview}>
        {/* Alias lists are unbounded, so the panel scrolls instead of running
            off a short viewport. */}
        <DialogContent className="max-h-[90vh] max-w-[calc(100vw-2rem)] overflow-y-auto bg-popover sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>병합 검토</DialogTitle>
            <DialogDescription>
              남길 항목을 고르면 나머지 항목의 별칭·인용·연결이 그쪽으로 옮겨갑니다.
              이 작업은 되돌릴 수 없습니다.
            </DialogDescription>
          </DialogHeader>

          {preview && (
            <>
              <div className="flex items-center gap-3 text-sm text-muted-foreground">
                <span>유사도</span>
                <span className="font-mono tabular-nums text-foreground">
                  {preview.score.toFixed(2)}
                </span>
                <span aria-hidden>·</span>
                <ReasonList reasons={preview.reasons} />
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <PreviewPanel
                  node={preview.node_a}
                  kept={keepId === preview.node_a.id}
                  decided={keepId !== null && keepId !== preview.node_a.id}
                  onKeep={() => setKeepId(preview.node_a.id)}
                />
                <PreviewPanel
                  node={preview.node_b}
                  kept={keepId === preview.node_b.id}
                  decided={keepId !== null && keepId !== preview.node_b.id}
                  onKeep={() => setKeepId(preview.node_b.id)}
                />
              </div>

              <p className="flex flex-wrap items-center gap-2 text-sm">
                {keptNode && droppedNode ? (
                  <>
                    {/* The direction reads as an operator rather than a
                        sentence: a Korean particle glued to a variable noun
                        ("~으로"/"~로") would agree with the wrong ending. */}
                    <span className="text-ink-draft">{droppedNode.name}</span>
                    <ArrowRight className="size-4 text-muted-foreground" aria-hidden />
                    <span className="font-medium">{keptNode.name}</span>
                    <span className="text-muted-foreground">
                      이 방향으로 병합합니다.
                    </span>
                  </>
                ) : (
                  <span className="text-muted-foreground">
                    남길 항목을 먼저 선택해야 병합할 수 있습니다.
                  </span>
                )}
              </p>

              {dialogError && (
                <Alert
                  variant="destructive"
                  className="border-destructive/50 bg-destructive-soft"
                >
                  <TriangleAlert className="size-4" />
                  <AlertTitle>병합하지 못했습니다</AlertTitle>
                  <AlertDescription className="space-y-2">
                    <p className="text-foreground">{dialogError.message}</p>
                    <details className="text-xs text-muted-foreground">
                      <summary className="cursor-pointer select-none">
                        자세한 내용
                      </summary>
                      <p className="mt-1 font-mono break-all">{dialogError.detail}</p>
                    </details>
                  </AlertDescription>
                </Alert>
              )}

              <div className="flex flex-wrap items-center justify-end gap-2">
                <Button
                  variant="ghost"
                  onClick={() => void dismiss(preview).then(() => closePreview(false))}
                  disabled={merging || busyId === preview.id}
                  className="mr-auto text-muted-foreground hover:text-foreground"
                >
                  <Ban />
                  무시
                </Button>
                <Button
                  variant="outline"
                  onClick={() => closePreview(false)}
                  disabled={merging}
                >
                  취소
                </Button>
                <Button onClick={() => void confirmMerge()} disabled={!keepId || merging}>
                  {merging ? <LoaderCircle className="animate-spin" /> : <GitMerge />}
                  {merging ? "병합 중…" : "병합 실행"}
                </Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
