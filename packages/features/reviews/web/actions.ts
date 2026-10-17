"use server";

import { api } from "@clinic/core/web/api";
import { revalidatePath } from "next/cache";

export async function saveGoogleProfile(formData: FormData) {
  const { client } = await api();
  const { error } = await client.POST("/features/reviews/integration/google", {
    body: {
      listing_name: String(formData.get("listing_name") ?? ""),
      review_url: String(formData.get("review_url") ?? ""),
    },
  });
  if (error) throw new Error("Could not save the Google review link");
  revalidatePath("/reviews");
}

export async function createReviewCampaign(formData: FormData) {
  const { client } = await api();
  const channel = String(formData.get("channel") ?? "sms");
  const { error } = await client.POST("/features/reviews/campaigns", {
    body: {
      name: String(formData.get("name") || "Post Appointment Review"),
      delay_minutes: Number(formData.get("delay_minutes") || 120),
      channels: [channel === "email" ? "email" : "sms"],
      fallback_enabled: true,
      frequency_days: Number(formData.get("frequency_days") || 30),
    },
  });
  if (error) throw new Error("Could not create the campaign");
  revalidatePath("/reviews");
}

export async function activateReviewCampaign(campaignId: string) {
  const { client } = await api();
  const { error } = await client.POST("/features/reviews/campaigns/{campaign_id}/activate", {
    params: { path: { campaign_id: campaignId } },
  });
  if (error) throw new Error("Could not activate the campaign");
  revalidatePath("/reviews");
}

export async function resolveFollowUp(taskId: string) {
  const { client } = await api();
  const { error } = await client.POST("/features/reviews/follow-ups/{task_id}/resolve", {
    params: { path: { task_id: taskId } },
  });
  if (error) throw new Error("Could not resolve the follow-up");
  revalidatePath("/reviews");
}
