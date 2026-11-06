import { Link, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { EmptyState } from "./components/ui";
import { EvaluationDetail, EvaluationList, EvaluationRuns } from "./pages/Evaluation";
import History from "./pages/History";
import NewReview from "./pages/NewReview";
import Performance from "./pages/Performance";
import ReviewDetail from "./pages/ReviewDetail";

function NotFound() {
  return (
    <EmptyState title="Page not found">
      <Link to="/" className="text-accent-ink underline">
        Go to the dashboard
      </Link>
    </EmptyState>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<NewReview />} />
        <Route path="reviews" element={<History />} />
        <Route path="reviews/:id" element={<ReviewDetail />} />
        <Route path="performance" element={<Performance />} />
        <Route path="evaluation" element={<EvaluationList />} />
        <Route path="evaluation/runs" element={<EvaluationRuns />} />
        <Route path="evaluation/:name" element={<EvaluationDetail />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
