# DisruptRadar — Test Credentials

## Admin
- Email: admin@disruptradar.io
- Password: radar1234
- Role: admin

## Auth
- JWT Bearer token returned by /api/auth/login and /api/auth/register (store in Authorization: Bearer <token>)

## Endpoints
- POST /api/auth/register {email,password,name}
- POST /api/auth/login {email,password}
- GET /api/auth/me
- GET /api/workspaces
- POST /api/workspaces {name}
- GET /api/workspaces/{id}/watchlist
- POST /api/workspaces/{id}/watchlist {domain,tags}
- DELETE /api/watchlist/{item_id}
- POST /api/runs/run-now {workspace_id, watchlist_item_id}
- GET /api/workspaces/{id}/dashboard
- GET /api/watchlist/{item_id} , /runs , /snapshots
- GET/PUT /api/workspaces/{id}/settings