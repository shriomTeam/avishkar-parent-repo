import { getMe } from "@clinic/core/web/api";
import { Overview } from "../components/overview";
import { CallHistory } from "../components/calls";
export const metadata = { title: "Overview" };
export default async function Page() {
  const me = await getMe();
  return me?.role === "front_desk" ? <CallHistory /> : <Overview />;
}
