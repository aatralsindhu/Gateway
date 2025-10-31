import asyncio
from datetime import timedelta
from openleadr import OpenADRClient, enable_default_logging
from asgiref.sync import sync_to_async
import threading
from Gateway.models import IHG_InboundConnector,Device

enable_default_logging()
openadr_thread = None
openadr_thread_stop_event = threading.Event()


openadr_clients = {}  # Map gateway_id → VEN client instance

class OpenADRVenClient:
    def __init__(self, ven_name, vtn_url,sampling_interval_seconds=5,conn=None):
        self.ven_name = ven_name
        self.vtn_url = vtn_url
        cert_file_path = conn.certificate.path if conn.certificate else None
        key_file_path = conn.private_key.path if conn.private_key else None
        print("cert_file_path",cert_file_path)
        self.client = OpenADRClient(ven_name=self.ven_name, vtn_url=self.vtn_url,cert=cert_file_path,key=key_file_path)
        self.report_cache = {}  # {measurement_key: latest_value}
        self.registered_reports = set()
        self.sampling_interval = sampling_interval_seconds

    def add_event_handler(self):
        async def handle(event):
            print(f"VEN {self.ven_name} received event: {event}")
            return "optIn"
        self.client.add_handler('on_event', handle)

    def add_report(self, resource_id, measurement):
        resource_id = resource_id
        measurement = measurement
        print(f"VEN {self.ven_name}: Adding report for resource '{resource_id}', measurement '{measurement}'")

        async def collect():
            val = self.report_cache.get((resource_id, measurement))
            if val:
                print(f"VEN {self.ven_name}: Serving resource '{resource_id}', measurement '{measurement}' value: {val}")
                return val
            return ''

        self.client.add_report(
            callback=collect,
            resource_id=resource_id,
            measurement=measurement,
            sampling_rate=timedelta(seconds=self.sampling_interval),
            report_duration=timedelta(seconds=self.sampling_interval * 12),
        )
        self.registered_reports.add((resource_id, measurement))

    def update(self, resource_id, measurement, value):
        resource_id = resource_id
        measurement = measurement
        if (resource_id, measurement) not in self.registered_reports:
            self.add_report(resource_id, measurement)
        self.report_cache[(resource_id, measurement)] = value
        print(f"VEN {self.ven_name}: Updated report cache for resource '{resource_id}', measurement '{measurement}' with value {value}")


    async def initialize_reports(self, conn):
        gateway = conn.gateway

        inbound_connector = await sync_to_async(lambda: IHG_InboundConnector.objects.filter(gateway=gateway).first())()
        if inbound_connector is None:
            print("No inbound connector found for gateway")
            return

        if inbound_connector.connector_type == 'modbus':
            devices = await sync_to_async(lambda: list(Device.objects.filter(connector=inbound_connector)) )()
            for device in devices:
                timeseries = await sync_to_async(lambda: list(device.timeseries.all()))()
                for ts in timeseries:
                    self.add_report(device.device_name, ts.name)
                    # self.report_cache[(device.device_name, ts.name)] = 0.0
        elif inbound_connector.connector_type == 'mqtt':
            mqtt_topics = await sync_to_async(lambda: list(inbound_connector.mqtt_config.topics.all()))()
            for topic in mqtt_topics:
                mqtt_devices = await sync_to_async(lambda: list(topic.devices.all()))()
                for mqtt_device in mqtt_devices:
                    mqtt_timeseries = await sync_to_async(lambda: list(mqtt_device.timeseries.all()))()
                    for mts in mqtt_timeseries:
                        self.add_report(mqtt_device.device_name, mts.key)
                        # self.report_cache[(mqtt_device.device_name, mts.key)] = 0.0
        else:
            print(f"Connector type {inbound_connector.connector_type} not handled!")

    async def run(self,conn):
        # self.add_event_handler()
        await self.initialize_reports(conn)
        await self.client.run()

async def start_ven_clients():
    from Gateway.models import IHG_OutboundConnector
    connectors = await sync_to_async(list)(IHG_OutboundConnector.objects.filter(connector_type='openadr-ven').select_related('gateway'))
    clients = []
    for conn in connectors:
        sampling_interval = int(conn.interval or 5)  # use connector's configured interval or default 5s
        ven_client = OpenADRVenClient(conn.name, conn.rest_url, sampling_interval_seconds=sampling_interval,conn=conn)
        openadr_clients[conn.gateway.id] = ven_client
        conn.status = 'active'
        await sync_to_async(conn.save)()
        clients.append(ven_client)
        asyncio.create_task(ven_client.run(conn))
    return clients



def openadr_ven_loop():
    # Single asyncio event loop running start_ven_clients
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(start_ven_clients())
        while not openadr_thread_stop_event.is_set():
            # Keep loop alive and responsive to stop event
            loop.run_until_complete(asyncio.sleep(1))
    except Exception as e:
        print(f"⚠ OpenADR VEN loop error: {e}")
    finally:
        loop.close()


def start_openadr_ven_loop():
    global openadr_thread, openadr_thread_stop_event
    if openadr_thread and openadr_thread.is_alive():
        print("Stopping existing OpenADR VEN thread before starting a new one")
        stop_openadr_ven_loop()
    openadr_thread_stop_event.clear()
    openadr_thread = threading.Thread(target=openadr_ven_loop, daemon=True)
    openadr_thread.start()
    print("OpenADR VEN thread started")

def stop_openadr_ven_loop():
    global openadr_thread, openadr_thread_stop_event
    if openadr_thread and openadr_thread.is_alive():
        openadr_thread_stop_event.set()
        openadr_thread.join(timeout=10)
        print("OpenADR VEN thread stopped")
        openadr_thread = None