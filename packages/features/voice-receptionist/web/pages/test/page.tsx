import { requireManagement } from "@clinic/core/web/api";
import { Suspense } from "react";
import { TestStudioSkeleton } from "../../components/skeletons";
import { TestStudio } from "../../components/test-studio";
export const metadata = { title: "Test studio" };
export default async function Page() {
  await requireManagement();
  return (
    <Suspense fallback={<TestStudioSkeleton />}>
      <TestStudio />
    </Suspense>
  );
}
