import Link from "next/link";
import { buttonStyles, Muted } from "@clinic/ui";
import { StandalonePage } from "../components/standalone-page";

export default function NotFound() {
  return (
    <StandalonePage title="Page not found">
      <Muted>This page is not part of the workspace.</Muted>
      <Link className={buttonStyles("brand")} href="/voice-receptionist">
        Back to dashboard
      </Link>
    </StandalonePage>
  );
}
