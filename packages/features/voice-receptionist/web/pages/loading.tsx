import { PageSkeleton } from "../components/skeletons";

/** Shown by Next while a voice route is being prepared. Each screen then shows its own skeleton while its data loads. */
export default function Loading() {
  return <PageSkeleton />;
}
