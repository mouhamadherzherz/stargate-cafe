# Docker Instructions for Stargate Cafe

## 1. Quick Start

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Generate a secure secret key and set it in `.env`:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

3. Build and run with Docker Compose:
   ```bash
   docker compose up --build -d
   ```

4. Access the application in your browser:
   * **POS & Home:** `http://localhost:5000`
   * **Employee Cashier:** `http://localhost:5000/employee/login`
   * **Admin Login:** `http://localhost:5000/admin_login`

## 2. Architecture & Data Persistence

* **Database:** SQLite is stored inside the mounted `./data` directory on the host (`./data:/opt/stargate/data`), preserving all sales, inventory, and accounting across container restarts without needing a standalone database container.
* **Uploads:** Product images are persisted in `./static/uploads`.
* **Security:** Runs as a non-privileged user (`stargate`) with container healthcheck monitoring enabled.
* **Healthcheck:** Periodically queries `/api/check_update` to verify web server responsiveness.
