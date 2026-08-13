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

## 5. Connect to issue tracking toolsv (MCP servers)

- Right now a "ticket" is just a string typed into the chat box. Real integration with Jira/GitHub.
- Importing an existing issue as the ticket text (so the Planner sees the
same description and acceptance criteria a human would), and pushing the result back as a PR.

## 6. Automated tests (Agents and content generated)
  - Add tests for the intents (pytest)
  - `LLM-as-judge`: send the output of an agent + rubric to a separate call and score it
  - Schema validation rather than content, if the `Planner` should output a plan with specific steps/files validate that instead of wording
  - Failure middle stream: What would happen if the connection drops? Does the backend still complete the query/job?

## 7. Allucination
Where can each agent allucinate?

  `Intent`: Might misclasify a message because it is a single Haiku call, no tool and no judges

  `Planner`: Might invent a task that is not implied by the `ticket` intent. This can happen because it didnt have any tool either, just "reasoning" over the ticket

  `Coder`: Might exaggerate what the file does. 

  `Reviewer`: Might set "approved" to True for code that does not work, it compiles files but only was set to catch syntax errors. "Does this met the plan" is up to the model to judge.

  ## 8. Token optimization 
  - Modified models (currently 3 models - Haiku, Sonet and Opus) based on the intent 
  - `Cache`: There is a min of tokens to be cached per model. The average conv think for this app is short.
  - `Effort`: Let the user control how many tokens Claude spends when responding. Does more thinking always means better output?

  | Factor | Low Effort | Medium Effort | High Effort | Max Effort |
|---|---|---|---|---|
| Speed | Fastest | Fast | Moderate | Slow |
| Cost per call | Lowest | Low–Moderate | Moderate–High | Highest |
| Best for | Retrieval, formatting, classification | Writing, summarization, light reasoning | Complex reasoning, analysis | Hard math, multi-step logic, research |
| Risk of over-engineering | None | Low | Medium | High |

*Claude can sometimes overthink straightforward problems — generating long reasoning chains that don’t add value and inflating your token bill in the process*
[See: How to Use Effort Levels in Claude to Get Better Results Without Overspending](https://www.mindstudio.ai/blog/claude-effort-levels-better-results-without-overspending)
