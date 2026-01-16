---
up:
  - "[[architecture-bionicpro]]"
---
# BionicPRO - Sprint 9 Project Work

## Project Overview

This project implements a secure, scalable architecture for the BionicPRO prosthetics company, addressing:
- **Security**: SSO with PKCE, MFA, LDAP integration, Yandex ID OAuth
- **Reports**: ETL pipeline with Airflow, OLAP storage with ClickHouse
- **Performance**: S3 storage with CDN caching via Nginx
- **Real-time data**: CDC with Debezium, Kafka, and ClickHouse

## Architecture

### Task 1: Security Enhancement

```
User -> Frontend -> bionicpro-auth -> Keycloak
                         |               |
                       Redis        OpenLDAP/Yandex ID
```

**Key Features:**
- PKCE OAuth 2.0 flow (no tokens exposed to frontend)
- Session-based authentication with HTTP-only cookies
- Session rotation to prevent fixation attacks
- MFA with TOTP (Google Authenticator / FreeOTP)
- LDAP user federation for international offices
- Yandex ID Identity Brokering

### Task 2: Reports Service

```
CRM/Telemetry DBs -> Airflow ETL -> ClickHouse -> Reports API -> Frontend
```

**Key Features:**
- Daily ETL pipeline aggregating user data
- Pre-computed datamart for fast queries
- User-specific access control

### Task 3: CDN & Caching

```
Reports API -> MinIO (S3) -> Nginx CDN -> User
```

**Key Features:**
- Reports cached in S3-compatible storage
- Nginx reverse proxy with caching
- Cache invalidation support

### Task 4: CDC Pipeline

```
CRM PostgreSQL -> Debezium -> Kafka -> ClickHouse (KafkaEngine)
```

**Key Features:**
- Real-time change data capture
- Kafka as message broker
- Automatic data sync via MaterializedViews

## Project Structure

```
architecture-bionicpro/
├── bionicpro-auth/          # Auth service (Python/FastAPI)
├── reports-api/             # Reports API (Python/FastAPI)
├── frontend/                # React frontend
├── airflow/                 # ETL Pipeline
├── keycloak/                # Keycloak configuration
├── ldap/                    # OpenLDAP configuration
├── nginx/                   # CDN configuration
├── clickhouse/              # OLAP database
├── debezium/                # CDC configuration
├── db/                      # Database init scripts
├── diagrams/                # Architecture diagrams
├── screenshots/             # Project screenshots
└── docker-compose.yaml      # Full deployment config
```

## Quick Start

### Prerequisites
- Docker & Docker Compose
- 16GB+ RAM recommended

### Start Services

```bash
docker-compose up -d
```

### Access Points

| Service | URL | Credentials |
|---------|-----|-------------|
| Frontend | http://localhost:3000 | - |
| Keycloak Admin | http://localhost:8080 | admin/admin |
| Airflow | http://localhost:8084 | admin/admin |
| MinIO Console | http://localhost:9001 | minioadmin/minioadmin |

### Test Users

| Username | Password | Role |
|----------|----------|------|
| prothetic1 | prothetic123 | prothetic_user |
| prothetic2 | prothetic123 | prothetic_user |

## Screenshots

All screenshots are organized by tasks in the `screenshots/` folder:
- `Task1_Security/` - SSO, PKCE, MFA, LDAP, Yandex ID
- `Task2_Reports/` - Airflow DAG, Report UI
- `Task3_S3_CDN/` - MinIO bucket
- `Task4_CDC/` - Debezium connector

## License

Educational project for Yandex Practicum Architecture Course.
