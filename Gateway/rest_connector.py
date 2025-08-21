import requests
import json
import time
from Gateway.models import IHG_Timeseries, IHG_ModbusData,IHG_OutboundConnector,IHG_InboundConnector

def run_restapi_connector(connector):
    """Fetch or send data using REST API Connector."""
    print(f"🌐 Running REST API connector: {connector.name}")

    try:
        if connector.connector_type == "restapi":
            url = connector.rest_url
            method = connector.rest_method.upper()

            payload = {
                "gateway": connector.gateway.name,
                "timestamp": int(time.time() * 1000),
                "data": {}
            }

            # Example: gather latest timeseries for this gateway
            ts_data = IHG_ModbusData.objects.filter(
                timeseries__device__connector=connector
            ).order_by("-id")[:10]

            for row in ts_data:
                payload["data"][row.timeseries.name] = row.value

            if method == "POST":
                r = requests.post(url, json=payload, timeout=5)
            else:
                r = requests.get(url, timeout=5)

            print(f"✅ REST API response {r.status_code}: {r.text[:100]}")

    except Exception as e:
        print(f"❌ REST API connector failed: {e}")


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