## 3. Technology Stack

### 3.1 Summary

| Layer | Choice | Why |
|---|---|---|
| Frontend | **React 18 + Vite** | Fast build, small bundle, as you requested |
| Routing | React Router | Standard, light |
| Server data | TanStack Query | Caching, fewer loading states, fast navigation |
| Forms | React Hook Form + Zod | Light, fast, strong validation |
| Styling | Tailwind CSS (or plain CSS modules) | Small CSS output, consistent design |
| Charts | Recharts (lazy loaded) | Needed for the pie, bar and area charts in the reference UI |
| Icons | lucide-react | Tree-shaken, only used icons are bundled |
| Dates | dayjs | Very small |
| PWA | vite-plugin-pwa | Installable on phone, no separate app |
| Backend | **Python 3.12, Django 5, Django REST Framework** | Strong transactions, ORM, admin panel, migrations, Excel libraries |
| Auth | SimpleJWT | Short-lived access token plus refresh |
| Filtering | django-filter | List filters |
| Excel | openpyxl (and pandas where useful) | Import/export |
| Database | **PostgreSQL 16** | ACID, exact decimals, row locking, strong reporting queries |
| App server | Gunicorn behind Nginx | Standard production setup |
| Cloud | Frontend on Vercel; backend on AWS (Lightsail/EC2) or Render/Railway; DB on AWS RDS (or Neon/Supabase) | See 3.3 |
| Monitoring | Sentry (errors), UptimeRobot (uptime) | Simple and cheap |

### 3.2 Why not the alternatives
- **Node.js (NestJS/Express):** fine, but you must assemble auth, admin, migrations and validation yourself. Django gives these built in.
- **MongoDB:** billing, stock and commissions are highly relational and need strict consistency. PostgreSQL fits better.
- **Heavy UI kits and animation libraries:** rejected to keep the frontend light.
- **Redux:** not needed. Server data lives in TanStack Query; small UI state uses React state/context.
- **Celery/Redis queues:** not needed for one shop. Imports, backups and reports run as direct requests or scheduled commands.

### 3.3 Hosting notes
- Vercel suits the static React build. It is **not** suited to Django (long-running Python server), so the backend runs on a small server or a managed platform.
- Starting size: one small server (1-2 GB RAM) and a small managed PostgreSQL instance is enough for one shop.
- Managed PostgreSQL gives automated backups and point-in-time recovery.
- Use HTTPS everywhere. The database must not be publicly reachable.
