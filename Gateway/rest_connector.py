import requests
import json
import time
from Gateway.models import IHG_Timeseries, IHG_ModbusData,IHG_OutboundConnector,IHG_InboundConnector

def send_data_to_api(url,payload,connector_id):
    print(f"🌐 Sending data to REST API: {url}")
    try:
        connector = IHG_OutboundConnector.objects.get(id=connector_id)
        r = requests.post(url, json=payload, timeout=5)
        r.raise_for_status()
        connector.status = "active"
        connector.save(update_fields=["status"])
        
        
    except Exception as e:
        print(f"❌ REST API connector failed: {e}")
        connector.status = "inactive"
        connector.save(update_fields=["status"])