import { useCallback, useEffect, useMemo, useState, type ComponentType } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Cpu,
  Database,
  FlaskConical,
  ListChecks,
  Loader2,
  PlugZap,
  RefreshCw,
  Search,
  Sparkles,
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
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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

// ---------------------------------------------------------------------------
// Wire shapes — mirrored from ontologylab/server/routes.py and schemas.py.
// ---------------------------------------------------------------------------

type SourceRow = {
  id: string;
  role: string;
  label: string | null;
  key_present: boolean;
};

type EngineInfo = {
  name: string;
  available: boolean;
  default_model: string | null;
  models: string[];
};

type PaperSource = {
  id: string;
  label: string;
  keyed: boolean;
  connectable: boolean;
  key_present: boolean;
  available: boolean;
};

type Job = {
  job_id: string;
  kind: string;
  status: string;
  phase: string;
  engine: string;
  model: string | null;
  started_ts: number;
  finished_ts: number | null;
  error?: string | null;
};

type TestResponse = { ok: boolean; verification_status: number };

type CollectResponse = {
  ok: boolean;
  error_kind?: string;
  detail?: string;
  documents?: number;
  created?: number;
  duplicates?: number;
  failures?: { source_uri: string; error_class: string; kind: string }[];
};

type StartResponse = {
  ok?: boolean;
  job_id?: string;
  status?: string;
  error_kind?: string;
  detail?: string;
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
  busy: "border-highlight/40 bg-highlight-soft text-highlight",
};

type IconType = ComponentType<{ className?: string }>;

type StatusView = { label: string; tone: Tone; icon: IconType; spin?: boolean };

const JOB_STATUS: Record<string, StatusView> = {
  running: { label: "실행 중", tone: "busy", icon: Loader2, spin: true },
  complete: { label: "완료", tone: "ok", icon: CheckCircle2 },
  partial: { label: "부분 완료", tone: "warn", icon: CheckCircle2 },
  failed: { label: "실패", tone: "danger", icon: XCircle },
  cancelled: { label: "취소됨", tone: "muted", icon: XCircle },
};

const JOB_KIND_LABEL: Record<string, string> = {
  research: "리서치",
  extract: "추출",
};

/** Typed outcomes the gates return with HTTP 200 instead of a 4xx. */
const ERROR_KIND_LABEL: Record<string, string> = {
  rejected: "요청 거부됨",
  unsupported: "지원하지 않는 요청",
  offline: "오프라인 정책 차단",
  busy: "이미 실행 중",
  failed: "실행 실패",
  unconfigured: "설정되지 않음",
};

/** The credential probe reports an HTTP class, never the upstream response. */
const VERIFICATION_VIEW: Record<number, StatusView> = {
  200: { label: "정상", tone: "ok", icon: CheckCircle2 },
  401: { label: "인증 실패", tone: "danger", icon: XCircle },
  429: { label: "요청 한도 초과", tone: "warn", icon: AlertCircle },
  503: { label: "응답 없음", tone: "danger", icon: XCircle },
};

const JOB_LIMIT = 10;

const TIME_FMT = new Intl.DateTimeFormat("ko-KR", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function formatTs(ts: number): string {
  if (!Number.isFinite(ts) || ts <= 0) return "—";
  return TIME_FMT.format(new Date(ts * 1000));
}

function formatElapsed(job: Job): string {
  if (!job.finished_ts) return "—";
  const total = Math.max(0, Math.round(job.finished_ts - job.started_ts));
  if (total < 60) return `${total}초`;
  return `${Math.floor(total / 60)}분 ${total % 60}초`;
}

/** Render a gate refusal as "종류 — 상세", falling back to whatever arrived. */
function refusalText(kind: string | undefined, detail: string | undefined): string {
  const label = (kind && ERROR_KIND_LABEL[kind]) || kind || "실패";
  return detail ? `${label} — ${detail}` : label;
}

// ---------------------------------------------------------------------------
// Presentational primitives
// ---------------------------------------------------------------------------

function StatusBadge({ view }: { view: StatusView }) {
  const Icon = view.icon;
  return (
    <Badge variant="outline" className={cn("gap-1.5 font-medium", TONE_CLASS[view.tone])}>
      <Icon className={cn("h-3.5 w-3.5 shrink-0", view.spin && "animate-spin")} />
      {view.label}
    </Badge>
  );
}

type Result = { tone: Tone; text: string };

function ResultNote({ result }: { result: Result | null }) {
  if (!result) return null;
  const Icon =
    result.tone === "ok" ? CheckCircle2 : result.tone === "warn" ? AlertCircle : XCircle;
  return (
    // The icon lives inside the description so Alert's absolute `[&>svg]`
    // placement does not fight the tone color inherited from the container.
    <Alert className={cn("mt-4", TONE_CLASS[result.tone])} aria-live="polite">
      <AlertDescription className="flex items-start gap-2 text-xs leading-relaxed">
        <Icon className="mt-px h-3.5 w-3.5 shrink-0" />
        <span className="break-words">{result.text}</span>
      </AlertDescription>
    </Alert>
  );
}

function FieldLabel({ htmlFor, children }: { htmlFor: string; children: React.ReactNode }) {
  return (
    <label
      htmlFor={htmlFor}
      className="text-label font-medium uppercase tracking-[var(--ls-label)] text-muted-foreground"
    >
      {children}
    </label>
  );
}

function SectionIcon({ icon: Icon }: { icon: IconType }) {
  return (
    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
      <Icon className="h-4 w-4" />
    </span>
  );
}

function TableSkeleton({ rows, cols }: { rows: number; cols: number }) {
  return (
    <div className="space-y-2 p-2">
      {Array.from({ length: rows }, (_, row) => (
        <div key={row} className="flex items-center gap-4">
          {Array.from({ length: cols }, (_, col) => (
            <Skeleton key={col} className={cn("h-4", col === 0 ? "w-40" : "flex-1")} />
          ))}
        </div>
      ))}
    </div>
  );
}

function EmptyRow({ span, children }: { span: number; children: React.ReactNode }) {
  return (
    <TableRow className="hover:bg-transparent">
      <TableCell colSpan={span} className="py-8 text-center text-sm text-muted-foreground">
        {children}
      </TableCell>
    </TableRow>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SourcesPage() {
  const [sources, setSources] = useState<SourceRow[]>([]);
  const [engines, setEngines] = useState<EngineInfo[]>([]);
  const [paperSources, setPaperSources] = useState<PaperSource[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [collectSource, setCollectSource] = useState("");
  const [topic, setTopic] = useState("");
  const [researchEngine, setResearchEngine] = useState("");
  const [docId, setDocId] = useState("");
  const [extractEngine, setExtractEngine] = useState("");

  const [collecting, setCollecting] = useState(false);
  const [researching, setResearching] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [testing, setTesting] = useState<Record<string, boolean>>({});

  const [collectResult, setCollectResult] = useState<Result | null>(null);
  const [researchResult, setResearchResult] = useState<Result | null>(null);
  const [extractResult, setExtractResult] = useState<Result | null>(null);
  const [testResults, setTestResults] = useState<Record<string, StatusView>>({});

  const loadJobs = useCallback(async () => {
    const res = await get<{ jobs: Job[] }>(`/jobs?limit=${JOB_LIMIT}`);
    setJobs(res.jobs ?? []);
  }, []);

  const load = useCallback(
    async (mode: "initial" | "refresh") => {
      if (mode === "initial") setLoading(true);
      else setRefreshing(true);
      try {
        const [sourceRes, engineRes, paperRes, jobRes] = await Promise.all([
          get<{ sources: SourceRow[] }>("/sources"),
          get<EngineInfo[]>("/engines"),
          get<{ sources: PaperSource[]; default: string }>("/paper-sources"),
          get<{ jobs: Job[] }>(`/jobs?limit=${JOB_LIMIT}`),
        ]);

        setSources(sourceRes.sources ?? []);
        setEngines(engineRes ?? []);
        setPaperSources(paperRes.sources ?? []);
        setJobs(jobRes.jobs ?? []);
        setLoadError(null);

        // Seed the pickers once, from what the server says it can actually
        // run — never overwrite a choice the operator already made.
        const firstUsableSource =
          paperRes.sources?.find((item) => item.id === paperRes.default && item.available) ??
          paperRes.sources?.find((item) => item.available);
        if (firstUsableSource) {
          setCollectSource((prev) => prev || firstUsableSource.id);
        }
        const firstUsableEngine =
          engineRes?.find((item) => item.available) ?? engineRes?.[0];
        if (firstUsableEngine) {
          setResearchEngine((prev) => prev || firstUsableEngine.name);
          setExtractEngine((prev) => prev || firstUsableEngine.name);
        }
      } catch (err) {
        setLoadError(errorText(err));
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    []
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  // Long-running jobs (a research run can take over an hour) must not need a
  // manual refresh to show progress. Poll while anything is running; stop
  // once the queue settles so an idle page never spins.
  const hasRunningJobs = jobs.some((job) => job.status === "running");
  useEffect(() => {
    if (!hasRunningJobs) return;
    const timer = window.setInterval(() => {
      void loadJobs().catch(() => undefined);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [hasRunningJobs, loadJobs]);

  const [cancelling, setCancelling] = useState<Record<string, boolean>>({});
  const cancelJob = async (jobId: string) => {
    if (cancelling[jobId]) return;
    setCancelling((prev) => ({ ...prev, [jobId]: true }));
    try {
      await post(`/jobs/${encodeURIComponent(jobId)}/cancel`, {});
      await loadJobs();
    } catch {
      // The next poll reconciles the row either way.
    } finally {
      setCancelling((prev) => ({ ...prev, [jobId]: false }));
    }
  };

  const modelFor = useCallback(
    (engineName: string) =>
      engines.find((engine) => engine.name === engineName)?.default_model ?? null,
    [engines]
  );

  const recentJobs = useMemo(
    () => [...jobs].sort((a, b) => b.started_ts - a.started_ts).slice(0, JOB_LIMIT),
    [jobs]
  );

  async function runCollect() {
    const trimmed = query.trim();
    if (!trimmed || !collectSource) return;
    setCollecting(true);
    setCollectResult(null);
    try {
      const res = await post<CollectResponse>("/collect", {
        paper_queries: [trimmed],
        paper_source: collectSource,
      });
      if (!res.ok && res.documents === undefined) {
        setCollectResult({ tone: "danger", text: refusalText(res.error_kind, res.detail) });
        return;
      }
      const failed = res.failures?.length ?? 0;
      const summary =
        `문서 ${res.documents ?? 0}건 확인 · 신규 ${res.created ?? 0}건 · ` +
        `중복 ${res.duplicates ?? 0}건` +
        (failed ? ` · 실패 ${failed}건` : "");
      setCollectResult({ tone: failed ? "warn" : "ok", text: summary });
    } catch (err) {
      setCollectResult({ tone: "danger", text: errorText(err) });
    } finally {
      setCollecting(false);
    }
  }

  async function runResearch() {
    const trimmed = topic.trim();
    if (!trimmed || !researchEngine) return;
    setResearching(true);
    setResearchResult(null);
    try {
      const res = await post<StartResponse>("/research", {
        topic: trimmed,
        engine: researchEngine,
        model: modelFor(researchEngine),
      });
      if (res.ok === false) {
        setResearchResult({ tone: "danger", text: refusalText(res.error_kind, res.detail) });
        return;
      }
      setResearchResult({
        tone: "ok",
        text: `리서치 작업을 시작했습니다. (${res.job_id ?? "작업 ID 없음"})`,
      });
      await loadJobs();
    } catch (err) {
      setResearchResult({ tone: "danger", text: errorText(err) });
    } finally {
      setResearching(false);
    }
  }

  async function runExtract() {
    const trimmed = docId.trim();
    if (!trimmed || !extractEngine) return;
    setExtracting(true);
    setExtractResult(null);
    try {
      const res = await post<StartResponse>("/extract", {
        doc_ids: [trimmed],
        engine: extractEngine,
        model: modelFor(extractEngine),
      });
      setExtractResult({
        tone: "ok",
        text: `추출 작업을 시작했습니다. (${res.job_id ?? "작업 ID 없음"})`,
      });
      await loadJobs();
    } catch (err) {
      setExtractResult({ tone: "danger", text: errorText(err) });
    } finally {
      setExtracting(false);
    }
  }

  async function testSource(id: string) {
    setTesting((prev) => ({ ...prev, [id]: true }));
    try {
      const res = await post<TestResponse>(`/sources/${encodeURIComponent(id)}/test`);
      const view = VERIFICATION_VIEW[res.verification_status] ?? {
        label: `확인 불가 (${res.verification_status})`,
        tone: "danger" as Tone,
        icon: XCircle,
      };
      setTestResults((prev) => ({ ...prev, [id]: view }));
    } catch {
      // The probe never forwards upstream detail, so neither does this.
      setTestResults((prev) => ({
        ...prev,
        [id]: { label: "확인 실패", tone: "danger", icon: XCircle },
      }));
    } finally {
      setTesting((prev) => ({ ...prev, [id]: false }));
    }
  }

  const busy = collecting || researching || extracting;

  return (
    <div className="mx-auto w-full max-w-[var(--content-max)] space-y-6 p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">리서치</h1>
          <p className="text-sm text-muted-foreground">
            논문 소스를 확인하고, 수집·리서치·추출 작업을 실행합니다.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void load("refresh")}
          disabled={loading || refreshing}
        >
          <RefreshCw className={cn(refreshing && "animate-spin")} />
          새로고침
        </Button>
      </header>

      {loadError && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>불러오지 못했습니다</AlertTitle>
          <AlertDescription className="break-words">{loadError}</AlertDescription>
        </Alert>
      )}

      {/* Research is the one action that collects and extracts in a single
          run, so it leads the page rather than sitting in the column grid. */}
      <Card>
        <CardHeader className="flex-row items-start gap-3 space-y-0">
          <SectionIcon icon={Sparkles} />
          <div className="space-y-1.5">
            <CardTitle>리서치</CardTitle>
            <CardDescription>
              주제 하나로 여러 소스를 수집한 뒤 추출까지 한 작업으로 실행합니다.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-[1fr_minmax(0,200px)_auto] sm:items-end">
            <div className="space-y-1.5">
              <FieldLabel htmlFor="research-topic">주제</FieldLabel>
              <Input
                id="research-topic"
                value={topic}
                onChange={(event) => setTopic(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void runResearch();
                }}
                placeholder="예: 단백질 접힘 예측"
                disabled={busy}
              />
            </div>
            <div className="space-y-1.5">
              <FieldLabel htmlFor="research-engine">엔진</FieldLabel>
              <Select
                value={researchEngine}
                onValueChange={setResearchEngine}
                disabled={busy || engines.length === 0}
              >
                <SelectTrigger id="research-engine">
                  <SelectValue placeholder="엔진 선택" />
                </SelectTrigger>
                <SelectContent>
                  {engines.map((engine) => (
                    <SelectItem key={engine.name} value={engine.name} disabled={!engine.available}>
                      {engine.name}
                      {!engine.available && " (사용 불가)"}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button onClick={() => void runResearch()} disabled={busy || !topic.trim() || !researchEngine}>
              {researching ? <Loader2 className="animate-spin" /> : <Sparkles />}
              리서치 시작
            </Button>
          </div>
          <ResultNote result={researchResult} />
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-start gap-3 space-y-0">
            <SectionIcon icon={Search} />
            <div className="space-y-1.5">
              <CardTitle>수집</CardTitle>
              <CardDescription>검색어 하나를 지정한 논문 소스에서 수집합니다.</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <FieldLabel htmlFor="collect-query">검색어</FieldLabel>
              <Input
                id="collect-query"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void runCollect();
                }}
                placeholder="예: knowledge graph construction"
                disabled={busy}
              />
            </div>
            <div className="space-y-1.5">
              <FieldLabel htmlFor="collect-source">소스</FieldLabel>
              <Select
                value={collectSource}
                onValueChange={setCollectSource}
                disabled={busy || paperSources.length === 0}
              >
                <SelectTrigger id="collect-source">
                  <SelectValue placeholder="소스 선택" />
                </SelectTrigger>
                <SelectContent>
                  {paperSources.map((source) => (
                    <SelectItem key={source.id} value={source.id} disabled={!source.available}>
                      {source.label}
                      {!source.available && " (키 필요)"}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                onClick={() => void runCollect()}
                disabled={busy || !query.trim() || !collectSource}
              >
                {collecting ? <Loader2 className="animate-spin" /> : <Search />}
                수집 시작
              </Button>
            </div>
            <ResultNote result={collectResult} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-start gap-3 space-y-0">
            <SectionIcon icon={FlaskConical} />
            <div className="space-y-1.5">
              <CardTitle>추출</CardTitle>
              <CardDescription>수집된 문서 하나에서 지식 그래프를 추출합니다.</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <FieldLabel htmlFor="extract-doc">문서 ID</FieldLabel>
              <Input
                id="extract-doc"
                value={docId}
                onChange={(event) => setDocId(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void runExtract();
                }}
                placeholder="예: doc-01H..."
                className="font-mono text-xs"
                disabled={busy}
              />
            </div>
            <div className="space-y-1.5">
              <FieldLabel htmlFor="extract-engine">엔진</FieldLabel>
              <Select
                value={extractEngine}
                onValueChange={setExtractEngine}
                disabled={busy || engines.length === 0}
              >
                <SelectTrigger id="extract-engine">
                  <SelectValue placeholder="엔진 선택" />
                </SelectTrigger>
                <SelectContent>
                  {engines.map((engine) => (
                    <SelectItem key={engine.name} value={engine.name} disabled={!engine.available}>
                      {engine.name}
                      {!engine.available && " (사용 불가)"}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                onClick={() => void runExtract()}
                disabled={busy || !docId.trim() || !extractEngine}
              >
                {extracting ? <Loader2 className="animate-spin" /> : <FlaskConical />}
                추출 시작
              </Button>
            </div>
            <ResultNote result={extractResult} />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-start gap-3 space-y-0">
          <SectionIcon icon={Database} />
          <div className="space-y-1.5">
            <CardTitle>연결된 소스</CardTitle>
            <CardDescription>
              등록된 소스의 자격 증명을 확인합니다. 키 값은 저장되거나 표시되지 않습니다.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <TableSkeleton rows={3} cols={4} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>이름</TableHead>
                  <TableHead>유형</TableHead>
                  <TableHead>상태</TableHead>
                  <TableHead>검증</TableHead>
                  <TableHead className="text-right">동작</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sources.length === 0 ? (
                  <EmptyRow span={5}>
                    연결된 소스가 없습니다. 설정에서 논문 소스를 연결하세요.
                  </EmptyRow>
                ) : (
                  sources.map((source) => {
                    const result = testResults[source.id];
                    return (
                      <TableRow key={source.id}>
                        <TableCell className="py-3">
                          <div className="font-medium">{source.label || source.id}</div>
                          <div className="font-mono text-xs text-muted-foreground">{source.id}</div>
                        </TableCell>
                        <TableCell className="font-mono text-xs text-muted-foreground">
                          {source.role}
                        </TableCell>
                        <TableCell>
                          <StatusBadge
                            view={
                              source.key_present
                                ? { label: "연결됨", tone: "ok", icon: PlugZap }
                                : { label: "미연결", tone: "muted", icon: XCircle }
                            }
                          />
                        </TableCell>
                        <TableCell>
                          {result ? (
                            <StatusBadge view={result} />
                          ) : (
                            <span className="text-xs text-muted-foreground">미확인</span>
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => void testSource(source.id)}
                            disabled={Boolean(testing[source.id])}
                          >
                            {testing[source.id] ? (
                              <Loader2 className="animate-spin" />
                            ) : (
                              <PlugZap />
                            )}
                            테스트
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-start gap-3 space-y-0">
          <SectionIcon icon={ListChecks} />
          <div className="space-y-1.5">
            <CardTitle>최근 작업</CardTitle>
            <CardDescription>
              최근 리서치·추출 작업 {JOB_LIMIT}건입니다. 실행 중인 작업은 자동으로 갱신됩니다.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <TableSkeleton rows={4} cols={5} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>작업</TableHead>
                  <TableHead>종류</TableHead>
                  <TableHead>상태</TableHead>
                  <TableHead>엔진</TableHead>
                  <TableHead>시작</TableHead>
                  <TableHead className="text-right">소요</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recentJobs.length === 0 ? (
                  <EmptyRow span={6}>아직 실행한 작업이 없습니다.</EmptyRow>
                ) : (
                  recentJobs.map((job) => {
                    const view = JOB_STATUS[job.status] ?? {
                      label: job.status,
                      tone: "muted" as Tone,
                      icon: AlertCircle,
                    };
                    return (
                      <TableRow key={job.job_id}>
                        <TableCell className="py-3 font-mono text-xs">{job.job_id}</TableCell>
                        <TableCell>
                          <Badge variant="outline" className="font-medium">
                            {JOB_KIND_LABEL[job.kind] ?? job.kind}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-wrap items-center gap-2">
                            <StatusBadge view={view} />
                            {job.status === "running" && job.phase && (
                              <span className="text-xs text-muted-foreground">{job.phase}</span>
                            )}
                            {job.status === "running" && (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 px-2 text-xs"
                                disabled={!!cancelling[job.job_id]}
                                onClick={() => void cancelJob(job.job_id)}
                              >
                                {cancelling[job.job_id] ? "취소 중…" : "취소"}
                              </Button>
                            )}
                          </div>
                          {(job.status === "failed" || job.status === "partial") && job.error && (
                            <div className="mt-1 max-w-md text-xs text-destructive">
                              {job.error}
                            </div>
                          )}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1.5 text-xs">
                            <Cpu className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                            <span className="font-mono">{job.engine}</span>
                          </div>
                          {job.model && (
                            <div className="pl-5 font-mono text-xs text-muted-foreground">
                              {job.model}
                            </div>
                          )}
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                          {formatTs(job.started_ts)}
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-right text-xs text-muted-foreground">
                          {formatElapsed(job)}
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
