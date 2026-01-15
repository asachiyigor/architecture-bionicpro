"""
BionicPRO Reports ETL DAG

This DAG performs ETL process to:
1. Extract data from CRM PostgreSQL database
2. Extract telemetry data from Telemetry PostgreSQL database
3. Transform and join the data
4. Load into ClickHouse OLAP database
5. Create reports datamart

Schedule: Daily at 2:00 AM
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from clickhouse_driver import Client as ClickHouseClient
import logging

logger = logging.getLogger(__name__)

default_args = {
    'owner': 'bionicpro',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=5),
}


def get_clickhouse_client():
    """Create ClickHouse client."""
    return ClickHouseClient(
        host='clickhouse',
        port=9000,
        database='bionicpro'
    )


def create_clickhouse_tables():
    """Create necessary tables in ClickHouse if they don't exist."""
    client = get_clickhouse_client()

    # Create database if not exists
    client.execute('CREATE DATABASE IF NOT EXISTS bionicpro')

    # Create customers table (from CRM)
    client.execute('''
        CREATE TABLE IF NOT EXISTS bionicpro.customers (
            user_id String,
            username String,
            email String,
            first_name String,
            last_name String,
            prosthetic_model String,
            prosthetic_serial String,
            registration_date Date,
            updated_at DateTime DEFAULT now()
        ) ENGINE = ReplacingMergeTree(updated_at)
        ORDER BY user_id
    ''')

    # Create telemetry table
    client.execute('''
        CREATE TABLE IF NOT EXISTS bionicpro.telemetry (
            user_id String,
            device_serial String,
            event_date Date,
            event_time DateTime,
            battery_level Float32,
            usage_minutes Int32,
            movement_count Int32,
            error_code Nullable(String),
            sensor_data String,
            updated_at DateTime DEFAULT now()
        ) ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(event_date)
        ORDER BY (user_id, event_date, event_time)
    ''')

    # Create reports datamart (aggregated by user and day)
    client.execute('''
        CREATE TABLE IF NOT EXISTS bionicpro.reports_datamart (
            user_id String,
            report_date Date,
            total_usage_hours Float32,
            avg_battery_level Float32,
            total_movements Int64,
            error_count Int32,
            last_sync_date DateTime,
            username String,
            email String,
            prosthetic_model String,
            updated_at DateTime DEFAULT now()
        ) ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(report_date)
        ORDER BY (user_id, report_date)
    ''')

    logger.info("ClickHouse tables created successfully")


def extract_crm_data(**context):
    """Extract customer data from CRM PostgreSQL."""
    pg_hook = PostgresHook(postgres_conn_id='crm_postgres')
    conn = pg_hook.get_conn()
    cursor = conn.cursor()

    # Get execution date for incremental load
    execution_date = context['ds']

    query = '''
        SELECT
            id::text as user_id,
            username,
            email,
            first_name,
            last_name,
            prosthetic_model,
            prosthetic_serial,
            registration_date::date
        FROM customers
        WHERE updated_at >= %s::date - interval '1 day'
           OR registration_date >= %s::date - interval '1 day'
    '''

    cursor.execute(query, (execution_date, execution_date))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    logger.info(f"Extracted {len(rows)} customers from CRM")
    return rows


def extract_telemetry_data(**context):
    """Extract telemetry data from Telemetry PostgreSQL."""
    pg_hook = PostgresHook(postgres_conn_id='telemetry_postgres')
    conn = pg_hook.get_conn()
    cursor = conn.cursor()

    execution_date = context['ds']

    query = '''
        SELECT
            user_id::text,
            device_serial,
            event_date::date,
            event_time,
            battery_level,
            usage_minutes,
            movement_count,
            error_code,
            sensor_data::text
        FROM telemetry_events
        WHERE event_date >= %s::date - interval '1 day'
          AND event_date < %s::date + interval '1 day'
    '''

    cursor.execute(query, (execution_date, execution_date))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    logger.info(f"Extracted {len(rows)} telemetry records")
    return rows


def load_customers_to_clickhouse(**context):
    """Load customer data to ClickHouse."""
    ti = context['ti']
    customers = ti.xcom_pull(task_ids='extract_crm_data')

    if not customers:
        logger.info("No customers to load")
        return

    client = get_clickhouse_client()

    # Insert customers
    client.execute(
        '''INSERT INTO bionicpro.customers
           (user_id, username, email, first_name, last_name,
            prosthetic_model, prosthetic_serial, registration_date)
           VALUES''',
        customers
    )

    logger.info(f"Loaded {len(customers)} customers to ClickHouse")


def load_telemetry_to_clickhouse(**context):
    """Load telemetry data to ClickHouse."""
    ti = context['ti']
    telemetry = ti.xcom_pull(task_ids='extract_telemetry_data')

    if not telemetry:
        logger.info("No telemetry data to load")
        return

    client = get_clickhouse_client()

    client.execute(
        '''INSERT INTO bionicpro.telemetry
           (user_id, device_serial, event_date, event_time,
            battery_level, usage_minutes, movement_count, error_code, sensor_data)
           VALUES''',
        telemetry
    )

    logger.info(f"Loaded {len(telemetry)} telemetry records to ClickHouse")


def build_reports_datamart(**context):
    """Build aggregated reports datamart from telemetry and customer data."""
    execution_date = context['ds']
    client = get_clickhouse_client()

    # Insert aggregated data into datamart
    query = f'''
        INSERT INTO bionicpro.reports_datamart
        SELECT
            t.user_id,
            t.event_date as report_date,
            SUM(t.usage_minutes) / 60.0 as total_usage_hours,
            AVG(t.battery_level) as avg_battery_level,
            SUM(t.movement_count) as total_movements,
            countIf(t.error_code IS NOT NULL AND t.error_code != '') as error_count,
            MAX(t.event_time) as last_sync_date,
            c.username,
            c.email,
            c.prosthetic_model,
            now() as updated_at
        FROM bionicpro.telemetry t
        LEFT JOIN bionicpro.customers c ON t.user_id = c.user_id
        WHERE t.event_date = '{execution_date}'
        GROUP BY t.user_id, t.event_date, c.username, c.email, c.prosthetic_model
    '''

    client.execute(query)
    logger.info(f"Built reports datamart for {execution_date}")


def cleanup_old_reports(**context):
    """Clean up reports older than 90 days from S3 cache."""
    # This would connect to MinIO and delete old report files
    # Implementation depends on retention policy
    logger.info("Cleanup task completed")


# Define the DAG
with DAG(
    'bionicpro_reports_etl',
    default_args=default_args,
    description='ETL pipeline for BionicPRO reports',
    schedule_interval='0 2 * * *',  # Daily at 2:00 AM
    catchup=False,
    tags=['bionicpro', 'etl', 'reports']
) as dag:

    # Task: Create ClickHouse tables
    create_tables_task = PythonOperator(
        task_id='create_clickhouse_tables',
        python_callable=create_clickhouse_tables
    )

    # Task: Extract CRM data
    extract_crm_task = PythonOperator(
        task_id='extract_crm_data',
        python_callable=extract_crm_data
    )

    # Task: Extract telemetry data
    extract_telemetry_task = PythonOperator(
        task_id='extract_telemetry_data',
        python_callable=extract_telemetry_data
    )

    # Task: Load customers to ClickHouse
    load_customers_task = PythonOperator(
        task_id='load_customers_to_clickhouse',
        python_callable=load_customers_to_clickhouse
    )

    # Task: Load telemetry to ClickHouse
    load_telemetry_task = PythonOperator(
        task_id='load_telemetry_to_clickhouse',
        python_callable=load_telemetry_to_clickhouse
    )

    # Task: Build reports datamart
    build_datamart_task = PythonOperator(
        task_id='build_reports_datamart',
        python_callable=build_reports_datamart
    )

    # Task: Cleanup old reports
    cleanup_task = PythonOperator(
        task_id='cleanup_old_reports',
        python_callable=cleanup_old_reports
    )

    # Define task dependencies
    create_tables_task >> [extract_crm_task, extract_telemetry_task]
    extract_crm_task >> load_customers_task
    extract_telemetry_task >> load_telemetry_task
    [load_customers_task, load_telemetry_task] >> build_datamart_task
    build_datamart_task >> cleanup_task
