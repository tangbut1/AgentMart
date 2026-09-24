import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import HomePage from "./pages/HomePage";
import SearchPage from "./pages/SearchPage";
import ProductPage from "./pages/ProductPage";
import ComparePage from "./pages/ComparePage";
import ReviewsPage from "./pages/ReviewsPage";
import SourcesPage from "./pages/SourcesPage";
import BrowserHomePage from "./pages/BrowserHomePage";
import BrowserTaskPage from "./pages/BrowserTaskPage";
import BrowserSettingsPage from "./pages/BrowserSettingsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/product" element={<ProductPage />} />
        <Route path="/compare" element={<ComparePage />} />
        <Route path="/reviews" element={<ReviewsPage />} />
        <Route path="/sources" element={<SourcesPage />} />
        <Route path="/browser" element={<BrowserHomePage />} />
        <Route path="/browser/task/:taskId" element={<BrowserTaskPage />} />
        <Route path="/browser/settings" element={<BrowserSettingsPage />} />
        <Route path="*" element={<HomePage />} />
      </Route>
    </Routes>
  );
}
