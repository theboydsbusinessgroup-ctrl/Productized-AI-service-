"""JARVIS telemetry adapter for Productized AI Service."""
from __future__ import annotations
import json, os, urllib.request
from datetime import datetime, timezone
PROJECT_ID="productized_ai_service"
def build_event(event_type:str,payload:dict)->dict:
    now=datetime.now(timezone.utc).isoformat(); return {"schema_version":"1.0","event_id":f"{PROJECT_ID}:{now}","project_id":PROJECT_ID,"event_type":event_type,"occurred_at":now,"payload":payload}
def emit(event_type:str,payload:dict)->bool:
    url=os.getenv("JARVIS_INGEST_URL")
    if not url:return False
    req=urllib.request.Request(url,data=json.dumps(build_event(event_type,payload)).encode(),headers={"Content-Type":"application/json","Authorization":f"Bearer {os.getenv('JARVIS_INGEST_TOKEN','')}"},method="POST")
    with urllib.request.urlopen(req,timeout=5) as response:return 200<=response.status<300
