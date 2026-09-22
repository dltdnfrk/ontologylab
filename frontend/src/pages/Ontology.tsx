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
  BookOpen,
  Boxes,
  CircleAlert,
  Download,
  ListChecks,
  LoaderCircle,
  RefreshCw,
  Settings,
  ShieldAlert,
  Waypoints,
} from "lucide-react";
import { get } from "@/lib/api";
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
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
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

/* ==========================================================================
   서버 계약 — 이름은 서버 쪽 철자 그대로 둔다.

   GET /api/schema           routes.py:get_schema → active = KGStore.get_schema()
   GET /api/ontology/audit   schema_audit.audit_schema()
   GET /api/ontology/cq      { questions: list_schema_cqs(), coverage: check_schema_cqs() }
   GET /api/ontology/export/{skos,owl}  text/turtle — 링크로만 연다(JSON 아님).
   ========================================================================== */

type EntityType = {
  name: string;
  description: string | null;
  attributes: unknown;
  parent: string | null;
};

type RelationType = {
  name: string;
  description: string | null;
  domain_type: string;
  range_type: string;
  directed: boolean;
  qualifiers: Record<string, unknown>;
};

type ActiveSchema = {
  schema_version_id: number;
  schema_label: string;
  entity_types: EntityType[];
  relation_types: RelationType[];
};

type InstalledSchema = {
  id: number;
  label: string;
  description: string;
  created_ts: number;
  active: boolean;
  items: number;
};

type SchemaResponse = {
  active: ActiveSchema | null;
  installed: InstalledSchema[];
};

type Finding = {
  pitfall: string;
  severity: string;
  subject: string;
  detail: string;
};

type AuditResponse = {
  schema_version_id: number;
  schema_label: string;
  findings: Finding[];
  warnings: number;
  info: number;
};

type CompetencyQuestion = {
  id: string | number;
  question: string;
  requires: string[];
  reviewer: string | null;
  provenance: string | null;
  created_ts: number;
};

type CoverageRow = CompetencyQuestion & {
  covered: boolean;
  missing: string[];
  reason: "unscoped" | null;
};

type CqResponse = {
  questions: CompetencyQuestion[];
  coverage: {
    schema_version_id: number;
    total: number;
    covered: number;
    questions: CoverageRow[];
  };
};

/* ==========================================================================
   Helpers
   ========================================================================== */

const NUM = new Intl.NumberFormat("ko-KR");

/**
 * `api.ts` 는 실패를 `"<status>: <body>"` 한 줄로 던진다. FastAPI 본문은
 * `{"detail": "..."}` 이라 읽을 수 있으면 풀고, 아니면 원문을 그대로 둔다.
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

/* pitfall 코드의 출처: ontologylab/schema_audit.py */
const PITFALL_LABEL: Record<string, string> = {
  "missing-description": "설명 없음",
  "unconstrained-relation": "제약 없는 관계",
  "partially-unconstrained-relation": "한쪽만 제약된 관계",
  "orphan-type": "고립된 타입",
  "name-collision": "이름 충돌",
  "unused-type": "미사용 타입",
  "unused-relation": "미사용 관계",
  "unscoped-cq": "범위 없는 질문",
  "uncovered-cq": "미충족 질문",
};

const SEVERITY_ORDER: Record<string, number> = { warning: 0, info: 1 };

type Resource<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
};

/**
 * GET 하나를 상태로 들고 있는 최소 훅. 재조회가 실패해도 앞서 받은 데이터는
 * 지우지 않는다 — 오류와 빈 목록을 구분할 수 있어야 한다.
 */
function useResource<T>(path: string): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(() => {
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

  useEffect(() => reload(), [reload]);

  return { data, error, loading, reload };
}

/* ==========================================================================
   조각들 — 프리미티브와 같은 토큰으로만 조립한다
   ========================================================================== */

function Stat({
  icon: Icon,
  label,
  children,
}: {
  icon: ComponentType<{ className?: string }>;
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded-lg border bg-muted/40 p-4">
      <div className="flex items-center gap-2 text-label font-medium tracking-label text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        <span>{label}</span>
      </div>
      <div className="mt-2 font-mono text-xl tabular-nums">{children}</div>
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
      <CircleAlert className="h-4 w-4" />
      <AlertTitle>불러오지 못했습니다</AlertTitle>
      <AlertDescription className="space-y-3">
        <p className="break-all font-mono text-xs">{message}</p>
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

function EmptyRow({ cols, children }: { cols: number; children: ReactNode }) {
  return (
    <TableRow className="hover:bg-transparent">
      <TableCell colSpan={cols} className="h-24 text-center text-muted-foreground">
        {children}
      </TableCell>
    </TableRow>
  );
}

function MachineValue({ children }: { children: ReactNode }) {
  return (
    <code className="block break-all rounded-md bg-muted px-2 py-1 font-mono text-xs text-foreground">
      {children}
    </code>
  );
}

/** 설명이 비어 있으면 감사에서 경고가 되므로, 목록에서도 같은 색으로 드러낸다. */
function Description({ text }: { text: string | null }) {
  const trimmed = (text ?? "").trim();
  if (!trimmed) return <span className="text-xs text-warn-text">설명 없음</span>;
  return <span className="text-muted-foreground">{trimmed}</span>;
}

/** 도메인·범위의 '*' 는 "아무거나" 라는 뜻이다 — 감사가 경고하는 자리. */
function TypeRef({ name }: { name: string }) {
  if (name === "*") return <span className="font-mono text-warn-text">*</span>;
  return <span className="font-mono">{name}</span>;
}

function SeverityBadge({ severity }: { severity: string }) {
  if (severity === "warning") return <Badge variant="warning">경고</Badge>;
  if (severity === "info") return <Badge variant="outline">참고</Badge>;
  return (
    <Badge variant="outline" className="font-mono font-normal">
      {severity}
    </Badge>
  );
}

function CoverageBadge({ row }: { row: CoverageRow }) {
  if (row.covered) return <Badge variant="success">충족</Badge>;
  if (row.reason === "unscoped") return <Badge variant="outline">범위 없음</Badge>;
  return <Badge variant="warning">미충족</Badge>;
}

/* ==========================================================================
   섹션
   ========================================================================== */

function SchemaCard({ schema }: { schema: Resource<SchemaResponse> }) {
  const active = schema.data?.active ?? null;
  const pending = schema.loading && schema.data === null;

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
        <div className="space-y-1.5">
          <CardTitle className="flex items-center gap-2">
            <BookOpen className="h-4 w-4" />
            활성 온톨로지
          </CardTitle>
          <CardDescription>
            추출기가 찾는 엔티티·관계 타입입니다. 전환은 설정 화면에서 하며,
            이전 버전은 편집되지 않고 비활성화만 됩니다.
          </CardDescription>
        </div>
        <Button asChild variant="outline" size="sm" className="shrink-0 text-foreground">
          <Link to="/settings">
            <Settings />
            설정에서 전환
          </Link>
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {schema.error ? (
          <SectionError message={schema.error} onRetry={schema.reload} />
        ) : null}

        {pending ? (
          <div className="space-y-4">
            <Skeleton className="h-6 w-56" />
            <div className="grid gap-4 sm:grid-cols-2">
              <Skeleton className="h-[5.5rem] w-full" />
              <Skeleton className="h-[5.5rem] w-full" />
            </div>
            <Skeleton className="h-40 w-full" />
          </div>
        ) : !active ? (
          schema.error ? null : (
            <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
              활성 온톨로지가 없습니다. <strong>설정</strong> 화면에서 프리셋을
              적용하세요.
            </p>
          )
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-lg font-semibold">{active.schema_label}</span>
              <Badge>활성</Badge>
              <Badge variant="outline" className="font-mono font-normal">
                v{active.schema_version_id}
              </Badge>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <Stat icon={Boxes} label="엔티티 타입">
                {NUM.format(active.entity_types.length)}
                <span className="ml-1 text-sm text-muted-foreground">개</span>
              </Stat>
              <Stat icon={Waypoints} label="관계 타입">
                {NUM.format(active.relation_types.length)}
                <span className="ml-1 text-sm text-muted-foreground">개</span>
              </Stat>
            </div>

            <Tabs defaultValue="entity">
              <TabsList>
                <TabsTrigger value="entity">
                  엔티티 타입
                  <span className="ml-1.5 font-mono text-xs tabular-nums text-muted-foreground">
                    {active.entity_types.length}
                  </span>
                </TabsTrigger>
                <TabsTrigger value="relation">
                  관계 타입
                  <span className="ml-1.5 font-mono text-xs tabular-nums text-muted-foreground">
                    {active.relation_types.length}
                  </span>
                </TabsTrigger>
              </TabsList>

              <TabsContent value="entity">
                <ScrollArea className="max-h-96 rounded-lg border">
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead className="w-[12rem]">이름</TableHead>
                        <TableHead className="w-[10rem]">상위 타입</TableHead>
                        <TableHead>설명</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {active.entity_types.length === 0 ? (
                        <EmptyRow cols={3}>정의된 엔티티 타입이 없습니다.</EmptyRow>
                      ) : (
                        active.entity_types.map((type) => (
                          <TableRow key={type.name}>
                            <TableCell className="font-mono text-xs font-medium">
                              {type.name}
                            </TableCell>
                            <TableCell className="font-mono text-xs">
                              {type.parent ?? (
                                <span className="text-muted-foreground">—</span>
                              )}
                            </TableCell>
                            <TableCell className="text-xs">
                              <Description text={type.description} />
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </ScrollArea>
              </TabsContent>

              <TabsContent value="relation">
                <ScrollArea className="max-h-96 rounded-lg border">
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead className="w-[12rem]">이름</TableHead>
                        <TableHead className="w-[16rem]">도메인 → 범위</TableHead>
                        <TableHead className="w-[6rem]">방향</TableHead>
                        <TableHead>설명</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {active.relation_types.length === 0 ? (
                        <EmptyRow cols={4}>정의된 관계 타입이 없습니다.</EmptyRow>
                      ) : (
                        active.relation_types.map((type) => (
                          <TableRow key={type.name}>
                            <TableCell className="font-mono text-xs font-medium">
                              {type.name}
                            </TableCell>
                            <TableCell className="text-xs">
                              <TypeRef name={type.domain_type} />
                              <span className="mx-1.5 text-muted-foreground">→</span>
                              <TypeRef name={type.range_type} />
                            </TableCell>
                            <TableCell className="text-xs text-muted-foreground">
                              {type.directed ? "방향 있음" : "무방향"}
                            </TableCell>
                            <TableCell className="text-xs">
                              <Description text={type.description} />
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </ScrollArea>
              </TabsContent>
            </Tabs>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function AuditCard({ audit }: { audit: Resource<AuditResponse> }) {
  const pending = audit.loading && audit.data === null;

  // 경고를 위로. 서버는 점검 순서대로 보내는데, 고칠 사람은 결함부터 본다.
  const findings = useMemo(() => {
    const list = audit.data?.findings ?? [];
    return [...list].sort(
      (a, b) =>
        (SEVERITY_ORDER[a.severity] ?? 2) - (SEVERITY_ORDER[b.severity] ?? 2),
    );
  }, [audit.data]);

  const warnings = audit.data?.warnings ?? 0;
  const info = audit.data?.info ?? 0;

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
        <div className="space-y-1.5">
          <CardTitle className="flex items-center gap-2">
            <ShieldAlert className="h-4 w-4" />
            설계 감사
          </CardTitle>
          <CardDescription>
            OOPS! 방식의 정적 점검입니다. <strong>경고</strong>는 추출 전에 고칠
            결함, <strong>참고</strong>는 의도일 수 있는 냄새입니다. 판정은 바꾸지
            않습니다.
          </CardDescription>
        </div>
        {pending ? (
          <Skeleton className="h-6 w-28" />
        ) : audit.data ? (
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
            {warnings > 0 ? (
              <Badge variant="warning">경고 {NUM.format(warnings)}</Badge>
            ) : null}
            {info > 0 ? (
              <Badge variant="outline">참고 {NUM.format(info)}</Badge>
            ) : null}
            {warnings === 0 && info === 0 ? (
              <Badge variant="success">문제 없음</Badge>
            ) : null}
          </div>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-4">
        {audit.error ? (
          <SectionError message={audit.error} onRetry={audit.reload} />
        ) : null}
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-[5rem]">심각도</TableHead>
              <TableHead className="w-[14rem]">유형</TableHead>
              <TableHead className="w-[12rem]">대상</TableHead>
              <TableHead>내용</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pending ? (
              <SkeletonRows rows={4} cols={4} />
            ) : audit.error && audit.data === null ? (
              <EmptyRow cols={4}>감사 결과를 표시할 수 없습니다.</EmptyRow>
            ) : findings.length === 0 ? (
              <EmptyRow cols={4}>발견된 설계 문제가 없습니다.</EmptyRow>
            ) : (
              findings.map((finding, index) => (
                <TableRow
                  key={`${finding.pitfall}:${finding.subject}:${index}`}
                  className="align-top"
                >
                  <TableCell>
                    <SeverityBadge severity={finding.severity} />
                  </TableCell>
                  <TableCell>
                    <div className="space-y-0.5">
                      <div className="text-xs font-medium">
                        {PITFALL_LABEL[finding.pitfall] ?? finding.pitfall}
                      </div>
                      {PITFALL_LABEL[finding.pitfall] ? (
                        <div className="font-mono text-xs text-ink-draft">
                          {finding.pitfall}
                        </div>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell className="break-all font-mono text-xs">
                    {finding.subject}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {finding.detail}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function CqCard({ cq }: { cq: Resource<CqResponse> }) {
  const pending = cq.loading && cq.data === null;
  const coverage = cq.data?.coverage ?? null;
  const rows = coverage?.questions ?? [];
  const total = coverage?.total ?? 0;
  const covered = coverage?.covered ?? 0;
  const share = total > 0 ? (covered / total) * 100 : 0;

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
        <div className="space-y-1.5">
          <CardTitle className="flex items-center gap-2">
            <ListChecks className="h-4 w-4" />
            역량 질문 커버리지
          </CardTitle>
          <CardDescription>
            온톨로지가 자기 질문에 답할 어휘를 갖췄는지 확인합니다. 용어를 하나도
            지정하지 않은 질문은 검사할 수 없어 <strong>범위 없음</strong>으로
            미충족 처리됩니다.
          </CardDescription>
        </div>
        {pending ? (
          <Skeleton className="h-6 w-20" />
        ) : coverage ? (
          <Badge
            variant={total === 0 ? "outline" : covered === total ? "success" : "warning"}
            className="shrink-0 font-mono font-normal tabular-nums"
          >
            {NUM.format(covered)} / {NUM.format(total)}
          </Badge>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-4">
        {cq.error ? <SectionError message={cq.error} onRetry={cq.reload} /> : null}

        {coverage && total > 0 ? (
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-label font-medium tracking-label text-muted-foreground">
                충족률
              </span>
              <span className="text-xs tabular-nums text-muted-foreground">
                {NUM.format(covered)}개 충족 · {NUM.format(total - covered)}개 미충족 ·{" "}
                {share.toFixed(0)}%
              </span>
            </div>
            <Progress value={share} className="h-1.5 bg-muted" aria-label="역량 질문 충족률" />
          </div>
        ) : null}

        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-[6rem]">상태</TableHead>
              <TableHead>질문</TableHead>
              <TableHead className="w-[18rem]">필요 용어</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pending ? (
              <SkeletonRows rows={3} cols={3} />
            ) : cq.error && cq.data === null ? (
              <EmptyRow cols={3}>역량 질문을 표시할 수 없습니다.</EmptyRow>
            ) : rows.length === 0 ? (
              <EmptyRow cols={3}>등록된 역량 질문이 없습니다.</EmptyRow>
            ) : (
              rows.map((row) => {
                const missing = new Set(row.missing);
                return (
                  <TableRow key={String(row.id)} className="align-top">
                    <TableCell>
                      <CoverageBadge row={row} />
                    </TableCell>
                    <TableCell>
                      <div className="space-y-0.5">
                        <div className="text-sm">{row.question}</div>
                        <div className="font-mono text-xs text-ink-draft">
                          {String(row.id)}
                          {row.reviewer ? ` · 검토자 ${row.reviewer}` : ""}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      {row.requires.length === 0 ? (
                        <span className="text-xs text-muted-foreground">없음</span>
                      ) : (
                        <div className="flex flex-wrap gap-1">
                          {row.requires.map((term) => (
                            <Badge
                              key={term}
                              variant={missing.has(term) ? "warning" : "secondary"}
                              className="font-mono text-xs font-normal"
                              title={missing.has(term) ? "온톨로지에 선언되지 않은 용어" : undefined}
                            >
                              {term}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

/** 내보내기는 Turtle 텍스트라 JSON 클라이언트를 거치지 않는다. 같은 출처 링크에
 *  세션 쿠키가 실리고, GET 은 CSRF 검사 대상이 아니다(server/security.py). */
const EXPORTS = [
  {
    key: "skos",
    title: "SKOS 개념 체계",
    description: "엔티티 타입을 skos:Concept 으로, 상위 타입을 broader 로 씁니다.",
    suffix: "skos.ttl",
    button: "SKOS Turtle 내려받기",
  },
  {
    key: "owl",
    title: "OWL 클래스·속성",
    description: "엔티티 타입을 owl:Class 로, 관계 타입을 ObjectProperty 로 씁니다.",
    suffix: "owl.ttl",
    button: "OWL Turtle 내려받기",
  },
] as const;

function ExportCard({ versionId }: { versionId: number | null }) {
  const query = versionId === null ? "" : `?version=${versionId}`;
  const stem = versionId === null ? "ontology" : `ontology-v${versionId}`;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Download className="h-4 w-4" />
          내보내기
        </CardTitle>
        <CardDescription>
          {versionId === null
            ? "활성 온톨로지를 표준 어휘(Turtle)로 내려받습니다."
            : `v${versionId} 온톨로지를 표준 어휘(Turtle)로 내려받습니다.`}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 sm:grid-cols-2">
          {EXPORTS.map((item) => {
            const path = `/api/ontology/export/${item.key}${query}`;
            return (
              <div key={item.key} className="space-y-3 rounded-lg border bg-muted/40 p-4">
                <div className="space-y-1">
                  <p className="text-sm font-medium">{item.title}</p>
                  <p className="text-xs text-muted-foreground">{item.description}</p>
                </div>
                <Button asChild variant="outline" size="sm" className="text-foreground">
                  <a href={path} download={`${stem}.${item.suffix}`}>
                    <Download />
                    {item.button}
                  </a>
                </Button>
                <MachineValue>{path}</MachineValue>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

/* ==========================================================================
   페이지
   ========================================================================== */

export default function OntologyPage() {
  const schema = useResource<SchemaResponse>("/schema");
  const audit = useResource<AuditResponse>("/ontology/audit");
  const cq = useResource<CqResponse>("/ontology/cq");

  const busy = schema.loading || audit.loading || cq.loading;

  const reloadAll = useCallback(() => {
    schema.reload();
    audit.reload();
    cq.reload();
  }, [schema, audit, cq]);

  const versionId = schema.data?.active?.schema_version_id ?? null;

  return (
    <div className="mx-auto w-full max-w-[var(--content-max)] space-y-6 p-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight">온톨로지</h1>
          <p className="text-sm text-muted-foreground">
            활성 온톨로지의 타입, 설계 감사, 역량 질문 커버리지를 확인하고
            표준 어휘로 내보냅니다 · 읽기 전용
          </p>
        </div>
        <Button type="button" variant="outline" onClick={reloadAll} disabled={busy}>
          {busy ? <LoaderCircle className="animate-spin" /> : <RefreshCw className={cn(busy && "animate-spin")} />}
          새로고침
        </Button>
      </header>

      <SchemaCard schema={schema} />
      <AuditCard audit={audit} />
      <CqCard cq={cq} />
      <ExportCard versionId={versionId} />
    </div>
  );
}
