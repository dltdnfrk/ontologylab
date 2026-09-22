import { Routes, Route, NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Home, Download, CheckSquare, Package, FolderOpen, Plug, Merge, Users, Network, BookOpen, Cpu, Settings } from "lucide-react";
import HomePage from "@/pages/Home";
import SourcesPage from "@/pages/Sources";
import ReviewPage from "@/pages/Review";
import PacksPage from "@/pages/Packs";
import ArtifactsPage from "@/pages/Artifacts";
import McpPage from "@/pages/Mcp";
import MergePage from "@/pages/Merge";
import CommunitiesPage from "@/pages/Communities";
import GraphPage from "@/pages/Graph";
import OntologyPage from "@/pages/Ontology";
import EnginesPage from "@/pages/Engines";
import SettingsPage from "@/pages/Settings";

const NAV = [
  { to: "/", icon: Home, label: "홈" },
  { to: "/sources", icon: Download, label: "리서치" },
  { to: "/review", icon: CheckSquare, label: "검토" },
  { to: "/packs", icon: Package, label: "팩" },
  { to: "/artifacts", icon: FolderOpen, label: "아티팩트" },
  { to: "/mcp", icon: Plug, label: "연결" },
  { to: "/merge", icon: Merge, label: "병합" },
  { to: "/communities", icon: Users, label: "커뮤니티" },
  { to: "/graph", icon: Network, label: "그래프" },
  { to: "/ontology", icon: BookOpen, label: "온톨로지" },
  { to: "/engines", icon: Cpu, label: "엔진" },
  { to: "/settings", icon: Settings, label: "설정" },
];

export default function App() {
  return (
    <div className="flex h-screen bg-background">
      <nav className="flex w-16 flex-col items-center border-r py-4 gap-1">
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => cn("flex flex-col items-center gap-1 rounded-lg px-2 py-2 text-xs transition-colors", isActive ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:text-foreground")}>
            <Icon className="h-5 w-5" /><span>{label}</span>
          </NavLink>
        ))}
      </nav>
      <main className="flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/packs" element={<PacksPage />} />
          <Route path="/artifacts" element={<ArtifactsPage />} />
          <Route path="/mcp" element={<McpPage />} />
          <Route path="/merge" element={<MergePage />} />
          <Route path="/communities" element={<CommunitiesPage />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/ontology" element={<OntologyPage />} />
          <Route path="/engines" element={<EnginesPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
