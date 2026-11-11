import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import NewRun from "./pages/NewRun";
import ReferenceData from "./pages/ReferenceData";
import RunDetail from "./pages/RunDetail";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/new" element={<NewRun />} />
        <Route path="/runs/:id" element={<RunDetail />} />
        <Route path="/reference" element={<ReferenceData />} />
        <Route path="/settings" element={<Settings />} />
        <Route
          path="*"
          element={<div className="p-10 text-slate-500">Page not found.</div>}
        />
      </Route>
    </Routes>
  );
}
