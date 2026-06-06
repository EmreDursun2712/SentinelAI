# SentinelAI — Frontend

React + TypeScript + Vite dashboard for the SentinelAI backend. The shell is
Tailwind-styled, the data layer is TanStack Query against a typed API service,
and every page is bound to the real backend endpoints documented under
[../docs](../docs).

## Stack

- React 18, TypeScript 5, Vite 5
- Tailwind CSS for styling (no UI kit — primitives live in `src/components/ui/`)
- TanStack Query for data fetching, caching, refetch, and mutations
- React Router for routing (with a single `AppShell` layout route)
- Native WebSocket via `useStream` (used opportunistically; not required for any page)

## Pages

| Path                | What it shows                                                                |
| ------------------- | ---------------------------------------------------------------------------- |
| `/`                 | Dashboard — KPIs, highest-priority alerts, system health, model info          |
| `/alerts`           | Filterable alert list (severity / status / disposition / sort), URL-driven   |
| `/alerts/:id`       | Alert detail — overview, decision chain, response actions, investigation     |
| `/response`         | Response Center — pending approval queue + recent activity                   |
| `/reports`          | Reports — list + viewer (rendered markdown), daily-summary trigger           |
| `/ingestion`        | CSV upload + ingestion job list + replay button                              |

## Run locally

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
# → http://localhost:5173
```

## Folder layout

```
src/
├── main.tsx                 entry: providers (Query, Router)
├── App.tsx                  route table only
├── components/
│   ├── layout/
│   │   ├── AppShell.tsx     sidebar + topbar + <Outlet/>
│   │   ├── Sidebar.tsx      nav with icons
│   │   └── Topbar.tsx       section title + connection pills
│   ├── ui/                  unstyled-but-styled primitives
│   │   ├── Badge.tsx
│   │   ├── Button.tsx
│   │   ├── Card.tsx
│   │   ├── EmptyState.tsx
│   │   ├── ErrorState.tsx
│   │   ├── PageHeader.tsx
│   │   ├── Select.tsx
│   │   ├── Spinner.tsx
│   │   └── Table.tsx
│   ├── ConnectionPill.tsx
│   ├── DispositionPill.tsx
│   ├── SeverityPill.tsx
│   ├── StatusPill.tsx
│   ├── StatCard.tsx
│   └── icons.tsx            inline SVGs (no icon-library dep)
├── lib/
│   ├── api/                 typed service layer per resource
│   │   ├── client.ts        fetch wrapper + ApiError + qs builder
│   │   ├── alerts.ts
│   │   ├── detection.ts
│   │   ├── health.ts
│   │   ├── ingestion.ts
│   │   ├── investigation.ts
│   │   ├── reports.ts
│   │   ├── response.ts
│   │   └── index.ts         barrel re-exports
│   ├── cn.ts                clsx + tailwind-merge wrapper
│   ├── format.ts            date / duration / number formatters
│   ├── types.ts             every backend DTO, hand-mirrored
│   └── ws.ts                useStream() hook
├── pages/                   one component per route
└── styles/globals.css
```

## API service layer

One barrel import, namespaced per resource:

```ts
import { alertsApi, detectionApi, responseApi } from "@/lib/api";

await alertsApi.listAlerts({ severity: "HIGH", sort: "priority" });
await detectionApi.runDetection({ limit: 1000 });
await responseApi.approveResponseAction(7, { analyst_id: "alice" });
```

The low-level `request` / `rootRequest` helpers in
[src/lib/api/client.ts](src/lib/api/client.ts) handle the API base URL,
`x-request-id` header, JSON parsing, and `ApiError` raising. The query string
builder skips `undefined`/`null`/`""` automatically.

## Environment variables

| Variable             | Default                                  | Purpose                                              |
| -------------------- | ---------------------------------------- | ---------------------------------------------------- |
| `VITE_API_BASE_URL`  | `http://localhost:8000/api/v1`           | Versioned API base. The client derives the root.    |
| `VITE_WS_BASE_URL`   | `ws://localhost:8000/api/v1`             | WebSocket base for `useStream()`.                    |

Defined in [.env.example](.env.example); the same names are set by
`docker-compose.yml` for the frontend container.

## Design tokens

- **Dark theme.** Slate-900/950 surfaces, slate-800 borders, emerald-500
  accents for primary actions.
- **Severity palette** (`tailwind.config.ts`): LOW=blue, MEDIUM=amber,
  HIGH=orange, CRITICAL=rose.
- **Density:** small/medium UI — security tools live and die on information
  density, so cards are padded `md` (20 px), tables are tight, fonts are
  small (text-xs/text-sm) by default.

## Patterns

- Pages own their queries with `useQuery({ queryKey: […], refetchInterval })`
  so each route refreshes itself. No global polling loop.
- Mutations call `queryClient.invalidateQueries({ queryKey: ["alert", id] })`
  on success so the affected views refetch.
- Lists use `Card padding="none"` + the `Table` set so they look unified.
- Conditional UI is `isLoading → Spinner` / `isError → ErrorState` /
  `data.length === 0 → EmptyState` / otherwise content. Every list follows
  this contract.
- URL is the source of truth for filterable lists: the Alerts page reads
  `severity`, `status`, `disposition`, `sort` from `useSearchParams`, so
  bookmarks and back-navigation work.

## Demo flow end-to-end

```bash
# Backend up + model loaded (see ../README.md)
docker compose up -d --build
python -m ml.train --synthetic 50000

# Frontend
cd frontend && npm install && npm run dev
# → http://localhost:5173
```

1. **/ingestion** → upload `backend/data/samples/sample_flows.csv` (or click
   "Replay sample CSV"). Watch the jobs table populate.
2. **/** → KPI cards update with alert counts; "Highest-priority alerts"
   shows the new rows; system health pills go green.
3. **/alerts** → filter by `severity=HIGH` and sort by `priority`.
4. **/alerts/:id** → click into one. Use **Run investigation**, then
   **Generate report**, then set a disposition.
5. **/response** → approve or reject a pending action; the alert detail
   refreshes automatically thanks to the invalidation.
6. **/reports** → click "Generate daily summary"; click any report in the
   list to read the rendered markdown.
