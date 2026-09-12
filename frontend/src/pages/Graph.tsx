import * as React from "react";
import {
  AlertTriangle,
  Crosshair,
  Eye,
  EyeOff,
  Loader2,
  Network,
  RefreshCw,
  Search,
  Share2,
  X,
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
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { get } from "@/lib/api";
import { cn } from "@/lib/utils";

/* ==========================================================================
   자유 탐색용 지식그래프 화면.

   읽기 전용이다 — 승인/거부는 검토 화면의 게이트에서만 일어난다(HITL 불변식).
   여기서 하는 일은 "무엇이 있고 무엇이 아직 사람 눈을 기다리는지"를 한 화면에
   보여 주는 것까지다.

   두 개의 색 축을 쓴다. 섞으면 화면이 거짓말을 한다:
     · 채움(fill)  = 엔티티 타입  → --chart-1..5 순환
     · 링(stroke)  = 검토 상태    → 실선 초록(승인) / 점선 호박(대기)
   선택은 '상호작용 상태'라 '데이터 상태'를 덮지 않는다 — 상태 링은 그대로
   두고 바깥에 --accent 후광만 덧댄다.
   ========================================================================== */

type EntityStatus = "proposed" | "verified" | "rejected";

interface ApiNode {
  id: string;
  entity_type: string;
  name: string;
  aliases: string[];
  properties: Record<string, unknown>;
  status: EntityStatus;
  confidence: number | null;
  source_doc_id: string | null;
  /** neighbors 응답에만 있는 BFS 깊이. */
  hop?: number;
}

interface ApiEdge {
  id: string;
  relation_type: string;
  source_id: string;
  target_id: string;
  status: EntityStatus;
  confidence: number | null;
}

interface GraphPayload {
  nodes: ApiNode[];
  edges: ApiEdge[];
}

interface SearchHit {
  id: string;
  name: string;
  entity_type: string;
  status: EntityStatus;
  score: number | null;
}

interface SearchPayload {
  results: SearchHit[];
}

interface EntityRelation {
  id: string;
  relation_type: string;
  direction: "in" | "out";
  other: { id: string; name: string; status: EntityStatus };
  status: EntityStatus;
  confidence: number | null;
  critic_score: number | null;
}

interface EntityMention {
  source_doc_id: string;
  doc_title: string | null;
  excerpt: string;
}

interface EntityDetail {
  entity: ApiNode;
  critic: { engine: string; model: string | null; score: number; rationale: string | null } | null;
  mentions: EntityMention[];
  relations: EntityRelation[];
  counts: {
    mentions: number;
    relations_proposed: number;
    relations_verified: number;
    merge_candidates: number;
  };
}

/* ---------- 시뮬레이션 상태 ---------- */

interface SimNode {
  id: string;
  name: string;
  entityType: string;
  status: EntityStatus;
  confidence: number | null;
  x: number;
  y: number;
  vx: number;
  vy: number;
  /** 드래그로 고정된 좌표. null 이면 힘이 지배한다. */
  fx: number | null;
  fy: number | null;
}

interface SimEdge {
  id: string;
  source: string;
  target: string;
  relationType: string;
  status: EntityStatus;
}

interface Viewport {
  x: number;
  y: number;
  k: number;
}

interface Size {
  w: number;
  h: number;
}

/* ---------- 상수 ----------
   값은 구 구현(web/app.js)에서 그대로 가져왔다. 노드 200개 스코프에서
   실제로 가라앉는 것이 확인된 조합이라, 임의로 바꾸면 배치가 진동한다. */

const NODE_LIMIT = 200;
const REPULSION = 1400;
const REPULSION_CUTOFF = 160_000; /* 400px 밖은 무시 */
const SPRING_LENGTH = 90;
const SPRING_K = 0.02;
const GRAVITY = 0.002;
const DAMPING = 0.85;
const ALPHA_DECAY = 0.985;
const ALPHA_MIN = 0.02;
const ZOOM_MIN = 0.2;
const ZOOM_MAX = 4;
const FIT_ZOOM_MAX = 1.6;
const FIT_PADDING = 64;
const LABEL_BASE_PX = 11; /* --fs-label */
const TYPE_PALETTE = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

const STATUS_KO: Record<string, string> = {
  proposed: "검토 대기",
  verified: "승인됨",
  rejected: "거부됨",
};

function statusKo(status: string): string {
  return STATUS_KO[String(status).toLowerCase()] ?? status ?? "—";
}

function statusVariant(status: string): "success" | "warning" | "error" | "secondary" {
  const key = String(status).toLowerCase();
  if (key === "verified") return "success";
  if (key === "proposed") return "warning";
  if (key === "rejected") return "error";
  return "secondary";
}

/** 차수가 큰 노드를 크게 — 크기로 구조를 읽게 한다. */
function nodeRadius(degree: number): number {
  return Math.min(16, 6 + 1.6 * Math.sqrt(degree));
}

/** 확대해도 라벨의 화면상 크기가 일정하도록 역보정한다. */
function labelFontSize(scale: number): number {
  return LABEL_BASE_PX / Math.max(0.05, scale || 1);
}

/* ---------- 오류 문장 ----------
   api 클라이언트는 `"<status>: <body>"` 형태로 throw 한다. 사용자에게
   원문(raw)을 그대로 보여 주지 않고, 상태코드별 한국어 한 문장으로 번역한다. */

function errorText(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err ?? "");
  const status = Number(raw.match(/^(\d{3}):/)?.[1] ?? 0);
  if (status === 401) return "인증이 만료되었습니다. 화면을 새로고침해 다시 로그인합니다.";
  if (status === 403) return "이 자료를 볼 권한이 없습니다.";
  if (status === 404) return "대상을 찾을 수 없습니다. 이미 거부되었거나 보기 조건에서 제외되었습니다.";
  if (status === 422) return "요청 값이 올바르지 않습니다.";
  if (status === 429 || status === 503) return "서버가 혼잡합니다. 잠시 후 다시 시도합니다.";
  if (status >= 500) return "서버에서 오류가 발생했습니다.";
  if (!status) return "서버에 연결할 수 없습니다. 네트워크와 로컬 서버 상태를 확인합니다.";
  return "요청을 처리하지 못했습니다.";
}

/* ---------- 라벨 겹침 제거 ----------
   전부 그리면 200개가 서로를 덮어 아무것도 못 읽는다. 차수 높은 것과 선택된
   것을 먼저 놓고, 이미 놓인 상자와 겹치면 버린다. */

interface LabelCandidate {
  id: string;
  name: string;
  x: number;
  y: number;
  degree: number;
}

interface LabelBox {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

function overlaps(a: LabelBox, b: LabelBox): boolean {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

function visibleLabelIds(
  nodes: LabelCandidate[],
  view: Viewport,
  size: Size,
  selectedId: string | null,
): Set<string> {
  const scale = Math.max(0.05, view.k || 1);
  const maxLabels = scale < 0.55 ? 14 : scale < 0.9 ? 24 : scale < 1.4 ? 40 : 70;
  const boxes: LabelBox[] = [];
  const visible = new Set<string>();

  const ordered = [...nodes].sort((a, b) => {
    if (a.id === selectedId) return -1;
    if (b.id === selectedId) return 1;
    return b.degree - a.degree || a.name.localeCompare(b.name);
  });

  for (const node of ordered) {
    if (visible.size >= maxLabels && node.id !== selectedId) break;
    const x = view.x + node.x * scale;
    const y = view.y + node.y * scale + 14;
    const width = Math.max(24, node.name.length * 7);
    const box: LabelBox = {
      left: x - width / 2,
      right: x + width / 2,
      top: y - 7,
      bottom: y + 7,
    };
    const inView = box.right >= 0 && box.left <= size.w && box.bottom >= 0 && box.top <= size.h;
    if (!inView && node.id !== selectedId) continue;
    if (node.id !== selectedId && boxes.some((placed) => overlaps(box, placed))) continue;
    boxes.push(box);
    visible.add(node.id);
  }
  return visible;
}

/* ---------- 물리 한 스텝 ---------- */

function tick(
  nodes: SimNode[],
  edges: SimEdge[],
  index: Map<string, SimNode>,
  size: Size,
  alpha: number,
): void {
  /* 반발 — O(n²). limit 200 스코프에서는 이것으로 충분하고, 근사(quadtree)를
     넣으면 배치가 미묘하게 달라져 좌표 안정성을 다시 검증해야 한다. */
  for (let i = 0; i < nodes.length; i += 1) {
    for (let j = i + 1; j < nodes.length; j += 1) {
      const a = nodes[i];
      const b = nodes[j];
      let dx = b.x - a.x;
      let dy = b.y - a.y;
      let d2 = dx * dx + dy * dy;
      if (d2 < 1) {
        /* 완전히 겹친 두 점은 힘의 방향이 없다 — 무작위로 떼어 놓는다. */
        dx = Math.random() - 0.5;
        dy = Math.random() - 0.5;
        d2 = 1;
      }
      if (d2 > REPULSION_CUTOFF) continue;
      const d = Math.sqrt(d2);
      const f = REPULSION / d2;
      a.vx -= (dx / d) * f;
      a.vy -= (dy / d) * f;
      b.vx += (dx / d) * f;
      b.vy += (dy / d) * f;
    }
  }

  /* 엣지 스프링 */
  for (const edge of edges) {
    const s = index.get(edge.source);
    const t = index.get(edge.target);
    if (!s || !t) continue;
    const ex = t.x - s.x;
    const ey = t.y - s.y;
    const ed = Math.hypot(ex, ey) || 1;
    const force = (ed - SPRING_LENGTH) * SPRING_K;
    s.vx += (ex / ed) * force;
    s.vy += (ey / ed) * force;
    t.vx -= (ex / ed) * force;
    t.vy -= (ey / ed) * force;
  }

  /* 중심 중력 + 적분 */
  for (const node of nodes) {
    node.vx += (size.w / 2 - node.x) * GRAVITY;
    node.vy += (size.h / 2 - node.y) * GRAVITY;
    if (node.fx != null && node.fy != null) {
      node.x = node.fx;
      node.y = node.fy;
      node.vx = 0;
      node.vy = 0;
      continue;
    }
    node.vx *= DAMPING;
    node.vy *= DAMPING;
    node.x += node.vx * alpha;
    node.y += node.vy * alpha;
  }
}

/* ========================================================================== */

export default function GraphPage() {
  const [includeProposed, setIncludeProposed] = React.useState(true);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [scene, setScene] = React.useState<{ nodes: SimNode[]; edges: SimEdge[] }>({
    nodes: [],
    edges: [],
  });
  const [legend, setLegend] = React.useState<{ type: string; color: string }[]>([]);
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [expanding, setExpanding] = React.useState(false);
  const [expandError, setExpandError] = React.useState<string | null>(null);

  const [detail, setDetail] = React.useState<EntityDetail | null>(null);
  const [detailLoading, setDetailLoading] = React.useState(false);
  const [detailError, setDetailError] = React.useState<string | null>(null);

  const [query, setQuery] = React.useState("");
  const [hits, setHits] = React.useState<SearchHit[]>([]);
  const [searching, setSearching] = React.useState(false);
  const [searchError, setSearchError] = React.useState<string | null>(null);

  /* 시뮬레이션은 매 프레임 좌표를 바꾼다. 그것을 React 상태로 들고 있으면
     200개 노드가 60fps 로 리렌더된다 — 구조는 상태로, 좌표는 ref + 속성
     직접 쓰기로 나눈다. */
  const svgRef = React.useRef<SVGSVGElement | null>(null);
  const rootRef = React.useRef<SVGGElement | null>(null);
  const nodesRef = React.useRef<SimNode[]>([]);
  const edgesRef = React.useRef<SimEdge[]>([]);
  const indexRef = React.useRef<Map<string, SimNode>>(new Map());
  const degreeRef = React.useRef<Map<string, number>>(new Map());
  const typeColorRef = React.useRef<Map<string, string>>(new Map());
  const nodeElsRef = React.useRef<Map<string, SVGGElement>>(new Map());
  const edgeElsRef = React.useRef<Map<string, SVGLineElement>>(new Map());
  const viewRef = React.useRef<Viewport>({ x: 0, y: 0, k: 1 });
  const alphaRef = React.useRef(0);
  const rafRef = React.useRef<number | null>(null);
  const fitPendingRef = React.useRef(false);
  const selectedIdRef = React.useRef<string | null>(null);
  const dragRef = React.useRef<SimNode | null>(null);
  const panRef = React.useRef<{ px: number; py: number; vx: number; vy: number } | null>(null);
  const downAtRef = React.useRef<{ x: number; y: number } | null>(null);
  const queryRef = React.useRef("");

  selectedIdRef.current = selectedId;
  queryRef.current = query;

  const measure = React.useCallback((): Size => {
    const rect = svgRef.current?.getBoundingClientRect();
    return { w: rect?.width || 900, h: rect?.height || 520 };
  }, []);

  const typeColor = React.useCallback((type: string): string => {
    const known = typeColorRef.current.get(type);
    if (known) return known;
    const next = TYPE_PALETTE[typeColorRef.current.size % TYPE_PALETTE.length];
    typeColorRef.current.set(type, next);
    return next;
  }, []);

  /* ---------- 좌표를 DOM 에 반영 ---------- */

  const position = React.useCallback(() => {
    const root = rootRef.current;
    if (!root) return;
    const view = viewRef.current;
    root.setAttribute("transform", `translate(${view.x},${view.y}) scale(${view.k})`);

    for (const edge of edgesRef.current) {
      const el = edgeElsRef.current.get(edge.id);
      if (!el) continue;
      const s = indexRef.current.get(edge.source);
      const t = indexRef.current.get(edge.target);
      if (!s || !t) continue;
      el.setAttribute("x1", String(s.x));
      el.setAttribute("y1", String(s.y));
      el.setAttribute("x2", String(t.x));
      el.setAttribute("y2", String(t.y));
    }

    const size = measure();
    const selected = selectedIdRef.current;
    const labels = visibleLabelIds(
      nodesRef.current.map((n) => ({
        id: n.id,
        name: n.name,
        x: n.x,
        y: n.y,
        degree: degreeRef.current.get(n.id) ?? 0,
      })),
      view,
      size,
      selected,
    );
    const needle = queryRef.current.trim().toLowerCase();

    for (const node of nodesRef.current) {
      const el = nodeElsRef.current.get(node.id);
      if (!el) continue;
      el.setAttribute("transform", `translate(${node.x},${node.y})`);
      el.classList.toggle("g-selected", selected === node.id);
      /* 검색어가 있으면 일치하지 않는 노드를 가라앉힌다(지우지 않는다 —
         맥락이 사라지면 왜 강조됐는지 알 수 없다). */
      el.classList.toggle("g-dim", Boolean(needle) && !node.name.toLowerCase().includes(needle));
      const label = el.querySelector<SVGTextElement>(".g-label");
      if (label) {
        label.style.fontSize = `${labelFontSize(view.k)}px`;
        label.setAttribute(
          "dy",
          String(nodeRadius(degreeRef.current.get(node.id) ?? 0) + 12 / Math.max(0.05, view.k)),
        );
        label.classList.toggle("g-label-hidden", !labels.has(node.id));
      }
    }
  }, [measure]);

  /* ---------- 화면 맞춤 ---------- */

  const fitToView = React.useCallback(() => {
    const nodes = nodesRef.current;
    if (nodes.length === 0) return;
    /* rect 0 (탭이 숨겨진 상태)에서는 맞출 기준이 없다. */
    if (!svgRef.current || svgRef.current.getBoundingClientRect().width === 0) return;
    const size = measure();
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const n of nodes) {
      if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) continue;
      minX = Math.min(minX, n.x);
      maxX = Math.max(maxX, n.x);
      minY = Math.min(minY, n.y);
      maxY = Math.max(maxY, n.y);
    }
    if (!Number.isFinite(minX) || !Number.isFinite(minY)) return;
    const w = Math.max(maxX - minX, 1);
    const h = Math.max(maxY - minY, 1);
    /* 노드가 서너 개뿐일 때 화면을 꽉 채우겠다고 과확대하면 맥락이 사라진다. */
    const k = Math.min(
      FIT_ZOOM_MAX,
      Math.max(ZOOM_MIN, Math.min((size.w - FIT_PADDING * 2) / w, (size.h - FIT_PADDING * 2) / h)),
    );
    viewRef.current = {
      k,
      x: size.w / 2 - ((minX + maxX) / 2) * k,
      y: size.h / 2 - ((minY + maxY) / 2) * k,
    };
    position();
  }, [measure, position]);

  /* ---------- rAF 루프 ---------- */

  const loop = React.useCallback(() => {
    /* 화면에서 빠지면(폭 0) 좌표가 엉뚱하게 드리프트하므로 루프를 멈춘다. */
    if (!svgRef.current || svgRef.current.getBoundingClientRect().width === 0) {
      rafRef.current = null;
      return;
    }
    if (alphaRef.current > ALPHA_MIN) {
      tick(nodesRef.current, edgesRef.current, indexRef.current, measure(), alphaRef.current);
      alphaRef.current *= ALPHA_DECAY;
      position();
      rafRef.current = requestAnimationFrame(loop);
      return;
    }
    /* 가라앉은 뒤 한 번만 맞춘다. 스프링 길이가 90px 고정이라 캔버스가 크면
       그래프가 가운데 작게 뭉쳐 남는다. */
    if (fitPendingRef.current) {
      fitPendingRef.current = false;
      fitToView();
    }
    rafRef.current = null;
  }, [fitToView, measure, position]);

  const reheat = React.useCallback(
    (alpha: number) => {
      alphaRef.current = Math.max(alphaRef.current, alpha);
      if (rafRef.current == null) rafRef.current = requestAnimationFrame(loop);
    },
    [loop],
  );

  /* ---------- 데이터 병합 ---------- */

  const mergePayload = React.useCallback(
    (payload: GraphPayload, anchor: SimNode | null) => {
      const size = measure();
      const cx = anchor ? anchor.x : size.w / 2;
      const cy = anchor ? anchor.y : size.h / 2;
      /* 확장이면 앵커 근처에 좁게 흩뿌려 "여기서 자라났다"가 보이게 한다. */
      const spread = anchor ? 90 : Math.max(size.w, size.h) * 0.7;

      for (const raw of payload.nodes ?? []) {
        if (indexRef.current.has(raw.id)) continue;
        const node: SimNode = {
          id: raw.id,
          name: raw.name || raw.id.slice(0, 8),
          entityType: raw.entity_type || "?",
          status: raw.status ?? "proposed",
          confidence: raw.confidence ?? null,
          x: cx + (Math.random() - 0.5) * spread,
          y: cy + (Math.random() - 0.5) * spread,
          vx: 0,
          vy: 0,
          fx: null,
          fy: null,
        };
        indexRef.current.set(node.id, node);
        nodesRef.current.push(node);
      }

      const seen = new Set(edgesRef.current.map((e) => e.id));
      for (const raw of payload.edges ?? []) {
        if (seen.has(raw.id)) continue;
        /* traverse 가 limit 로 끊기면 한쪽 끝이 없는 엣지가 올 수 있다. */
        if (!indexRef.current.has(raw.source_id) || !indexRef.current.has(raw.target_id)) continue;
        seen.add(raw.id);
        edgesRef.current.push({
          id: raw.id,
          source: raw.source_id,
          target: raw.target_id,
          relationType: raw.relation_type,
          status: raw.status,
        });
      }

      const degree = new Map<string, number>();
      for (const edge of edgesRef.current) {
        degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
        degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
      }
      degreeRef.current = degree;

      for (const node of nodesRef.current) typeColor(node.entityType);
      setLegend(
        [...typeColorRef.current.entries()].map(([type, color]) => ({ type, color })),
      );
      setScene({ nodes: [...nodesRef.current], edges: [...edgesRef.current] });
    },
    [measure, typeColor],
  );

  /* ---------- 전체 그래프 적재 ---------- */

  const loadGraph = React.useCallback(
    async (proposed: boolean) => {
      setLoading(true);
      setError(null);
      setExpandError(null);
      try {
        const payload = await get<GraphPayload>(
          `/graph?limit=${NODE_LIMIT}&include_proposed=${proposed ? "true" : "false"}`,
        );
        /* 보기 조건이 바뀌면 배치를 처음부터 다시 잡는다. */
        nodesRef.current = [];
        edgesRef.current = [];
        indexRef.current = new Map();
        degreeRef.current = new Map();
        typeColorRef.current = new Map();
        nodeElsRef.current = new Map();
        edgeElsRef.current = new Map();
        viewRef.current = { x: 0, y: 0, k: 1 };
        setSelectedId(null);
        setDetail(null);
        setDetailError(null);
        mergePayload(payload, null);
        fitPendingRef.current = true;
        reheat(1);
      } catch (err) {
        setError(errorText(err));
        setScene({ nodes: [], edges: [] });
        setLegend([]);
      } finally {
        setLoading(false);
      }
    },
    [mergePayload, reheat],
  );

  React.useEffect(() => {
    void loadGraph(includeProposed);
  }, [includeProposed, loadGraph]);

  React.useEffect(
    () => () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    },
    [],
  );

  /* 캔버스 크기가 바뀌면 중력의 중심이 옮겨진다 — 다시 데운다. */
  React.useEffect(() => {
    const svg = svgRef.current;
    if (!svg || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (nodesRef.current.length > 0) reheat(0.25);
    });
    observer.observe(svg);
    return () => observer.disconnect();
  }, [reheat]);

  /* ---------- 상세 ---------- */

  const loadDetail = React.useCallback(async (id: string) => {
    setDetailLoading(true);
    setDetailError(null);
    try {
      /* 자유 탐색용 엔티티 상세는 review 컨텍스트가 그대로 담고 있다
         (엔티티 + 관계 + 출처 + 크리틱 점수). 별도 엔드포인트는 없다. */
      const payload = await get<EntityDetail>(`/entity/${encodeURIComponent(id)}/review`);
      /* HTTP 응답은 시스템 경계다 — 목록 필드가 빠진 응답 하나가 화면 전체를
         내리지 않도록 여기서 한 번만 정규화한다. JSX 안에 옵셔널 체이닝을
         흩뿌리는 대신 경계에서 형태를 보장한다. */
      setDetail({
        ...payload,
        entity: { ...payload.entity, aliases: payload.entity?.aliases ?? [] },
        relations: payload.relations ?? [],
        mentions: payload.mentions ?? [],
        counts: {
          mentions: payload.counts?.mentions ?? 0,
          relations_proposed: payload.counts?.relations_proposed ?? 0,
          relations_verified: payload.counts?.relations_verified ?? 0,
          merge_candidates: payload.counts?.merge_candidates ?? 0,
        },
      });
    } catch (err) {
      setDetail(null);
      setDetailError(errorText(err));
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const select = React.useCallback(
    (id: string | null) => {
      setSelectedId(id);
      selectedIdRef.current = id;
      position();
      if (!id) {
        setDetail(null);
        setDetailError(null);
        return;
      }
      void loadDetail(id);
    },
    [loadDetail, position],
  );

  /* ---------- 이웃 확장 ---------- */

  const expand = React.useCallback(
    async (id: string) => {
      const anchor = indexRef.current.get(id);
      if (!anchor) return;
      setExpanding(true);
      setExpandError(null);
      try {
        const payload = await get<GraphPayload>(
          `/graph/neighbors/${encodeURIComponent(id)}?hops=1&include_proposed=${
            includeProposed ? "true" : "false"
          }`,
        );
        mergePayload(payload, anchor);
        reheat(0.6);
      } catch (err) {
        setExpandError(errorText(err));
      } finally {
        setExpanding(false);
      }
    },
    [includeProposed, mergePayload, reheat],
  );

  /* ---------- 검색 ----------
     서버 이름 검색. 마지막 입력만 반영하도록 세대 번호로 늦게 온 응답을 버린다. */

  const searchSeqRef = React.useRef(0);

  React.useEffect(() => {
    const needle = query.trim();
    if (needle.length === 0) {
      setHits([]);
      setSearching(false);
      setSearchError(null);
      position();
      return;
    }
    const seq = searchSeqRef.current + 1;
    searchSeqRef.current = seq;
    setSearching(true);
    const timer = window.setTimeout(async () => {
      try {
        const payload = await get<SearchPayload>(
          `/search?q=${encodeURIComponent(needle)}&limit=8`,
        );
        if (searchSeqRef.current !== seq) return;
        setHits(payload.results ?? []);
        setSearchError(null);
      } catch (err) {
        if (searchSeqRef.current !== seq) return;
        setHits([]);
        setSearchError(errorText(err));
      } finally {
        if (searchSeqRef.current === seq) setSearching(false);
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query, position]);

  /* 검색어가 바뀌면 강조(가라앉힘)를 즉시 반영한다. */
  React.useEffect(() => {
    position();
  }, [query, scene, position]);

  /** 검색 결과를 고르면: 화면에 있으면 선택, 없으면 이웃을 불러 합친다. */
  const openHit = React.useCallback(
    async (hit: SearchHit) => {
      if (indexRef.current.has(hit.id)) {
        select(hit.id);
        const node = indexRef.current.get(hit.id);
        if (node) {
          const size = measure();
          /* 고른 것을 화면 가운데로 — 목록에서 골랐는데 어디 있는지 못 찾으면
             검색이 제 일을 못한 것이다. */
          viewRef.current = {
            k: viewRef.current.k,
            x: size.w / 2 - node.x * viewRef.current.k,
            y: size.h / 2 - node.y * viewRef.current.k,
          };
          fitPendingRef.current = false;
          position();
        }
        return;
      }
      setExpanding(true);
      setExpandError(null);
      try {
        const payload = await get<GraphPayload>(
          `/graph/neighbors/${encodeURIComponent(hit.id)}?hops=1&include_proposed=${
            includeProposed ? "true" : "false"
          }`,
        );
        mergePayload(payload, null);
        fitPendingRef.current = true;
        reheat(0.8);
        select(hit.id);
      } catch (err) {
        setExpandError(errorText(err));
      } finally {
        setExpanding(false);
      }
    },
    [includeProposed, measure, mergePayload, position, reheat, select],
  );

  /* ---------- 포인터: 팬 / 드래그 / 줌 ---------- */

  const nodeIdFromEvent = (target: EventTarget | null): string | null => {
    if (!(target instanceof Element)) return null;
    return target.closest("g.g-node")?.getAttribute("data-id") ?? null;
  };

  const onPointerDown = (ev: React.PointerEvent<SVGSVGElement>) => {
    downAtRef.current = { x: ev.clientX, y: ev.clientY };
    const id = nodeIdFromEvent(ev.target);
    if (id) {
      const node = indexRef.current.get(id) ?? null;
      dragRef.current = node;
      if (node) {
        node.fx = node.x;
        node.fy = node.y;
      }
    } else {
      panRef.current = {
        px: ev.clientX,
        py: ev.clientY,
        vx: viewRef.current.x,
        vy: viewRef.current.y,
      };
    }
    try {
      ev.currentTarget.setPointerCapture(ev.pointerId);
    } catch {
      /* 캡처 실패는 치명적이지 않다 — 포인터가 캔버스를 벗어나면 끝난다. */
    }
  };

  const onPointerMove = (ev: React.PointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current;
    if (drag) {
      const rect = ev.currentTarget.getBoundingClientRect();
      const view = viewRef.current;
      drag.fx = (ev.clientX - rect.left - view.x) / view.k;
      drag.fy = (ev.clientY - rect.top - view.y) / view.k;
      reheat(0.35);
      return;
    }
    const pan = panRef.current;
    if (!pan) return;
    viewRef.current = {
      k: viewRef.current.k,
      x: pan.vx + (ev.clientX - pan.px),
      y: pan.vy + (ev.clientY - pan.py),
    };
    /* 사용자가 직접 시야를 잡았으면 자동 맞춤을 취소한다 — 배치가 가라앉는
       사이에 화면이 튕겨 나가면 안 된다. */
    fitPendingRef.current = false;
    position();
  };

  const onPointerUp = (ev: React.PointerEvent<SVGSVGElement>) => {
    const from = downAtRef.current;
    /* movementX/Y 는 pointerup 에서 신뢰할 수 없다 — 시작점과의 거리로 본다. */
    const moved = from ? Math.abs(ev.clientX - from.x) + Math.abs(ev.clientY - from.y) : 0;
    const drag = dragRef.current;
    if (drag) {
      const id = drag.id;
      drag.fx = null;
      drag.fy = null;
      dragRef.current = null;
      if (moved < 4) select(id);
    }
    panRef.current = null;
    downAtRef.current = null;
  };

  const onWheel = React.useCallback(
    (ev: WheelEvent) => {
      ev.preventDefault();
      const svg = svgRef.current;
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      const mx = ev.clientX - rect.left;
      const my = ev.clientY - rect.top;
      const view = viewRef.current;
      const k = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, view.k * Math.exp(-ev.deltaY * 0.0015)));
      /* 커서 아래 지점을 고정한 채 스케일 — 그러지 않으면 확대할 때마다
         보고 있던 곳이 화면 밖으로 밀려난다. */
      viewRef.current = {
        k,
        x: mx - ((mx - view.x) / view.k) * k,
        y: my - ((my - view.y) / view.k) * k,
      };
      fitPendingRef.current = false;
      position();
    },
    [position],
  );

  /* 휠은 passive 가 아니어야 preventDefault 가 듣는다 — React 의 onWheel 은
     passive 로 붙으므로 직접 등록한다. */
  React.useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, [onWheel]);

  const onDoubleClick = (ev: React.MouseEvent<SVGSVGElement>) => {
    const id = nodeIdFromEvent(ev.target);
    if (!id) return;
    ev.preventDefault();
    void expand(id);
  };

  /* 포인터와 키보드는 같은 기하(g.g-node)에 묶인다 — 둘이 갈라지면 키보드
     사용자만 다른 화면을 쓰게 된다. */
  const onKeyDown = (ev: React.KeyboardEvent<SVGSVGElement>) => {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    const id = nodeIdFromEvent(ev.target);
    if (!id) return;
    ev.preventDefault();
    select(id);
  };

  const selectedNode = selectedId ? indexRef.current.get(selectedId) ?? null : null;
  const isEmpty = !loading && !error && scene.nodes.length === 0;

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      <style>{GRAPH_CSS}</style>

      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="flex items-center gap-2 text-2xl font-bold">
          <Network className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
          그래프
        </h1>
        <p className="text-xs text-muted-foreground">
          노드를 누르면 상세가 열립니다 · 엔터 또는 스페이스바로 선택 · 두 번 누르면 이웃을 펼칩니다 ·
          승인과 거부는 검토 화면에서 수행합니다
        </p>
      </header>

      {/* ---------- 도구 모음 ---------- */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-60 flex-1">
          <Search
            className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            value={query}
            onChange={(ev) => setQuery(ev.target.value)}
            type="search"
            placeholder="이름으로 개념 검색…"
            aria-label="개념 이름 검색"
            autoComplete="off"
            className="pl-9"
          />
          {searching ? (
            <Loader2
              className="absolute top-1/2 right-3 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground"
              aria-hidden="true"
            />
          ) : null}

          {/* 검색 결과 — 고르면 화면으로 데려간다 */}
          {query.trim() && (hits.length > 0 || searchError || (!searching && hits.length === 0)) ? (
            <div className="absolute top-full left-0 z-20 mt-1 w-full overflow-hidden rounded-md border bg-popover">
              {searchError ? (
                <p className="px-3 py-2 text-xs text-destructive">{searchError}</p>
              ) : hits.length === 0 ? (
                <p className="px-3 py-2 text-xs text-muted-foreground">
                  일치하는 개념이 없습니다.
                </p>
              ) : (
                <ScrollArea className="max-h-64">
                  <ul>
                    {hits.map((hit) => (
                      <li key={hit.id}>
                        <button
                          type="button"
                          onClick={() => void openHit(hit)}
                          className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-accent"
                        >
                          <span className="truncate">{hit.name}</span>
                          <span className="flex shrink-0 items-center gap-1.5">
                            <span className="text-xs text-muted-foreground">{hit.entity_type}</span>
                            <Badge variant={statusVariant(hit.status)}>{statusKo(hit.status)}</Badge>
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </ScrollArea>
              )}
            </div>
          ) : null}
        </div>

        <Button
          type="button"
          variant={includeProposed ? "secondary" : "outline"}
          size="sm"
          onClick={() => setIncludeProposed((prev) => !prev)}
          aria-pressed={includeProposed}
        >
          {includeProposed ? (
            <Eye className="h-4 w-4" aria-hidden="true" />
          ) : (
            <EyeOff className="h-4 w-4" aria-hidden="true" />
          )}
          {includeProposed ? "제안 포함" : "승인된 것만"}
        </Button>

        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void loadGraph(includeProposed)}
          disabled={loading}
        >
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} aria-hidden="true" />
          새로고침
        </Button>

        <Button type="button" variant="outline" size="sm" onClick={fitToView} disabled={isEmpty}>
          <Crosshair className="h-4 w-4" aria-hidden="true" />
          화면에 맞춤
        </Button>

        <span className="text-xs text-muted-foreground tabular-nums">
          노드 {scene.nodes.length} · 관계 {scene.edges.length}
        </span>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" aria-hidden="true" />
          <AlertTitle>그래프를 불러오지 못했습니다</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-3">
            <span>{error}</span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void loadGraph(includeProposed)}
            >
              다시 시도
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      {expandError ? (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" aria-hidden="true" />
          <AlertTitle>이웃을 펼치지 못했습니다</AlertTitle>
          <AlertDescription>{expandError}</AlertDescription>
        </Alert>
      ) : null}

      {/* ---------- 캔버스 + 상세 ---------- */}
      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="relative min-h-[420px] overflow-hidden rounded-lg border bg-card">
          {loading ? (
            <div className="absolute inset-0 grid place-items-center gap-3 p-6">
              <div className="flex w-full max-w-sm flex-col items-center gap-3">
                <Skeleton className="h-32 w-32 rounded-full" />
                <Skeleton className="h-3 w-40" />
                <Skeleton className="h-3 w-28" />
                <p className="text-xs text-muted-foreground">그래프를 불러옵니다…</p>
              </div>
            </div>
          ) : null}

          {isEmpty ? (
            <div className="absolute inset-0 grid place-items-center p-6">
              <div className="flex max-w-sm flex-col items-center gap-2 text-center">
                <Share2 className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
                <p className="text-md font-semibold">표시할 그래프가 없습니다</p>
                <p className="text-sm text-muted-foreground">
                  {includeProposed
                    ? "리서치를 실행하면 제안 노드가 만들어집니다."
                    : "승인된 개념이 아직 없습니다. 제안을 포함해 보거나 검토 화면에서 승인합니다."}
                </p>
                {!includeProposed ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setIncludeProposed(true)}
                  >
                    <Eye className="h-4 w-4" aria-hidden="true" />
                    제안 포함해 보기
                  </Button>
                ) : null}
              </div>
            </div>
          ) : null}

          <svg
            ref={svgRef}
            className="g-canvas block h-full w-full"
            role="group"
            aria-label="지식그래프 탐색 화면"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onDoubleClick={onDoubleClick}
            onKeyDown={onKeyDown}
          >
            <g ref={rootRef}>
              <g>
                {scene.edges.map((edge) => (
                  <line
                    key={edge.id}
                    ref={(el) => {
                      if (el) edgeElsRef.current.set(edge.id, el);
                      else edgeElsRef.current.delete(edge.id);
                    }}
                    className={cn("g-edge", edge.status === "verified" && "g-edge-verified")}
                  >
                    <title>{`${edge.relationType} (${statusKo(edge.status)})`}</title>
                  </line>
                ))}
              </g>
              <g>
                {scene.nodes.map((node) => {
                  const degree = degreeRef.current.get(node.id) ?? 0;
                  const r = nodeRadius(degree);
                  return (
                    <g
                      key={node.id}
                      ref={(el) => {
                        if (el) nodeElsRef.current.set(node.id, el);
                        else nodeElsRef.current.delete(node.id);
                      }}
                      data-id={node.id}
                      className={cn(
                        "g-node",
                        node.status === "verified" ? "g-verified" : "g-proposed",
                      )}
                      role="button"
                      tabIndex={0}
                      aria-label={`${node.name} · ${node.entityType} · ${statusKo(node.status)} · 연결 ${degree}개`}
                    >
                      <title>{`${node.name} · ${node.entityType} · ${statusKo(node.status)}`}</title>
                      {/* 포인터와 키보드가 같은 히트 타겟을 공유한다 */}
                      <circle className="g-hit-target" r={Math.max(22, r + 8)} />
                      <circle r={r} fill={typeColor(node.entityType)} />
                      <text className="g-label" dy={r + 11}>
                        {node.name}
                      </text>
                    </g>
                  );
                })}
              </g>
            </g>
          </svg>

          {/* 범례 — 두 색 축을 모두 설명해야 화면을 읽을 수 있다 */}
          {!isEmpty && !loading ? (
            <div
              className="pointer-events-none absolute top-3 left-3 flex max-w-[60%] flex-wrap gap-1.5"
              aria-hidden="true"
            >
              {legend.map((item) => (
                <span key={item.type} className="g-chip">
                  <i style={{ background: item.color }} />
                  {item.type}
                </span>
              ))}
              <span className="g-chip">
                <i className="g-chip-proposed" />
                점선 = 검토 대기
              </span>
              <span className="g-chip">
                <i className="g-chip-verified" />
                실선 = 승인됨
              </span>
            </div>
          ) : null}

          {/* 선택한 노드 요약 */}
          {selectedNode ? (
            <Card className="absolute top-3 right-3 w-64">
              <CardHeader className="flex-row items-start justify-between gap-2 space-y-0 p-4">
                <div className="min-w-0">
                  <CardTitle className="truncate text-md">{selectedNode.name}</CardTitle>
                  <CardDescription className="mt-1 text-xs">
                    {selectedNode.entityType} · 연결{" "}
                    {degreeRef.current.get(selectedNode.id) ?? 0}개
                    {selectedNode.confidence == null
                      ? ""
                      : ` · 확신도 ${selectedNode.confidence.toFixed(2)}`}
                  </CardDescription>
                </div>
                <button
                  type="button"
                  onClick={() => select(null)}
                  aria-label="선택 해제"
                  className="shrink-0 rounded-sm text-muted-foreground transition-colors hover:text-foreground"
                >
                  <X className="h-4 w-4" aria-hidden="true" />
                </button>
              </CardHeader>
              <CardContent className="flex flex-wrap items-center gap-2 p-4 pt-0">
                <Badge variant={statusVariant(selectedNode.status)}>
                  {statusKo(selectedNode.status)}
                </Badge>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => void expand(selectedNode.id)}
                  disabled={expanding}
                >
                  {expanding ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <Share2 className="h-4 w-4" aria-hidden="true" />
                  )}
                  이웃 펼치기
                </Button>
              </CardContent>
            </Card>
          ) : null}
        </div>

        {/* ---------- 상세 패널 ---------- */}
        <Card className="flex min-h-0 flex-col overflow-hidden">
          <CardHeader className="p-4">
            <CardTitle className="text-md">개념 상세</CardTitle>
            <CardDescription className="text-xs">
              {selectedId ? "선택한 개념의 출처와 관계입니다." : "노드를 선택하면 표시됩니다."}
            </CardDescription>
          </CardHeader>
          <CardContent className="min-h-0 flex-1 p-0">
            {!selectedId ? (
              <p className="px-4 pb-4 text-sm text-muted-foreground">
                캔버스에서 노드를 누르거나, 위 검색에서 개념을 고릅니다.
              </p>
            ) : detailLoading ? (
              <div className="flex flex-col gap-2 px-4 pb-4">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-5/6" />
                <Skeleton className="h-3 w-2/3" />
              </div>
            ) : detailError ? (
              <div className="px-4 pb-4">
                <Alert variant="destructive">
                  <AlertTriangle className="h-4 w-4" aria-hidden="true" />
                  <AlertTitle>상세를 불러오지 못했습니다</AlertTitle>
                  <AlertDescription className="flex flex-wrap items-center gap-2">
                    <span>{detailError}</span>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => void loadDetail(selectedId)}
                    >
                      다시 시도
                    </Button>
                  </AlertDescription>
                </Alert>
              </div>
            ) : detail ? (
              <ScrollArea className="h-full">
                <div className="flex flex-col gap-4 px-4 pb-4">
                  <div className="flex flex-col gap-1.5">
                    <p className="text-md font-semibold">{detail.entity.name}</p>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge variant="outline">{detail.entity.entity_type}</Badge>
                      <Badge variant={statusVariant(detail.entity.status)}>
                        {statusKo(detail.entity.status)}
                      </Badge>
                      {detail.entity.confidence == null ? null : (
                        <span className="text-xs text-muted-foreground tabular-nums">
                          확신도 {detail.entity.confidence.toFixed(2)}
                        </span>
                      )}
                    </div>
                    <p className="font-mono text-xs text-muted-foreground" title={detail.entity.id}>
                      {detail.entity.id.slice(0, 18)}
                      {detail.entity.id.length > 18 ? "…" : ""}
                    </p>
                  </div>

                  {detail.entity.aliases.length > 0 ? (
                    <section className="flex flex-col gap-1.5">
                      <h2 className="text-label font-semibold tracking-label text-muted-foreground uppercase">
                        다른 이름
                      </h2>
                      <div className="flex flex-wrap gap-1.5">
                        {detail.entity.aliases.map((alias) => (
                          <Badge key={alias} variant="secondary">
                            {alias}
                          </Badge>
                        ))}
                      </div>
                    </section>
                  ) : null}

                  {detail.critic ? (
                    <section className="flex flex-col gap-1.5">
                      <h2 className="text-label font-semibold tracking-label text-muted-foreground uppercase">
                        크리틱 점수 (참고용)
                      </h2>
                      <p className="text-sm tabular-nums">
                        {detail.critic.score.toFixed(2)}
                        <span className="ml-1.5 text-xs text-muted-foreground">
                          {detail.critic.engine}
                        </span>
                      </p>
                      {detail.critic.rationale ? (
                        <p className="text-xs text-muted-foreground">{detail.critic.rationale}</p>
                      ) : null}
                    </section>
                  ) : null}

                  <section className="flex flex-col gap-1.5">
                    <h2 className="text-label font-semibold tracking-label text-muted-foreground uppercase">
                      관계 {detail.relations.length}개 · 승인 {detail.counts.relations_verified} · 대기{" "}
                      {detail.counts.relations_proposed}
                    </h2>
                    {detail.relations.length === 0 ? (
                      <p className="text-sm text-muted-foreground">아직 연결된 관계가 없습니다.</p>
                    ) : (
                      <ul className="flex flex-col gap-1">
                        {detail.relations.map((relation) => (
                          <li key={relation.id}>
                            <button
                              type="button"
                              onClick={() => void openHit({
                                id: relation.other.id,
                                name: relation.other.name,
                                entity_type: "",
                                status: relation.other.status,
                                score: null,
                              })}
                              className="flex w-full flex-col items-start gap-0.5 rounded-sm px-2 py-1.5 text-left transition-colors hover:bg-accent"
                            >
                              <span className="flex w-full items-center gap-1.5">
                                <span className="text-xs text-muted-foreground">
                                  {relation.direction === "out" ? "→" : "←"}
                                </span>
                                <span className="min-w-0 flex-1 truncate text-sm">
                                  {relation.other.name}
                                </span>
                                <span
                                  className={cn(
                                    "h-1.5 w-1.5 shrink-0 rounded-full",
                                    relation.status === "verified" ? "bg-ok" : "bg-warn",
                                  )}
                                  aria-hidden="true"
                                />
                              </span>
                              <span className="pl-5 text-xs text-muted-foreground">
                                {relation.relation_type} · {statusKo(relation.status)}
                              </span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>

                  <section className="flex flex-col gap-1.5">
                    <h2 className="text-label font-semibold tracking-label text-muted-foreground uppercase">
                      출처 {detail.counts.mentions}곳
                    </h2>
                    {detail.mentions.length === 0 ? (
                      <p className="text-sm text-muted-foreground">연결된 출처가 없습니다.</p>
                    ) : (
                      <ul className="flex flex-col gap-2">
                        {detail.mentions.slice(0, 5).map((mention, i) => (
                          <li
                            key={`${mention.source_doc_id}-${i}`}
                            className="border-l-2 pl-2 text-xs"
                          >
                            <p className="font-medium">{mention.doc_title ?? "제목 없음"}</p>
                            <p className="mt-0.5 text-muted-foreground">{mention.excerpt}</p>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                </div>
              </ScrollArea>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------------------
   SVG 전용 규칙. Tailwind 유틸리티로는 표현할 수 없는 것만 남긴다
   (paint-order, stroke-dasharray, focus-visible 상태의 자식 선택자).
   색은 전부 토큰을 참조한다 — 이 블록에 리터럴 색을 적지 말 것.

   주의: circle 의 fill/r 과 g.g-node 의 transform 은 JS 가 속성으로 직접
   쓴다. 여기서 그 셋을 지정하면 타입별 색·차수별 크기·힘기반 배치가 한꺼번에
   죽는다.
   -------------------------------------------------------------------------- */
const GRAPH_CSS = `
.g-canvas { cursor: grab; touch-action: none; user-select: none; }
.g-canvas:active { cursor: grabbing; }

.g-edge {
  stroke: var(--warn);
  stroke-opacity: 0.32;
  stroke-width: 1.4;
  stroke-dasharray: 4 3;
}
.g-edge-verified {
  stroke: var(--ok);
  stroke-opacity: 0.75;
  stroke-dasharray: none;
}

.g-node { cursor: pointer; outline: none; }
.g-node .g-hit-target { fill: transparent; stroke: none; pointer-events: all; }
.g-node:focus-visible .g-hit-target {
  fill: none;
  stroke: var(--ring);
  stroke-width: 2;
}
.g-node circle { stroke: var(--card); stroke-width: 1.5; transition: opacity var(--t-micro) ease; }

/* 확실성 = 선명도. 미검증은 흐린 초안처럼 가라앉고 승인된 것만 또렷하다 —
   검토를 진행할수록 그래프가 실제로 선명해진다. */
.g-node.g-proposed circle {
  stroke: var(--warn);
  stroke-width: 2;
  stroke-dasharray: 3 2;
  opacity: 0.55;
}
.g-node.g-proposed text { fill: var(--ink-draft); }
.g-node.g-verified circle { stroke: var(--ok); stroke-width: 2; opacity: 1; }
.g-node.g-verified text { fill: var(--foreground); }

/* 선택은 상호작용 상태다 — 데이터 상태(링 색·점선)를 덮지 않고 후광만 덧댄다.
   후광은 상호작용 단일 포인트색(--point)이다. --accent 는 이 팔레트에서
   중성 채움면(#353532)이라, 여기에 쓰면 어두운 캔버스에서 후광이 보이지 않는다. */
.g-node.g-selected circle { opacity: 1; filter: drop-shadow(0 0 3px var(--point)); }
.g-node.g-dim { opacity: 0.15; }

/* 라벨은 엣지 위에 얹힌다. 캔버스색 테두리를 글자 뒤에 깔아 선을 끊어 준다. */
.g-node text {
  font-size: var(--fs-label);
  text-anchor: middle;
  pointer-events: none;
  paint-order: stroke;
  stroke: var(--card);
  stroke-width: 3px;
  stroke-linejoin: round;
}
.g-label-hidden { display: none; }

.g-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1, 4px);
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--card);
  font-size: var(--fs-xs);
  color: var(--muted-foreground);
}
.g-chip i { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.g-chip i.g-chip-proposed { background: transparent; border: 1.5px dashed var(--warn); }
.g-chip i.g-chip-verified { background: transparent; border: 1.5px solid var(--ok); }
`;
