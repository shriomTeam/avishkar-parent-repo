import {
  AudioLines,
  ChartNoAxesCombined,
  Images,
  MessageSquareText,
  NotebookPen,
  Sparkles,
  Users,
  Zap,
  type LucideIcon,
} from "lucide-react";

// Presentation only: entitlements and routes always come from /me.
const products: Record<
  string,
  { title: string; description: string; icon: LucideIcon }
> = {
  blueprints: {
    title: "Patient Blueprints",
    description: "Understand your highest-value patient profiles.",
    icon: Users,
  },
  reactivation: {
    title: "Dormant Revenue Finder",
    description: "Find patients ready to reconnect with your clinic.",
    icon: Sparkles,
  },
  voice_receptionist: {
    title: "Voice Receptionist",
    description: "Manage voice agents, calls and conversations.",
    icon: AudioLines,
  },
  command_center: {
    title: "The Command Center",
    description: "Revenue, performance and forecasting.",
    icon: ChartNoAxesCombined,
  },
  lead_response: {
    title: "The 60-Second Response System",
    description: "Follow up with new leads, faster.",
    icon: Zap,
  },
  reviews: {
    title: "The 5-Star Machine",
    description: "Turn happy visits into trusted reviews.",
    icon: MessageSquareText,
  },
  scribe: {
    title: "The Chart-While-You-Talk System",
    description: "Visit notes, ready for provider review.",
    icon: NotebookPen,
  },
  photos: {
    title: "Before/After Photo Pipeline",
    description: "Organize consent-based patient photos.",
    icon: Images,
  },
};
export function featurePresentation(feature: {
  key: string;
  name: string;
  description: string;
}) {
  return (
    products[feature.key] ?? {
      title: feature.name,
      description: feature.description,
      icon: Sparkles,
    }
  );
}
