# Docker instructions for Stargate Cafe

1. Copy .env.example to .env and edit values (set STARGATE_SECRET_KEY at minimum).

2. Build and run with docker-compose (development/test):

   docker compose up --build -d

3. The app will be accessible at http://localhost:5000

Notes:
- The compose file keeps SQLite as a host-mounted file under ./data for portability.
- For production, use a proper WSGI server behind a reverse proxy and consider moving to Postgres.
