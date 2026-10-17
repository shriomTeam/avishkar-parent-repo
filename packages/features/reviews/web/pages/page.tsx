import { api, requireFeature } from "@clinic/core/web/api";

import { activateReviewCampaign, createReviewCampaign, resolveFollowUp, saveGoogleProfile } from "../actions";

export const metadata = { title: "Reviews" };
export const dynamic = "force-dynamic";

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
      <div className="heading">
        <div>
          <h1>Reviews</h1>
          <p>After a completed visit, patients rate the practice on Avishkar. Only 4 and 5 star ratings are invited to Google.</p>
        </div>
      </div>

      <div className="cards">
        <div className="panel metric feature">
          <label>Google review link</label>
          <div className="value">{connected ? "Ready" : "Missing"}</div>
          <small>{connected ? "Happy patients can be sent to Google" : "Add the link below before requests go out"}</small>
        </div>
        <div className="panel metric">
          <label>Waiting to send</label>
          <div className="value">{scheduled}</div>
          <small>{requests} already sent to patients</small>
        </div>
        <div className="panel metric">
          <label>Ratings received</label>
          <div className="value">{ratings}</div>
          <small>Submitted on this page, not on Google</small>
        </div>
      </div>

      <section className="panel">
        <div className="panelHead">
          <h2>What the patient goes through</h2>
        </div>
        <div className="flow">
          <article>
            <div className="step">1</div>
            <h3>We ask for a rating</h3>
            <p>When an appointment is completed, the campaign texts or emails the patient a link.</p>
          </article>
          <article>
            <div className="step">2</div>
            <h3>They rate the visit here</h3>
            <p>They choose 1 to 5 stars and can add a comment. That rating stays on Avishkar.</p>
          </article>
          <article>
            <div className="step">3</div>
            <h3>Only 4 and 5 stars see Google</h3>
            <p>Those patients get a button to your Google review link. A lower rating stops there and becomes a follow-up.</p>
          </article>
        </div>
      </section>

      <section className="panel" id="google">
        <div className="panelHead">
          <div>
            <h2>Google review link</h2>
            <p>This is the page happy patients open. It is not shown to anyone who rates 1, 2, or 3 stars.</p>
          </div>
        </div>
        <form action={saveGoogleProfile}>
          <div className="formgrid">
            <div className="field">
              <label htmlFor="listing_name">Listing name</label>
              <input id="listing_name" name="listing_name" required defaultValue={data.integration.listing_name ?? ""} />
            </div>
            <div className="field">
              <label htmlFor="review_url">Review link</label>
              <input
                id="review_url"
                name="review_url"
                type="url"
                required
                placeholder="https://g.page/r/…/review"
                defaultValue={data.integration.google_review_url ?? ""}
              />
            </div>
          </div>
          <button className="primary" type="submit">
            Save link
          </button>
        </form>
      </section>

      <section className="panel" id="campaigns">
        <div className="panelHead">
          <div>
            <h2>When the request is sent</h2>
            <p>A completed appointment schedules one message. Delay is how many minutes we wait before texting or emailing the patient.</p>
          </div>
        </div>
        <form action={createReviewCampaign} className="inline-form">
            <div className="field">
              <label htmlFor="delay_minutes">Delay (minutes)</label>
              <input id="delay_minutes" name="delay_minutes" type="number" min={0} defaultValue={120} />
            </div>
            <div className="field">
              <label htmlFor="channel">Channel</label>
              <select id="channel" name="channel">
                <option value="sms">SMS</option>
                <option value="email">Email</option>
              </select>
            </div>
            <button type="submit">Create draft</button>
          </form>
        {data.campaigns.length === 0 ? (
          <p>No campaigns yet.</p>
        ) : (
          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th>Delay</th>
                  <th>Sent</th>
                  <th>Ratings</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.campaigns.map((campaign) => (
                  <tr key={campaign.id}>
                    <td>{campaign.name}</td>
                    <td>
                      <span className={campaign.status === "active" ? "badge" : "badge neutral"}>{campaign.status}</span>
                    </td>
                    <td>{campaign.delay_minutes} min</td>
                    <td>{campaign.stats.requests}</td>
                    <td>{campaign.stats.ratings_submitted}</td>
                    <td>
                      {campaign.status === "draft" ? (
                        <form action={activateReviewCampaign.bind(null, campaign.id)}>
                          <button type="submit">Activate</button>
                        </form>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel" id="follow-ups">
        <div className="panelHead">
          <div>
            <h2>Patients not sent to Google</h2>
            <p>Someone on the team should call these patients. They already saw a thank-you. They did not see the Google link.</p>
          </div>
        </div>
        {data.pending_follow_ups.length === 0 ? (
          <p>None waiting. A 1, 2, or 3 star rating will show up here.</p>
        ) : (
          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  <th>Rating</th>
                  <th>Reason</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.pending_follow_ups.map((task) => (
                  <tr key={task.id}>
                    <td>{task.rating}</td>
                    <td>{task.reason.replaceAll("_", " ")}</td>
                    <td>
                      <form action={resolveFollowUp.bind(null, task.id)}>
                        <button type="submit">Resolve</button>
                      </form>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
