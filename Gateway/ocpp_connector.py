import asyncio
import threading
from ocpp.v16 import ChargePoint
from websockets import connect
from ocpp.v16 import call
from ocpp.v16.enums import Measurand
from Gateway.models import Device,IHG_InboundConnector
from asgiref.sync import sync_to_async
import json
import uuid
from Gateway.models import IHG_OutboundConnector

from datetime import datetime

ocpp_clients = {}  # Map gateway_id to OCPP client instances
ocpp_thread_stop_event = threading.Event()


class OCPPClient:
    def __init__(self, gateway_id, connector, ws_url, charge_point_id):
        self.gateway_id = gateway_id
        self.connector = connector
        self.ws_url = ws_url
        self.charge_point_id = charge_point_id
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.websocket = None  # Hold the websocket connection
        

    def start(self):
        self.thread.start()

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._connect())
        finally:
            self.loop.close()
    def _update_connector_status(self, status):
        self.connector.status = status
        self.connector.save(update_fields=["status"])

    # async def _connect(self):
    #     ws_url_with_cp = f"{self.ws_url}/{self.charge_point_id}"
    #     while True:  # Retry loop if server not up yet
    #         try:
    #             # Use subprotocol for OCPP 1.6
    #             async with connect(ws_url_with_cp, subprotocols=["ocpp1.6"]) as ws:
    #                 self.websocket = ws
    #                 print(f"Connected to {ws_url_with_cp}")
    #                 await sync_to_async(self._update_connector_status)("active")
    #                 await self.send_boot_notification()
    #                 asyncio.create_task(self.handle_server_messages())
    #                 await asyncio.Future()  # Keeps the connection alive
    #         except Exception as e:
    #             print(f"Websocket connection failed: {e}. Retrying in 5s...")
    #             await sync_to_async(self._update_connector_status)("inactive")
    #             await asyncio.sleep(5)
    async def _connect(self):
        ws_url_with_cp = f"{self.ws_url}/{self.charge_point_id}"
        while True:
            try:
                async with connect(ws_url_with_cp, subprotocols=["ocpp1.6"]) as ws:
                    self.websocket = ws
                    print(f"Connected to {ws_url_with_cp}")
                    await sync_to_async(self._update_connector_status)("active")

                    # Start listening for messages before sending BootNotification
                    asyncio.create_task(self.handle_server_messages())

                    # Send BootNotification message, no explicit recv here
                    await self.send_boot_notification()

                    await asyncio.Future()  # Keeps the connection alive
            except Exception as e:
                print(f"Websocket connection failed: {e}. Retrying in 5s...")
                await sync_to_async(self._update_connector_status)("inactive")
                await asyncio.sleep(5)

    async def send_boot_notification(self):
        msg_id = str(uuid.uuid4())
        payload = {
            "chargePointModel": "MockModel",
            "chargeVendor": "MockVendor"
        }
        boot_msg = [2, msg_id, "BootNotification", payload]
        await self.websocket.send(json.dumps(boot_msg))
        print("BootNotification sent")
    # Remove recv and waiting for response here


    async def handle_server_messages(self):
        while True:
            try:
                msg = await self.websocket.recv()
                arr = json.loads(msg)
                if arr[0] == 2:
                    msg_id, action, payload = arr[1], arr[2], arr[3]
                    print(f"Received server action: {action}, payload: {payload}")
                    result = await self.handle_action(action, payload)
                    await self.websocket.send(json.dumps([3, msg_id, result]))
                elif arr[0] == 3:
                    print(f"Received CallResult from server: {arr}")
                elif arr[0] == 4:
                    print(f"CallError from server: {arr}")
            except Exception as e:
                print(f"Error in server message handler: {e}")
    async def handle_action(self, action, payload):
        if action == "SendLocalList":
            # (Store list as needed)
            return {"status": "Accepted", "listVersion": payload.get("listVersion", 1)}
        elif action == "ChangeConfiguration":
            return {"status": "Accepted"}
        elif action == "RemoteStartTransaction":
            return {"status": "Accepted"}
        # Add similar handlers for other actions...
        else:
            # For unsupported actions, return error dict
            return {"status": "Accepted"}

    #
   


    # async def send_boot_notification(self):
    #     msg_id = str(uuid.uuid4())
    #     payload = {
    #         "chargePointModel": "MockModel",
    #         "chargePointVendor": "MockVendor"
    #     }
    #     boot_msg = [2, msg_id, "BootNotification", payload]
    #     await self.websocket.send(json.dumps(boot_msg))
    #     print("BootNotification sent")
    #     try:
    #         response = await asyncio.wait_for(self.websocket.recv(), timeout=10)
            
    #         print("BootNotification response:", response)
    #     except Exception as e:
    #         print("BootNotification response timed out or error:", e)

    async def send_meter_values(self, meter_data, device_name=None):
        try:
            if not self.websocket:
                print(f"No websocket/connection for {self.charge_point_id}")
                return

            msg_id = device_name
            # All samples share this timestamp
            now_iso = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
            sampled_value = []
            for m in meter_data:
                # Ensure value is always a STRING, and fields not None
                val = str(m.get('value', ''))
                unit = m.get('unit')
                measurand = m.get('measurand')
                if val != '' and unit and measurand:
                    sampled_value.append({
                        "value": val,
                        "unit": unit,
                        "measurand": measurand
                    })
            print("sampled_value",sampled_value)
            if not sampled_value:
                print("EMPTY sampled_value! Not sending message.")
                return
            meter_value_entry = {
                "timestamp": now_iso,
                "sampledValue": sampled_value
            }
            payload = {
                "connectorId": 1,   # Or set dynamically per device
                "meterValue": [meter_value_entry]
            }
            
            meter_msg = [2, msg_id, "MeterValues", payload]
            await self.websocket.send(json.dumps(meter_msg))
            print("Sent MeterValues")

            # Receive and print the server's response
            # meter_response = await self.websocket.recv()
            
            # print("MeterValues response:", meter_response)
            # await self.handle_server_messages(meter_response)

        except Exception as e:
            print(f'Error in Send Meter Values function:{e}')

def start_ocpp_clients():
    try:
        global ocpp_thread_stop_event
        ocpp_thread_stop_event.clear()
        connectors = IHG_OutboundConnector.objects.filter(connector_type='ocpp')

        for conn in connectors:
            print("conn.rest_url",conn.rest_url)
            ocpp_client = OCPPClient(conn.gateway.id, conn, conn.rest_url,conn.charge_point_id)
            ocpp_clients[conn.gateway.id] = ocpp_client
            ocpp_client.start()
    except Exception as e:
        print(f'Error in Start Client function:{e}')
        if conn:
            conn.status = 'inactive'
            conn.save(update_fields=["status"])

def stop_ocpp_clients():
    global ocpp_thread_stop_event
    ocpp_thread_stop_event.set()
    for client in ocpp_clients.values():
        client.stop()
    ocpp_clients.clear()
