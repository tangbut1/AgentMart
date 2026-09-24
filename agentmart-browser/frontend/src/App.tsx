import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import BrowserHomePage from "./pages/BrowserHomePage";
import BrowserTaskPage from "./pages/BrowserTaskPage";
import BrowserSettingsPage from "./pages/BrowserSettingsPage";

/**
 * 个人浏览器版（1.0.0-browser）前端。
 *
 * 这个项目只做一件事：在你自己登录的浏览器会话里，于五个平台同台比价。
 * 官方 API 架构版是同仓库的另一个独立项目（agentmart-api/），两边不共享界面。
 */
export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Navigate to="/browser" replace />} />
        <Route path="/browser" element={<BrowserHomePage />} />
        <Route path="/browser/task/:taskId" element={<BrowserTaskPage />} />
        <Route path="/browser/settings" element={<BrowserSettingsPage />} />
        <Route path="*" element={<Navigate to="/browser" replace />} />
      </Route>
    </Routes>
  );
}
