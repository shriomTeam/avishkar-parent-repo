import { requireManagement } from "@clinic/core/web/api";
import { Muted } from "@clinic/ui";
import { Suspense } from "react";
import { TestStudio } from "../../components/test-studio";
export const metadata = { title: "Test studio" };
export default async function Page() {
  await requireManagement();
  return (
    <Suspense fallback={<Muted>Loading test studio…</Muted>}>
      <TestStudio />
    </Suspense>
  );
}
