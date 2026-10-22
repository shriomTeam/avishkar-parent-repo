import { Muted } from "@clinic/ui";
import { Suspense } from "react";
import { TestStudio } from "../../components/test-studio";
export const metadata = { title: "Test studio" };
export default function Page() {
  return (
    <Suspense fallback={<Muted>Loading test studio…</Muted>}>
      <TestStudio />
    </Suspense>
  );
}
