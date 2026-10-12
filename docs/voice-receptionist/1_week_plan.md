# Week plan

Two people can reach production on one GCP VM by Oct 16, 2026 if scope stays exactly as the BRD. This board splits the work across five working days, Monday 12 to Friday 16 October.

## Split

This split is a proposal: voice and infra on one person, app and backend on the other. Swap the owners by editing the table.

| Workstream | Owner | Covers |
| --- | --- | --- |
| Voice and infra | @Vishnu | Pipecat agent, Twilio, recordings, speech providers, GCP VM and storage |
| App and backend | Abhinav | Next.js app, FastAPI, database, Google sign-in, dashboard, deploy files |
| Both | Both | Shared interfaces, end-to-end test, production deploy |

## Task board

The first full end-to-end test is on Thursday, so Monday to Wednesday work is built to plug together. Update progress with the Status dropdown.

| ID | Day | Task | Workstream | Status |
| --- | --- | --- | --- | --- |
| 1 | Mon | Agree the interfaces between app and agent (agent config in, call data out) and decide how phone numbers are added | Both | Not started |
| 2 | Mon | Repo skeleton as a modular monolith, Docker Compose with Postgres, database schema | App and backend | Not started |
| 3 | Mon | Google sign-in working end to end | App and backend | Done: local Google login verified; production HTTPS validation pending |
| 4 | Mon | GCP project, VM, firewall, private storage bucket, secrets store | Voice and infra | Not started |
| 5 | Mon | Pipecat bot running in the browser with a fixed prompt | Voice and infra | Not started |
| 6 | Tue | Compare 2-3 speech-to-text and text-to-speech options on the same recorded audio, confirm Gemini on Vertex works, then choose | Voice and infra | Not started |
| 7 | Tue | Twilio number: inbound webhook with signature check, call audio sent to the bot | Voice and infra | Not started |
| 8 | Tue | Bot loads the agent's prompt based on the number called | Voice and infra | Not started |
| 9 | Tue | Agents API and screen: create, edit and list agents with a prompt | App and backend | Not started |
| 10 | Tue | Phone number API and screen: connect a number to an agent | App and backend | Not started |
| 11 | Wed | Collect caller details and save them to the database | Voice and infra | Not started |
| 12 | Wed | Save the transcript and upload the recording to Cloud Storage | Voice and infra | Not started |
| 13 | Wed | Tune turn-taking (VAD, interruptions) on real phone calls | Voice and infra | Not started |
| 14 | Wed | Call history list and detail page with transcript | App and backend | Not started |
| 15 | Wed | Authenticated start-session endpoint and browser call button | App and backend | Not started |
| 16 | Thu | End-to-end run: sign up, create agent, connect number, call, see it in the dashboard; fix bugs | Both | Not started |
| 17 | Thu | 20+ scored test calls for speed, interruptions and data accuracy, with cost per call | Voice and infra | Not started |
| 18 | Thu | Failure handling: LLM timeout and dropped calls | Voice and infra | Not started |
| 19 | Thu | HTTPS reverse proxy, production Compose file, config, no secrets in the repo | App and backend | Not started |
| 20 | Thu | Error logs and a budget alert on the VM | App and backend | Not started |
| 21 | Fri | Deploy to the GCP VM and smoke test with a real phone call | Both | Not started |
| 22 | Fri | Walk the BRD definition of done and fix gaps | Both | Not started |
| 23 | Fri | Short runbook: deploy, restart, where the logs are | Both | Not started |

## If time runs short

There is no spare day, so one slipped task early in the week pushes the Thursday end-to-end test. Decide cuts early, and update the BRD's definition of done to match each one.

**Cut in this order**

1. Browser call button (task 15). Keep the authenticated start endpoint.
2. Scored test calls from 20 down to 10 (task 17).
3. Runbook trimmed to the deploy and restart commands (task 23).

**Never cut:** the Twilio signature check (task 7) and authentication on any start endpoint.

**Dependencies and open items**

- Tasks 8, 9 and 10 need the schema from task 2.
- Tasks 1 and 6 settle two open BRD questions: how phone numbers are added, and which speech providers to use. Tasks 7, 8 and 10 wait on them.
- Start the Twilio, Vertex and GCP account setup today if any of it needs approval. I have not verified how long any of it takes.
- The plan assumes work starts Monday 12 October.