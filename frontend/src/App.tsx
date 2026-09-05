import { useEffect } from "react";
import Sidebar from "./components/Sidebar";
import ChatPanel from "./components/ChatPanel";
import RightPanel from "./components/RightPanel";
import BacktestList from "./components/BacktestList";
import BacktestDetail from "./components/BacktestDetail";
import ArenaList from "./components/ArenaList";
import ArenaDetail from "./components/ArenaDetail";
import LiveLogPanel from "./components/LiveLogPanel";
import { useStore } from "./store";

export default function App() {
  const init = useStore((s) => s.init);
  const view = useStore((s) => s.view);
  const liveLogOpen = useStore((s) => s.liveLogOpen);
  useEffect(() => {
    void init();
  }, [init]);

  return (
    <div className="flex h-screen w-full overflow-hidden bg-paper font-sans text-ink antialiased">
      <Sidebar />
      <div className="relative flex min-w-0 flex-1 overflow-hidden">
        {view === "chat" && (
          <>
            <ChatPanel />
            <RightPanel />
          </>
        )}
        {view === "backtest-list" && <BacktestList />}
        {view === "backtest-detail" && <BacktestDetail />}
        {view === "arena-list" && <ArenaList />}
        {view === "arena-detail" && <ArenaDetail />}
        {liveLogOpen && <LiveLogPanel />}
      </div>
    </div>
  );
}
