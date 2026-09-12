import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Boxes,
  ChevronRight,
  CircleAlert,
  Network,
  PackageOpen,
  RefreshCw,
  Sparkles,
  Users,
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

// ---------------------------------------------------------------------------
// Wire types — mirrored from ontologylab/server/routes.py. `top_members` holds
// display *names* (packbuilder writes member_names[:TOP_MEMBERS]), never node
// ids, so only the detail members below can be deep-linked into the graph.
// ---------------------------------------------------------------------------

type Community = {
  id: string;
  member_count: number;
  top_members: string[];
  summary: string;
  summary_method: string;
};

type CommunityMember = {
  id: string;
  name: string;
  entity_type: string;
  status: string;
};

type GraphEdge = {
  id: string;
  relation_type: string;
  source_id: string;
  target_id: string;
  status: string;
  confidence: number | null;
};

type PackSummary = {
  pack_id: string;
  created_ts?: number | null;
  counts?: Record<string, number> | null;
};

type CommunityListResponse = { communities: Community[]; count: number };
type CommunityDetailResponse = {
  community: Community | null;
  members: CommunityMember[];
};
type PacksResponse = { packs: PackSummary[]; count: number };
type GraphResponse = { edges: GraphEdge[] };

const MEMBER_PREVIEW = 3;
const LIST_LIMIT = 200;
const GRAPH_LIMIT = 500;

/** api.ts throws `Error("<status>: <raw body>")`; recover the typed detail. */
function errorText(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err);
  const match = /^(\d{3}): ([\s\S]*)$/.exec(raw);
  if (!match) return raw;
  const [, status, body] = match;
  if (status === "401") {
    return "세션이 만료되었습니다. 페이지를 새로고침해 주세요.";
  }
  let detail = body.trim();
  try {
    const parsed: unknown = JSON.parse(body);
    if (parsed && typeof parsed === "object") {
      const candidate = (parsed as Record<string, unknown>).detail;
      if (typeof candidate === "string" && candidate) detail = candidate;
    }
  } catch {
    // Body was not JSON (proxy/HTML error page) — keep the raw text.
  }
  return detail ? `${status} · ${detail}` : status;
}

/** Mirrors `_latest_community_pack`: newest by build timestamp, then pack id. */
function newestPack(packs: PackSummary[]): PackSummary | null {
  if (packs.length === 0) return null;
  return packs.reduce((best, pack) => {
    const a = pack.created_ts ?? 0;
    const b = best.created_ts ?? 0;
    if (a > b) return pack;
    if (a === b && pack.pack_id > best.pack_id) return pack;
    return best;
  });
}

const dateFormat = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "medium",
  timeStyle: "short",
});

function formatBuiltAt(ts?: number | null): string | null {
  if (typeof ts !== "number" || !Number.isFinite(ts) || ts <= 0) return null;
  return dateFormat.format(new Date(ts * 1000));
}

function methodLabel(method: string): string {
  return method === "extractive" ? "추출 요약" : `${method} 요약`;
}

function statusLabel(status: string): string {
  if (status === "verified") return "검증";
  if (status === "proposed") return "제안";
  return status;
}

// ---------------------------------------------------------------------------

export default function CommunitiesPage() {
  const [communities, setCommunities] = useState<Community[] | null>(null);
  const [packs, setPacks] = useState<PackSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(true);

  const [selectedId, setSelectedId] = useState<string | null>(null);

  const loadList = useCallback(async () => {
    setListLoading(true);
    setListError(null);
    try {
      // The pack list resolves *which* pack answered, and separates "no usable
      // pack" from "a pack that simply has no communities" — the list endpoint
      // returns an empty array for both.
      const [list, packList] = await Promise.all([
        get<CommunityListResponse>(`/communities?limit=${LIST_LIMIT}`),
        get<PacksResponse>("/packs"),
      ]);
      setCommunities(list.communities ?? []);
      setPacks(packList.packs ?? []);
    } catch (err) {
      setListError(errorText(err));
      setCommunities(null);
      setPacks(null);
    } finally {
      setListLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  // Keep a selection pinned to a row that still exists after a refresh.
  useEffect(() => {
    if (!communities || communities.length === 0) {
      setSelectedId(null);
      return;
    }
    setSelectedId((current) =>
      current && communities.some((c) => c.id === current)
        ? current
        : communities[0].id,
    );
  }, [communities]);

  const pack = useMemo(() => (packs ? newestPack(packs) : null), [packs]);
  const builtAt = formatBuiltAt(pack?.created_ts);

  const totals = useMemo(() => {
    const rows = communities ?? [];
    return {
      count: rows.length,
      members: rows.reduce((sum, c) => sum + c.member_count, 0),
      largest: rows.reduce((max, c) => Math.max(max, c.member_count), 0),
    };
  }, [communities]);

  const hasPack = packs !== null && packs.length > 0;
  const isEmpty = communities !== null && communities.length === 0;

  return (
    <div className="mx-auto flex w-full max-w-[var(--content-max)] flex-col gap-6 p-6">
      <PageHeader
        packId={pack?.pack_id ?? null}
        builtAt={builtAt}
        loading={listLoading}
        onRefresh={() => void loadList()}
      />

      {listError ? (
        <Alert variant="destructive">
          <CircleAlert className="h-4 w-4" />
          <AlertTitle>커뮤니티를 불러오지 못했습니다</AlertTitle>
          <AlertDescription className="flex flex-col items-start gap-3">
            <span className="text-muted-foreground">{listError}</span>
            <Button size="sm" variant="outline" onClick={() => void loadList()}>
              <RefreshCw className="h-4 w-4" />
              다시 시도
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      {!listError && !listLoading && communities !== null && !isEmpty ? (
        <StatStrip
          count={totals.count}
          members={totals.members}
          largest={totals.largest}
        />
      ) : null}

      {listLoading ? (
        <ListSkeleton />
      ) : listError ? null : isEmpty ? (
        hasPack ? (
          <NoCommunitiesState packId={pack?.pack_id ?? null} />
        ) : (
          <NoPackState />
        )
      ) : (
        <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(0,1.85fr)_minmax(0,1fr)]">
          <div className="min-w-0">
            <CommunityTable
              communities={communities ?? []}
              largest={totals.largest}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          </div>
          <div className="min-w-0 lg:sticky lg:top-6">
            <CommunityDetail communityId={selectedId} />
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

function PageHeader({
  packId,
  builtAt,
  loading,
  onRefresh,
}: {
  packId: string | null;
  builtAt: string | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4 rounded-lg border bg-card p-6">
      <div className="flex items-start gap-4">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md bg-secondary text-foreground">
          <Users className="h-5 w-5" />
        </div>
        <div className="space-y-1.5">
          <h1 className="text-2xl font-semibold leading-none tracking-tight">
            커뮤니티
          </h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            가장 최근에 빌드된 사용 가능한 팩에서 계산한 그래프 클러스터입니다.
            읽기 전용이며, 팩을 다시 빌드할 때 갱신됩니다.
          </p>
          {packId ? (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Badge
                variant="secondary"
                className="max-w-full break-all font-mono font-normal"
              >
                {packId}
              </Badge>
              {builtAt ? (
                <span className="text-xs text-muted-foreground">
                  빌드 {builtAt}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
      <Button
        variant="outline"
        size="sm"
        onClick={onRefresh}
        disabled={loading}
        aria-label="커뮤니티 새로고침"
      >
        <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
        새로고침
      </Button>
    </header>
  );
}

function StatStrip({
  count,
  members,
  largest,
}: {
  count: number;
  members: number;
  largest: number;
}) {
  const stats = [
    { icon: Boxes, label: "커뮤니티", value: count },
    { icon: Users, label: "총 구성원", value: members },
    { icon: Network, label: "최대 규모", value: largest },
  ];
  return (
    <div className="grid gap-4 sm:grid-cols-3">
      {stats.map(({ icon: Icon, label, value }) => (
        <Card key={label}>
          <CardContent className="flex items-center gap-3 p-4">
            <div className="flex h-9 w-9 items-center justify-center rounded-md bg-muted text-muted-foreground">
              <Icon className="h-4 w-4" />
            </div>
            <div className="space-y-0.5">
              <div className="text-label text-muted-foreground">{label}</div>
              <div className="text-xl font-semibold tabular-nums leading-none">
                {value.toLocaleString("ko-KR")}
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function CommunityTable({
  communities,
  largest,
  selectedId,
  onSelect,
}: {
  communities: Community[];
  largest: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <Card className="overflow-hidden">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">커뮤니티 목록</CardTitle>
        <CardDescription>
          구성원이 많은 순서입니다. 행을 선택하면 상세를 확인할 수 있습니다.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-6 whitespace-nowrap">ID</TableHead>
              <TableHead className="whitespace-nowrap">구성원 수</TableHead>
              <TableHead className="min-w-[11rem]">주요 구성원</TableHead>
              <TableHead className="min-w-[13rem]">요약</TableHead>
              <TableHead className="w-8 pr-6" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {communities.map((community) => {
              const selected = community.id === selectedId;
              const overflow = community.member_count - MEMBER_PREVIEW;
              return (
                <TableRow
                  key={community.id}
                  data-state={selected ? "selected" : undefined}
                  tabIndex={0}
                  role="button"
                  aria-pressed={selected}
                  onClick={() => onSelect(community.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelect(community.id);
                    }
                  }}
                  className="cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  <TableCell className="whitespace-nowrap pl-6 font-mono text-xs">
                    {community.id}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <span className="w-6 shrink-0 text-sm font-medium tabular-nums">
                        {community.member_count.toLocaleString("ko-KR")}
                      </span>
                      <div
                        className="h-1 w-14 shrink-0 overflow-hidden rounded-full bg-muted"
                        aria-hidden
                      >
                        <div
                          className="h-full rounded-full bg-chart-4"
                          style={{
                            width: `${
                              largest > 0
                                ? Math.max(
                                    8,
                                    (community.member_count / largest) * 100,
                                  )
                                : 0
                            }%`,
                          }}
                        />
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {community.top_members
                        .slice(0, MEMBER_PREVIEW)
                        .map((name) => (
                          <Badge
                            key={name}
                            variant="secondary"
                            className="font-normal"
                          >
                            {name}
                          </Badge>
                        ))}
                      {overflow > 0 ? (
                        <Badge variant="outline" className="font-normal">
                          +{overflow}
                        </Badge>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    <span className="line-clamp-2">{community.summary}</span>
                  </TableCell>
                  <TableCell className="pr-6">
                    <ChevronRight
                      className={cn(
                        "h-4 w-4 transition-colors",
                        selected ? "text-foreground" : "text-muted-foreground",
                      )}
                    />
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function CommunityDetail({ communityId }: { communityId: string | null }) {
  const [detail, setDetail] = useState<CommunityDetailResponse | null>(null);
  const [edges, setEdges] = useState<GraphEdge[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!communityId) {
      setDetail(null);
      setEdges(null);
      setError(null);
      return;
    }
    // Ignore responses from a superseded selection.
    let active = true;
    setLoading(true);
    setError(null);

    void (async () => {
      try {
        const response = await get<CommunityDetailResponse>(
          `/communities/${encodeURIComponent(communityId)}`,
        );
        if (!active) return;
        setDetail(response);

        // Relations are not part of the community payload; the graph endpoint
        // is the only source. Failing it degrades to a members-only view
        // rather than losing the whole panel.
        try {
          const graph = await get<GraphResponse>(
            `/graph?limit=${GRAPH_LIMIT}&include_proposed=true`,
          );
          if (active) setEdges(graph.edges ?? []);
        } catch {
          if (active) setEdges(null);
        }
      } catch (err) {
        if (active) {
          setError(errorText(err));
          setDetail(null);
          setEdges(null);
        }
      } finally {
        if (active) setLoading(false);
      }
    })();

    return () => {
      active = false;
    };
  }, [communityId]);

  const members = detail?.members ?? [];

  const nameById = useMemo(
    () => new Map(members.map((member) => [member.id, member.name])),
    [members],
  );

  const relations = useMemo(() => {
    if (!edges || members.length === 0) return [];
    return edges.filter(
      (edge) => nameById.has(edge.source_id) && nameById.has(edge.target_id),
    );
  }, [edges, members.length, nameById]);

  if (!communityId) return null;

  return (
    <Card>
      <CardHeader className="pb-4">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle className="font-mono text-base">{communityId}</CardTitle>
            <CardDescription>
              {loading
                ? "불러오는 중…"
                : `구성원 ${members.length.toLocaleString("ko-KR")}개 · 관계 ${relations.length.toLocaleString("ko-KR")}개`}
            </CardDescription>
          </div>
          {detail?.community ? (
            <Badge variant="outline" className="shrink-0 gap-1 font-normal">
              <Sparkles className="h-3 w-3" />
              {methodLabel(detail.community.summary_method)}
            </Badge>
          ) : null}
        </div>
      </CardHeader>

      <CardContent className="space-y-5">
        {error ? (
          <Alert variant="destructive">
            <CircleAlert className="h-4 w-4" />
            <AlertTitle>상세를 불러오지 못했습니다</AlertTitle>
            <AlertDescription className="text-muted-foreground">
              {error}
            </AlertDescription>
          </Alert>
        ) : loading ? (
          <DetailSkeleton />
        ) : (
          <>
            {detail?.community?.summary ? (
              <p className="rounded-lg bg-muted p-3 text-sm leading-relaxed text-muted-foreground">
                {detail.community.summary}
              </p>
            ) : null}

            <section className="space-y-2">
              <SectionLabel icon={Users} title="구성원" count={members.length} />
              {members.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  구성원이 없습니다.
                </p>
              ) : (
                <ScrollArea className="max-h-64">
                  <div className="flex flex-wrap gap-1.5 pr-3">
                    {members.map((member) => (
                      <Link
                        key={member.id}
                        to={`/graph?node=${encodeURIComponent(member.id)}`}
                        title={`${member.name} · ${member.entity_type} · ${statusLabel(member.status)}`}
                        className="rounded-md focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                      >
                        <Badge
                          variant="secondary"
                          className={cn(
                            "gap-1.5 font-normal transition-colors hover:bg-accent hover:text-accent-foreground",
                            member.status !== "verified" && "text-ink-draft",
                          )}
                        >
                          <span
                            aria-hidden
                            className={cn(
                              "h-1.5 w-1.5 rounded-full",
                              member.status === "verified"
                                ? "bg-ok"
                                : "bg-warn",
                            )}
                          />
                          {member.name}
                          <span className="text-muted-foreground">
                            {member.entity_type}
                          </span>
                        </Badge>
                      </Link>
                    ))}
                  </div>
                </ScrollArea>
              )}
            </section>

            <Separator />

            <section className="space-y-2">
              <SectionLabel
                icon={Waypoints}
                title="관계"
                count={relations.length}
              />
              {edges === null ? (
                <p className="text-sm text-muted-foreground">
                  그래프를 불러오지 못해 관계를 표시할 수 없습니다.
                </p>
              ) : relations.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  구성원 사이의 관계가 없습니다.
                </p>
              ) : (
                <ScrollArea className="max-h-56">
                  <ul className="space-y-1.5 pr-3">
                    {relations.map((edge) => (
                      <li
                        key={edge.id}
                        className="flex flex-wrap items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs"
                      >
                        <span className="font-medium">
                          {nameById.get(edge.source_id)}
                        </span>
                        <Badge
                          variant="outline"
                          className="font-mono font-normal"
                        >
                          {edge.relation_type}
                        </Badge>
                        <span className="font-medium">
                          {nameById.get(edge.target_id)}
                        </span>
                        {edge.status !== "verified" ? (
                          <span className="text-warn-text">
                            {statusLabel(edge.status)}
                          </span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </ScrollArea>
              )}
            </section>

            <Button
              asChild
              variant="outline"
              size="sm"
              className="w-full text-foreground"
            >
              <Link to="/graph">
                <Network className="h-4 w-4" />
                그래프에서 보기
              </Link>
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function SectionLabel({
  icon: Icon,
  title,
  count,
}: {
  icon: typeof Users;
  title: string;
  count: number;
}) {
  return (
    <div className="flex items-center gap-2">
      <Icon className="h-4 w-4 text-muted-foreground" />
      <h3 className="text-sm font-medium">{title}</h3>
      <span className="text-xs tabular-nums text-muted-foreground">
        {count.toLocaleString("ko-KR")}
      </span>
    </div>
  );
}

function NoPackState() {
  return (
    <EmptyState
      icon={PackageOpen}
      title="사용 가능한 팩이 없습니다"
      description="커뮤니티는 빌드된 팩에서 계산됩니다. 팩을 먼저 빌드해 주세요."
      action={
        <Button asChild size="sm">
          <Link to="/packs">
            팩으로 이동
            <ChevronRight className="h-4 w-4" />
          </Link>
        </Button>
      }
    />
  );
}

function NoCommunitiesState({ packId }: { packId: string | null }) {
  return (
    <EmptyState
      icon={Boxes}
      title="커뮤니티가 없습니다"
      description={
        packId
          ? `팩 ${packId}에는 계산된 커뮤니티가 없습니다. 팩을 다시 빌드하면 계산됩니다.`
          : "계산된 커뮤니티가 없습니다. 팩을 다시 빌드하면 계산됩니다."
      }
      action={
        <Button asChild size="sm" variant="outline" className="text-foreground">
          <Link to="/packs">
            팩으로 이동
            <ChevronRight className="h-4 w-4" />
          </Link>
        </Button>
      }
    />
  );
}

function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: typeof Users;
  title: string;
  description: string;
  action: React.ReactNode;
}) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-4 px-6 py-16 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <Icon className="h-6 w-6" />
        </div>
        <div className="space-y-1.5">
          <h2 className="font-semibold tracking-tight">{title}</h2>
          <p className="mx-auto max-w-md text-sm text-muted-foreground">
            {description}
          </p>
        </div>
        {action}
      </CardContent>
    </Card>
  );
}

function ListSkeleton() {
  return (
    <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(0,1.85fr)_minmax(0,1fr)]">
      <Card className="min-w-0">
        <CardHeader className="pb-3">
          <Skeleton className="h-5 w-28" />
          <Skeleton className="h-4 w-64" />
        </CardHeader>
        <CardContent className="space-y-3">
          {Array.from({ length: 5 }).map((_, index) => (
            <div key={index} className="flex items-center gap-4">
              <Skeleton className="h-4 w-28 shrink-0" />
              <Skeleton className="h-4 w-16 shrink-0" />
              <Skeleton className="h-5 w-40 shrink-0" />
              <Skeleton className="h-4 w-full" />
            </div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-4">
          <Skeleton className="h-5 w-36" />
          <Skeleton className="h-4 w-24" />
        </CardHeader>
        <CardContent>
          <DetailSkeleton />
        </CardContent>
      </Card>
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-16 w-full" />
      <div className="space-y-2">
        <Skeleton className="h-4 w-24" />
        <div className="flex flex-wrap gap-1.5">
          <Skeleton className="h-5 w-28" />
          <Skeleton className="h-5 w-36" />
          <Skeleton className="h-5 w-24" />
        </div>
      </div>
      <div className="space-y-2">
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    </div>
  );
}
