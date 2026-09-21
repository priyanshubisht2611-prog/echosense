from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import engine, Base, SessionLocal
from .routes import detections, devices, analytics, transmission, processing, mesh
from .logic.aggregates import refresh_all_aggregates
from .logic.mqtt_subscriber import start_mqtt_subscriber
from .logic.coap_server import start_coap_server
from fastapi.staticfiles import StaticFiles
import os
import asyncio
from datetime import datetime

app = FastAPI(title="EchoSense API")

# Setup CORS so the dashboard can talk to the backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(detections.router)
app.include_router(devices.router)
app.include_router(analytics.router)
app.include_router(transmission.router)
app.include_router(processing.router)
app.include_router(mesh.router)
# Serve the dashboard static files
dashboard_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dashboard")
if os.path.exists(dashboard_path):
    app.mount("/dashboard", StaticFiles(directory=dashboard_path, html=True), name="dashboard")


@app.on_event("startup")
def startup_event():
    """Create database tables, refresh aggregates, and start MQTT subscriber."""
    Base.metadata.create_all(bind=engine)
    # Initial aggregate refresh
    db = SessionLocal()
    try:
        refresh_all_aggregates(db)
    finally:
        db.close()
    
    # Start MQTT subscriber
    try:
        start_mqtt_subscriber(
            broker=os.environ.get("MQTT_BROKER", "localhost"),
            port=int(os.environ.get("MQTT_PORT", "1883")),
            topic=os.environ.get("MQTT_TOPIC", "echosense/detections"),
            username=os.environ.get("MQTT_USERNAME"),
            password=os.environ.get("MQTT_PASSWORD")
        )
    except Exception as e:
        print(f"Failed to start MQTT subscriber: {e}")
    
    # Start CoAP server (async, needs to be started in background task)
    async def start_coap_async():
        try:
            await start_coap_server(
                host=os.environ.get("COAP_HOST", "0.0.0.0"),
                port=int(os.environ.get("COAP_PORT", "5683"))
            )
        except Exception as e:
            print(f"Failed to start CoAP server: {e}")
    
    asyncio.create_task(start_coap_async())


async def aggregate_refresh_task():
    """Background task to refresh aggregates every hour."""
    while True:
        await asyncio.sleep(3600)  # Sleep for 1 hour
        db = SessionLocal()
        try:
            refresh_all_aggregates(db)
            print(f"[{datetime.utcnow()}] Aggregates refreshed")
        except Exception as e:
            print(f"[{datetime.utcnow()}] Aggregate refresh failed: {e}")
        finally:
            db.close()


@app.on_event("startup")
def start_background_tasks():
    """Start background tasks on startup."""
    asyncio.create_task(aggregate_refresh_task())


@app.get("/")
def read_root():
    return {"message": "EchoSense API is online", "version": "1.0.0"}
