import { Suspense } from "react";
import { TestStudio } from "@/components/voice/test-studio";
export const metadata = { title: "Test studio" };
export default function Page() {
  return (
    <Suspense fallback={<p>Loading test studio…</p>}>
      <TestStudio />
    </Suspense>
  );
}
