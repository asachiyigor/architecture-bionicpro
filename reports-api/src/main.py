"""
BionicPRO Reports API

This service provides:
- User reports from ClickHouse OLAP database
- Access control (users can only access their own reports)
- S3 storage for generated reports
- CDN URL generation for cached reports
"""

import json
from datetime import datetime, timedelta
from typing import Optional
import hashlib

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
from clickhouse_driver import Client as ClickHouseClient
import boto3
from botocore.client import Config
from pydantic import BaseModel
from pydantic_settings import BaseSettings
from jose import jwt


class Settings(BaseSettings):
    # Auth service
    auth_service_url: str = "http://bionicpro-auth:8001"

    # ClickHouse settings
    clickhouse_host: str = "clickhouse"
    clickhouse_port: int = 9000
    clickhouse_database: str = "bionicpro"

    # S3/MinIO settings
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "reports"

    # CDN settings
    cdn_base_url: str = "http://localhost:8082"

    # Frontend URL for CORS
    frontend_url: str = "http://localhost:3000"

    # Keycloak settings for JWT validation
    keycloak_url: str = "http://keycloak:8080"
    keycloak_realm: str = "reports-realm"

    class Config:
        env_file = ".env"


settings = Settings()

app = FastAPI(title="BionicPRO Reports API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_clickhouse_client() -> ClickHouseClient:
    """Create ClickHouse client."""
    return ClickHouseClient(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        database=settings.clickhouse_database
    )


def get_s3_client():
    """Create S3/MinIO client."""
    return boto3.client(
        's3',
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=Config(signature_version='s3v4')
    )


async def get_current_user(request: Request) -> dict:
    """
    Validate session and get user info from bionicpro-auth service.
    Returns user info with user_id extracted from the access token.
    """
    # Forward cookies to auth service
    cookies = request.cookies

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{settings.auth_service_url}/auth/validate",
            cookies=cookies
        )

        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Unauthorized")

        data = response.json()
        access_token = data.get("access_token")

        if not access_token:
            raise HTTPException(status_code=401, detail="No access token")

        # Decode JWT to get user info (without verification - already validated by auth service)
        try:
            # Get public key from Keycloak
            payload = jwt.get_unverified_claims(access_token)
            return {
                "user_id": payload.get("sub"),
                "username": payload.get("preferred_username"),
                "email": payload.get("email"),
                "roles": payload.get("realm_access", {}).get("roles", [])
            }
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")


def get_report_s3_key(user_id: str, report_date: str) -> str:
    """Generate S3 key for report storage."""
    return f"reports/{user_id}/{report_date}/report.json"


def get_report_hash(user_id: str, report_date: str) -> str:
    """Generate hash for report caching."""
    return hashlib.md5(f"{user_id}:{report_date}".encode()).hexdigest()


class ReportRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class ReportResponse(BaseModel):
    user_id: str
    username: str
    report_date: str
    report_url: Optional[str] = None
    data: Optional[dict] = None
    message: Optional[str] = None


@app.get("/reports")
async def get_user_report(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """
    Get report for the authenticated user.
    Users can only access their own reports.

    First checks S3 for cached report, if not found - generates from ClickHouse.
    """
    user_id = user["user_id"]
    username = user["username"]

    # Set default dates if not provided
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    report_key = get_report_s3_key(user_id, end_date)
    s3_client = get_s3_client()

    # Check if report exists in S3
    try:
        s3_client.head_object(Bucket=settings.s3_bucket, Key=report_key)
        # Report exists in S3, return CDN URL
        cdn_url = f"{settings.cdn_base_url}/{report_key}"
        return ReportResponse(
            user_id=user_id,
            username=username,
            report_date=end_date,
            report_url=cdn_url,
            message="Report retrieved from cache"
        )
    except Exception:
        pass  # Report not in S3, will generate

    # Generate report from ClickHouse
    try:
        ch_client = get_clickhouse_client()

        # Query report datamart - user can only see their own data
        # Use username for matching since that's what we have in the datamart
        query = """
            SELECT
                user_id,
                report_date,
                total_usage_hours,
                avg_battery_level,
                total_movements,
                error_count,
                last_sync_date
            FROM reports_datamart
            WHERE username = %(username)s
            AND report_date BETWEEN %(start_date)s AND %(end_date)s
            ORDER BY report_date DESC
        """

        result = ch_client.execute(
            query,
            {
                "username": username,
                "start_date": start_date,
                "end_date": end_date
            }
        )

        # Check if data exists for requested period
        if not result:
            return ReportResponse(
                user_id=user_id,
                username=username,
                report_date=end_date,
                message="No data available for the requested period. Data may not have been processed yet by ETL."
            )

        # Format report data
        report_data = {
            "user_id": user_id,
            "username": username,
            "generated_at": datetime.now().isoformat(),
            "period": {
                "start": start_date,
                "end": end_date
            },
            "summary": {
                "total_days": len(result),
                "total_usage_hours": sum(r[2] for r in result if r[2]),
                "avg_battery_level": sum(r[3] for r in result if r[3]) / len(result) if result else 0,
                "total_movements": sum(r[4] for r in result if r[4]),
                "total_errors": sum(r[5] for r in result if r[5])
            },
            "daily_data": [
                {
                    "date": str(r[1]),
                    "usage_hours": r[2],
                    "battery_level": r[3],
                    "movements": r[4],
                    "errors": r[5]
                }
                for r in result
            ]
        }

        # Store report in S3
        try:
            s3_client.put_object(
                Bucket=settings.s3_bucket,
                Key=report_key,
                Body=json.dumps(report_data),
                ContentType='application/json'
            )
        except Exception as e:
            # Log error but continue - return data even if S3 fails
            print(f"Failed to store report in S3: {e}")

        cdn_url = f"{settings.cdn_base_url}/{report_key}"

        return ReportResponse(
            user_id=user_id,
            username=username,
            report_date=end_date,
            report_url=cdn_url,
            data=report_data,
            message="Report generated successfully"
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {str(e)}")


@app.get("/reports/{target_user_id}")
async def get_report_by_user_id(
    target_user_id: str,
    request: Request,
    user: dict = Depends(get_current_user)
):
    """
    Get report for a specific user ID.
    Access control: users can only access their own reports.
    """
    # Enforce access control - users can only access their own reports
    if user["user_id"] != target_user_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied. You can only access your own reports."
        )

    # Delegate to main report endpoint
    return await get_user_report(request, user=user)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
