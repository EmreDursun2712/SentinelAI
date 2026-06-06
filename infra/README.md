# SentinelAI — Infra

Container helpers and one-shot scripts.

```
infra/
├── postgres/init.sql       runs once on first DB container start
└── scripts/wait_for_db.sh  blocks until Postgres is reachable
```

Future home for an optional Nginx reverse-proxy config used in the demo recording.
