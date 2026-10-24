import { api, requireFeature } from "@clinic/core/web/api";
import {
  Button,
  DataTable,
  H2,
  H3,
  Input,
  Muted,
  NativeSelect,
  PageHeading,
  Panel,
  StatCard,
  StatusBadge,
  Td,
  TextField,
  Th,
  Tr,
} from "@clinic/ui";

import { activateReviewCampaign, createReviewCampaign, resolveFollowUp, saveGoogleProfile } from "../actions";

export const metadata = { title: "Reviews" };
export const dynamic = "force-dynamic";

const steps = [
  {
    title: "We ask for a rating",
    body: "When an appointment is completed, the campaign texts or emails the patient a link.",
  },
  {
    title: "They rate the visit here",
    body: "They choose 1 to 5 stars and can add a comment. That rating stays on Avishkar.",
  },
  {
    title: "Only 4 and 5 stars see Google",
    body: "Those patients get a button to your Google review link. A lower rating stops there and becomes a follow-up.",
  },
];

export default async function ReviewsPage() {
  await requireFeature("reviews");
  const { client } = await api();
  const { data } = await client.GET("/features/reviews/overview");
  if (!data) throw new Error("Failed to load reviews");

  const scheduled = data.campaigns.reduce((n, c) => n + (c.stats.by_status.scheduled ?? 0), 0);
  const ratings = data.campaigns.reduce((n, c) => n + c.stats.ratings_submitted, 0);
  const requests = data.campaigns.reduce((n, c) => n + c.stats.requests, 0);
  const connected = data.integration.status === "connected";

  return (
    <>
      <PageHeading
        title="Reviews"
        description="After a completed visit, patients rate the practice on Avishkar. Only 4 and 5 star ratings are invited to Google."
      />

      <div className="mb-[22px] grid grid-cols-3 gap-[18px] max-[1100px]:grid-cols-1">
        <StatCard
          highlight
          label="Google review link"
          value={connected ? "Ready" : "Missing"}
          hint={connected ? "Happy patients can be sent to Google" : "Add the link below before requests go out"}
        />
        <StatCard label="Waiting to send" value={String(scheduled)} hint={`${requests} already sent to patients`} />
        <StatCard label="Ratings received" value={String(ratings)} hint="Submitted on this page, not on Google" />
      </div>

      <Panel className="mb-[22px]">
        <div className="mb-5">
          <H2>What the patient goes through</H2>
        </div>
        <div className="grid grid-cols-3 gap-3.5 max-[1100px]:grid-cols-1">
          {steps.map((step, index) => (
            <article key={step.title} className="min-w-0 rounded-xl bg-[#f7faf5] p-4">
              <div className="mb-3 inline-flex size-7 items-center justify-center rounded-lg bg-brand text-[13px] font-bold text-ink">
                {index + 1}
              </div>
              <H3>{step.title}</H3>
              <Muted flush>{step.body}</Muted>
            </article>
          ))}
        </div>
      </Panel>

      <Panel className="mb-[22px]" id="google">
        <div className="mb-5">
          <H2>Google review link</H2>
          <Muted>This is the page happy patients open. It is not shown to anyone who rates 1, 2, or 3 stars.</Muted>
        </div>
        <form action={saveGoogleProfile}>
          <div className="mb-4 grid grid-cols-2 gap-x-[18px] max-[1100px]:grid-cols-1">
            <TextField flush label="Listing name" name="listing_name" required defaultValue={data.integration.listing_name ?? ""} />
            <TextField
              flush
              label="Review link"
              name="review_url"
              type="url"
              required
              placeholder="https://g.page/r/…/review"
              defaultValue={data.integration.google_review_url ?? ""}
            />
          </div>
          <Button variant="brand" type="submit">
            Save link
          </Button>
        </form>
      </Panel>

      <Panel className="mb-[22px]" id="campaigns">
        <div className="mb-5">
          <H2>When the request is sent</H2>
          <Muted>
            A completed appointment schedules one message. Delay is how many minutes we wait before texting or emailing the
            patient.
          </Muted>
        </div>
        <form action={createReviewCampaign} className="mb-[18px] flex flex-wrap items-end gap-2.5">
          <div>
            <label htmlFor="delay_minutes" className="mb-2 block text-[12px] font-medium text-muted">
              Delay (minutes)
            </label>
            <div className="w-28">
              <Input id="delay_minutes" name="delay_minutes" type="number" min={0} defaultValue={120} />
            </div>
          </div>
          <div>
            <label htmlFor="channel" className="mb-2 block text-[12px] font-medium text-muted">
              Channel
            </label>
            <NativeSelect id="channel" name="channel" inline className="max-w-[7.5rem] [field-sizing:content]">
              <option value="sms">SMS</option>
              <option value="email">Email</option>
            </NativeSelect>
          </div>
          <Button variant="outline" type="submit">
            Create draft
          </Button>
        </form>
        {data.campaigns.length === 0 ? (
          <Muted>No campaigns yet.</Muted>
        ) : (
          <DataTable>
            <thead>
              <tr>
                <Th>Name</Th>
                <Th>Status</Th>
                <Th>Delay</Th>
                <Th>Sent</Th>
                <Th>Ratings</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {data.campaigns.map((campaign) => (
                <Tr key={campaign.id}>
                  <Td>{campaign.name}</Td>
                  <Td>
                    <StatusBadge tone={campaign.status === "active" ? "brand" : "muted"}>{campaign.status}</StatusBadge>
                  </Td>
                  <Td>{campaign.delay_minutes} min</Td>
                  <Td>{campaign.stats.requests}</Td>
                  <Td>{campaign.stats.ratings_submitted}</Td>
                  <Td>
                    {campaign.status === "draft" ? (
                      <form action={activateReviewCampaign.bind(null, campaign.id)}>
                        <Button variant="outline" type="submit">
                          Activate
                        </Button>
                      </form>
                    ) : null}
                  </Td>
                </Tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </Panel>

      <Panel id="follow-ups">
        <div className="mb-5">
          <H2>Patients not sent to Google</H2>
          <Muted>Someone on the team should call these patients. They already saw a thank-you. They did not see the Google link.</Muted>
        </div>
        {data.pending_follow_ups.length === 0 ? (
          <Muted>None waiting. A 1, 2, or 3 star rating will show up here.</Muted>
        ) : (
          <DataTable>
            <thead>
              <tr>
                <Th>Rating</Th>
                <Th>Reason</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {data.pending_follow_ups.map((task) => (
                <Tr key={task.id}>
                  <Td>{task.rating}</Td>
                  <Td>{task.reason.replaceAll("_", " ")}</Td>
                  <Td>
                    <form action={resolveFollowUp.bind(null, task.id)}>
                      <Button variant="outline" type="submit">
                        Resolve
                      </Button>
                    </form>
                  </Td>
                </Tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </Panel>
    </>
  );
}
