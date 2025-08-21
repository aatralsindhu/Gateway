from django.apps import AppConfig
import threading
import os


class GatewayConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Gateway'

    def ready(self):
        if os.environ.get('RUN_MAIN') == 'true':  # Prevent double run in dev mode
            # Import here to avoid Django app registry issues
            from . import modbus, mqtt

            # Start Modbus loop
            threading.Thread(target=modbus.gateway_loop, daemon=True).start()

            # Start MQTT loop
            threading.Thread(target=mqtt.mqtt_loop, daemon=True).start()
