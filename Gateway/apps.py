from django.apps import AppConfig
import threading
import os
import asyncio


class GatewayConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Gateway'

    def ready(self):
        if os.environ.get('RUN_MAIN') == 'true':  # Prevent double run in dev mode
            # Import here to avoid Django app registry issues
            from . import modbus, mqtt,openadr_ven

            # # Start Modbus loop
            modbus.start_modbus_loop()

            # # Start MQTT loop
            mqtt.start_mqtt_loop()
            # Start OpenADR VEN loop
            openadr_ven.start_openadr_ven_loop()