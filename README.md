# iTutor — Backend

Django REST API for iTutor, an adaptive learning platform. Students take
quizzes on course topics, the system tracks per-topic mastery and generates
recommendations, and a RAG-based chatbot answers questions using the actual
course material an admin uploaded — not just whatever the model happens to
know.

The frontend that consumes this API lives in a separate repository
(`itutor-frontend`).

## What it does

- **Auth** — email-based login with JWT access/refresh tokens, and a
  student/admin role split.
- **Learning** — courses, topics, lessons, quizzes and questions, plus
  attempt submission and automatic scoring.
- **AI quiz generation** — an admin can generate a quiz for a topic from
  the topic's own uploaded material via the Groq API.
- **Mastery tracking** — after each attempt, the student's profile for that
  topic is recalculated into weak / average / strong, with recommendations
  logged and an analytics overview endpoint.
- **RAG chatbot** — questions are answered from retrieved course chunks,
  with conversational memory so follow-ups like "give an example of that"
  resolve correctly.

## Tech stack

| Concern | Choice |
|---|---|
| Language | Python 3.13 |
| Framework | Django 6.0 + Django REST Framework 3.17 |
| Database | PostgreSQL with the **pgvector** extension |
| Auth | `djangorestframework-simplejwt` (JWT) |
| Embeddings | `sentence-transformers`, `all-MiniLM-L6-v2`, 384-dim, runs locally |
| LLM | Groq API (`openai/gpt-oss-120b` by default) |
| Doc parsing | `pdfplumber` (PDF), `python-docx` (DOCX) |
| Tests | pytest + pytest-django + pytest-mock |

## Project layout

```
itutor/settings/       Split settings: base.py + development.py + production.py
accounts/              Custom User model (email login, role), register/login/me
learning/              Course, Topic, Lesson, Quiz, Question, Attempt + scoring
mastery/               StudentProfile, Recommendation, analytics
chatbot/               RAG pipeline, document upload/parsing, chat history
conftest.py            Shared pytest fixtures, auto-loaded by every test
```

Settings are split rather than one `settings.py` with `if DEBUG` branches.
`base.py` holds what every environment shares; `development.py` and
`production.py` set `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` and JWT lifetimes
explicitly, so a production deploy can't silently inherit a dev-only value.
Select one with `DJANGO_SETTINGS_MODULE`.

## Prerequisites

- **Python 3.13**
- **PostgreSQL** with the pgvector extension available. `chatbot.DocumentChunk.embedding`
  is a `vector(384)` column, so `migrate` fails outright on a plain Postgres
  install. On Debian/Ubuntu that's `postgresql-16-pgvector`; on macOS,
  `brew install pgvector`; on Windows, use the installer from the
  [pgvector releases](https://github.com/pgvector/pgvector) or run Postgres
  via the `pgvector/pgvector` Docker image.
- A **Groq API key** — free at [console.groq.com/keys](https://console.groq.com/keys).

## Setup

**1. Create and activate a virtual environment**

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

This pulls in `torch` as a transitive dependency of sentence-transformers.
It is roughly 2.5 GB, so expect the first install to take a while.

**3. Configure environment variables**

```bash
cp .env.example .env
```

Then fill in `.env`. Every variable is documented in `.env.example`; the
ones without defaults are `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `GROQ_API_KEY`
and `SECRET_KEY`. Generate a secret key with:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

`.env` is gitignored and must never be committed.

**4. Create the database and enable pgvector**

```sql
CREATE DATABASE itutor;
\c itutor
CREATE EXTENSION IF NOT EXISTS vector;
```

The `CREATE EXTENSION` step is per-database, not per-server, and it must
run before `migrate`. Skipping it produces a `type "vector" does not exist`
error.

**5. Run migrations and create an admin**

```bash
python manage.py migrate
python manage.py createsuperuser
```

`createsuperuser` prompts for email, username and full name, because
`USERNAME_FIELD` is `email` while `username` and `full_name` remain
required.

**6. Start the server**

```bash
python manage.py runserver
```

The API is then at `http://127.0.0.1:8000/`, and the Django admin at
`/admin/`. `DJANGO_SETTINGS_MODULE` defaults to
`itutor.settings.development` via `manage.py` and `pytest.ini`.

## API reference

All routes are prefixed with `/api/`. Everything except register, login and
refresh requires an `Authorization: Bearer <access_token>` header.

### Auth — `/api/auth/`

| Method | Path | Purpose |
|---|---|---|
| POST | `register/` | Create an account (defaults to the `student` role) |
| POST | `login/` | Exchange email + password for an access/refresh token pair |
| POST | `refresh/` | Get a new access token from a refresh token |
| GET | `me/` | The authenticated user's own profile |

### Learning — `/api/learning/`

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `courses/` | List or create courses |
| GET/POST | `topics/` | List or create topics |
| GET/POST | `lessons/` | List or create lessons |
| GET/POST | `quizzes/` | List or create quizzes |
| GET/POST | `questions/` | List or create questions |
| POST | `quizzes/generate/` | Generate a quiz for a topic with the LLM (admin) |
| POST | `quizzes/<quiz_id>/submit/` | Submit answers, get a score, trigger mastery recalculation |
| GET | `attempts/mine/` | The authenticated student's attempt history |

The two literal paths are registered *before* the router include, because
the router's `quizzes/<pk>/` pattern would otherwise match `generate` as a
quiz ID — Django resolves patterns top to bottom.

### Mastery — `/api/mastery/`

| Method | Path | Purpose |
|---|---|---|
| GET | `profiles/mine/` | Per-topic mastery levels (weak / average / strong) |
| GET | `recommendations/mine/` | Logged study recommendations with reasons |
| GET | `analytics/overview/` | Aggregate progress summary for dashboards |

### Chatbot — `/api/chatbot/`

| Method | Path | Purpose |
|---|---|---|
| POST | `ask/` | Ask a question; answered from retrieved course material |
| GET | `history/` | The student's chat history, segmented by topic |
| GET/POST | `documents/` | List or upload course documents (PDF/DOCX/TXT/MD) |

`ask/` accepts `{"question": "...", "topic": <topic_id or null>}`. It is
throttled separately at **10 requests/minute** via a `chatbot` scope,
because it's the only endpoint that costs money per call. Everything else
falls under the global 120/min authenticated and 20/min anonymous limits.

## How the RAG pipeline works

1. **Upload** — an admin posts a document to `/api/chatbot/documents/`, or
   types `raw_text` directly. `document_parsing.py` extracts plain text
   based on file extension.
2. **Chunk** — `chunk_text()` splits on paragraph breaks, then subdivides
   any paragraph longer than 150 words.
3. **Embed** — each chunk goes through `all-MiniLM-L6-v2` into a
   384-dimensional vector stored in a pgvector column. The model is loaded
   lazily once per process, not per request, since loading costs 1–2 seconds.
4. **Retrieve** — the question is embedded and compared by cosine distance,
   taking the top 3 matches, then discarding anything above
   `RELEVANCE_THRESHOLD = 0.7`. That filter matters: pgvector always returns
   *something*, so without a cutoff the LLM gets fed the closest member of
   an irrelevant set.
5. **Answer** — `build_system_prompt(chunks)` produces a system message
   that either restricts the model to the retrieved context or, when
   nothing relevant was found, explicitly permits general knowledge. Recent
   turns are replayed between that system message and the current question.

Retrieval keys off the latest question only, while conversational memory
comes from replayed turns — so follow-ups work without a vague pronoun
("that", "it") polluting the vector search.

Chat history is scoped to student + topic and capped at
`CHAT_HISTORY_LIMIT = 8` messages, taken newest-first for trimming and then
flipped to chronological order for the API.

### When Groq retires a model

Groq periodically decommissions hosted models, and every LLM call then
fails with a 404 `model_not_found`. This already happened once with
`llama-3.3-70b-versatile`. The model ID is therefore read from the
environment:

```env
GROQ_MODEL=openai/gpt-oss-120b
```

Any replacement must support `response_format={"type": "json_object"}`,
since quiz generation depends on guaranteed-valid JSON. Recovery is a
one-line `.env` change, not a code change and redeploy.

## Testing

```bash
pytest                            # whole suite
pytest chatbot                    # one app
pytest -k build_system_prompt     # one test by name
```

`pytest.ini` sets `DJANGO_SETTINGS_MODULE` and `--reuse-db`, so the test
database persists between runs. Add `--create-db` after a migration change
to force a rebuild. The test database also needs pgvector, which it
inherits from the template database on the same server.

Groq calls and embedding generation are mocked with `pytest-mock`, so the
suite needs no API key and makes no network requests. Shared fixtures
(`api_client`, `student_user`, `admin_user`, `authenticated_client`,
`admin_client`, `topic`, `quiz_with_questions`) live in `conftest.py` and
are available without importing.

## Security notes

- `.env` is gitignored, and `.env.example` documents the required keys with
  no values.
- `media/` is gitignored. Uploaded course material is often copyrighted and
  belongs in object storage (S3 or similar) in production, not the repo.
- The Postman collections at the repo root are gitignored, because they
  export with real bearer tokens and passwords baked into their variable
  blocks. Sanitise before sharing one deliberately.
- `production.py` has no fallback for `SECRET_KEY` — the app refuses to
  start rather than run with a weak key. It also forces HTTPS redirects,
  secure cookies, HSTS, and short-lived (15-minute) access tokens with
  refresh rotation and blacklisting.

## Deploying

Set `DJANGO_SETTINGS_MODULE=itutor.settings.production` and provide
`SECRET_KEY`, the `DB_*` values, `GROQ_API_KEY`, `ALLOWED_HOSTS` and
`CORS_ALLOWED_ORIGINS` (the last two comma-separated) in the environment.
Then:

```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

Production settings assume a reverse proxy terminating SSL and forwarding
the `X-Forwarded-Proto` header.
