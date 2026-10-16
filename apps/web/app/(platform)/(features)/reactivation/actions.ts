"use server";

import { revalidatePath } from "next/cache";

import { api } from "@/lib/api";

export async function createCampaign() {
  const { client } = await api();
  const name = `Dormant Revenue Finder – ${new Date().toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;
  const { error } = await client.POST("/features/reactivation/campaigns", {
    body: { name },
  });
  if (error) throw new Error("Could not create campaign");
  revalidatePath("/reactivation");
}

export async function launchCampaign(campaignId: string) {
  const { client } = await api();
  const { error } = await client.POST(
    "/features/reactivation/campaigns/{campaign_id}/launch",
    {
      params: { path: { campaign_id: campaignId } },
    },
  );
  if (error) throw new Error("Could not launch campaign");
  revalidatePath("/reactivation");
}
