# What I'd Do Differently
## 1. Add another agent role

A "Tester" agent, slotted in after the Reviewer approves: it would write and run a small test
(or execute an existing one) against what the Coder produced, rather than relying entirely on the
Reviewer's read-through plus a syntax check. 

## 2. Extend file upload capabilities

- A PDF text extractor, most feature tickets that come with a PDF are a spec or a screenshot
- A proper parser
- Vision-model input for images, so a screenshot of a bug or a mockup can actually inform the
  Planner instead of being a named-but-unread attachment.
- Multiple files per message 

## 3. Add login features

There's currently no auth layer at all — `user_id` is a hardcoded string, and
every visitor shares one pool of conversations.

## 4. Move the database and caches to the cloud

SQLite plus three in-memory Python dicts (`plan_cache`, `ticket_cache`, `conversation_cache`) is
fine for one developer running one process locally, but it's the reason the app can only run as a
single `uvicorn` worker today.

I'd move to a managed Postgres instance for the durable data and Redis
(or similar) for the pending-plan/ticket-history caches.

## 5. Connect to issue tracking tools

Right now a "ticket" is just a string typed into the chat box. Real integration with Jira/GitHub
Issues/Linear would mean: importing an existing issue as the ticket text (so the Planner sees the
same description and acceptance criteria a human would), and pushing the result back

## 6. The user interface

## 7. Automated tests
  None of the above is safe to build
  on without a test suite that at least covers the intent gate's routing and the retry loop's
  exit conditions.
