from mqtt_as import MQTTClient
from mqtt_local import config
import uasyncio as asyncio
import dht, machine, ujson
from settings import SSID, password, BROKER, MQTT_USR, MQTT_PASS, MQTT_PORT

# Inicialización de pines
d = dht.DHT22(machine.Pin(15))
relay = machine.Pin(2, machine.Pin.OUT)
led_board = machine.Pin("LED", machine.Pin.OUT)

# Estado MQTT
event_mqtt = asyncio.Event()
mqtt_messages = []

# ID único del dispositivo
id = "".join("{:02X}".format(b) for b in machine.unique_id())
print(f"ID del dispositivo: {id}")

# Cargar o crear configuración local
def load_params():
    try:
        with open("params.json", "r") as f:
            params = ujson.load(f)
    except (OSError, ValueError):
        params = {"setpoint": 25, "periodo": 10, "modo": "auto", "rele": 0}
        save_params(params)
    return params

def save_params(params):
    with open("params.json", "w") as f:
        ujson.dump(params, f)

params = load_params()
relay.value(params["rele"])

# Callback de MQTT
def mqtt_handler(topic, msg, retained):
    global mqtt_messages
    mqtt_messages.append((topic.decode(), msg.decode()))
    event_mqtt.set()

# Procesamiento de mensajes recibidos
async def process_mqtt_messages(client):
    global mqtt_messages, params
    while True:
        await event_mqtt.wait()
        while mqtt_messages:
            topic, msg = mqtt_messages.pop(0)
            print(f"Procesando: {topic} -> {msg}")

            if topic.endswith("/setpoint"):
                params["setpoint"] = int(msg)
            elif topic.endswith("/periodo"):
                params["periodo"] = int(msg)
            elif topic.endswith("/modo"):
                params["modo"] = msg
            elif topic.endswith("/rele"):
                if params["modo"] == "manual":
                    asyncio.create_task(rele(msg))
            elif topic.endswith("/destello"):
                if msg == "true":
                    asyncio.create_task(destello())
                await client.publish(f"{id}/estado", msg)

            save_params(params)
        event_mqtt.clear()

# LED de destello
async def destello():
    for _ in range(5):
        led_board.value(1)
        await asyncio.sleep(0.5)
        led_board.value(0)
        await asyncio.sleep(0.5)

# Cambio de estado del relé
async def rele(msg):
    if msg == "rele":
        params["rele"] = 1 - params["rele"]
        relay.value(params["rele"])
        await asyncio.sleep(0.5)

# Estado del Wi-Fi
async def wifi_han(state):
    print("WiFi", "conectado" if state else "desconectado")
    await asyncio.sleep(1)

# Suscripciones MQTT
async def conn_han(client):
    topics = ["setpoint", "periodo", "modo", "rele", "destello"]
    for t in topics:
        await client.subscribe(f"{id}/{t}", 1)
        await asyncio.sleep(0)
    print("Suscripciones completadas.")

# Lógica principal
async def main(client):
    await client.connect()
    asyncio.create_task(process_mqtt_messages(client))
    await asyncio.sleep(2)

    while True:
        try:
            d.measure()
            temp = d.temperature()
            hum = d.humidity()

            if params["modo"] == "auto":
                relay.value(1 if temp < params["setpoint"] else 0)

            payload = ujson.dumps({
                "temperatura": temp,
                "humedad": hum,
                "setpoint": params["setpoint"],
                "periodo": params["periodo"],
                "modo": params["modo"],
                "rele": relay.value(),
            })
            await client.publish(f"{id}/mediciones", payload, qos=1)
            print("Publicado:", payload)
        except OSError as e:
            print("Error leyendo DHT22:", e)

        await asyncio.sleep(max(params["periodo"], 2))

# CONFIGURACIÓN 
config.update({
    "ssid": SSID,
    "wifi_pw": password,
    "server": BROKER,
    "port": int(MQTT_PORT),        
    "user": MQTT_USR,
    "password": MQTT_PASS,
    "ssl": True,                  
    "subs_cb": mqtt_handler,
    "connect_coro": conn_han,
    "wifi_coro": wifi_han,
})

MQTTClient.DEBUG = True
client = MQTTClient(config)

# Ejecutar
try:
    asyncio.run(main(client))
finally:
    client.close()
    asyncio.new_event_loop()
