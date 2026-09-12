import * as React from "react";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Clock,
  Coins,
  Cpu,
  KeyRound,
  Loader2,
  Plus,
  RefreshCw,
  Server,
  ShieldCheck,
  XCircle,
  Zap,
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
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
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

/* ==========================================================================
   서버 계약 (ontologylab/server/schemas.py · routes.py)

   이름을 서버 쪽 철자 그대로 둔다. camelCase 로 바꿔 두면 응답을 한 번 더
   번역해야 하고, 그 번역이 조용히 어긋나면 화면은 undefined 를 "0" 으로
   그린다 — 없는 값과 0 은 다른 뜻이다.
   ========================================================================== */

/** GET /api/engines → EngineInfo[] (CLI 엔진 + 등록된 프로바이더 `api:<id>`) */
type EngineInfo = {
  name: string;
  available: boolean;
  default_model: string | null;
  models: string[];
};

/** GET /api/providers → { providers: ProviderModel[] }. 키 값은 절대 실리지 않고
 *  `key_present` 로 존재 여부만 온다. */
type ProviderModel = {
  id: string;
  kind: string;
  base_url: string;
  models: string[];
  label: string;
  key_present: boolean;
};

/** GET /api/cost → 잡 provenance 에 기록된 엔진 호출 집계 */
type CostSummary = {
  total_engine_calls: number;
  total_elapsed_s: number;
  per_engine: Record<string, { engine_calls: number; elapsed_s: number }>;
};

/** POST /api/providers/{id}/test → 실패도 200 + ok:false 로 온다(키는 비노출) */
type ProviderTestResult = {
  ok: boolean;
  latency_ms: number | null;
  sample: string | null;
  error: string | null;
};

/** POST /api/critic/run → { ok, ...stats } (ontologylab/critic.py) */
type CriticRunResult = {
  ok: boolean;
  candidates: number;
  scored: number;
  disagreements: number;
  batches_failed: number;
  skipped_uncited: number;
  docs_unloadable: string[];
  errors: unknown[];
};

/* 서버가 받는 유일한 두 종류(ontologylab/providers.py:PROVIDER_KINDS).
   고를 수 있는 값을 보여주기만 하고, 검증은 서버가 400 으로 한다. 라벨은
   기계값을 대체하지 않고 옆에 붙는다(DESIGN.md §5). */
const PROVIDER_KINDS = [
  { value: "anthropic", label: "Anthropic Messages" },
  { value: "openai", label: "OpenAI 호환" },
] as const;

const NUM = new Intl.NumberFormat("ko-KR");

/** 초를 사람이 읽는 길이로. 1분을 넘기면 분·초로 끊는다. */
function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0초";
  if (seconds < 60) return `${seconds.toFixed(1)}초`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${NUM.format(minutes)}분 ${rest}초`;
}

/**
 * `api.ts` 는 실패를 `"<status>: <body>"` 한 줄로 던진다. FastAPI 의 본문은
 * `{"detail": "..."}` 이라, 그대로 보여주면 사람이 읽을 문장이 JSON 괄호에
 * 싸여 나온다. 읽을 수 있으면 풀고, 아니면 원문을 그대로 둔다 — 삼키지 않는다.
 */
function errorText(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err);
  const matched = /^(\d{3}):\s*([\s\S]*)$/.exec(raw);
  if (!matched) return raw;
  const [, status, body] = matched;
  const trimmed = body.trim();
  if (!trimmed) return `${status} 오류`;
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      typeof (parsed as { detail?: unknown }).detail === "string"
    ) {
      return `${status} · ${(parsed as { detail: string }).detail}`;
    }
  } catch {
    // JSON 이 아니면 본문이 곧 메시지다.
  }
  return `${status} · ${trimmed}`;
}

/** 배열 안에 무엇이 들어 있든 한 줄로 보여준다(서버 오류 목록은 형태가 열려 있다). */
function lineOf(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

type Resource<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
};

/**
 * GET 하나를 상태로 들고 있는 최소 훅. 세 엔드포인트가 같은 모양이라 한 벌만
 * 둔다. 재조회가 실패해도 앞서 받은 데이터는 지우지 않는다 — 새로고침 한 번
 * 실패했다고 화면에서 사실이 사라지면, 오류와 빈 목록을 구분할 수 없다.
 */
function useResource<T>(path: string): Resource<T> {
  const [data, setData] = React.useState<T | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);

  const reload = React.useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    get<T>(path)
      .then((next) => {
        if (cancelled) return;
        setData(next);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(errorText(err));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  React.useEffect(() => reload(), [reload]);

  return { data, error, loading, reload };
}

/* ==========================================================================
   조각들
   ========================================================================== */

const TONE = {
  ok: "border-transparent bg-ok-soft text-ok-text",
  warn: "border-transparent bg-warn-soft text-warn-text",
  danger: "border-transparent bg-destructive-soft text-destructive",
  muted: "border-border bg-transparent text-muted-foreground",
} as const;

function StatusBadge({
  tone,
  icon: Icon,
  children,
}: {
  tone: keyof typeof TONE;
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
}) {
  return (
    <Badge variant="outline" className={cn("gap-1 font-medium", TONE[tone])}>
      <Icon className="h-3 w-3" />
      {children}
    </Badge>
  );
}

function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-label font-medium uppercase tracking-label text-muted-foreground">
      {children}
    </p>
  );
}

function StatTile({
  icon: Icon,
  label,
  value,
  hint,
  loading,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  hint?: string;
  loading?: boolean;
}) {
  return (
    <div className="rounded-md border border-border bg-background/60 p-4">
      <p className="flex items-center gap-1.5 text-label font-medium uppercase tracking-label text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </p>
      {loading ? (
        <Skeleton className="mt-2 h-6 w-24" />
      ) : (
        <p className="mt-2 font-mono text-xl tabular-nums">{value}</p>
      )}
      {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function SectionError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <Alert variant="destructive">
      <AlertCircle className="h-4 w-4" />
      <AlertTitle>불러오지 못했습니다</AlertTitle>
      <AlertDescription className="space-y-3">
        <p className="font-mono text-xs break-all">{message}</p>
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw />
          다시 시도
        </Button>
      </AlertDescription>
    </Alert>
  );
}

function SkeletonRows({ rows, cols }: { rows: number; cols: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, row) => (
        <TableRow key={row}>
          {Array.from({ length: cols }, (_, col) => (
            <TableCell key={col}>
              <Skeleton className="h-4 w-full max-w-32" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

function EmptyRow({ cols, children }: { cols: number; children: React.ReactNode }) {
  return (
    <TableRow className="hover:bg-transparent">
      <TableCell colSpan={cols} className="h-24 text-center text-muted-foreground">
        {children}
      </TableCell>
    </TableRow>
  );
}

function ModelList({ models }: { models: string[] }) {
  if (models.length === 0) {
    return <span className="text-muted-foreground">—</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {models.map((model) => (
        <Badge
          key={model}
          variant="secondary"
          className="font-mono text-xs font-normal"
        >
          {model}
        </Badge>
      ))}
    </div>
  );
}

function Field({
  htmlFor,
  label,
  hint,
  children,
}: {
  htmlFor: string;
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-xs font-medium">
        {label}
      </label>
      {children}
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

/* ==========================================================================
   프로바이더 추가
   ========================================================================== */

function AddProviderDialog({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = React.useState(false);
  const [id, setId] = React.useState("");
  const [label, setLabel] = React.useState("");
  const [kind, setKind] = React.useState<string>(PROVIDER_KINDS[0].value);
  const [baseUrl, setBaseUrl] = React.useState("");
  const [models, setModels] = React.useState("");
  const [apiKeyEnv, setApiKeyEnv] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const canSave = id.trim() !== "" && baseUrl.trim() !== "" && !saving;

  function reset() {
    setId("");
    setLabel("");
    setKind(PROVIDER_KINDS[0].value);
    setBaseUrl("");
    setModels("");
    setApiKeyEnv("");
    setError(null);
  }

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await post<{ ok: boolean }>("/providers", {
        id: id.trim(),
        kind,
        base_url: baseUrl.trim(),
        api_key_env: apiKeyEnv.trim(),
        models: models
          .split(",")
          .map((model) => model.trim())
          .filter(Boolean),
        label: label.trim(),
      });
      setOpen(false);
      reset();
      onCreated();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setError(null);
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm">
          <Plus />
          프로바이더 추가
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>프로바이더 추가</DialogTitle>
          <DialogDescription>
            등록하면 엔진 목록에 <code className="font-mono">api:&lt;식별자&gt;</code> 로
            함께 나타납니다.
          </DialogDescription>
        </DialogHeader>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
          className="space-y-4"
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              htmlFor="provider-id"
              label="식별자"
              hint="소문자·숫자·- ·_ 만 씁니다. 엔진 이름이 됩니다."
            >
              <Input
                id="provider-id"
                value={id}
                onChange={(event) => setId(event.target.value)}
                placeholder="openrouter"
                className="font-mono"
                autoComplete="off"
                spellCheck={false}
                required
              />
            </Field>

            <Field htmlFor="provider-label" label="표시 이름 (선택)">
              <Input
                id="provider-label"
                value={label}
                onChange={(event) => setLabel(event.target.value)}
                placeholder="OpenRouter"
                autoComplete="off"
              />
            </Field>
          </div>

          <Field
            htmlFor="provider-kind"
            label="종류"
            hint="응답을 읽는 방식입니다. OpenAI 호환은 /chat/completions 를 쓰는 모든 서버를 뜻합니다."
          >
            <Select value={kind} onValueChange={setKind}>
              <SelectTrigger id="provider-kind">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PROVIDER_KINDS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    <span className="font-mono">{option.value}</span>
                    <span className="ml-2 text-muted-foreground">{option.label}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field
            htmlFor="provider-base-url"
            label="기본 URL"
            hint="https 만 허용합니다. localhost·127.0.0.1 일 때만 http 를 받습니다."
          >
            <Input
              id="provider-base-url"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="https://openrouter.ai/api/v1"
              className="font-mono"
              autoComplete="off"
              spellCheck={false}
              inputMode="url"
              required
            />
          </Field>

          <Field
            htmlFor="provider-models"
            label="모델 목록 (선택)"
            hint="쉼표로 구분합니다. 적어 두면 이 목록만 허용되고, 첫 번째가 기본 모델이 됩니다."
          >
            <Input
              id="provider-models"
              value={models}
              onChange={(event) => setModels(event.target.value)}
              placeholder="anthropic/claude-sonnet-4, openai/gpt-4o-mini"
              className="font-mono"
              autoComplete="off"
              spellCheck={false}
            />
          </Field>

          <Field
            htmlFor="provider-api-key-env"
            label="API 키 환경변수 (선택)"
            hint="비워 두면 서버가 이 식별자와 origin 에 묶인 전용 이름을 정합니다."
          >
            <Input
              id="provider-api-key-env"
              value={apiKeyEnv}
              onChange={(event) => setApiKeyEnv(event.target.value)}
              placeholder="OPENROUTER_API_KEY"
              className="font-mono"
              autoComplete="off"
              spellCheck={false}
            />
          </Field>

          {/* 화면이 받지 않는 값을 받는 척하지 않는다. 서버는 키 자체를 저장하지도
              전송받지도 않고, 실행 시점에 환경변수에서 읽는다. */}
          <Alert>
            <KeyRound className="h-4 w-4" />
            <AlertTitle>키 값은 이 화면으로 보내지 않습니다</AlertTitle>
            <AlertDescription className="text-muted-foreground">
              서버는 위 환경변수에서만 키를 읽습니다. 변수를 설정한 뒤 서버를 다시
              시작하면 상태가 “키 있음”으로 바뀝니다.
            </AlertDescription>
          </Alert>

          {error ? (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>저장하지 못했습니다</AlertTitle>
              <AlertDescription className="font-mono text-xs break-all">
                {error}
              </AlertDescription>
            </Alert>
          ) : null}

          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="ghost">
                취소
              </Button>
            </DialogClose>
            <Button type="submit" disabled={!canSave}>
              {saving ? <Loader2 className="animate-spin" /> : <Plus />}
              저장
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/* ==========================================================================
   크리틱 실행
   ========================================================================== */

function CriticDialog({
  engines,
  enginesLoading,
  onFinished,
}: {
  engines: EngineInfo[];
  enginesLoading: boolean;
  onFinished: () => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [engine, setEngine] = React.useState("");
  const [running, setRunning] = React.useState(false);
  const [result, setResult] = React.useState<CriticRunResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const usable = engines.filter((item) => item.available);

  // 기본값은 "쓸 수 있는 엔진" 중에서 고른다. mock 은 합성 응답이라 품질 점검의
  // 답으로는 뜻이 없으므로 마지막 수단으로만 남긴다.
  React.useEffect(() => {
    setEngine((previous) => {
      if (previous) return previous;
      const available = engines.filter((item) => item.available);
      const preferred =
        available.find((item) => item.name !== "mock") ?? available[0];
      return preferred ? preferred.name : previous;
    });
  }, [engines]);

  async function run() {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      setResult(await post<CriticRunResult>("/critic/run", { engine }));
      onFinished();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setRunning(false);
    }
  }

  const degraded =
    result !== null &&
    (result.batches_failed > 0 ||
      result.docs_unloadable.length > 0 ||
      result.errors.length > 0);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">
          <ShieldCheck />
          크리틱 실행
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>품질 점검 실행</DialogTitle>
          <DialogDescription>
            대기 중인 제안을 근거와 대조해 점수만 기록합니다. 크리틱은 자문이라
            승인·거부 상태를 바꾸지 않습니다.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <Field
            htmlFor="critic-engine"
            label="엔진"
            hint="서버 기본 한도만큼 채점합니다. 모델은 엔진별 크리틱 기본값을 따릅니다."
          >
            <Select
              value={engine}
              onValueChange={setEngine}
              disabled={usable.length === 0}
            >
              <SelectTrigger id="critic-engine">
                <SelectValue placeholder="사용 가능한 엔진 없음" />
              </SelectTrigger>
              <SelectContent>
                {usable.map((item) => (
                  <SelectItem key={item.name} value={item.name}>
                    <span className="font-mono">{item.name}</span>
                    {item.default_model ? (
                      <span className="ml-2 text-muted-foreground">
                        {item.default_model}
                      </span>
                    ) : null}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          {/* 막힌 이유를 설명한다. "비활성"이라고만 적으면 고칠 방법이 없다. */}
          {!enginesLoading && usable.length === 0 ? (
            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>실행할 수 있는 엔진이 없습니다</AlertTitle>
              <AlertDescription className="text-muted-foreground">
                CLI 엔진을 설치하거나, 프로바이더를 등록하고 키 환경변수를 설정한 뒤
                다시 시도하십시오.
              </AlertDescription>
            </Alert>
          ) : null}

          {error ? (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>실행하지 못했습니다</AlertTitle>
              <AlertDescription className="font-mono text-xs break-all">
                {error}
              </AlertDescription>
            </Alert>
          ) : null}

          <div aria-live="polite" className="space-y-3">
            {running ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                채점하는 중입니다. 제안 수에 따라 시간이 걸립니다.
              </p>
            ) : null}

            {result ? (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {[
                    { label: "후보", value: result.candidates },
                    { label: "채점", value: result.scored },
                    { label: "이견", value: result.disagreements },
                    { label: "실패 배치", value: result.batches_failed },
                  ].map((stat) => (
                    <div
                      key={stat.label}
                      className="rounded-md border border-border bg-background/60 p-3"
                    >
                      <p className="text-label font-medium uppercase tracking-label text-muted-foreground">
                        {stat.label}
                      </p>
                      <p className="mt-1 font-mono text-lg tabular-nums">
                        {NUM.format(stat.value)}
                      </p>
                    </div>
                  ))}
                </div>

                <p className="text-xs text-muted-foreground">
                  근거가 없어 보내지 않은 항목{" "}
                  <span className="font-mono tabular-nums text-foreground">
                    {NUM.format(result.skipped_uncited)}
                  </span>
                  건. 판단할 근거가 없는 항목이라 검토 큐가 처리할 몫입니다.
                </p>

                {degraded ? (
                  <Alert>
                    <AlertCircle className="h-4 w-4" />
                    <AlertTitle>일부만 채점되었습니다</AlertTitle>
                    <AlertDescription className="space-y-1 text-muted-foreground">
                      {result.docs_unloadable.length > 0 ? (
                        <p>
                          원문을 읽지 못한 문서{" "}
                          {NUM.format(result.docs_unloadable.length)}건은 빈 근거로
                          채점되었습니다.
                        </p>
                      ) : null}
                      {result.errors.map((item, index) => (
                        <p key={index} className="font-mono text-xs break-all">
                          {lineOf(item)}
                        </p>
                      ))}
                    </AlertDescription>
                  </Alert>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="ghost">
                닫기
              </Button>
            </DialogClose>
            <Button onClick={run} disabled={running || engine === ""}>
              {running ? <Loader2 className="animate-spin" /> : <ShieldCheck />}
              실행
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/* ==========================================================================
   페이지
   ========================================================================== */

export default function EnginesPage() {
  const engines = useResource<EngineInfo[]>("/engines");
  const providers = useResource<{ providers: ProviderModel[] }>("/providers");
  const cost = useResource<CostSummary>("/cost");

  const [tests, setTests] = React.useState<
    Record<string, { loading: boolean; result?: ProviderTestResult; error?: string }>
  >({});

  const engineList = engines.data ?? [];
  const providerList = providers.data?.providers ?? [];
  const busy = engines.loading || providers.loading || cost.loading;

  const reloadAll = React.useCallback(() => {
    engines.reload();
    providers.reload();
    cost.reload();
  }, [engines, providers, cost]);

  async function runTest(providerId: string) {
    setTests((previous) => ({ ...previous, [providerId]: { loading: true } }));
    try {
      const result = await post<ProviderTestResult>(
        `/providers/${providerId}/test`,
      );
      setTests((previous) => ({
        ...previous,
        [providerId]: { loading: false, result },
      }));
    } catch (err) {
      setTests((previous) => ({
        ...previous,
        [providerId]: { loading: false, error: errorText(err) },
      }));
    }
  }

  const perEngine = Object.entries(cost.data?.per_engine ?? {}).sort(
    (a, b) => b[1].engine_calls - a[1].engine_calls,
  );
  const totalCalls = cost.data?.total_engine_calls ?? 0;
  const totalElapsed = cost.data?.total_elapsed_s ?? 0;
  const average = totalCalls > 0 ? totalElapsed / totalCalls : 0;

  return (
    <div className="pb-12">
      <header className="sticky top-0 z-10 border-b border-border bg-background">
        <div className="mx-auto flex max-w-[var(--content-max)] flex-wrap items-end justify-between gap-4 px-6 py-5">
          <div className="space-y-1">
            <p className="flex items-center gap-1.5 text-label font-medium uppercase tracking-label text-point">
              <Cpu className="h-3.5 w-3.5" />
              엔진 · 프로바이더
            </p>
            <h1 className="text-2xl">엔진</h1>
            <p className="text-sm text-muted-foreground">
              추출·크리틱이 쓰는 엔진과 API 프로바이더를 확인하고 등록합니다.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={reloadAll}
              disabled={busy}
              aria-label="전체 새로고침"
            >
              {busy ? <Loader2 className="animate-spin" /> : <RefreshCw />}
              새로고침
            </Button>
            <CriticDialog
              engines={engineList}
              enginesLoading={engines.loading}
              onFinished={cost.reload}
            />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[var(--content-max)] space-y-6 px-6 py-6">
        {/* ---------- 비용 요약 ---------- */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Coins className="h-4 w-4" />
              비용 요약
            </CardTitle>
            <CardDescription>
              잡 provenance 에 기록된 실제 엔진 호출입니다. 서버는 토큰 수와 단가를
              기록하지 않으므로, 요금 대신 호출 수와 소요 시간을 보여줍니다.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {cost.error ? (
              <SectionError message={cost.error} onRetry={cost.reload} />
            ) : null}

            <div className="grid gap-3 sm:grid-cols-3">
              <StatTile
                icon={Activity}
                label="총 엔진 호출"
                value={`${NUM.format(totalCalls)}회`}
                loading={cost.loading && cost.data === null}
              />
              <StatTile
                icon={Clock}
                label="누적 소요 시간"
                value={formatDuration(totalElapsed)}
                loading={cost.loading && cost.data === null}
              />
              <StatTile
                icon={Zap}
                label="호출당 평균"
                value={formatDuration(average)}
                loading={cost.loading && cost.data === null}
              />
            </div>

            <div className="space-y-3">
              <Eyebrow>엔진별</Eyebrow>
              {cost.loading && cost.data === null ? (
                <div className="space-y-3">
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-full" />
                </div>
              ) : perEngine.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  기록된 엔진 호출이 없습니다. 추출이나 리서치를 한 번 실행하면
                  여기에 쌓입니다.
                </p>
              ) : (
                perEngine.map(([name, usage]) => {
                  const share =
                    totalCalls > 0 ? (usage.engine_calls / totalCalls) * 100 : 0;
                  return (
                    <div key={name} className="space-y-1.5">
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <span className="font-mono text-sm">{name}</span>
                        <span className="text-xs tabular-nums text-muted-foreground">
                          {NUM.format(usage.engine_calls)}회 ·{" "}
                          {formatDuration(usage.elapsed_s)} · {share.toFixed(0)}%
                        </span>
                      </div>
                      <Progress
                        value={share}
                        className="h-1.5 bg-muted"
                        aria-label={`${name} 호출 비중`}
                      />
                    </div>
                  );
                })
              )}
            </div>
          </CardContent>
        </Card>

        {/* ---------- 엔진 ---------- */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Cpu className="h-4 w-4" />
              엔진
            </CardTitle>
            <CardDescription>
              설치된 CLI 엔진과 등록된 프로바이더(<code className="font-mono">api:*</code>)를
              합친 목록입니다. 사용 가능 여부는 CLI 설치 또는 키 설정을 뜻합니다.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {engines.error ? (
              <SectionError message={engines.error} onRetry={engines.reload} />
            ) : null}
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>이름</TableHead>
                  <TableHead>사용 가능</TableHead>
                  <TableHead>기본 모델</TableHead>
                  <TableHead>모델 목록</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {engines.loading && engines.data === null ? (
                  <SkeletonRows rows={4} cols={4} />
                ) : engineList.length === 0 ? (
                  <EmptyRow cols={4}>등록된 엔진이 없습니다.</EmptyRow>
                ) : (
                  engineList.map((engine) => (
                    <TableRow key={engine.name}>
                      <TableCell className="font-mono">{engine.name}</TableCell>
                      <TableCell>
                        {engine.available ? (
                          <StatusBadge tone="ok" icon={CheckCircle2}>
                            사용 가능
                          </StatusBadge>
                        ) : (
                          <StatusBadge tone="muted" icon={XCircle}>
                            사용 불가
                          </StatusBadge>
                        )}
                      </TableCell>
                      <TableCell className="font-mono">
                        {engine.default_model ?? (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <ModelList models={engine.models} />
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        {/* ---------- 프로바이더 ---------- */}
        <Card>
          <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
            <div className="space-y-1.5">
              <CardTitle className="flex items-center gap-2 text-lg">
                <Server className="h-4 w-4" />
                프로바이더
              </CardTitle>
              <CardDescription>
                HTTP API 로 부르는 엔진입니다. 키는 서버 환경변수에서만 읽고 이
                화면에는 존재 여부만 옵니다.
              </CardDescription>
            </div>
            <AddProviderDialog
              onCreated={() => {
                providers.reload();
                engines.reload();
              }}
            />
          </CardHeader>
          <CardContent className="space-y-4">
            {providers.error ? (
              <SectionError message={providers.error} onRetry={providers.reload} />
            ) : null}
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>이름</TableHead>
                  <TableHead>종류</TableHead>
                  <TableHead>상태</TableHead>
                  <TableHead className="text-right">연결 확인</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {providers.loading && providers.data === null ? (
                  <SkeletonRows rows={3} cols={4} />
                ) : providerList.length === 0 ? (
                  <EmptyRow cols={4}>
                    등록된 프로바이더가 없습니다. 오른쪽 위에서 추가하십시오.
                  </EmptyRow>
                ) : (
                  providerList.map((provider) => {
                    const state = tests[provider.id];
                    return (
                      <TableRow key={provider.id} className="align-top">
                        <TableCell>
                          <div className="space-y-0.5">
                            <div className="font-mono">{provider.id}</div>
                            {provider.label ? (
                              <div className="text-xs text-muted-foreground">
                                {provider.label}
                              </div>
                            ) : null}
                            <div className="font-mono text-xs text-ink-draft break-all">
                              {provider.base_url}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className="font-mono font-normal"
                          >
                            {provider.kind}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {provider.key_present ? (
                            <StatusBadge tone="ok" icon={CheckCircle2}>
                              키 있음
                            </StatusBadge>
                          ) : (
                            <StatusBadge tone="warn" icon={KeyRound}>
                              키 없음
                            </StatusBadge>
                          )}
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-col items-end gap-1.5">
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => runTest(provider.id)}
                              disabled={state?.loading}
                            >
                              {state?.loading ? (
                                <Loader2 className="animate-spin" />
                              ) : (
                                <Zap />
                              )}
                              연결 확인
                            </Button>
                            {state?.error ? (
                              <span className="max-w-64 text-right text-xs text-destructive break-all">
                                {state.error}
                              </span>
                            ) : null}
                            {state?.result ? (
                              state.result.ok ? (
                                <span className="max-w-64 text-right text-xs text-ok-text">
                                  응답{" "}
                                  <span className="font-mono tabular-nums">
                                    {NUM.format(state.result.latency_ms ?? 0)}ms
                                  </span>
                                  {state.result.sample
                                    ? ` · “${state.result.sample}”`
                                    : ""}
                                </span>
                              ) : (
                                <span className="max-w-64 text-right text-xs text-destructive">
                                  {state.result.error ?? "연결하지 못했습니다."}
                                </span>
                              )
                            ) : null}
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
