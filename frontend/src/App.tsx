import { useEffect } from "react";
import Sidebar from "./components/Sidebar";
import ChatPanel from "./components/ChatPanel";
import RightPanel from "./components/RightPanel";
import BacktestList from "./components/BacktestList";
import BacktestDetail from "./components/BacktestDetail";
import { useStore } from "./store";

export default function App() {
  const init = useStore((s) => s.init);
  const view = useStore((s) => s.view);
  useEffect(() => {
    void init();
  }, [init]);

  return (
    <div className="flex h-screen w-full overflow-hidden bg-paper font-sans text-ink antialiased">
      <Sidebar />
      {/*
        中间工作区 + 右栏：relative 容器让右栏展开时能 absolute 浮在 ChatPanel 之上，
        不再挤压主排版（design.md §7：右栏为浮层）。
      */}
      <div className="relative flex min-w-0 flex-1 overflow-hidden">
        {view === "chat" && (
          <>
            <ChatPanel />
            <RightPanel />
          </>
        )}
        {view === "backtest-list" && <BacktestList />}
        {view === "backtest-detail" && <BacktestDetail />}
      </div>
    </div>
  );
}
