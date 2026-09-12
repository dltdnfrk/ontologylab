import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
} from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Boxes,
  Check,
  Copy,
  FileText,
  Hash,
  LoaderCircle,
  Network,
  Package,
  PackagePlus,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
  Users,
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
import { get, post } from "@/lib/api";
import { cn } from "@/lib/utils";

/* ==========================================================================
   팩 — 승인분만 담는 불변 스냅샷.

   이 화면이 다루는 상태는 셋뿐이다: 검증됨 / 빌드 중 / 실패. 서버는
   /api/packs 에서 읽을 수 있는 매니페스트(packs)와 읽을 수 없는 폴더
   (unusable)를 나눠 내려주므로, 후자를 조용히 버리지 않고 실패 행으로
   같은 표에 세운다 — 방금 만든 팩이 목록에 없는 이유를 사람이 알아야 한다.
   ========================================================================== */

type PackCounts = {
  documents?: number;
  nodes_verified?: number;
  edges_verified?: number;
  entity_types?: number;
  relation_types?: number;
  communities?: number;
};

type PackManifest = {
  pack_id: string;
  created_ts?: number;
  schema_version_id?: number;
  schema_label?: string;
  source_job_id?: string | null;
  counts?: PackCounts;
  search_tier?: string;
  embedding_model?: string | null;
  ontologylab_version?: string;
  content_hash?: string;
  status?: string;
  extraction_completeness?: {
    status?: string;
    override?: { used?: boolean; operator_intent?: string };
  };
};

type UnusablePack = { pack_dir: string; reason: string };

type PacksResponse = {
  packs?: PackManifest[];
  count?: number;
  unusable?: UnusablePack[];
};

type BuildResponse = {
  ok?: boolean;
  manifest?: PackManifest;
  detail?: string;
  error_code?: string;
};

type VerifyResponse = {
  ok?: boolean;
  verified?: boolean;
  status?: string;
  detail?: string;
  checked_at?: number;
  content_hash?: string;
  checks?: { name?: string; ok?: boolean; detail?: string }[];
};

type PackEntity = {
  id?: string;
  node_id?: string;
  name?: string;
  label?: string;
  type?: string;
  entity_type?: string;
  status?: string;
};

type PackRelation = {
  id?: string;
  edge_id?: string;
  source?: string;
  target?: string;
  subject?: string;
  object?: string;
  from?: string;
  to?: string;
  type?: string;
  predicate?: string;
  relation_type?: string;
  status?: string;
};

type PackDetail = PackManifest & {
  entities?: PackEntity[];
  relations?: PackRelation[];
  verification?: VerifyResponse;
};

type PackStatus = "verified" | "building" | "failed";

type Verdict = {
  kind: "pass" | "fail" | "error";
  message: string;
  detail?: string;
};

type PackRow = {
  key: string;
  packId: string;
  createdTs?: number;
  entityCount: number | null;
  status: PackStatus;
  note?: string;
  reason?: string;
  manifest?: PackManifest;
};

type TypedError = { message: string; detail: string };

const STATUS_META: Record<
  PackStatus,
  { label: string; variant: "success" | "warning" | "error" }
> = {
  verified: { label: "검증됨", variant: "success" },
  building: { label: "빌드 중", variant: "warning" },
  failed: { label: "실패", variant: "error" },
};

/* 팩 안에서 쓰는 검색 방식은 기계 값이라 그대로 두면 읽히지 않는다. */
const SEARCH_TIER_KO: Record<string, string> = {
  fts5: "전문 검색 (FTS5)",
  vector: "벡터 검색",
  hybrid: "하이브리드 검색",
  like: "부분 일치",
};

const PAGE_SIZE = 30;
const numberKo = new Intl.NumberFormat("ko-KR");

/* ---------- 오류 문장 ----------
   api.ts 는 실패를 `"<status>: <body>"` 한 줄로 던진다. 사용자에게는
   상태 코드가 아니라 다음 행동이 보여야 하므로 여기서 한국어 한 문장으로
   바꾸고, 원문은 접힌 세부 정보에만 남긴다. */
function errorText(
  err: unknown,
  fallback: string,
  copy: { notFound?: string } = {},
): TypedError {
  if (!(err instanceof Error)) {
    return { message: fallback, detail: String(err ?? "") };
  }
  const raw = err.message;
  const matched = /^(\d{3}):\s*([\s\S]*)$/.exec(raw);
  if (!matched) {
    const offline =
      raw.includes("Failed to fetch") ||
      raw.includes("NetworkError") ||
      raw.includes("Load failed");
    return {
      message: offline
        ? "서버에 연결하지 못했습니다. 로컬 서버가 실행 중인지 확인합니다."
        : fallback,
      detail: raw,
    };
  }
  const status = Number(matched[1]);
  const detail = serverDetail(matched[2].trim());
  if (status === 401) {
    return {
      message: "세션이 만료되었습니다. 화면을 새로고침한 뒤 다시 시도합니다.",
      detail,
    };
  }
  if (status === 403) {
    return { message: "이 작업을 수행할 권한이 없습니다.", detail };
  }
  if (status === 404) {
    /* 404 의 뜻은 부르는 쪽이 안다 — 없는 것이 팩인지, 그 API 자체인지. */
    return {
      message: copy.notFound ?? "요청한 팩을 찾을 수 없습니다. 목록을 새로고침합니다.",
      detail,
    };
  }
  if (status === 422) {
    return { message: "요청 값을 확인해야 합니다.", detail };
  }
  if (status === 429 || status === 503) {
    return {
      message: "서버가 다른 작업을 처리하는 중입니다. 잠시 후 다시 시도합니다.",
      detail,
    };
  }
  if (status >= 500) {
    return { message: "서버에서 오류가 발생했습니다.", detail };
  }
  return { message: fallback, detail };
}

/* FastAPI 는 `{"detail": ...}` 로 실패를 싣는다. 사람이 읽을 부분만 꺼낸다. */
function serverDetail(body: string): string {
  if (!body) return "";
  try {
    const parsed: unknown = JSON.parse(body);
    if (parsed && typeof parsed === "object") {
      const record = parsed as Record<string, unknown>;
      const detail = record.detail;
      if (typeof detail === "string") return detail;
      if (detail !== undefined) return JSON.stringify(detail);
    }
  } catch {
    /* JSON 이 아니면 원문 그대로가 가장 정확한 세부 정보다. */
  }
  return body;
}

/* ---------- 시간 ----------
   목록과 표는 상대 시간을 보여주고, 정확한 값은 title/datetime 에 남긴다. */
const RELATIVE = new Intl.RelativeTimeFormat("ko", { numeric: "auto" });
const EXACT = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "medium",
  timeStyle: "short",
});
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

function toDate(ts?: number | null): Date | null {
  if (typeof ts !== "number" || !Number.isFinite(ts)) return null;
  /* 서버는 epoch 초(소수 포함)로 내려준다. */
  const date = new Date(ts * 1000);
  return Number.isNaN(date.getTime()) ? null : date;
}

function relativeKo(date: Date): string {
  const seconds = (date.getTime() - Date.now()) / 1000;
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) {
      return RELATIVE.format(Math.round(seconds / size), unit);
    }
  }
  return "방금 전";
}

function RelativeTime({ ts }: { ts?: number | null }) {
  const date = toDate(ts);
  if (!date) return <span className="text-muted-foreground">—</span>;
  return (
    <time dateTime={date.toISOString()} title={EXACT.format(date)}>
      {relativeKo(date)}
    </time>
  );
}

/* ---------- 복사 가능한 식별자 ----------
   해시와 팩 ID 는 열 너비를 결정해서는 안 된다. 짧게 보여주고 전체 값은
   복사 버튼이 정확히 넘긴다. */
function CopyValue({
  value,
  display,
  label,
  className,
}: {
  value: string;
  display?: string;
  label: string;
  className?: string;
}) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const copy = async () => {
    let ok = false;
    try {
      await navigator.clipboard.writeText(value);
      ok = true;
    } catch {
      ok = false;
    }
    setState(ok ? "copied" : "failed");
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setState("idle"), 1600);
  };

  return (
    <span className={cn("inline-flex items-center gap-1", className)}>
      <code
        className="truncate font-mono text-xs text-foreground"
        title={value}
      >
        {display ?? value}
      </code>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-6 w-6 shrink-0 text-muted-foreground hover:text-foreground"
        onClick={copy}
        aria-label={`${label} 복사`}
      >
        {state === "copied" ? (
          <Check className="text-ok-text" aria-hidden="true" />
        ) : (
          <Copy aria-hidden="true" />
        )}
      </Button>
      <span role="status" className="sr-only">
        {state === "copied"
          ? `${label}을(를) 복사했습니다.`
          : state === "failed"
            ? `${label}을(를) 복사하지 못했습니다.`
            : ""}
      </span>
      {state === "failed" ? (
        <span className="text-xs text-destructive">복사 실패</span>
      ) : null}
    </span>
  );
}

/* ---------- 오류 표면 ----------
   한 문장 + 다시 시도 + 접힌 원문. 세 층의 순서를 지킨다. */
function ErrorSurface({
  title,
  error,
  onRetry,
  retrying,
}: {
  title: string;
  error: TypedError;
  onRetry: () => void;
  retrying: boolean;
}) {
  return (
    <Alert variant="destructive">
      <TriangleAlert className="h-4 w-4" aria-hidden="true" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription className="mt-2 space-y-3">
        <p>{error.message}</p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onRetry}
          disabled={retrying}
          aria-busy={retrying}
        >
          {retrying ? (
            <LoaderCircle className="animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCw aria-hidden="true" />
          )}
          {retrying ? "다시 시도 중…" : "다시 시도"}
        </Button>
        {error.detail ? (
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer">기술 세부 정보</summary>
            <div className="mt-2 flex items-start gap-2">
              <code className="block max-w-(--measure) break-all font-mono">
                {error.detail}
              </code>
              <CopyValue
                value={error.detail}
                display=""
                label="오류 세부 정보"
                className="shrink-0"
              />
            </div>
          </details>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}

function StatusBadge({ status }: { status: PackStatus }) {
  const meta = STATUS_META[status];
  return (
    <Badge variant={meta.variant} className="gap-1">
      {status === "building" ? (
        <LoaderCircle className="h-3 w-3 animate-spin" aria-hidden="true" />
      ) : status === "verified" ? (
        <ShieldCheck className="h-3 w-3" aria-hidden="true" />
      ) : (
        <TriangleAlert className="h-3 w-3" aria-hidden="true" />
      )}
      {meta.label}
    </Badge>
  );
}

function CountTile({
  icon: Icon,
  label,
  value,
}: {
  icon: ComponentType<{ className?: string }>;
  label: string;
  value: number | null;
}) {
  return (
    <div className="rounded-md border bg-background/40 p-3">
      <p className="flex items-center gap-1.5 text-label tracking-label text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </p>
      <p className="mt-1 text-lg font-medium tabular-nums">
        {value === null ? "—" : numberKo.format(value)}
      </p>
    </div>
  );
}

function shortHash(hash?: string): string {
  if (!hash) return "—";
  const bare = hash.startsWith("sha256:") ? hash.slice(7) : hash;
  return bare.slice(0, 12);
}

function entityName(entity: PackEntity): string {
  return entity.name ?? entity.label ?? entity.id ?? entity.node_id ?? "—";
}

function entityType(entity: PackEntity): string | undefined {
  return entity.type ?? entity.entity_type;
}

function relationParts(relation: PackRelation): [string, string, string] {
  return [
    relation.source ?? relation.subject ?? relation.from ?? "—",
    relation.type ?? relation.predicate ?? relation.relation_type ?? "—",
    relation.target ?? relation.object ?? relation.to ?? "—",
  ];
}

function readVerdict(res: VerifyResponse): Verdict {
  const pass =
    res.ok === true ||
    res.verified === true ||
    res.status === "verified" ||
    res.status === "ok" ||
    res.status === "pass";
  const failedChecks = (res.checks ?? []).filter((check) => check.ok === false);
  if (pass) {
    return {
      kind: "pass",
      message: res.detail ?? "무결성 검증을 통과했습니다.",
      detail: res.content_hash,
    };
  }
  return {
    kind: "fail",
    message: res.detail ?? "무결성 검증에 실패했습니다.",
    detail: failedChecks
      .map((check) => `${check.name ?? "검사"}: ${check.detail ?? "실패"}`)
      .join("\n"),
  };
}

export default function PacksPage() {
  const [data, setData] = useState<PacksResponse | null>(null);
  const [listError, setListError] = useState<TypedError | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [name, setName] = useState("");
  const [building, setBuilding] = useState(false);
  const [buildResult, setBuildResult] = useState<
    | { kind: "ok"; packId: string; counts: PackCounts }
    | { kind: "failed"; message: string; detail: string }
    | null
  >(null);
  const nameRef = useRef<HTMLInputElement>(null);

  const [verifying, setVerifying] = useState<Record<string, boolean>>({});
  const [verdicts, setVerdicts] = useState<Record<string, Verdict>>({});

  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<PackDetail | null>(null);
  const [detailError, setDetailError] = useState<TypedError | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailNonce, setDetailNonce] = useState(0);
  const [entityLimit, setEntityLimit] = useState(PAGE_SIZE);
  const [relationLimit, setRelationLimit] = useState(PAGE_SIZE);

  const load = useCallback(async (mode: "initial" | "refresh") => {
    if (mode === "initial") setLoading(true);
    else setRefreshing(true);
    try {
      const res = await get<PacksResponse>("/packs");
      setData(res);
      setListError(null);
    } catch (err) {
      setListError(
        errorText(err, "팩 목록을 불러오지 못했습니다.", {
          notFound: "팩 목록 API를 찾을 수 없습니다. 서버가 최신 버전인지 확인합니다.",
        }),
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load("initial");
  }, [load]);

  /* 상세는 열릴 때만 가져온다. 닫으면 다음 팩의 내용이 섞이지 않도록 비운다. */
  useEffect(() => {
    if (!openId) return;
    let ignore = false;
    setDetailLoading(true);
    setDetailError(null);
    setEntityLimit(PAGE_SIZE);
    setRelationLimit(PAGE_SIZE);
    (async () => {
      try {
        const res = await get<PackDetail>(`/packs/${encodeURIComponent(openId)}`);
        if (ignore) return;
        setDetail(res);
      } catch (err) {
        if (ignore) return;
        setDetail(null);
        setDetailError(
          errorText(err, "팩 세부 정보를 불러오지 못했습니다.", {
            notFound:
              "이 서버는 팩 세부 정보를 제공하지 않습니다. 목록에서 받은 매니페스트 요약만 표시합니다.",
          }),
        );
      } finally {
        if (!ignore) setDetailLoading(false);
      }
    })();
    return () => {
      ignore = true;
    };
  }, [openId, detailNonce]);

  const buildPack = async () => {
    const trimmed = name.trim();
    if (!trimmed || building) return;
    setBuilding(true);
    setBuildResult(null);
    try {
      const res = await post<BuildResponse>("/packs/build", {
        name: trimmed,
        allow_incomplete_extraction: false,
      });
      if (res.ok) {
        setBuildResult({
          kind: "ok",
          packId: res.manifest?.pack_id ?? trimmed,
          counts: res.manifest?.counts ?? {},
        });
        setName("");
        await load("refresh");
      } else {
        setBuildResult({
          kind: "failed",
          message:
            res.error_code === "incomplete_extraction"
              ? "추출이 끝나지 않은 문서가 있어 팩을 만들지 않았습니다."
              : "팩을 만들지 못했습니다.",
          detail: res.detail ?? res.error_code ?? "",
        });
      }
    } catch (err) {
      const typed = errorText(err, "팩을 만들지 못했습니다.", {
        notFound: "팩 빌드 API를 찾을 수 없습니다. 서버가 최신 버전인지 확인합니다.",
      });
      setBuildResult({
        kind: "failed",
        message: typed.message,
        detail: typed.detail,
      });
    } finally {
      setBuilding(false);
    }
  };

  const verifyPack = useCallback(async (packId: string) => {
    setVerifying((prev) => ({ ...prev, [packId]: true }));
    try {
      const res = await post<VerifyResponse>(
        `/packs/${encodeURIComponent(packId)}/verify`,
      );
      setVerdicts((prev) => ({ ...prev, [packId]: readVerdict(res) }));
    } catch (err) {
      const typed = errorText(err, "무결성 검증을 실행하지 못했습니다.", {
        notFound: "이 서버는 무결성 재검증을 지원하지 않습니다.",
      });
      setVerdicts((prev) => ({
        ...prev,
        [packId]: {
          kind: "error",
          message: typed.message,
          detail: typed.detail,
        },
      }));
    } finally {
      setVerifying((prev) => ({ ...prev, [packId]: false }));
    }
  }, []);

  const packs = useMemo(() => data?.packs ?? [], [data]);
  const unusable = useMemo(() => data?.unusable ?? [], [data]);

  const rows = useMemo<PackRow[]>(() => {
    const built: PackRow[] = packs.map((pack) => {
      const verdict = verdicts[pack.pack_id];
      const status: PackStatus =
        verdict?.kind === "fail"
          ? "failed"
          : pack.status === "building"
            ? "building"
            : pack.status === "failed"
              ? "failed"
              : "verified";
      return {
        key: pack.pack_id,
        packId: pack.pack_id,
        createdTs: pack.created_ts,
        entityCount: pack.counts?.nodes_verified ?? null,
        status,
        note: pack.schema_label,
        manifest: pack,
      };
    });
    const broken: PackRow[] = unusable.map((item) => ({
      key: `unusable:${item.pack_dir}`,
      packId: item.pack_dir,
      entityCount: null,
      status: "failed",
      reason: item.reason,
    }));
    const pending: PackRow[] = building
      ? [
          {
            key: "building:current",
            packId: name.trim() || "새 팩",
            entityCount: null,
            status: "building",
            note: "빌드가 끝나면 목록에 표시됩니다.",
          },
        ]
      : [];
    return [...pending, ...built, ...broken];
  }, [packs, unusable, verdicts, building, name]);

  /* 합계를 말할 수 있는 조건: 목록을 실제로 읽었을 때뿐이다. */
  const known = !loading && listError === null;

  const totals = useMemo(() => {
    let concepts = 0;
    let relations = 0;
    let documents = 0;
    for (const pack of packs) {
      concepts += pack.counts?.nodes_verified ?? 0;
      relations += pack.counts?.edges_verified ?? 0;
      documents += pack.counts?.documents ?? 0;
    }
    return { concepts, relations, documents };
  }, [packs]);

  const openManifest = useMemo(
    () => packs.find((pack) => pack.pack_id === openId),
    [packs, openId],
  );
  const shown = detail ?? openManifest ?? null;
  const openVerdict = openId ? verdicts[openId] : undefined;
  const openStatus: PackStatus =
    openVerdict?.kind === "fail"
      ? "failed"
      : detail?.verification
        ? readVerdict(detail.verification).kind === "pass"
          ? "verified"
          : "failed"
        : "verified";

  const entities = detail?.entities ?? [];
  const relations = detail?.relations ?? [];

  return (
    <div className="mx-auto w-full max-w-(--content-max) p-6">
      {/* ---------- 화면 머리 ---------- */}
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-medium">
            <Package className="h-5 w-5 text-primary" aria-hidden="true" />팩
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            승인분만 담는 불변 스냅샷입니다 · MCP는 팩만 읽습니다
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void load("refresh")}
          disabled={refreshing || loading}
          aria-busy={refreshing}
        >
          <RefreshCw className={cn(refreshing && "animate-spin")} aria-hidden="true" />
          새로고침
        </Button>
      </header>

      {/* ---------- 집계 띠 ---------- */}
      {/* 목록을 못 읽었을 때 0 은 거짓말이다 — 모르는 값은 — 로 둔다. */}
      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <CountTile icon={Boxes} label="팩" value={known ? packs.length : null} />
        <CountTile
          icon={FileText}
          label="문서"
          value={known ? totals.documents : null}
        />
        <CountTile icon={Hash} label="개념" value={known ? totals.concepts : null} />
        <CountTile
          icon={Network}
          label="관계"
          value={known ? totals.relations : null}
        />
      </div>

      {/* ---------- 팩 빌드 ---------- */}
      <Card className="mt-6">
        <CardHeader>
          <CardTitle className="text-md">팩 빌드</CardTitle>
          <CardDescription>
            검토에서 승인한 개념과 관계만 담아 하나의 불변 스냅샷을 만듭니다.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              void buildPack();
            }}
          >
            <div className="min-w-60 flex-1 space-y-1.5">
              <label
                htmlFor="pack-name"
                className="text-label tracking-label text-muted-foreground"
              >
                팩 이름
              </label>
              <Input
                id="pack-name"
                ref={nameRef}
                value={name}
                maxLength={64}
                placeholder="my-pack"
                autoComplete="off"
                spellCheck={false}
                onChange={(event) => setName(event.target.value)}
                disabled={building}
                aria-describedby="pack-name-help"
              />
              <p id="pack-name-help" className="text-xs text-muted-foreground">
                폴더 이름이 되므로 영문·숫자·하이픈만 사용합니다. 빌드 시각이
                이름 뒤에 붙습니다.
              </p>
            </div>
            <Button type="submit" disabled={building || !name.trim()} aria-busy={building}>
              {building ? (
                <LoaderCircle className="animate-spin" aria-hidden="true" />
              ) : (
                <PackagePlus aria-hidden="true" />
              )}
              {building ? "빌드 중…" : "팩 빌드"}
            </Button>
          </form>

          <div aria-live="polite">
            {buildResult?.kind === "ok" ? (
              <Alert variant="success">
                <ShieldCheck className="h-4 w-4" aria-hidden="true" />
                <AlertTitle>팩을 만들었습니다.</AlertTitle>
                <AlertDescription className="mt-2 space-y-3">
                  <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-foreground">
                    <code className="font-mono text-xs">{buildResult.packId}</code>
                    <span className="text-muted-foreground">
                      문서{" "}
                      <span className="tabular-nums text-foreground">
                        {numberKo.format(buildResult.counts.documents ?? 0)}
                      </span>{" "}
                      · 개념{" "}
                      <span className="tabular-nums text-foreground">
                        {numberKo.format(buildResult.counts.nodes_verified ?? 0)}
                      </span>{" "}
                      · 관계{" "}
                      <span className="tabular-nums text-foreground">
                        {numberKo.format(buildResult.counts.edges_verified ?? 0)}
                      </span>
                    </span>
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setOpenId(buildResult.packId)}
                    >
                      세부 정보
                    </Button>
                    <Button asChild size="sm">
                      <Link to="/mcp">
                        연결로 이동
                        <ArrowRight aria-hidden="true" />
                      </Link>
                    </Button>
                  </div>
                </AlertDescription>
              </Alert>
            ) : buildResult?.kind === "failed" ? (
              <Alert variant="destructive">
                <TriangleAlert className="h-4 w-4" aria-hidden="true" />
                <AlertTitle>팩 빌드를 마치지 못했습니다.</AlertTitle>
                <AlertDescription className="mt-2 space-y-2">
                  <p>{buildResult.message}</p>
                  {buildResult.detail ? (
                    <details className="text-xs text-muted-foreground">
                      <summary className="cursor-pointer">기술 세부 정보</summary>
                      <code className="mt-2 block max-w-(--measure) break-all font-mono">
                        {buildResult.detail}
                      </code>
                    </details>
                  ) : null}
                </AlertDescription>
              </Alert>
            ) : null}
          </div>
        </CardContent>
      </Card>

      {/* ---------- 빌드된 팩 ---------- */}
      <Card className="mt-6">
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div className="space-y-1.5">
            <CardTitle className="text-md">빌드된 팩</CardTitle>
            <CardDescription>
              팩 이름을 선택하면 개념·관계와 검증 상태를 확인합니다.
            </CardDescription>
          </div>
          <span className="text-label tracking-label tabular-nums text-muted-foreground">
            {loading ? "불러오는 중" : `${numberKo.format(rows.length)}개`}
          </span>
        </CardHeader>
        <CardContent className="space-y-4">
          {listError ? (
            <ErrorSurface
              title="팩 목록을 불러오지 못했습니다."
              error={listError}
              onRetry={() => void load("refresh")}
              retrying={refreshing}
            />
          ) : null}

          {/* 행이 하나도 없을 때 빈 표머리는 정보가 아니라 잔해다. */}
          {loading || rows.length > 0 ? (
            <Table className="min-w-140">
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">팩</TableHead>
                  <TableHead scope="col">생성</TableHead>
                  <TableHead scope="col" className="text-right">
                    개념
                  </TableHead>
                  <TableHead scope="col">상태</TableHead>
                  <TableHead scope="col" className="text-right">
                    작업
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody aria-busy={loading}>
                {loading
                  ? Array.from({ length: 4 }, (_, index) => (
                      <TableRow key={`skeleton-${index}`}>
                        <TableCell>
                          <Skeleton className="h-4 w-48" />
                        </TableCell>
                        <TableCell>
                          <Skeleton className="h-4 w-20" />
                        </TableCell>
                        <TableCell>
                          <Skeleton className="ml-auto h-4 w-10" />
                        </TableCell>
                        <TableCell>
                          <Skeleton className="h-5 w-16 rounded-md" />
                        </TableCell>
                        <TableCell>
                          <Skeleton className="ml-auto h-8 w-28 rounded-md" />
                        </TableCell>
                      </TableRow>
                    ))
                  : rows.map((row) => {
                      const verdict = verdicts[row.packId];
                      const isVerifying = verifying[row.packId] === true;
                      const isBroken = row.reason !== undefined;
                      return (
                        <TableRow key={row.key}>
                          <TableCell className="align-top">
                            {isBroken || row.status === "building" ? (
                              <code className="font-mono text-xs text-ink-draft">
                                {row.packId}
                              </code>
                            ) : (
                              <button
                                type="button"
                                onClick={() => setOpenId(row.packId)}
                                className="rounded-sm text-left font-mono text-xs text-foreground underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                              >
                                {row.packId}
                              </button>
                            )}
                            {row.note ? (
                              <p className="mt-1 text-xs text-muted-foreground">
                                {row.note}
                              </p>
                            ) : null}
                            {row.reason ? (
                              <p className="mt-1 text-xs text-muted-foreground">
                                팩으로 읽을 수 없는 폴더입니다.
                                <span className="ml-1 font-mono">{row.reason}</span>
                              </p>
                            ) : null}
                            {verdict ? (
                              <p
                                className={cn(
                                  "mt-1 text-xs",
                                  verdict.kind === "pass"
                                    ? "text-ok-text"
                                    : "text-destructive",
                                )}
                              >
                                {verdict.message}
                              </p>
                            ) : null}
                          </TableCell>
                          <TableCell className="align-top whitespace-nowrap text-muted-foreground">
                            <RelativeTime ts={row.createdTs} />
                          </TableCell>
                          <TableCell className="align-top text-right tabular-nums">
                            {row.entityCount === null
                              ? "—"
                              : numberKo.format(row.entityCount)}
                          </TableCell>
                          <TableCell className="align-top">
                            <StatusBadge status={row.status} />
                          </TableCell>
                          <TableCell className="align-top text-right">
                            {isBroken || row.status === "building" ? (
                              <span className="text-xs text-muted-foreground">—</span>
                            ) : (
                              <div className="flex justify-end gap-2">
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  onClick={() => void verifyPack(row.packId)}
                                  disabled={isVerifying}
                                  aria-busy={isVerifying}
                                >
                                  {isVerifying ? (
                                    <LoaderCircle
                                      className="animate-spin"
                                      aria-hidden="true"
                                    />
                                  ) : (
                                    <ShieldCheck aria-hidden="true" />
                                  )}
                                  {isVerifying ? "검증 중…" : "검증"}
                                </Button>
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => setOpenId(row.packId)}
                                >
                                  세부 정보
                                </Button>
                              </div>
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    })}
              </TableBody>
            </Table>
          ) : null}

          {/* 좁은 화면에서는 표가 가로로 스크롤된다 — 숨은 열이 있다는 사실을
              말해 주지 않으면 상태와 작업이 없는 표로 읽힌다. */}
          {rows.length > 0 ? (
            <p className="text-xs text-muted-foreground sm:hidden">
              표를 가로로 스크롤하면 상태와 작업 열까지 확인할 수 있습니다.
            </p>
          ) : null}

          {!loading && rows.length === 0 && !listError ? (
            <div className="flex flex-col items-center gap-3 rounded-md border border-dashed py-12 text-center">
              <Boxes className="h-7 w-7 text-muted-foreground" aria-hidden="true" />
              <p className="text-md font-medium">빌드된 팩이 없습니다</p>
              <p className="max-w-(--measure) px-6 text-sm text-muted-foreground">
                검토에서 승인한 지식만 팩에 담깁니다. 이름을 지정한 뒤 팩 빌드를
                실행합니다.
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => nameRef.current?.focus()}
              >
                <PackagePlus aria-hidden="true" />팩 이름 입력하기
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* ---------- 팩 세부 정보 ---------- */}
      <Dialog
        open={openId !== null}
        onOpenChange={(next) => {
          if (!next) {
            setOpenId(null);
            setDetail(null);
            setDetailError(null);
          }
        }}
      >
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex flex-wrap items-center gap-2 pr-6">
              <span className="font-mono text-md break-all">{openId}</span>
              {/* 세부 정보를 못 읽었으면 상태를 단언하지 않는다. */}
              {detail || openVerdict ? <StatusBadge status={openStatus} /> : null}
            </DialogTitle>
            <DialogDescription>
              팩은 불변입니다. 여기 보이는 개념과 관계는 빌드 시점의 승인분
              그대로입니다.
            </DialogDescription>
          </DialogHeader>

          {detailLoading ? (
            <div className="space-y-3" aria-busy="true">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : (
            <div className="space-y-6">
              {detailError ? (
                <div className="space-y-3">
                  <ErrorSurface
                    title="세부 정보를 불러오지 못했습니다."
                    error={detailError}
                    onRetry={() => setDetailNonce((value) => value + 1)}
                    retrying={detailLoading}
                  />
                  {openManifest ? (
                    <p className="text-xs text-muted-foreground">
                      아래는 목록에서 이미 받은 매니페스트 요약입니다.
                    </p>
                  ) : null}
                </div>
              ) : null}

              {shown ? (
                <>
                  {/* 집계 */}
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <CountTile
                      icon={FileText}
                      label="문서"
                      value={shown.counts?.documents ?? null}
                    />
                    <CountTile
                      icon={Hash}
                      label="개념"
                      value={shown.counts?.nodes_verified ?? null}
                    />
                    <CountTile
                      icon={Network}
                      label="관계"
                      value={shown.counts?.edges_verified ?? null}
                    />
                    <CountTile
                      icon={Users}
                      label="커뮤니티"
                      value={shown.counts?.communities ?? null}
                    />
                  </div>

                  {/* 매니페스트 */}
                  <section className="space-y-3">
                    <h3 className="text-label tracking-label text-muted-foreground">
                      매니페스트
                    </h3>
                    <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
                      <div>
                        <dt className="text-xs text-muted-foreground">생성</dt>
                        <dd className="mt-0.5">
                          <RelativeTime ts={shown.created_ts} />
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs text-muted-foreground">스키마</dt>
                        <dd className="mt-0.5">
                          {shown.schema_label ?? "—"}
                          {shown.schema_version_id !== undefined ? (
                            <span className="ml-1 text-muted-foreground">
                              (v{shown.schema_version_id})
                            </span>
                          ) : null}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs text-muted-foreground">검색 방식</dt>
                        <dd className="mt-0.5">
                          {shown.search_tier
                            ? (SEARCH_TIER_KO[shown.search_tier] ?? shown.search_tier)
                            : "—"}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs text-muted-foreground">임베딩</dt>
                        <dd className="mt-0.5">
                          {shown.embedding_model ?? "없음 (어휘 검색만)"}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs text-muted-foreground">빌드 작업</dt>
                        <dd className="mt-0.5 font-mono text-xs break-all">
                          {shown.source_job_id ?? "—"}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs text-muted-foreground">버전</dt>
                        <dd className="mt-0.5 font-mono text-xs">
                          {shown.ontologylab_version ?? "—"}
                        </dd>
                      </div>
                      <div className="sm:col-span-2">
                        <dt className="text-xs text-muted-foreground">
                          지문 (내용 해시)
                        </dt>
                        <dd className="mt-0.5">
                          {shown.content_hash ? (
                            <CopyValue
                              value={shown.content_hash}
                              display={shortHash(shown.content_hash)}
                              label="내용 해시"
                            />
                          ) : (
                            "—"
                          )}
                        </dd>
                      </div>
                    </dl>
                  </section>

                  <Separator />

                  {/* 검증 */}
                  <section className="space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="text-label tracking-label text-muted-foreground">
                        무결성 검증
                      </h3>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => openId && void verifyPack(openId)}
                        disabled={openId === null || verifying[openId] === true}
                        aria-busy={openId !== null && verifying[openId] === true}
                      >
                        {openId !== null && verifying[openId] ? (
                          <LoaderCircle className="animate-spin" aria-hidden="true" />
                        ) : (
                          <ShieldCheck aria-hidden="true" />
                        )}
                        {openId !== null && verifying[openId]
                          ? "검증 중…"
                          : "무결성 재검증"}
                      </Button>
                    </div>
                    {openVerdict ? (
                      <Alert
                        variant={
                          openVerdict.kind === "pass"
                            ? "success"
                            : openVerdict.kind === "fail"
                              ? "destructive"
                              : "warning"
                        }
                      >
                        {openVerdict.kind === "pass" ? (
                          <ShieldCheck className="h-4 w-4" aria-hidden="true" />
                        ) : (
                          <TriangleAlert className="h-4 w-4" aria-hidden="true" />
                        )}
                        <AlertTitle>
                          {openVerdict.kind === "pass"
                            ? "검증을 통과했습니다."
                            : openVerdict.kind === "fail"
                              ? "검증에 실패했습니다."
                              : "검증을 실행하지 못했습니다."}
                        </AlertTitle>
                        <AlertDescription className="mt-2 space-y-2">
                          <p>{openVerdict.message}</p>
                          {openVerdict.detail ? (
                            <code className="block max-w-(--measure) break-all font-mono text-xs">
                              {openVerdict.detail}
                            </code>
                          ) : null}
                        </AlertDescription>
                      </Alert>
                    ) : detail?.verification ? (
                      <p className="text-sm text-muted-foreground">
                        마지막 검증:{" "}
                        <RelativeTime ts={detail.verification.checked_at} /> ·{" "}
                        {detail.verification.detail ??
                          (readVerdict(detail.verification).kind === "pass"
                            ? "통과"
                            : "실패")}
                      </p>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        아직 이 화면에서 검증을 실행하지 않았습니다. 재검증은 팩
                        내용을 다시 읽어 지문과 대조합니다.
                      </p>
                    )}
                  </section>

                  <Separator />

                  {/* 개념 */}
                  <section className="space-y-3">
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="text-label tracking-label text-muted-foreground">
                        개념
                      </h3>
                      <span className="text-xs tabular-nums text-muted-foreground">
                        {entities.length > 0
                          ? `${numberKo.format(Math.min(entityLimit, entities.length))} / ${numberKo.format(entities.length)}`
                          : "—"}
                      </span>
                    </div>
                    {entities.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        {detailError
                          ? "세부 정보를 불러오지 못해 개념 목록을 표시할 수 없습니다."
                          : "이 팩에 담긴 개념이 없습니다."}
                      </p>
                    ) : (
                      <>
                        <ul className="divide-y rounded-md border">
                          {entities.slice(0, entityLimit).map((entity, index) => (
                            <li
                              key={entity.id ?? entity.node_id ?? `entity-${index}`}
                              className="flex items-center justify-between gap-3 px-3 py-2"
                            >
                              <span
                                className={cn(
                                  "truncate",
                                  entity.status && entity.status !== "verified"
                                    ? "text-ink-draft"
                                    : "text-foreground",
                                )}
                              >
                                {entityName(entity)}
                              </span>
                              {entityType(entity) ? (
                                <Badge variant="outline" className="shrink-0">
                                  {entityType(entity)}
                                </Badge>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                        {entityLimit < entities.length ? (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => setEntityLimit((value) => value + PAGE_SIZE)}
                          >
                            더 보기
                          </Button>
                        ) : null}
                      </>
                    )}
                  </section>

                  {/* 관계 */}
                  <section className="space-y-3">
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="text-label tracking-label text-muted-foreground">
                        관계
                      </h3>
                      <span className="text-xs tabular-nums text-muted-foreground">
                        {relations.length > 0
                          ? `${numberKo.format(Math.min(relationLimit, relations.length))} / ${numberKo.format(relations.length)}`
                          : "—"}
                      </span>
                    </div>
                    {relations.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        {detailError
                          ? "세부 정보를 불러오지 못해 관계 목록을 표시할 수 없습니다."
                          : "이 팩에 담긴 관계가 없습니다."}
                      </p>
                    ) : (
                      <>
                        <ul className="divide-y rounded-md border">
                          {relations.slice(0, relationLimit).map((relation, index) => {
                            const [subject, predicate, object] =
                              relationParts(relation);
                            return (
                              <li
                                key={
                                  relation.id ?? relation.edge_id ?? `relation-${index}`
                                }
                                className="flex flex-wrap items-center gap-2 px-3 py-2"
                              >
                                <span className="truncate">{subject}</span>
                                <span className="inline-flex items-center gap-1 font-mono text-xs text-muted-foreground">
                                  {predicate}
                                  <ArrowRight className="h-3 w-3" aria-hidden="true" />
                                </span>
                                <span className="truncate">{object}</span>
                              </li>
                            );
                          })}
                        </ul>
                        {relationLimit < relations.length ? (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() =>
                              setRelationLimit((value) => value + PAGE_SIZE)
                            }
                          >
                            더 보기
                          </Button>
                        ) : null}
                      </>
                    )}
                  </section>
                </>
              ) : detailError ? null : (
                <p className="text-sm text-muted-foreground">
                  표시할 세부 정보가 없습니다.
                </p>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
