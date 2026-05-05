import streamlit as st
import paho.mqtt.client as mqtt
import json
import base64
import queue
import random
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

MQTT_HOST = "eu1.cloud.thethings.network"
MQTT_PORT = 1883
APP_ID = "masterarbeitsprojekt"
DEVICE_ID = "gps-voice-edgeai-node-01"
API_KEY = "NNSXS.NX2UXDMJZ3ADRCLM36WB4XQ4RHBMXOXADDG3UJI.LJHWYZKKCUHQYKJK2XMZTO4HLXPC6XLYO2YLTIC4ZIHNWIZEXTIA"
FPORT = 2
UPLINK_TOPIC = f"v3/{APP_ID}@ttn/devices/+/up"
DOWNLINK_TOPIC = f"v3/{APP_ID}@ttn/devices/{DEVICE_ID}/down/push"


@st.cache_resource
def get_mqtt():
    msg_queue = queue.Queue()

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            client.subscribe(UPLINK_TOPIC)
            msg_queue.put({"type": "status", "value": "connected"})
        else:
            msg_queue.put({"type": "status", "value": f"fehler_{rc}"})

    def on_disconnect(client, userdata, rc, properties=None):
        msg_queue.put({"type": "status", "value": "getrennt"})

    def on_message(client, userdata, msg):
        try:
            raw = msg.payload.decode("utf-8")
            msg_queue.put({"type": "raw", "value": raw})
        except Exception as e:
            msg_queue.put({"type": "error", "value": str(e)})

    client_id = f"streamlit-{random.randint(10000, 99999)}"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    client.username_pw_set(f"{APP_ID}@ttn", API_KEY)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        client.loop_start()
    except Exception as e:
        msg_queue.put({"type": "error", "value": f"Verbindungsfehler: {e}"})
    return client, msg_queue


if "log" not in st.session_state:
    st.session_state.log = []
if "last_word" not in st.session_state:
    st.session_state.last_word = "-"
if "gps" not in st.session_state:
    st.session_state.gps = "Noch keine Daten"
if "signal" not in st.session_state:
    st.session_state.signal = "-"
if "map_url" not in st.session_state:
    st.session_state.map_url = ""
if "mqtt_connected" not in st.session_state:
    st.session_state.mqtt_connected = False

mqtt_client, msg_queue = get_mqtt()

while not msg_queue.empty():
    item = msg_queue.get_nowait()
    ts = datetime.now().strftime("%H:%M:%S")

    if item["type"] == "status":
        val = item["value"]
        if val == "connected":
            st.session_state.mqtt_connected = True
            st.session_state.log.insert(0, f"[{ts}] MQTT verbunden")
        elif val == "getrennt":
            st.session_state.mqtt_connected = False
            st.session_state.log.insert(0, f"[{ts}] Verbindung getrennt")
        else:
            st.session_state.mqtt_connected = False
            st.session_state.log.insert(0, f"[{ts}] Fehler: {val}")

    elif item["type"] == "raw":
        raw = item["value"]
        try:
            payload = json.loads(raw)
            uplink = payload.get("uplink_message", {})
            decoded = uplink.get("decoded_payload", {})
            word = decoded.get("word", "-")
            lat = decoded.get("latitude")
            lon = decoded.get("longitude")
            gps_valid = decoded.get("gps_valid", False)
            maps_link = decoded.get("maps_link", "")
            rssi = uplink.get("rx_metadata", [{}])[0].get("rssi", "?")
            snr = uplink.get("rx_metadata", [{}])[0].get("snr", "?")

            if word and word != "-":
                st.session_state.last_word = word

            if gps_valid and lat not in [None, 0.0] and lon not in [None, 0.0]:
                st.session_state.gps = f"{lat:.6f}, {lon:.6f}"
                if maps_link:
                    st.session_state.map_url = maps_link
                else:
                    st.session_state.map_url = f"https://www.google.com/maps?q={lat},{lon}"

            st.session_state.signal = f"RSSI: {rssi} | SNR: {snr}"
            st.session_state.log.insert(0, f"[{ts}] Wort: {word} | GPS: {st.session_state.gps}")
        except Exception as e:
            st.session_state.log.insert(0, f"[{ts}] Parse-Fehler: {e}")

    elif item["type"] == "error":
        st.session_state.log.insert(0, f"[{ts}] Fehler: {item['value']}")

st_autorefresh(interval=3000, key="refresh")

st.title("TTN GPS & Voice Monitor")

if st.session_state.mqtt_connected:
    st.success("MQTT: Verbunden")
else:
    st.warning("MQTT: Warte auf Verbindung...")

col1, col2 = st.columns(2)
with col1:
    st.metric("Letztes Wort", st.session_state.last_word)
    st.metric("GPS", st.session_state.gps)
with col2:
    st.metric("Signal", st.session_state.signal)
    if st.session_state.map_url:
        st.markdown(f"[Google Maps öffnen]({st.session_state.map_url})")

st.subheader("Downlink senden")
text = st.text_input("Nachricht:")
if st.button("Senden") and text:
    encoded = base64.b64encode(text.encode()).decode()
    dl = {"downlinks": [{"frm_payload": encoded, "f_port": FPORT, "priority": "NORMAL"}]}
    mqtt_client.publish(DOWNLINK_TOPIC, json.dumps(dl))
    st.success("Gesendet!")

st.subheader("Log")
if st.button("Leeren"):
    st.session_state.log = []
for entry in st.session_state.log[:30]:
    st.text(entry)