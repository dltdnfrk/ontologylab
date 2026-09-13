import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Ban,
  Check,
  CircleAlert,
  CircleCheck,
  CircleX,
  FileText,
  Inbox,
  Layers,
  LoaderCircle,
  Network,
  Package,
  RefreshCw,
  Share2,
  X,
} from "lucide-react";
import { get, post } from "@/lib/api";
import { cn } from "@/lib/utils";
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
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

// --- server payloads -------------------------------------------------------

/** Review-queue tallies from `KGStore.counts()`. Every key is optional: a
 *  store built before a given status existed simply omits it. */
interface ReviewCounts {
  nodes_proposed?: number;
  nodes_verified?: number;
  edges_proposed?: number;
  edges_verified?: number;
  documents?: number;
}

/** One row of the `pending_review` view, as enriched by `pending_review()`. */
interface Proposal {
  kind: "node" | "edge";
  id: string;
  type_name: string;
  label: string;
  /** Epoch seconds — the column is REAL, not an ISO string. */
  created_ts: number;
  confidence: number | null;
  source_doc_id: string | null;
  src_label?: string | null;
  dst_label?: string | null;
  doc_title?: string | null;
}

interface Job {
  job_id: string;
  kind: string;
  status: string;
  phase: string | null;
  /** Epoch seconds, from `time.time()`. */
  started_ts: number | null;
  finished_ts: number | null;
  error: string | null;
}

interface ActiveSchema {
  schema_version_id: number;
  schema_label: string;
  entity_types: { name: string }[];
  relation_types: { name: string }[];
}

interface Dashboard {
  documents: number;
  entities: number;
  relations: number;
  pending: number;
  packs: number;
  verifiedEntities: number;
  verifiedRelations: number;
  proposals: Proposal[];
  jobs: Job[];
  schema: ActiveSchema | null;
}

// --- shared vocabulary -----------------------------------------------------

/** DESIGN.md terminology map: machine values resolve through one dictionary
 *  so the same run never reads two different ways on two screens. */
const JOB_KIND_LABEL: Record<string, string> = {
  research: "리서치",
  extract: "추출",
  unsupported: "미지원",
};

/** Status is always glyph plus text, never colour alone (DESIGN.md §5). */
const JOB_STATUS: Record<
  string,
  { label: string; icon: typeof CircleCheck; className: string; spin?: boolean }
> = {
  running: {
    label: "실행 중",
    icon: LoaderCircle,
    className: "border-warn/40 bg-warn-soft text-warn-text",
    spin: true,
  },
  complete: {
    label: "완료",
    icon: CircleCheck,
    className: "border-ok/40 bg-ok-soft text-ok-text",
  },
  failed: {
    label: "실패",
    icon: CircleX,
    className: "border-destructive/40 bg-destructive-soft text-destructive",
  },
  cancelled: {
    label: "취소됨",
    icon: Ban,
    className: "border-border bg-muted text-muted-foreground",
  },
};

const PROPOSAL_KIND_LABEL: Record<Proposal["kind"], string> = {
  node: "개념",
  edge: "관계",
};

const ACTION_LABEL = { approve: "승인", reject: "거부" } as const;

type Action = keyof typeof ACTION_LABEL;

// --- formatting ------------------------------------------------------------

const NUMBER = new Intl.NumberFormat("ko-KR");
const RELATIVE = new Intl.RelativeTimeFormat("ko", { numeric: "auto" });
const RELATIVE_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 31_536_000],
  ["month", 2_592_000],
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
];

/** Never render `[object Object]`: coerce anything thrown into one string. */
function errorText(cause: unknown): string {
  if (cause instanceof Error) return cause.message;
  if (typeof cause === "string") return cause;
  try {
    return JSON.stringify(cause);
  } catch {
    return String(cause);
  }
}

/** Korean relative time in a semantic `time` element (DESIGN.md §5).
 *  The exact value stays in `title`, machine-readable ISO in `datetime`, and
 *  an absent or unparseable timestamp renders as an em dash. */
function RelativeTime({ seconds }: { seconds: number | null | undefined }) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds)) {
    return <span className="text-muted-foreground">—</span>;
  }
  const date = new Date(seconds * 1000);
  if (Number.isNaN(date.getTime())) {
    return <span className="text-muted-foreground">—</span>;
  }
  const delta = (date.getTime() - Date.now()) / 1000;
  let text = RELATIVE.format(Math.round(delta), "second");
  for (const [unit, size] of RELATIVE_UNITS) {
    if (Math.abs(delta) >= size) {
      text = RELATIVE.format(Math.round(delta / size), unit);
      break;
    }
  }
  return (
    <time dateTime={date.toISOString()} title={date.toLocaleString("ko-KR")}>
      {text}
    </time>
  );
}

// --- building blocks -------------------------------------------------------

function StatCard({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof FileText;
  label: string;
  value: number;
  hint: string;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3 space-y-0 p-4 pb-2">
        <CardTitle className="text-xs font-medium text-muted-foreground">
          {label}
        </CardTitle>
        <Icon className="size-4 shrink-0 text-muted-foreground" />
      </CardHeader>
      <CardContent className="p-4 pt-0">
        <div className="font-mono text-2xl font-semibold tabular-nums">
          {NUMBER.format(value)}
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
      </CardContent>
    </Card>
  );
}

/** CTA empty state: semantic icon, formal title, one sentence, real action. */
function EmptyState({
  icon: Icon,
  title,
  description,
  to,
  action,
}: {
  icon: typeof Inbox;
  title: string;
  description: string;
  to: string;
  action: string;
}) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <Icon className="size-6 text-muted-foreground" />
      <div className="space-y-1">
        <p className="font-medium">{title}</p>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      <Button asChild variant="outline" size="sm">
        <Link to={to}>
          {action}
          <ArrowRight />
        </Link>
      </Button>
    </div>
  );
}

function JobStatusBadge({ status }: { status: string }) {
  const state = JOB_STATUS[status];
  if (!state) {
    return (
      <Badge variant="outline" className="font-mono">
        {status}
      </Badge>
    );
  }
  const Icon = state.icon;
  return (
    <Badge variant="outline" className={cn("gap-1.5", state.className)}>
      <Icon className={cn("size-3", state.spin && "animate-spin")} />
      {state.label}
    </Badge>
  );
}

function SummaryRow({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-sm text-muted-foreground">{term}</dt>
      <dd className="font-mono text-sm tabular-nums">{value}</dd>
    </div>
  );
}

function HomeSkeleton() {
  return (
    <div
      className="space-y-6"
      aria-busy="true"
      aria-label="대시보드를 불러오는 중"
    >
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Card key={i}>
            <CardHeader className="p-4 pb-2">
              <Skeleton className="h-3 w-20" />
            </CardHeader>
            <CardContent className="p-4 pt-0">
              <Skeleton className="h-6 w-16" />
              <Skeleton className="mt-2 h-3 w-24" />
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-3 w-56" />
          </CardHeader>
          <CardContent className="space-y-3">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-3 w-40" />
          </CardHeader>
          <CardContent className="space-y-3">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// --- page ------------------------------------------------------------------

export default function HomePage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<Record<string, Action>>({});
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // One `/proposals` read answers three questions at once: it returns the
      // queue preview and the store-wide `counts` block in the same payload.
      // `/graph` deliberately is not that source — it returns the capped
      // subgraph itself and carries no totals, so counting its nodes would
      // report the page size rather than the store.
      const [documents, queue, packs, jobs, schema] = await Promise.all([
        get<{ documents: unknown[]; count: number }>("/documents"),
        get<{ items: Proposal[]; counts: ReviewCounts }>("/proposals?limit=5"),
        get<{ packs: unknown[]; count: number }>("/packs"),
        get<{ jobs: Job[] }>("/jobs"),
        get<{ active: ActiveSchema | null }>("/schema"),
      ]);
      const counts = queue.counts ?? {};
      const verifiedEntities = counts.nodes_verified ?? 0;
      const verifiedRelations = counts.edges_verified ?? 0;
      const proposedEntities = counts.nodes_proposed ?? 0;
      const proposedRelations = counts.edges_proposed ?? 0;
      setData({
        documents: documents.count ?? documents.documents?.length ?? 0,
        entities: verifiedEntities + proposedEntities,
        relations: verifiedRelations + proposedRelations,
        pending: proposedEntities + proposedRelations,
        packs: packs.count ?? packs.packs?.length ?? 0,
        verifiedEntities,
        verifiedRelations,
        proposals: queue.items ?? [],
        // `/jobs` returns the whole registry with no limit parameter, so the
        // five most recent are selected here rather than assumed upstream.
        jobs: [...(jobs.jobs ?? [])]
          .sort((a, b) => (b.started_ts ?? 0) - (a.started_ts ?? 0))
          .slice(0, 5),
        schema: schema.active ?? null,
      });
      setError(null);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const decide = useCallback(
    async (proposal: Proposal, action: Action) => {
      setPending((current) => ({ ...current, [proposal.id]: action }));
      setActionError(null);
      try {
        await post(`/proposals/${action}`, { id: proposal.id });
        await load();
      } catch (cause) {
        setActionError(
          `제안을 ${ACTION_LABEL[action]}하지 못했습니다. ${errorText(cause)}`,
        );
      } finally {
        setPending((current) => {
          const next = { ...current };
          delete next[proposal.id];
          return next;
        });
      }
    },
    [load],
  );

  return (
    <div className="mx-auto max-w-[var(--content-max)] space-y-6 p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold">홈</h1>
          <p className="text-sm text-muted-foreground">
            지식 그래프의 현재 상태와 처리해야 할 작업을 요약합니다.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void load()}
          disabled={loading}
        >
          <RefreshCw className={cn(loading && "animate-spin")} />
          {loading ? "불러오는 중…" : "새로 고침"}
        </Button>
      </header>

      {error ? (
        <Alert variant="destructive">
          <CircleAlert className="size-4" />
          <AlertTitle>대시보드를 불러오지 못했습니다.</AlertTitle>
          <AlertDescription className="space-y-3">
            <p>
              서버에 연결하지 못했거나 요청이 거부되었습니다. 잠시 후 다시
              시도합니다.
            </p>
            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                size="sm"
                onClick={() => void load()}
                disabled={loading}
              >
                {loading ? "다시 시도 중…" : "다시 시도"}
              </Button>
            </div>
            <details className="text-xs">
              <summary className="cursor-pointer text-muted-foreground">
                자세한 내용
              </summary>
              <p className="mt-2 font-mono break-all">{error}</p>
            </details>
          </AlertDescription>
        </Alert>
      ) : null}

      {loading && !data ? <HomeSkeleton /> : null}

      {data ? (
        <div className="space-y-6">
          <section
            aria-label="저장소 요약 수치"
            className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"
          >
            <StatCard
              icon={FileText}
              label="문서"
              value={data.documents}
              hint="수집된 원본 문서"
            />
            <StatCard
              icon={Network}
              label="개념"
              value={data.entities}
              hint={`확정 ${NUMBER.format(data.verifiedEntities)}개 포함`}
            />
            <StatCard
              icon={Inbox}
              label="검토 대기"
              value={data.pending}
              hint="승인 또는 거부가 필요한 제안"
            />
            <StatCard
              icon={Package}
              label="팩"
              value={data.packs}
              hint="배포 가능한 지식 팩"
            />
          </section>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="min-w-0 lg:col-span-2">
              <CardHeader className="flex-row flex-wrap items-start justify-between gap-4 space-y-0">
                <div className="space-y-1">
                  <CardTitle className="text-md">검토 대기열</CardTitle>
                  <CardDescription>
                    승인 또는 거부를 기다리는 제안입니다.
                  </CardDescription>
                </div>
                <Button asChild variant="ghost" size="sm">
                  <Link to="/review">
                    전체 검토
                    <ArrowRight />
                  </Link>
                </Button>
              </CardHeader>
              <CardContent className="p-0">
                {actionError ? (
                  <div className="px-6 pb-4">
                    <Alert variant="destructive">
                      <CircleAlert className="size-4" />
                      <AlertDescription>{actionError}</AlertDescription>
                    </Alert>
                  </div>
                ) : null}
                {data.proposals.length === 0 ? (
                  <EmptyState
                    icon={Inbox}
                    title="검토할 제안이 없습니다."
                    description="문서를 수집하고 추출하면 이곳에 제안이 쌓입니다."
                    to="/sources"
                    action="리서치 시작"
                  />
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead className="pl-6">종류</TableHead>
                        <TableHead>대상</TableHead>
                        <TableHead className="text-right">확신도</TableHead>
                        <TableHead>등록</TableHead>
                        <TableHead className="pr-6 text-right">결정</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.proposals.map((proposal) => {
                        const busy = pending[proposal.id];
                        return (
                          <TableRow key={proposal.id}>
                            <TableCell className="pl-6 align-top">
                              <Badge variant="secondary">
                                {PROPOSAL_KIND_LABEL[proposal.kind] ??
                                  proposal.kind}
                              </Badge>
                            </TableCell>
                            <TableCell className="max-w-xs align-top">
                              <div className="truncate font-medium">
                                {proposal.kind === "edge" &&
                                proposal.src_label ? (
                                  <span className="flex items-center gap-1.5">
                                    <span className="truncate">
                                      {proposal.src_label}
                                    </span>
                                    <ArrowRight className="size-3 shrink-0 text-muted-foreground" />
                                    <span className="truncate">
                                      {proposal.dst_label}
                                    </span>
                                  </span>
                                ) : (
                                  proposal.label
                                )}
                              </div>
                              <div className="truncate font-mono text-xs text-muted-foreground">
                                {proposal.type_name}
                              </div>
                            </TableCell>
                            <TableCell className="text-right align-top font-mono text-sm tabular-nums">
                              {typeof proposal.confidence === "number"
                                ? proposal.confidence.toFixed(2)
                                : "—"}
                            </TableCell>
                            <TableCell className="align-top text-sm whitespace-nowrap text-muted-foreground">
                              <RelativeTime seconds={proposal.created_ts} />
                            </TableCell>
                            <TableCell className="pr-6 align-top">
                              <div className="flex justify-end gap-2">
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="border-ok/40 text-ok-text hover:bg-ok-soft hover:text-ok-text"
                                  disabled={Boolean(busy)}
                                  aria-label={`${proposal.label} 승인`}
                                  onClick={() =>
                                    void decide(proposal, "approve")
                                  }
                                >
                                  {busy === "approve" ? (
                                    <LoaderCircle className="animate-spin" />
                                  ) : (
                                    <Check />
                                  )}
                                  승인
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="border-destructive/40 text-destructive hover:bg-destructive-soft hover:text-destructive"
                                  disabled={Boolean(busy)}
                                  aria-label={`${proposal.label} 거부`}
                                  onClick={() => void decide(proposal, "reject")}
                                >
                                  {busy === "reject" ? (
                                    <LoaderCircle className="animate-spin" />
                                  ) : (
                                    <X />
                                  )}
                                  거부
                                </Button>
                              </div>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-md">저장소 요약</CardTitle>
                <CardDescription>
                  활성 온톨로지와 확정된 그래프 규모입니다.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {data.schema ? (
                  <>
                    <div>
                      <p className="text-xs text-muted-foreground">
                        활성 온톨로지
                      </p>
                      <p className="mt-1 flex items-center gap-2 font-medium">
                        <Layers className="size-4 shrink-0 text-muted-foreground" />
                        <span className="truncate">
                          {data.schema.schema_label}
                        </span>
                      </p>
                      <p className="mt-1 font-mono text-xs text-muted-foreground">
                        버전 {data.schema.schema_version_id}
                      </p>
                    </div>
                    <dl className="space-y-2 border-t pt-4">
                      <SummaryRow
                        term="개념 유형"
                        value={NUMBER.format(data.schema.entity_types.length)}
                      />
                      <SummaryRow
                        term="관계 유형"
                        value={NUMBER.format(data.schema.relation_types.length)}
                      />
                    </dl>
                    <dl className="space-y-2 border-t pt-4">
                      <SummaryRow
                        term="확정 개념"
                        value={NUMBER.format(data.verifiedEntities)}
                      />
                      <SummaryRow
                        term="확정 관계"
                        value={NUMBER.format(data.verifiedRelations)}
                      />
                      <SummaryRow
                        term="전체 관계"
                        value={NUMBER.format(data.relations)}
                      />
                    </dl>
                  </>
                ) : (
                  <EmptyState
                    icon={Share2}
                    title="활성 온톨로지가 없습니다."
                    description="추출을 시작하려면 먼저 온톨로지를 설치합니다."
                    to="/settings"
                    action="온톨로지 설정"
                  />
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
              <div className="space-y-1">
                <CardTitle className="text-md">최근 작업</CardTitle>
                <CardDescription>
                  가장 최근에 실행된 수집 및 추출 작업입니다.
                </CardDescription>
              </div>
              <Button asChild variant="ghost" size="sm">
                <Link to="/sources">
                  작업 보기
                  <ArrowRight />
                </Link>
              </Button>
            </CardHeader>
            <CardContent className="p-0">
              {data.jobs.length === 0 ? (
                <EmptyState
                  icon={Layers}
                  title="실행된 작업이 없습니다."
                  description="리서치를 시작하면 실행 기록이 이곳에 남습니다."
                  to="/sources"
                  action="리서치 시작"
                />
              ) : (
                <ul className="divide-y">
                  {data.jobs.map((job) => (
                    <li
                      key={job.job_id}
                      className="flex flex-wrap items-center justify-between gap-3 px-6 py-3"
                    >
                      <div className="min-w-0 space-y-1">
                        <p className="flex items-center gap-2 font-medium">
                          <span>{JOB_KIND_LABEL[job.kind] ?? job.kind}</span>
                          <span className="truncate font-mono text-xs text-muted-foreground">
                            {job.job_id}
                          </span>
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {job.error
                            ? job.error
                            : (job.phase ?? "단계 정보가 없습니다.")}
                        </p>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="text-xs whitespace-nowrap text-muted-foreground">
                          <RelativeTime
                            seconds={job.finished_ts ?? job.started_ts}
                          />
                        </span>
                        <JobStatusBadge status={job.status} />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
      ) : null}
    </div>
  );
}
