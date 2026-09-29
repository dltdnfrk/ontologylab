import { useCallback, useEffect, useState } from "react";
import { CircleAlert, Layers, Lightbulb, RefreshCw } from "lucide-react";
import { get } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

// Wire types mirrored from ontologylab/server/routes.py
// (GET /api/claims/stages, GET /api/interpretations).

type StageRelation = {
  relation_type: string;
  polarity: Record<string, number>;
  total: number;
};
type Stage = { key: string; label: string; relations: StageRelation[]; total: number };
type StagesResponse = { stages: Stage[]; include_proposed: boolean };

type InterpretationLink = {
  id: string;
  relation_type: string;
  status: string;
  dst_name: string;
  dst_type: string;
  dst_origin: string;
  dst_status: string;
};
type Interpretation = {
  id: string;
  entity_type: string;
  name: string;
  status: string;
  properties: Record<string, unknown>;
  links: InterpretationLink[];
};
type InterpretationsResponse = { interpretations: Interpretation[]; count: number };

const POLARITY: Record<string, { label: string; className: string }> = {
  supports: { label: "지지", className: "bg-ok-soft text-ok-text" },
  refutes: { label: "반박", className: "bg-destructive-soft text-destructive" },
  no_effect: { label: "효과 없음", className: "bg-warn-soft text-warn-text" },
  unspecified: { label: "극성 미기재", className: "bg-muted text-muted-foreground" },
};
const POLARITY_ORDER = ["supports", "refutes", "no_effect", "unspecified"];

/** api.ts throws `Error("<status>: <raw body>")`; surface the typed detail. */
function errorText(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err);
  const match = /^(\d{3}): ([\s\S]*)$/.exec(raw);
  if (!match) return raw;
  const [, status, body] = match;
  try {
    const parsed: unknown = JSON.parse(body);
    const detail = parsed && typeof parsed === "object"
      ? (parsed as Record<string, unknown>).detail
      : null;
    if (typeof detail === "string" && detail) return `${status} · ${detail}`;
  } catch {
    // Not JSON: keep the raw body.
  }
  return body.trim() ? `${status} · ${body.trim()}` : status;
}

function statusLabel(status: string): string {
  return status === "verified" ? "검증" : status === "proposed" ? "제안" : status;
}

export default function ClaimsPage() {
  const [includeProposed, setIncludeProposed] = useState(false);
  const [stages, setStages] = useState<Stage[] | null>(null);
  const [overlay, setOverlay] = useState<Interpretation[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [stageBody, overlayBody] = await Promise.all([
        get<StagesResponse>(`/claims/stages?include_proposed=${includeProposed}`),
        get<InterpretationsResponse>(`/interpretations?include_proposed=${includeProposed}`),
      ]);
      setStages(stageBody.stages ?? []);
      setOverlay(overlayBody.interpretations ?? []);
    } catch (err) {
      setError(errorText(err));
      setStages(null);
      setOverlay(null);
    } finally {
      setLoading(false);
    }
  }, [includeProposed]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="mx-auto flex w-full max-w-[var(--content-max)] flex-col gap-6 p-6">
      <header className="flex flex-wrap items-start justify-between gap-4 rounded-lg border bg-card p-6">
        <div className="flex items-start gap-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md bg-secondary">
            <Layers className="h-5 w-5" />
          </div>
          <div className="space-y-1.5">
            <h1 className="text-2xl font-semibold leading-none tracking-tight">주장</h1>
            <p className="max-w-2xl text-sm text-muted-foreground">
              관계를 방제 흐름의 단계별로 묶고, 각 주장이 지지·반박·효과 없음 중 무엇인지 셉니다.
              아래 해석은 사람이 큐레이션한 것으로, 논문에서 추출한 사실과 구분됩니다.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant={includeProposed ? "default" : "outline"}
            size="sm"
            aria-pressed={includeProposed}
            onClick={() => setIncludeProposed((value) => !value)}
          >
            {includeProposed ? "제안 포함" : "검증만"}
          </Button>
          <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}
            aria-label="주장 새로고침">
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
            새로고침
          </Button>
        </div>
      </header>

      {error ? (
        <Alert variant="destructive">
          <CircleAlert className="h-4 w-4" />
          <AlertTitle>주장을 불러오지 못했습니다</AlertTitle>
          <AlertDescription className="text-muted-foreground">{error}</AlertDescription>
        </Alert>
      ) : null}

      <section aria-labelledby="stages-heading" className="space-y-3">
        <h2 id="stages-heading" className="text-lg font-semibold">단계별 관계</h2>
        {loading && !stages ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-40" />)}
          </div>
        ) : stages ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {stages
              .filter((stage) => stage.key !== "other" || stage.relations.length > 0)
              .map((stage) => <StageCard key={stage.key} stage={stage} />)}
          </div>
        ) : null}
      </section>

      <section aria-labelledby="overlay-heading" className="space-y-3">
        <h2 id="overlay-heading" className="flex items-center gap-2 text-lg font-semibold">
          <Lightbulb className="h-4 w-4" />
          해석 (큐레이션)
        </h2>
        {overlay && overlay.length === 0 ? (
          <p className="rounded-md border border-dashed p-6 text-sm text-muted-foreground">
            아직 기록된 해석이 없습니다. 질문·시나리오는 POST /api/interpretations 로 기록하며,
            검토 화면에서 승인해야 팩에 들어갑니다.
          </p>
        ) : null}
        {overlay && overlay.length > 0 ? (
          <ul className="grid gap-3">
            {overlay.map((item) => <InterpretationRow key={item.id} item={item} />)}
          </ul>
        ) : null}
      </section>
    </div>
  );
}

function StageCard({ stage }: { stage: Stage }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{stage.label}</CardTitle>
        <CardDescription className="tabular-nums">주장 {stage.total.toLocaleString("ko-KR")}건</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {stage.relations.map((relation) => (
          <div key={relation.relation_type} className="flex flex-wrap items-center gap-1.5 text-sm">
            <span className={cn("font-mono text-xs", relation.total === 0 && "text-muted-foreground")}>
              {relation.relation_type}
            </span>
            {POLARITY_ORDER.filter((key) => relation.polarity[key]).map((key) => (
              <span
                key={key}
                className={cn("rounded px-1.5 py-0.5 text-[11px] tabular-nums", POLARITY[key].className)}
              >
                {POLARITY[key].label} {relation.polarity[key]}
              </span>
            ))}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function InterpretationRow({ item }: { item: Interpretation }) {
  return (
    <li className="rounded-md border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="font-mono">{item.entity_type}</Badge>
        <span className="font-medium">{item.name}</span>
        <Badge variant="running" className="text-[10px]">큐레이션</Badge>
        <Badge variant={item.status === "verified" ? "success" : "warning"} className="text-[10px]">
          {statusLabel(item.status)}
        </Badge>
      </div>
      {item.links.length > 0 ? (
        <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
          {item.links.map((link) => (
            <li key={link.id} className="flex flex-wrap items-center gap-1.5">
              <span className="font-mono text-xs">{link.relation_type}</span>
              <span aria-hidden>→</span>
              <span className="text-foreground">{link.dst_name}</span>
              <span className="text-xs">
                ({link.dst_type} · {link.dst_origin === "curated" ? "큐레이션" : "추출"} · {statusLabel(link.dst_status)})
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-xs text-warn-text">연결된 근거가 없어 팩에 포함할 수 없습니다.</p>
      )}
    </li>
  );
}
