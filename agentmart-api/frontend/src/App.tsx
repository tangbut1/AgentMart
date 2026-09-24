import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import HomePage from "./pages/HomePage";
import SearchPage from "./pages/SearchPage";
import ProductPage from "./pages/ProductPage";
import ComparePage from "./pages/ComparePage";
import ReviewsPage from "./pages/ReviewsPage";
import SourcesPage from "./pages/SourcesPage";

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
        <Route path="*" element={<HomePage />} />
      </Route>
    </Routes>
  );
}
