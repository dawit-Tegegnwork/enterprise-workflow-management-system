# API examples

```bash
# Login
curl -X POST http://127.0.0.1:8001/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"staff@demo.local","password":"Demo123!"}'

# Create request (use token)
curl -X POST http://127.0.0.1:8001/api/v1/requests \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Synthetic access request","description":"Demo workflow item","department":"Operations"}'

# Approve
curl -X POST http://127.0.0.1:8001/api/v1/requests/{id}/transition \
  -H "Authorization: Bearer $MANAGER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action":"approve","note":"Approved in demo"}'
```
